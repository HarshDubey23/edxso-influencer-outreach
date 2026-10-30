"""Live search: describe a brand in a sentence, and the whole pipeline runs now with every step streamed.

brief -> AI search plan -> YouTube discovery -> filtering -> enrichment -> messages -> (test) emails through Gmail.
Nothing is precomputed: a new brief means new YouTube searches. Shares the autopilot lock, so the two never overlap.
"""
import contextlib
import io
import sys
import threading

from . import autopilot, brand, classify, discover, enrich, gmail, personalize, sender, workspace
from .config import ROOT, load_campaign
from .sender import now


class _Feed(io.TextIOBase):
    """Every line a stage prints becomes a live event (and still reaches the server log)."""

    def write(self, s):
        for line in s.splitlines():
            if line.strip():
                workspace.event(line.strip()[:300])
        sys.__stdout__.write(s)
        return len(s)


def state() -> dict:
    return workspace.get("live_state") or {"status": "idle"}


def start(name: str, brief: str, region: str = "IN", language: str = "en", send: int = 0,
          creator_value: list[str] | None = None) -> bool:
    if not autopilot._lock.acquire(blocking=False):
        return False
    workspace.put(live_state={"status": "running", "stage": "planning", "name": name, "brief": brief,
                              "send": send, "started_at": now()})
    threading.Thread(target=_run, args=(name, brief, region, language, send, creator_value), daemon=True).start()
    return True


def _stage(stage: str, **counts) -> None:
    workspace.put(live_state={**state(), "stage": stage, **counts})


def _run(name, brief, region, language, send, creator_value) -> None:
    try:
        with contextlib.redirect_stdout(_Feed()):
            workspace.event(f"Live search started: {name}: {brief}")
            plan = brand.draft({"name": name, "about": brief, "audience": "",
                                "creator_value": creator_value or ["paid collaboration", "free product"]}, region, language)
            brand.save(plan)
            c = load_campaign(ROOT / workspace.get("campaign_file"))
            _stage("discovering", campaign=c["name"], campaign_id=c["id"], queries=len(c["discovery"]["queries"]))
            found = discover.run(c)
            _stage("filtering", discovered=len(found))
            classified = classify.run(c, found)
            qualified = sum(r["status"] == "qualified" for r in classified)
            _stage("enriching", qualified=qualified)
            enriched = enrich.run(c, classified)
            _stage("writing", emails=sum(e["email"] != enrich.NOT_FOUND for e in enriched))
            s = workspace.all_settings()
            msgs = personalize.run(c, enriched, keep=autopilot._stage(c, "messages"),
                                   sender_name=s.get("sender_name") or f"Partnerships Team, {c['brand']['name']}")
            workspace.put(last_pipeline=now())
            sent = 0
            if send and gmail.connected():
                _stage("sending", messages=len(msgs))
                # test mode only: every email goes to the owner's inbox, so the first-sends review gate is not needed here
                test_to = s.get("test_recipient") or s.get("gmail_email")
                sent = sender.run(c, msgs, enriched, "test", "gmail", limit=send, confirm_live=True, test_to=test_to)["sent"]
            elif send:
                workspace.event("Gmail not connected: messages are ready but nothing was sent", "warn")
            _stage("done", messages=len(msgs), sent=sent, finished_at=now())
            workspace.event(f"Live search finished: {qualified} qualified, {len(msgs)} messages, {sent} test emails sent")
    except BaseException as e:  # SystemExit from a stage (e.g. quota) must also end the run cleanly
        workspace.put(live_state={**state(), "status": "error", "stage": "error", "error": f"{type(e).__name__}: {e}"})
        workspace.event(f"Live search failed: {type(e).__name__}: {e}", "error")
    else:
        workspace.put(live_state={**state(), "status": "done"})
    finally:
        autopilot._lock.release()


def results() -> dict:
    """What the live page shows: every profile found so far with its verdict, the shortlist, messages and sends."""
    st, c = state(), brand.load()
    if not c:
        return {"state": st, "campaign": None}
    lc = load_campaign(ROOT / workspace.get("campaign_file"))
    classified = autopilot._stage(lc, "classified")
    enriched = {e["channel_id"]: e for e in autopilot._stage(lc, "enriched")}
    msgs = {m["channel_id"]: m for m in autopilot._stage(lc, "messages")}
    log = {r["channel_id"]: dict(r) for r in sender.connect().execute(
        "SELECT channel_id, status, delivered_to, created_at, thread_id FROM outreach_log "
        "WHERE campaign_id=? AND kind='email' ORDER BY id", (lc["id"],))}
    rows = []
    # emailed first, then creators with a published email, then the rest by fit
    order = lambda r: (r["status"] != "qualified", r["channel_id"] not in log,
                       enriched.get(r["channel_id"], {}).get("email") in (None, enrich.NOT_FOUND), -(r.get("fit_score") or 0))
    for r in sorted(classified, key=order):
        e, m = enriched.get(r["channel_id"], {}), msgs.get(r["channel_id"])
        rows.append({"channel_id": r["channel_id"], "name": r["name"], "url": r["profile_url"], "followers": r["followers"],
                     "engagement_rate": r["engagement_rate"], "segment": r.get("segment_label"), "status": r["status"],
                     "reasons": r["reasons"][:3], "email": e.get("email"), "email_source": e.get("email_source"),
                     "message": m and {"subject": m["email_subject"], "body": m["email_body"], "dm": m["instagram_dm"],
                                       "review": m["review_status"], "issues": m["validation_issues"]},
                     "sent": log.get(r["channel_id"])})
    return {"state": st, "campaign": {"name": lc["name"], "queries": lc["discovery"]["queries"]}, "rows": rows}
