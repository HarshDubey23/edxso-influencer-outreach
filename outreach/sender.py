"""Stage 5 - Sending layer + outreach tracker (SQLite).

Modes
  dry-run  simulate: nothing leaves the machine; an .eml preview is written to output/outbox/   (default)
  test     really send, but every email is redirected to TEST_RECIPIENT (your own inbox)
  live     really send to the creator; requires --confirm-live
Transports (test/live): smtp (Gmail app password or any SMTP) or n8n (POST to the n8n webhook workflow).

Duplicate outreach is blocked twice: a pre-send lookup by creator *and* by email address, and partial
UNIQUE indexes in SQLite so even a crash/race cannot log the same successful send twice.
Instagram DMs are never automated (no permitted API for cold DMs): they go to a manual queue.
"""
import smtplib
import sqlite3
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid

from .config import DATA, OUTPUT, env
from .enrich import NOT_FOUND, VALID_EMAIL
from .http import HttpError, request_json

SUCCESS = ("simulated", "test_sent", "sent", "dm_queued_manual", "dm_sent_manual")
SCHEMA = """
CREATE TABLE IF NOT EXISTS outreach_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id TEXT NOT NULL, channel_id TEXT NOT NULL, influencer TEXT, email TEXT,
  kind TEXT NOT NULL,          -- 'email' | 'instagram_dm'
  mode TEXT NOT NULL,          -- 'dry-run' | 'test' | 'live' | 'manual'
  status TEXT NOT NULL,        -- simulated | test_sent | sent | failed | dm_queued_manual | dm_sent_manual
  subject TEXT, delivered_to TEXT, transport TEXT, provider_id TEXT, error TEXT,
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_per_creator ON outreach_log(campaign_id, kind, mode, channel_id)
  WHERE status != 'failed';
CREATE UNIQUE INDEX IF NOT EXISTS one_per_email ON outreach_log(campaign_id, kind, mode, email)
  WHERE status != 'failed' AND email IS NOT NULL;
"""


def connect(path=None) -> sqlite3.Connection:
    db = sqlite3.connect(path or DATA / "outreach.db")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def already_contacted(db, campaign_id, kind, mode, channel_id, email) -> bool:
    return db.execute(
        "SELECT 1 FROM outreach_log WHERE campaign_id=? AND kind=? AND mode=? AND status!='failed' "
        "AND (channel_id=? OR (email IS NOT NULL AND email=?))",
        (campaign_id, kind, mode, channel_id, email)).fetchone() is not None


def log(db, **row) -> None:
    row.setdefault("created_at", now())
    cols = ", ".join(row)
    db.execute(f"INSERT INTO outreach_log ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
    db.commit()


def build_email(msg: dict, to: str, original_to: str, mode: str) -> EmailMessage:
    m = EmailMessage()
    m["From"] = env("SENDER_EMAIL", "partnerships@example.invalid")
    m["To"] = to
    m["Subject"] = msg["email_subject"] if mode == "live" else f"[{mode.upper()} -> {original_to}] {msg['email_subject']}"
    m["Message-ID"] = make_msgid(domain="edxso-outreach.local")
    m.set_content(msg["email_body"])
    return m


def send_smtp(m: EmailMessage) -> str:
    host, port = env("SMTP_HOST", "smtp.gmail.com"), int(env("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port, timeout=30) as s:
        s.login(env("SMTP_USER", required=True), env("SMTP_PASSWORD", required=True))
        s.send_message(m)
    return m["Message-ID"]


def send_n8n(items: list[dict]) -> dict[str, dict]:
    r = request_json(env("N8N_WEBHOOK_URL", required=True), body={"items": items}, cache=False, retries=2,
                     headers={"X-Outreach-Token": env("N8N_WEBHOOK_TOKEN", "")})
    return {x["channel_id"]: x for x in r.get("results", [])}


def eligible(messages: list[dict]) -> tuple[list[dict], list[tuple[dict, str]]]:
    ok, skipped = [], []
    for m in messages:
        if m.get("review_status") != "approved":
            skipped.append((m, f"message not approved ({m.get('review_status')})"))
        elif not m.get("email") or m["email"] == NOT_FOUND:
            skipped.append((m, "no contact email (Not Found)"))
        elif not VALID_EMAIL.match(m["email"]):
            skipped.append((m, f"invalid email format: {m['email']}"))
        else:
            ok.append(m)
    return ok, skipped


def run(campaign: dict, messages: list[dict], enriched: list[dict], mode="dry-run", transport="smtp",
        limit=None, confirm_live=False, db=None) -> dict:
    if mode == "live" and not confirm_live:
        raise SystemExit("Refusing to email real creators without --confirm-live.")
    test_to = env("TEST_RECIPIENT") if mode == "test" else None
    if mode == "test" and not test_to:
        raise SystemExit("Set TEST_RECIPIENT in .env for test mode.")
    db = db or connect()
    cid = campaign["id"]
    stats = {"sent": 0, "duplicates_skipped": 0, "failed": 0, "ineligible": 0, "dms_queued": 0}
    ok, skipped = eligible(messages)
    stats["ineligible"] = len(skipped)
    for m, why in skipped:
        print(f"  skip {m['influencer']}: {why}")

    todo, batch_emails = [], set()
    for m in ok:
        if m["email"] in batch_emails or already_contacted(db, cid, "email", mode, m["channel_id"], m["email"]):
            stats["duplicates_skipped"] += 1
            print(f"  skip {m['influencer']}: already contacted in {mode} mode (duplicate prevented)")
        else:
            todo.append(m)
            batch_emails.add(m["email"])
    todo = todo[:limit] if limit else todo

    outbox = OUTPUT / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    n8n_results = {}
    if mode != "dry-run" and transport == "n8n" and todo:
        items = [{"channel_id": m["channel_id"], "to": test_to or m["email"], "original_to": m["email"],
                  "subject": build_email(m, test_to or m["email"], m["email"], mode)["Subject"],
                  "body": m["email_body"]} for m in todo]
        try:
            n8n_results = send_n8n(items)
        except (HttpError, OSError) as e:
            n8n_results = {m["channel_id"]: {"status": "failed", "error": f"n8n unreachable: {e}"} for m in todo}

    for m in todo:
        to = test_to or m["email"]
        em = build_email(m, to, m["email"], mode)
        row = dict(campaign_id=cid, channel_id=m["channel_id"], influencer=m["influencer"], email=m["email"],
                   kind="email", mode=mode, subject=em["Subject"], delivered_to=to,
                   transport="none" if mode == "dry-run" else transport)
        try:
            if mode == "dry-run":
                (outbox / f"{m['channel_id']}.eml").write_bytes(bytes(em))
                row.update(status="simulated", provider_id=em["Message-ID"])
            elif transport == "n8n":
                res = n8n_results.get(m["channel_id"], {"status": "failed", "error": "no result from n8n"})
                if res.get("status") != "sent":
                    raise RuntimeError(res.get("error", "n8n reported failure"))
                row.update(status="test_sent" if mode == "test" else "sent", provider_id=res.get("provider_id"))
            else:
                row.update(status="test_sent" if mode == "test" else "sent", provider_id=send_smtp(em))
            stats["sent"] += 1
        except Exception as e:  # one bad send must not abort the batch; it is logged and retryable
            row.update(status="failed", error=str(e)[:500])
            stats["failed"] += 1
        log(db, **row)
        print(f"  {row['status']:<10} {m['influencer']} -> {to}")

    # Instagram DMs: manual workflow only (queue once per creator).
    by_id = {r["channel_id"]: r for r in enriched}
    for m in messages:
        if m.get("review_status") == "approved" and not already_contacted(db, cid, "instagram_dm", "manual", m["channel_id"], None):
            ig = by_id.get(m["channel_id"], {}).get("socials", {}).get("instagram")
            log(db, campaign_id=cid, channel_id=m["channel_id"], influencer=m["influencer"], email=None,
                kind="instagram_dm", mode="manual", status="dm_queued_manual",
                delivered_to=ig or "Instagram not linked publicly", transport="manual")
            stats["dms_queued"] += 1
    print(f"Sending ({mode}): {stats}")
    return stats


def mark_dm_sent(campaign: dict, channel_id: str, db=None) -> bool:
    db = db or connect()
    cur = db.execute("UPDATE outreach_log SET status='dm_sent_manual', created_at=? WHERE campaign_id=? AND "
                     "channel_id=? AND kind='instagram_dm' AND status='dm_queued_manual'", (now(), campaign["id"], channel_id))
    db.commit()
    return cur.rowcount > 0
