"""Gmail over OAuth: connect once, then send from the owner's real address and read creator replies live.

Each self-hosted copy uses its owner's own Google Cloud OAuth client (README: "Connect Gmail"). In Google's
"Testing" mode no app review is needed for the owner's own account (up to 100 test users).
Scopes: gmail.compose (send + create draft replies) and gmail.readonly (read reply threads).
"""
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

from . import workspace
from .config import env
from .http import request_json

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = "openid email https://www.googleapis.com/auth/gmail.compose https://www.googleapis.com/auth/gmail.readonly"
_access = {"token": None, "exp": 0.0}


class GmailError(Exception):
    pass


def configured() -> bool:
    return bool(env("GOOGLE_CLIENT_ID") and env("GOOGLE_CLIENT_SECRET"))


def connected() -> bool:
    return bool(workspace.get_secret("gmail_refresh"))


def redirect_uri() -> str:
    return env("BASE_URL", "http://localhost:8000").rstrip("/") + "/auth/google/callback"


def auth_url(state: str) -> str:
    return AUTH + "?" + urllib.parse.urlencode({
        "client_id": env("GOOGLE_CLIENT_ID", required=True), "redirect_uri": redirect_uri(), "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state})


def _form(url: str, fields: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise GmailError(f"Google token endpoint said {e.code}: {e.read().decode(errors='replace')[:300]}") from None


def connect_with_code(code: str) -> str:
    tok = _form(TOKEN, {"code": code, "client_id": env("GOOGLE_CLIENT_ID"), "client_secret": env("GOOGLE_CLIENT_SECRET"),
                        "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
    if "refresh_token" not in tok:
        raise GmailError("Google returned no refresh token; remove the app at myaccount.google.com/permissions and connect again.")
    claims = json.loads(base64.urlsafe_b64decode(tok["id_token"].split(".")[1] + "=="))
    workspace.put_secret("gmail_refresh", tok["refresh_token"])
    workspace.put(gmail_email=claims["email"])
    _access.update(token=tok["access_token"], exp=time.time() + tok.get("expires_in", 3600) - 60)
    workspace.event(f"Gmail connected as {claims['email']}")
    return claims["email"]


def disconnect() -> None:
    refresh = workspace.get_secret("gmail_refresh")
    if refresh:
        try:
            _form("https://oauth2.googleapis.com/revoke", {"token": refresh})
        except GmailError:
            pass  # already revoked on Google's side; still forget it here
    workspace.put_secret("gmail_refresh", None)
    workspace.put(gmail_email=None)
    _access.update(token=None, exp=0)
    workspace.event("Gmail disconnected")


def _token() -> str:
    if _access["token"] and time.time() < _access["exp"]:
        return _access["token"]
    refresh = workspace.get_secret("gmail_refresh")
    if not refresh:
        raise GmailError("Gmail is not connected")
    tok = _form(TOKEN, {"refresh_token": refresh, "client_id": env("GOOGLE_CLIENT_ID"),
                        "client_secret": env("GOOGLE_CLIENT_SECRET"), "grant_type": "refresh_token"})
    _access.update(token=tok["access_token"], exp=time.time() + tok.get("expires_in", 3600) - 60)
    return _access["token"]


def _api(path: str, body=None, params=None) -> dict:
    # cache=False and a single attempt: a send must never be repeated by a transport retry
    return request_json(f"{API}/{path}", params=params, body=body, cache=False, retries=1,
                        headers={"Authorization": f"Bearer {_token()}"})


def send(msg: EmailMessage, thread_id: str | None = None) -> dict:
    body = {"raw": base64.urlsafe_b64encode(bytes(msg)).decode()}
    if thread_id:
        body["threadId"] = thread_id
    r = _api("messages/send", body=body)
    return {"id": r["id"], "thread_id": r["threadId"]}


def thread(thread_id: str) -> list[dict]:
    """Messages of a thread as {id, from, date, text}, oldest first."""
    t = _api(f"threads/{thread_id}", params={"format": "full"})
    out = []
    for m in t.get("messages", []):
        headers = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
        out.append({"id": m["id"], "from": headers.get("from", ""), "message_id": headers.get("message-id", ""),
                    "subject": headers.get("subject", ""), "text": _plain(m["payload"]) or m.get("snippet", "")})
    return out


def _plain(part: dict) -> str:
    if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(part["body"]["data"] + "==").decode(errors="replace")
    return next((t for p in part.get("parts", []) if (t := _plain(p))), "")


def draft_reply(thread_id: str, to: str, subject: str, body: str, in_reply_to: str) -> str:
    m = EmailMessage()
    m["To"], m["Subject"] = to, subject if subject.lower().startswith("re:") else f"Re: {subject}"
    if in_reply_to:
        m["In-Reply-To"] = m["References"] = in_reply_to
    m.set_content(body)
    r = _api("drafts", body={"message": {"raw": base64.urlsafe_b64encode(bytes(m)).decode(), "threadId": thread_id}})
    return r["id"]
