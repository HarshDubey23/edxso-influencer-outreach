"""Reply intelligence: classify a creator's reply, extract what they asked, draft the next message.

Unsubscribe / not-interested replies put the address on a suppression list that the sender always checks,
so nobody is contacted again after saying no.
"""
from . import llm
from .sender import connect, now

INTENTS = ["interested", "needs_more_info", "rate_negotiation", "not_interested", "out_of_office", "unsubscribe", "other"]
SUPPRESS = {"not_interested", "unsubscribe"}

SCHEMA = {"type": "OBJECT", "properties": {
    "intent": {"type": "STRING", "enum": INTENTS},
    "sentiment": {"type": "STRING", "enum": ["positive", "neutral", "negative"]},
    "summary": {"type": "STRING"},
    "questions_asked": {"type": "ARRAY", "items": {"type": "STRING"}},
    "quoted_rate": {"type": "STRING"},
    "next_action": {"type": "STRING"},
    "suggested_reply": {"type": "STRING"},
}, "required": ["intent", "sentiment", "summary", "questions_asked", "quoted_rate", "next_action", "suggested_reply"]}


def classify(reply: str, brand: dict | None = None, original_pitch: str = "") -> dict:
    b = brand or {"name": "the brand", "about": ""}
    system = (f"You triage creator replies to influencer outreach from {b['name']}. {b.get('about', '')}\n"
              "Intents: interested = wants to go ahead; rate_negotiation = quotes a fee or asks about budget/pay "
              "(takes priority over interested and needs_more_info); needs_more_info = asks about deliverables, audience or "
              "terms without discussing money; not_interested; out_of_office; unsubscribe = asks not to be contacted.\n"
              "List any questions the creator asked, copy any rate/fee they quoted verbatim (else empty string), and write "
              "next_action in one short line for a human.\n"
              "suggested_reply: under 110 words, warm and specific, answers their questions only with facts present in "
              "the brand description or original pitch (otherwise say you will confirm). Never invent prices, budgets, "
              "dates, days or times, and never accept or counter a quoted rate: ask for their availability instead. "
              "For not_interested or unsubscribe: a one-line polite confirmation that they won't be contacted again. "
              "For out_of_office: empty string.")
    prompt = f"Original pitch:\n{original_pitch or '(not provided)'}\n\nCreator reply:\n{reply}"
    out = llm.generate_json(system, prompt, SCHEMA, temperature=0.2)
    out["suppress"] = out["intent"] in SUPPRESS
    return out


def record(campaign: dict, channel_id: str, email: str | None, reply: str, result: dict, db=None) -> None:
    db = db or connect()
    db.execute("INSERT INTO replies (campaign_id, channel_id, email, intent, summary, body, created_at) VALUES (?,?,?,?,?,?,?)",
               (campaign["id"], channel_id, email, result["intent"], result["summary"], reply, now()))
    if result["suppress"] and email:
        db.execute("INSERT OR IGNORE INTO suppression (email, reason, created_at) VALUES (?,?,?)",
                   (email, f"reply intent: {result['intent']}", now()))
    db.commit()
