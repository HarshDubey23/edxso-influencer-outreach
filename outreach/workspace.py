"""The self-hosted workspace: settings, encrypted secrets and the live event log, all in data/outreach.db.

One deployment = one brand team. Secrets (the Gmail refresh token) are encrypted with a key derived from
SECRET_KEY, so a copied database file alone cannot send mail as the owner.
"""
import base64
import hashlib
import hmac
import json
from contextlib import closing

from cryptography.fernet import Fernet, InvalidToken

from .config import env
from .sender import connect, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL);
"""

DEFAULTS = {
    "autopilot": False,          # the scheduler does nothing until the owner switches it on
    "send_live": False,          # off = every email is redirected to the owner's own inbox
    "daily_cap": 20,             # emails per day, follow-ups included (new mailboxes should start low)
    "window_start": 10, "window_end": 18, "utc_offset_min": 330,   # send only in working hours (default IST)
    "review_first": 10,          # the first N emails must be approved by a human before autopilot sends
    "followup_days": 4,
    "postal_address": "",        # shown in every email footer; required before sending for real
    "sender_name": "",
    "campaign_file": "campaigns/workspace.json",
    "pipeline_every_hours": 24,
}


def _db():
    db = connect()
    db.executescript(SCHEMA)
    return db


def get(key: str):
    with closing(_db()) as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else DEFAULTS.get(key)


def put(**kv) -> None:
    with closing(_db()) as db:
        for k, v in kv.items():
            db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (k, json.dumps(v)))
        db.commit()


def all_settings() -> dict:
    with closing(_db()) as db:
        stored = {r["key"]: json.loads(r["value"]) for r in db.execute("SELECT key, value FROM settings")}
    return {k: v for k, v in {**DEFAULTS, **stored}.items() if not k.startswith("secret:")}


def _key() -> bytes:
    return hashlib.sha256(env("SECRET_KEY", required=True).encode()).digest()


def put_secret(name: str, value: str | None) -> None:
    if value is None:
        with closing(_db()) as db:
            db.execute("DELETE FROM settings WHERE key=?", (f"secret:{name}",))
            db.commit()
        return
    put(**{f"secret:{name}": Fernet(base64.urlsafe_b64encode(_key())).encrypt(value.encode()).decode()})


def get_secret(name: str) -> str | None:
    token = get(f"secret:{name}")
    if not token:
        return None
    try:
        return Fernet(base64.urlsafe_b64encode(_key())).decrypt(token.encode()).decode()
    except InvalidToken:  # SECRET_KEY changed: the owner must reconnect, never a crash
        return None


def sign(value: str) -> str:
    """Tamper-proof token for links in emails (unsubscribe) and the login cookie."""
    raw = base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")
    mac = hmac.new(_key(), raw.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{raw}.{mac}"


def unsign(token: str) -> str | None:
    raw, _, mac = token.partition(".")
    if not hmac.compare_digest(hmac.new(_key(), raw.encode(), hashlib.sha256).hexdigest()[:24], mac):
        return None
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
    except Exception:
        return None


def event(message: str, level: str = "info") -> None:
    print(f"[{level}] {message}")
    with closing(_db()) as db:
        db.execute("INSERT INTO events (at, level, message) VALUES (?, ?, ?)", (now(), level, message[:1000]))
        db.commit()


def events_after(last_id: int, limit: int = 200) -> list[dict]:
    with closing(_db()) as db:
        return [dict(r) for r in db.execute("SELECT * FROM events WHERE id > ? ORDER BY id LIMIT ?", (last_id, limit))]
