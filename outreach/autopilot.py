"""Autopilot: the scheduler that runs a self-hosted install end to end, with guardrails.

Every tick (about 5 minutes):
  1. refresh the pipeline (discover → classify → enrich → write) when it is due, keeping existing messages;
  2. read replies in every thread we started, triage them, honour unsubscribes, save a draft answer in Gmail;
  3. send at most ONE email or follow-up, only inside the sending window, under the daily cap, only messages that
     passed validation, and only human-approved ones until the first `review_first` have gone out.
Nothing is sent to creators while `send_live` is off: every email is redirected to the owner's test inbox.
"""
import random
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from . import brand, classify, discover, enrich, gmail, personalize, replies, sender, workspace
from .config import load_stage, save_stage

_lock = threading.Lock()
TICK_SECONDS = 300
BOUNCE = re.compile(r"mailer-daemon|postmaster@", re.I)


def _stage(c, name):
    try:
        return load_stage(c, name)
    except SystemExit:
        return []


def _local_now(s) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=s["utc_offset_min"])


def sent_today(c, s, mode) -> int:
    start_local = _local_now(s).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = (start_local - timedelta(minutes=s["utc_offset_min"])).replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
    return sender.connect().execute(
        "SELECT COUNT(*) FROM outreach_log WHERE campaign_id=? AND mode=? AND kind LIKE 'email%' "
        "AND status IN ('sent','test_sent') AND created_at >= ?", (c["id"], mode, start_utc)).fetchone()[0]


def refresh_pipeline(c, s, force=False) -> None:
    last = s.get("last_pipeline")
    due = force or not last or datetime.fromisoformat(last) < datetime.now(timezone.utc) - timedelta(hours=s["pipeline_every_hours"])
    if not due:
        return
    workspace.event(f"Pipeline started for {c['name']}")
    discovered = discover.run(c)
    workspace.event(f"Discovery: {len(discovered)} channels")
    classified = classify.run(c, discovered)
    q = sum(r["status"] == "qualified" for r in classified)
    workspace.event(f"Filtering: {q} qualified of {len(classified)}")
    enriched = enrich.run(c, classified)
    workspace.event(f"Enrichment: {sum(e['email'] != 'Not Found' for e in enriched)} published emails among {len(enriched)}")
    msgs = personalize.run(c, enriched, keep=_stage(c, "messages"), sender_name=s.get("sender_name") or f"Partnerships Team, {c['brand']['name']}")
    workspace.event(f"Messages: {sum(m['review_status'] == 'approved' for m in msgs)} passed checks, "
                    f"{sum(m['review_status'] != 'approved' for m in msgs)} need a human")
    workspace.put(last_pipeline=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def poll_replies(c, s) -> int:
    me = (s.get("gmail_email") or "").lower()
    seen = set(workspace.get("seen_reply_ids") or [])
    msgs_by_id = {m["channel_id"]: m for m in _stage(c, "messages")}
    db, n = sender.connect(), 0
    rows = db.execute("SELECT DISTINCT channel_id, email, thread_id FROM outreach_log WHERE campaign_id=? AND thread_id IS NOT NULL "
                      "AND status IN ('sent','test_sent')", (c["id"],)).fetchall()
    for row in rows:
        for m in gmail.thread(row["thread_id"]):
            if m["id"] in seen or me in m["from"].lower():
                continue
            seen.add(m["id"])
            original = msgs_by_id.get(row["channel_id"], {})
            if BOUNCE.search(m["from"]):  # a delivery-failure notice is not the creator talking
                workspace.event(f"Delivery failure notice in the thread with {original.get('influencer', row['email'])}", "warn")
                continue
            result = replies.classify(m["text"][:5000], c["brand"], original.get("email_body", ""))
            replies.record(c, row["channel_id"], row["email"], m["text"][:5000], result)
            note = f"Reply from {original.get('influencer', row['email'])}: {result['intent'].replace('_', ' ')}"
            if result["suppress"]:
                note += " (added to do-not-contact)"
            if result["suggested_reply"]:
                gmail.draft_reply(row["thread_id"], m["from"], m["subject"], result["suggested_reply"], m["message_id"])
                note += "; suggested answer saved as a Gmail draft"
            workspace.event(note)
            n += 1
    workspace.put(seen_reply_ids=sorted(seen)[-5000:])
    return n


def send_next(c, s) -> str:
    mode = "live" if s["send_live"] else "test"
    if mode == "live" and not s.get("postal_address"):
        return "live sending needs a postal address in the footer (Settings)"
    hour = _local_now(s).hour
    if not s["window_start"] <= hour < s["window_end"]:
        return f"outside the sending window ({s['window_start']}:00-{s['window_end']}:00)"
    if sent_today(c, s, mode) >= s["daily_cap"]:
        return f"daily cap of {s['daily_cap']} reached"
    test_to = s.get("test_recipient") or s.get("gmail_email")
    msgs, enriched = _stage(c, "messages"), _stage(c, "enriched")
    db = sender.connect()
    gone = db.execute("SELECT COUNT(*) FROM outreach_log WHERE campaign_id=? AND mode=? AND kind='email' AND status IN ('sent','test_sent')",
                      (c["id"], mode)).fetchone()[0]
    pool = msgs if gone >= s["review_first"] else [m for m in msgs if m.get("human_approved")]
    st = sender.run(c, pool, enriched, mode, "gmail", limit=1, confirm_live=True, test_to=test_to)
    if st["sent"]:
        return f"sent 1 email ({'to the creator' if mode == 'live' else 'redirected to ' + test_to})"
    if st["failed"]:
        return "a send failed; see the tracker for the error"
    fu = sender.followups(c, msgs, mode, "gmail", s["followup_days"], limit=1, test_to=test_to)
    if fu["followups_sent"]:
        return "sent 1 follow-up"
    if gone < s["review_first"] and not any(m.get("human_approved") for m in msgs):
        return f"waiting for you to approve messages (the first {s['review_first']} need a human)"
    return "nothing due to send"


def tick(force=False) -> None:
    if not _lock.acquire(blocking=False):
        workspace.event("A run is already in progress", "warn")
        return
    try:
        s = workspace.all_settings()
        if not (s["autopilot"] or force):
            return
        c = brand.load()
        if not c:
            workspace.event("No campaign yet: write your brand brief in the Control room", "warn")
            return
        from .config import load_campaign, ROOT
        c = load_campaign(ROOT / s["campaign_file"])  # merged over campaigns/_defaults.json
        refresh_pipeline(c, s, force=force and not _stage(c, "messages"))
        if not gmail.connected():
            workspace.event("Gmail not connected: messages are ready, nothing can be sent", "warn")
            return
        n = poll_replies(c, s)
        if n:
            workspace.event(f"{n} new repl{'y' if n == 1 else 'ies'} triaged")
        workspace.event(f"Sender: {send_next(c, s)}")
    except Exception as e:  # the scheduler must survive any single failure; the owner sees it in the log
        workspace.event(f"Autopilot error: {type(e).__name__}: {e}", "error")
    finally:
        _lock.release()


def start_scheduler() -> threading.Thread:
    def loop():
        time.sleep(20)
        while True:
            tick()
            time.sleep(TICK_SECONDS + random.randint(0, 90))  # jitter so sends never land on a fixed rhythm
    t = threading.Thread(target=loop, name="autopilot", daemon=True)
    t.start()
    return t
