"""Control-room routes for a self-hosted install: login, Gmail connect, settings, brand plan, autopilot, live events,
and the public unsubscribe link every email carries."""
import asyncio
import hmac
import json
import threading

from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import autopilot, brand, gmail, live, llm, workspace
from .config import env
from .sender import connect, now

PUBLIC = ("/login", "/u/", "/healthz")
EDITABLE = {  # setting -> (type, validator)
    "autopilot": (bool, None), "send_live": (bool, None), "daily_cap": (int, lambda v: 1 <= v <= 200),
    "window_start": (int, lambda v: 0 <= v <= 23), "window_end": (int, lambda v: 1 <= v <= 24),
    "utc_offset_min": (int, lambda v: -720 <= v <= 840), "review_first": (int, lambda v: 0 <= v <= 500),
    "followup_days": (int, lambda v: 1 <= v <= 30), "postal_address": (str, lambda v: len(v) <= 300),
    "sender_name": (str, lambda v: len(v) <= 80), "test_recipient": (str, lambda v: v == "" or "@" in v),
    "pipeline_every_hours": (int, lambda v: 6 <= v <= 168),
}


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#1d3a31;font:16px/1.5 system-ui,sans-serif;color:#15181a}}
.card{{background:#f6f7f4;padding:32px;max-width:420px;width:calc(100% - 32px);box-shadow:0 18px 40px -12px rgba(0,0,0,.55)}}
h1{{margin:0 0 12px;font-size:26px;text-transform:uppercase;letter-spacing:.02em}}input{{width:100%;padding:10px;font:inherit;border:1.5px solid #15181a;margin:8px 0 14px}}
button{{padding:10px 16px;font:600 15px/1 system-ui;background:#c62f26;color:#fff;border:0;cursor:pointer}}p{{color:#4f5752}}</style></head>
<body><div class="card">{body}</div></body></html>""", status_code=status)


def _authed(request: Request) -> bool:
    token, key = env("API_TOKEN"), request.headers.get("x-api-key", "")
    if token and key and hmac.compare_digest(key.encode(), token.encode()):
        return True  # machine access (n8n agent) with the install's API token
    pw = env("ADMIN_PASSWORD")
    if not pw:
        return True  # local development without a password
    return workspace.unsign(request.cookies.get("session", "")) == "owner"


class SettingsIn(BaseModel):
    values: dict


class LiveIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    brief: str = Field(min_length=10, max_length=800)
    region: str = Field("IN", pattern="^[A-Z]{2}$")
    language: str = Field("en", pattern="^[a-z]{2}$")
    send: int = Field(0, ge=0, le=10)  # test emails to send at the end (always to the owner's inbox)


class BrandIn(BaseModel):
    name: str
    about: str
    creator_value: list[str] = []
    audience: str = ""
    website: str = ""
    region: str = "IN"
    language: str = "en"


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.url.path.startswith(PUBLIC) or _authed(request):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "login required"}, status_code=401)
        return RedirectResponse("/login")

    @app.on_event("startup")
    def _start():
        if env("AUTOPILOT_THREAD", "1") == "1":
            autopilot.start_scheduler()

    @app.get("/healthz")
    def health():
        return {"ok": True}

    @app.get("/login")
    def login_page():
        return _page("Sign in", """<h1>Outreach engine</h1><p>Enter the admin password set for this install.</p>
<form method="post" action="/login"><input type="password" name="password" autocomplete="current-password" required autofocus>
<button type="submit">Sign in</button></form>""")

    @app.post("/login")
    async def login(request: Request):
        # stdlib parsing of the one-field form; avoids a multipart dependency for a password box
        password = parse_qs((await request.body()).decode())["password"][0] if b"password=" in await request.body() else ""
        pw = env("ADMIN_PASSWORD") or ""
        if not pw or not hmac.compare_digest(password.encode(), pw.encode()):
            return _page("Sign in", "<h1>Wrong password</h1><p><a href='/login'>Try again</a></p>", 401)
        r = RedirectResponse("/live.html", status_code=303)
        r.set_cookie("session", workspace.sign("owner"), httponly=True, samesite="lax", max_age=30 * 86400,
                     secure=env("BASE_URL", "").startswith("https"))
        return r

    # --- Gmail ------------------------------------------------------------------------------------------------
    @app.get("/auth/google/start")
    def google_start():
        if not gmail.configured():
            raise HTTPException(400, "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first (README: Connect Gmail)")
        return RedirectResponse(gmail.auth_url(workspace.sign(f"oauth:{now()}")))

    @app.get("/auth/google/callback")
    def google_callback(code: str = "", state: str = "", error: str = ""):
        if error:
            return _page("Gmail", f"<h1>Not connected</h1><p>Google said: {error}</p><p><a href='/control.html'>Back</a></p>", 400)
        if not (workspace.unsign(state) or "").startswith("oauth:"):
            raise HTTPException(400, "invalid OAuth state")
        try:
            gmail.connect_with_code(code)
        except gmail.GmailError as e:
            return _page("Gmail", f"<h1>Not connected</h1><p>{e}</p><p><a href='/control.html'>Back</a></p>", 400)
        return RedirectResponse("/control.html#connected")

    @app.post("/api/gmail/disconnect")
    def google_disconnect():
        gmail.disconnect()
        return {"ok": True}

    # --- settings, plan, autopilot ----------------------------------------------------------------------------
    @app.get("/api/workspace")
    def workspace_state():
        s = workspace.all_settings()
        c = brand.load()
        return {"settings": s, "campaign": c,
                "status": {"gmail_configured": gmail.configured(), "gmail_connected": gmail.connected(),
                           "gmail_email": s.get("gmail_email"), "youtube_key": bool(env("YOUTUBE_API_KEY")),
                           "gemini_key": bool(env("GEMINI_API_KEY")), "base_url": env("BASE_URL", "http://localhost:8000"),
                           "redirect_uri": gmail.redirect_uri(), "has_campaign": bool(c)}}

    @app.put("/api/workspace")
    def workspace_update(body: SettingsIn):
        clean = {}
        for k, v in body.values.items():
            if k not in EDITABLE:
                raise HTTPException(400, f"unknown setting {k}")
            typ, ok = EDITABLE[k]
            if typ is int and isinstance(v, str) and v.strip().lstrip("-").isdigit():
                v = int(v)
            if not isinstance(v, typ) or (ok and not ok(v)):
                raise HTTPException(400, f"invalid value for {k}")
            clean[k] = v.strip() if isinstance(v, str) else v
        merged = {**workspace.all_settings(), **clean}
        if merged["window_start"] >= merged["window_end"]:
            raise HTTPException(400, "the sending window must start before it ends")
        if clean.get("send_live") and not merged.get("postal_address"):
            raise HTTPException(400, "add a postal address for the email footer before sending for real")
        workspace.put(**clean)
        changed = ", ".join(f"{k}={v}" for k, v in clean.items())
        workspace.event(f"Settings changed: {changed}")
        return workspace.all_settings()

    @app.post("/api/workspace/plan")
    def plan(body: BrandIn):
        try:
            return brand.draft(body.model_dump(), body.region, body.language)
        except llm.LLMError as e:
            raise HTTPException(502, str(e))

    @app.put("/api/workspace/campaign")
    def save_campaign(c: dict):
        try:
            return {"saved": brand.save(c)}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/autopilot/run")
    def run_now():
        threading.Thread(target=autopilot.tick, kwargs={"force": True}, daemon=True).start()
        workspace.event("Run requested from the Control room")
        return {"started": True}

    # --- live search: brief in, the whole pipeline runs now ----------------------------------------------------
    @app.post("/api/live/run")
    def live_run(body: LiveIn):
        if not live.start(body.name.strip(), body.brief.strip(), body.region, body.language, body.send):
            raise HTTPException(409, "a run is already in progress; wait for it to finish")
        return live.state()

    @app.get("/api/live/status")
    def live_status():
        return live.state()

    @app.get("/api/live/results")
    def live_results():
        return live.results()

    @app.get("/api/events")
    def events(after: int = 0):
        return workspace.events_after(after)

    @app.get("/api/events/stream")
    async def stream(request: Request, after: int = 0):
        async def gen():
            last = after
            while not await request.is_disconnected():
                for e in workspace.events_after(last):
                    last = e["id"]
                    yield f"id: {e['id']}\ndata: {json.dumps(e)}\n\n"
                yield ": keep-alive\n\n"
                await asyncio.sleep(2)
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    # --- public unsubscribe (every email links here) ----------------------------------------------------------
    @app.get("/u/{token}")
    def unsubscribe_page(token: str):
        if not workspace.unsign(token):
            return _page("Unsubscribe", "<h1>Link not valid</h1><p>This unsubscribe link is broken or expired.</p>", 400)
        return _page("Unsubscribe", f"""<h1>Stop emails?</h1><p>You won't hear from us again about collaborations.</p>
<form method="post" action="/u/{token}"><button type="submit">Unsubscribe</button></form>""")

    @app.post("/u/{token}")
    def unsubscribe(token: str):
        email = workspace.unsign(token)
        if not email:
            return _page("Unsubscribe", "<h1>Link not valid</h1>", 400)
        db = connect()
        db.execute("INSERT OR IGNORE INTO suppression (email, reason, created_at) VALUES (?, 'unsubscribe link', ?)", (email, now()))
        db.commit()
        workspace.event(f"Unsubscribed via link: {email}")
        return _page("Unsubscribe", "<h1>Done</h1><p>You're unsubscribed. No further emails will be sent.</p>")
