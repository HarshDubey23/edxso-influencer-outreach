"""FastAPI service: the pipeline, the models and the review workflow behind one API + the dashboard.

Run:  uvicorn outreach.api:app --reload      then open http://localhost:8000
Every endpoint works on the same JSON stage files and SQLite log the CLI uses.
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import llm, match, ml, personalize, replies, sender
from .config import ROOT, all_campaigns, load_stage, save_stage
from .export import dashboard_data

app = FastAPI(title="Creator Outreach Engine", version="2.0",
              description="Discovery → filtering → ML niche classification → enrichment → AI personalization → review → sending → tracking")
DASH = ROOT / "dashboard"


def campaign_or_404(cid: str) -> dict:
    for c in all_campaigns():
        if c["id"] == cid:
            return c
    raise HTTPException(404, f"unknown campaign {cid}")


def stage_or_empty(c: dict, stage: str) -> list:
    try:
        return load_stage(c, stage)
    except SystemExit:
        return []


@app.get("/api/data")
def data():
    """Everything the dashboard renders (same payload the static/public build bakes into JSON)."""
    return dashboard_data()


class TextIn(BaseModel):
    text: str = Field(min_length=3, max_length=8000)


@app.post("/api/classify")
def classify_text(body: TextIn):
    """Model serving: hybrid niche classifier on free text (each line is treated as a video title)."""
    lines = [ln for ln in body.text.splitlines() if ln.strip()]
    rec = {"name": lines[0][:80] if lines else "", "description": body.text, "channel_keywords": "",
           "recent_videos": [{"title": ln} for ln in lines[1:20]]}
    out = ml.predict(rec)
    if out["ml_niche"] is None:
        raise HTTPException(503, "model not trained yet: run `python -m outreach train`")
    return out


class BriefIn(BaseModel):
    brief: str = Field(min_length=10, max_length=2000)
    top: int = Field(15, ge=1, le=50)


@app.post("/api/match")
def match_brief(body: BriefIn):
    """Brand-brief engine: rank qualified creators from every niche against a plain-English brief."""
    try:
        return {"brief": body.brief, "results": match.match_all(body.brief, body.top)}
    except llm.LLMError as e:
        raise HTTPException(502, str(e))


ASK_SCHEMA = {"type": "OBJECT", "properties": {
    "niches": {"type": "ARRAY", "items": {"type": "STRING"}},
    "status": {"type": "STRING", "enum": ["qualified", "rejected", "any"]},
    "min_followers": {"type": "INTEGER", "nullable": True}, "max_followers": {"type": "INTEGER", "nullable": True},
    "min_engagement": {"type": "NUMBER", "nullable": True}, "min_authenticity": {"type": "INTEGER", "nullable": True},
    "country": {"type": "STRING", "nullable": True}, "has_email": {"type": "BOOLEAN", "nullable": True},
    "text_contains": {"type": "STRING", "nullable": True},
    "sort_by": {"type": "STRING", "enum": ["final_score", "engagement_rate", "followers", "authenticity"]},
    "limit": {"type": "INTEGER"}, "explanation": {"type": "STRING"},
}, "required": ["niches", "status", "sort_by", "limit", "explanation"]}


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/api/ask")
def ask(body: AskIn):
    """Conversational analytics: the LLM only translates the question into a typed filter; the answer rows come
    straight from the data, so nothing in the result can be hallucinated."""
    camps = all_campaigns()
    niches = [c["niche"] for c in camps]
    system = ("Translate a question about a creator dataset into a JSON filter. Niche keys: " + ", ".join(niches) +
              ". Countries are ISO-2 codes (India = IN). Empty niches list = all niches. Use null for unused filters. "
              "status 'qualified' unless the user asks about rejected or all creators. limit 1-50 (default 10). "
              "explanation: one sentence describing the filter you applied.")
    try:
        f = llm.generate_json(system, body.question, ASK_SCHEMA, temperature=0.0)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    rows = []
    for c in camps:
        enriched = {r["channel_id"]: r for r in stage_or_empty(c, "enriched")}
        for r in stage_or_empty(c, "classified"):
            rows.append({**r, **enriched.get(r["channel_id"], {}), "niche": c["niche"]})

    def keep(r):
        t = (f.get("text_contains") or "").lower()
        return ((not f["niches"] or r["niche"] in f["niches"])
                and (f["status"] == "any" or r["status"] == f["status"])
                and (f.get("min_followers") is None or (r["followers"] or 0) >= f["min_followers"])
                and (f.get("max_followers") is None or (r["followers"] or 0) <= f["max_followers"])
                and (f.get("min_engagement") is None or (r["engagement_rate"] or 0) >= f["min_engagement"])
                and (f.get("min_authenticity") is None or (r.get("authenticity") or 0) >= f["min_authenticity"])
                and (not f.get("country") or r["country"] == f["country"].upper())
                and (f.get("has_email") is None or (r.get("email") not in (None, "Not Found")) == f["has_email"])
                and (not t or t in (r["name"] + " " + " ".join(v["title"] for v in r["recent_videos"])).lower()))

    hits = sorted({r["channel_id"]: r for r in rows if keep(r)}.values(),
                  key=lambda r: -(r.get(f["sort_by"]) or r.get("fit_score") or 0))
    limit = max(1, min(f["limit"], 50))
    return {"question": body.question, "filter": f, "total_matches": len(hits),
            "results": [{"name": r["name"], "niche": r["niche"], "segment": r["segment_label"], "status": r["status"],
                         "followers": r["followers"], "engagement_rate": r["engagement_rate"],
                         "authenticity": r.get("authenticity"), "country": r["country"], "email": r.get("email", "Not enriched"),
                         "profile_url": r["profile_url"], "reasons": r["reasons"]} for r in hits[:limit]]}


class MessageEdit(BaseModel):
    email_subject: str | None = None
    email_body: str | None = None
    instagram_dm: str | None = None
    approve: bool = True


@app.patch("/api/campaigns/{cid}/messages/{channel_id}")
def edit_message(cid: str, channel_id: str, body: MessageEdit):
    """Human review: edit and/or approve. Edited text is re-validated with the same rules as generated text."""
    c = campaign_or_404(cid)
    msgs = stage_or_empty(c, "messages")
    rec = next((r for r in stage_or_empty(c, "enriched") if r["channel_id"] == channel_id), None)
    m = next((x for x in msgs if x["channel_id"] == channel_id), None)
    if not m or not rec:
        raise HTTPException(404, "message not found")
    for k in ("email_subject", "email_body", "instagram_dm"):
        if getattr(body, k) is not None:
            m[k] = getattr(body, k).strip()
    issues = personalize.validate(m, rec, c)
    m.update(validation_issues=issues, email_words=personalize.words(m["email_body"]),
             dm_words=personalize.words(m["instagram_dm"]), edited_by_human=True,
             review_status="approved" if body.approve and not issues else "needs_review")
    save_stage(c, "messages", msgs)
    return m


class SendIn(BaseModel):
    mode: str = Field("dry-run", pattern="^(dry-run|test)$")  # live sending is CLI-only, behind --confirm-live
    via: str = Field("n8n", pattern="^(smtp|n8n)$")
    limit: int | None = Field(None, ge=1, le=50)


@app.post("/api/campaigns/{cid}/send")
def send(cid: str, body: SendIn):
    c = campaign_or_404(cid)
    return sender.run(c, stage_or_empty(c, "messages"), stage_or_empty(c, "enriched"), body.mode, body.via, body.limit)


class ReplyIn(BaseModel):
    campaign_id: str
    channel_id: str
    reply: str = Field(min_length=2, max_length=5000)
    save: bool = False


@app.post("/api/replies")
def triage_reply(body: ReplyIn):
    """Reply intelligence: intent, questions, quoted rate, suggested response; unsubscribes go on the suppression list."""
    c = campaign_or_404(body.campaign_id)
    m = next((x for x in stage_or_empty(c, "messages") if x["channel_id"] == body.channel_id), {})
    try:
        out = replies.classify(body.reply, c["brand"], m.get("email_body", ""))
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    if body.save:
        replies.record(c, body.channel_id, m.get("email"), body.reply, out)
    return out


@app.get("/api/model-web")
def model_web():
    path = ml.MODELS / "niche_classifier_web.json"
    if not path.exists():
        raise HTTPException(503, "model not trained yet: run `python -m outreach train`")
    return FileResponse(path, media_type="application/json")


@app.get("/")
def index():
    return FileResponse(DASH / "index.html")


app.mount("/", StaticFiles(directory=DASH), name="dashboard")
