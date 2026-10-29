"""Capture real outputs of the live-only features (ask, brand match, reply triage) for the read-only public dashboard.

The questions, briefs and sample replies below are demo inputs written for this showcase (labelled as such in the UI);
every answer is produced by the same code paths the API serves.
"""
import json
import re

from . import llm, match, replies
from .api import AskIn, ask
from .config import DATA, all_campaigns, load_stage

QUESTIONS = [
    "Top 5 beauty or fashion creators by engagement",
    "Teachers or parenting creators with more than 20,000 followers and a public email",
    "Which crypto creators were rejected?",
]
BRIEFS = [
    "EDXSO wants creators who influence how parents in Delhi NCR choose a school and judge teaching quality.",
    "An affordable, sweat-proof wireless earbud brand for gym-goers and runners.",
]
SAMPLE_REPLIES = [
    ("Interested, asks about rate", "Hi! Thanks for reaching out, this sounds interesting. What's the budget, and would it be a dedicated video "
     "or an integration? I usually charge Rs 15,000 for a 60-second integration. Also, can I see the product first?"),
    ("Not interested", "Thanks, but I'm not taking brand collaborations right now. Please don't email me again."),
    ("Out of office", "I'm travelling until the 15th with limited access to email. I'll get back to you when I return."),
    ("Needs more info", "Hey, can you tell me more about who your audience is and what deliverables you're expecting? Is there a contract?"),
]


def run() -> None:
    out = {"ask": [], "match": [], "replies": []}
    for q in QUESTIONS:
        r = ask(AskIn(question=q))
        out["ask"].append({**r, "results": r["results"][:10]})
        print(f"  ask: {q} -> {r['total_matches']} matches")
    for b in BRIEFS:
        try:
            out["match"].append({"brief": b, "results": match.match_all(b, 10)})
            print(f"  match: {b[:50]}...")
        except llm.LLMError as e:  # embeddings are rate-limited on the free tier; the page then shows no examples
            print(f"  ! match skipped: {str(e)[:120]}")
    edu = next(c for c in all_campaigns() if c["niche"] == "education_parenting")
    pitch = next((m["email_body"] for m in load_stage(edu, "messages") if m["review_status"] == "approved"), "")
    for label, text in SAMPLE_REPLIES:
        r = replies.classify(text, edu["brand"], pitch)
        # self-check: the drafted reply must not commit to days the creator never mentioned
        assert not re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", r["suggested_reply"].lower()), r
        out["replies"].append({"label": f"Sample: {label}", "reply": text, "result": r})
        print(f"  reply: {label} -> {r['intent']}")
    (DATA / "demo_examples.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    run()
