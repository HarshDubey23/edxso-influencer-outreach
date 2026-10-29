"""Stdlib HTTP client with on-disk caching, retries and per-host throttling.

Caching makes re-runs free (no API quota) and reproducible. API keys travel in
headers, never in the URL, so they never end up in cache keys or logs.
"""
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from .config import CACHE

UA = "edxso-outreach-bot/1.0 (+influencer research prototype)"
_last_call: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


class HttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


def _cache_file(kind: str, url: str, body: bytes | None):
    key = hashlib.sha256(url.encode() + (body or b"")).hexdigest()[:32]
    return CACHE / f"{kind}-{key}.json"


def _throttle(host: str, min_interval: float) -> None:
    wait = _last_call.get(host, 0) + min_interval - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call[host] = time.monotonic()


def request_json(url, *, params=None, body=None, headers=None, cache=True,
                 retries=5, timeout=60, min_interval=0.0):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    data = json.dumps(body).encode() if body is not None else None
    path = _cache_file("json", url, data)
    if cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    hdrs = {"User-Agent": UA, "Accept": "application/json", **(headers or {})}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    host = urllib.parse.urlparse(url).netloc
    for attempt in range(retries):
        _throttle(host, min_interval)
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(min(60, (15 if e.code == 429 else 2) * 2 ** attempt))
                continue
            raise HttpError(e.code, msg) from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    if cache:
        path.write_text(json.dumps(out), encoding="utf-8")
    return out


def allowed_by_robots(url: str) -> bool:
    parts = urllib.parse.urlparse(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser(base + "/robots.txt")
        try:
            rp.read()
        except Exception:
            rp = None  # unreachable robots.txt: treat as no rules, per RFC 9309
        _robots[base] = rp
    rp = _robots[base]
    return rp is None or rp.can_fetch(UA, url)


def get_text(url: str, timeout: int = 12, max_bytes: int = 600_000) -> str | None:
    """Fetch a public web page (cached). Returns None if blocked by robots.txt or unreachable."""
    path = _cache_file("page", url, None)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["text"]
    text = None
    if allowed_by_robots(url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if "html" in r.headers.get("Content-Type", "") or "text" in r.headers.get("Content-Type", ""):
                    text = r.read(max_bytes).decode("utf-8", "replace")
        except Exception:
            text = None
    path.write_text(json.dumps({"url": url, "text": text}), encoding="utf-8")
    return text
