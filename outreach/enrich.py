"""Stage 3 - Profile enrichment for qualified creators.

Contact email: only emails the creator published themselves, in priority order
  1. channel description  2. their own website (homepage + /contact, robots.txt respected)
  3. a "business/contact" line in a recent video description.
Nothing is guessed. If none is found the field is "Not Found".
YouTube's hidden "View email address" button is behind a CAPTCHA and is deliberately not touched.
"""
import re
import urllib.parse
from collections import Counter

from . import llm
from .config import save_stage
from .http import get_text

NOT_FOUND = "Not Found"
NOT_PUBLIC = "Not Available (private YouTube Analytics data)"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
VALID_EMAIL = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
# Video descriptions often quote *other* people's emails (exam boards, sponsors), so only business-intent lines count.
CONTACT_LINE = re.compile(r"business|collab|sponsor|promotion|brand (deal|enquir|inquir)|work with me|for enquiries", re.I)
INSTITUTIONAL = re.compile(r"\.(ac|edu|gov|nic|mil)(\.[a-z]{2})?$")
SOCIAL = {
    "instagram": re.compile(r"instagram\.com/([A-Za-z0-9._]+)", re.I),
    "tiktok": re.compile(r"tiktok\.com/@([A-Za-z0-9._]+)", re.I),
    "twitter": re.compile(r"(?<![a-z0-9])(?:twitter|x)\.com/([A-Za-z0-9_]+)", re.I),
    "facebook": re.compile(r"facebook\.com/([A-Za-z0-9.]+)", re.I),
    "linkedin": re.compile(r"linkedin\.com/(?:in|company)/([A-Za-z0-9-]+)", re.I),
}
NOT_A_WEBSITE = ("youtube.", "youtu.be", "instagram.", "facebook.", "fb.", "twitter.", "x.com", "tiktok.", "linkedin.",
                 "amzn.", "amazon.", "flipkart.", "meesho.", "wa.me", "whatsapp.", "t.me", "telegram.", "play.google.",
                 "apps.apple.", "forms.gle", "docs.google.", "drive.google.", "goo.gl", "bit.ly", "spotify.", "pinterest.",
                 "threads.net", "snapchat.", "discord.")
IGNORED_EMAIL_PARTS = ("example.", "sentry", "wixpress", "noreply", "no-reply", "domain.com", "email.com", "yourname")


def extract_emails(text: str) -> list[str]:
    """Emails as written, including common de-obfuscations like 'name [at] site [dot] com'."""
    t = re.sub(r"\s*[\[(]\s*at\s*[\])]\s*", "@", text or "", flags=re.I)
    t = re.sub(r"\s*[\[(]\s*dot\s*[\])]\s*", ".", t, flags=re.I)
    out = []
    for m in EMAIL_RE.findall(t):
        e = m.strip(".").lower()
        if e.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")) or any(p in e for p in IGNORED_EMAIL_PARTS):
            continue
        if VALID_EMAIL.match(e) and e not in out:
            out.append(e)
    return out


def find_links(text: str) -> tuple[dict, list[str]]:
    urls = [u.rstrip(".,;") for u in URL_RE.findall(text or "")]
    socials = {}
    for name, rx in SOCIAL.items():
        for u in urls:
            m = rx.search(u)
            if m and name not in socials and m.group(1).lower() not in ("p", "reel", "share", "watch", "intent", "sharer", "hashtag"):
                socials[name] = f"https://{urllib.parse.urlparse(u).netloc}/{'@' if name == 'tiktok' else ''}{m.group(1)}"
    hosts = {u: "." + urllib.parse.urlparse(u).netloc.lower() for u in urls}
    sites = [u for u in urls if not any("." + b in hosts[u] for b in NOT_A_WEBSITE)]
    return socials, list(dict.fromkeys(sites))


def website_emails(site: str) -> tuple[list[str], str | None]:
    root = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(site))
    for url in dict.fromkeys([site, root + "/contact", root + "/contact-us"]):
        html = get_text(url)
        if html:
            found = extract_emails(" ".join(re.findall(r"mailto:([^\"'?>\s]+)", html, re.I)) + " " + re.sub(r"<[^>]+>", " ", html))
            if found:
                return found, url
    return [], None


def find_contact(rec: dict) -> dict:
    socials, sites = find_links(rec["description"])
    email, source = NOT_FOUND, None
    if found := extract_emails(rec["description"]):
        email, source = found[0], "YouTube channel description"
    if email == NOT_FOUND:
        for site in sites[:2]:
            found, url = website_emails(site)
            if found:
                email, source = found[0], f"creator website ({url})"
                break
    if email == NOT_FOUND:
        for v in rec["recent_videos"]:
            lines = [ln for ln in v["description"].splitlines() if CONTACT_LINE.search(ln)]
            if found := [e for e in extract_emails("\n".join(lines)) if not INSTITUTIONAL.search(e)]:
                email, source = found[0], f"business line in video description ({v['url']})"
                break
    for v in rec["recent_videos"][:5]:  # socials often only appear in video descriptions
        more, _ = find_links(v["description"])
        socials = {**more, **socials}
    return {"email": email, "email_source": source, "website": sites[0] if sites else None, "socials": socials}


THEME_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "content_themes": {"type": "ARRAY", "items": {"type": "STRING"}},
        "tone": {"type": "STRING"},
        "inferred_audience": {"type": "STRING"},
        "standout_video_title": {"type": "STRING"},
        "standout_reason": {"type": "STRING"},
    },
    "required": ["content_themes", "tone", "inferred_audience", "standout_video_title", "standout_reason"],
}

THEME_SYSTEM = ("You are an influencer-research analyst. Describe a YouTube creator ONLY from the data given. "
                "Never invent facts, numbers, names or collaborations. Keep every field short.")


def content_profile(rec: dict) -> dict:
    """LLM summary of themes/tone from real titles + description; keyword fallback without an API key."""
    titles = [v["title"] for v in rec["recent_videos"]]
    if llm.available() and titles:
        prompt = (f"Channel: {rec['name']}\nDescription: {rec['description'][:1200]}\n"
                  f"Recent video titles (newest first):\n- " + "\n- ".join(titles) +
                  "\n\nReturn: content_themes (3-5 short phrases), tone (3-6 words describing style), "
                  "inferred_audience (one sentence, who this content is for, inferred from topics), "
                  "standout_video_title (copy EXACTLY one title from the list that best represents the channel), "
                  "standout_reason (one short clause).")
        try:
            out = llm.generate_json(THEME_SYSTEM, prompt, THEME_SCHEMA, temperature=0.3)
            if out["standout_video_title"] not in titles:  # guard against a paraphrased/hallucinated title
                out["standout_video_title"] = titles[0]
            out["themes_method"] = "LLM (Gemini) over real titles/description"
            return out
        except llm.LLMError as e:
            print(f"  ! theme extraction fell back to keywords for {rec['name']}: {e}")
    words = Counter(w for t in titles for w in re.findall(r"[a-z]{5,}", t.lower())
                    if w not in {"video", "these", "their", "about", "which", "where", "there", "every", "should", "shorts"})
    return {"content_themes": [w for w, _ in words.most_common(5)], "tone": "Not analysed (no LLM key)",
            "inferred_audience": rec["segment_label"], "standout_video_title": titles[0] if titles else "",
            "standout_reason": "most recent upload", "themes_method": "keyword frequency fallback"}


def enrich(rec: dict) -> dict:
    standout = content_profile(rec)
    return {**rec, **find_contact(rec), **standout,
            "audience_age": NOT_PUBLIC,
            "audience_gender": NOT_PUBLIC,
            "audience_geography": (f"Creator based in {rec['country']}; audience split not public" if rec["country"]
                                   else "Not Available (country not set, audience split not public)")}


def run(campaign: dict, classified: list[dict]) -> list[dict]:
    shortlist = [r for r in classified if r["status"] == "qualified"]
    print(f"Enrichment: {len(shortlist)} shortlisted profiles")
    out = []
    for i, r in enumerate(shortlist, 1):
        e = enrich(r)
        print(f"  [{i}/{len(shortlist)}] {e['name']}: email={e['email']}")
        out.append(e)
    save_stage(campaign, "enriched", out)
    found = sum(e["email"] != NOT_FOUND for e in out)
    print(f"  emails found for {found}/{len(out)}")
    return out
