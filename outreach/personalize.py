"""Stage 4 - AI personalization: one email pitch (60-90 words) + one Instagram DM (15-30 words) per creator.

Each message is generated from that creator's own signals (segment, themes, tone, a real recent video),
then checked by `validate`. Failures are fed back to the model (up to 3 attempts); anything still failing
is marked `needs_review` and is never auto-sent. That is the human Review gate.
"""
import re
from collections import Counter

from . import llm
from .config import env, save_stage

GENERIC_DM_OPENER = re.compile(r"\s*(hello|hi|hey)\s*[!,.]|\s*(loved?|really loved?) your\b", re.I)
STOP = set("the a an and or of to in for on with your you my our is are how what why this that from at by be it as "
           "can do i we will all into about not but so if no its it's new top best tips video part".split())

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "greeting_name": {"type": "STRING"},
        "collaboration_angle": {"type": "STRING"},
        "personalization_signals": {"type": "ARRAY", "items": {"type": "STRING"}},
        "email_subject": {"type": "STRING"},
        "email_body": {"type": "STRING"},
        "instagram_dm": {"type": "STRING"},
    },
    "required": ["greeting_name", "collaboration_angle", "personalization_signals", "email_subject", "email_body", "instagram_dm"],
}


def schema_for(campaign: dict) -> dict:
    """The angle is an enum of the campaign's allowed angles, so the model cannot return a free-text variant."""
    props = {**SCHEMA["properties"], "collaboration_angle": {"type": "STRING", "enum": campaign["collaboration_angles"]}}
    return {**SCHEMA, "properties": props}


def system_prompt(campaign: dict, sender: str) -> str:
    b = campaign["brand"]
    return f"""You write creator-partnership outreach for {b['name']}.
About {b['name']}: {b['about']}
What creators get: {'; '.join(b['creator_value'])}.

Write like a thoughtful human partnerships manager, not a marketer. Rules:
- greeting_name: the creator's first name if the channel name clearly contains a person's name, else the channel name.
- email_body: aim for 70-80 words (hard limits 60-90) TOTAL, including the greeting line and the sign-off "{sender}". Plain text, no emojis, no links.
  It must (1) open by referencing ONE specific recent video by its title or a concrete theme, in your own words,
  (2) say why their audience matters to {b['name']}, (3) propose the given collaboration angle concretely,
  (4) state what is in it for the creator, (5) end with a low-pressure ask (e.g. a 15-minute call).
- instagram_dm: aim for 20-25 words (hard limits 15-30), casual and warm, one specific content reference, the angle in a few words, no links,
  at most one emoji. It must NOT reuse the email's opening sentence. Open with the creator's name or straight
  into their specific video/topic, never with a generic "Hello!", "Hi!", "Hey!", "Loved your" or "Love your".
- email_subject: under 9 words, specific to the creator, no clickbait.
- collaboration_angle: exactly one of the allowed angles.
- personalization_signals: the 2-4 creator-specific facts you used.
- Use ONLY facts given. Never invent numbers, past collaborations, awards, locations or personal details.
  Do not quote follower counts or engagement rates. No placeholders like [Name]."""


def user_prompt(rec: dict, campaign: dict, feedback: list[str] | None, avoid: list[str] = (),
                angles_used: dict | None = None) -> str:
    seg = campaign["segments"][rec["segment"]]
    recent = rec["recent_videos"][0] if rec["recent_videos"] else None
    lines = [
        f"Channel name: {rec['name']}",
        f"Platform: YouTube ({rec['profile_url']})",
        f"Audience segment: {seg['label']}",
        f"Content themes: {', '.join(rec['content_themes'])}",
        f"Tone/style: {rec['tone']}",
        f"Who the content is for: {rec['inferred_audience']}",
        f"Standout recent video: \"{rec['standout_video_title']}\" ({rec['standout_reason']})",
    ]
    if recent and recent["title"] != rec["standout_video_title"]:
        lines.append(f"Latest upload: \"{recent['title']}\" ({recent['published_at'][:10]})")
    if rec["country"]:
        lines.append(f"Creator country: {rec['country']}")
    lines += [f"Suggested collaboration angle: {seg['angle_hint']}",
              f"Allowed angles: {', '.join(campaign['collaboration_angles'])}"]
    if angles_used:  # nudge the batch toward the full range of angles the brief lists
        lines.append("Angles already pitched in this batch: " + ", ".join(f"{k} x{v}" for k, v in angles_used.items())
                     + ". Prefer a less-used angle when it genuinely fits this creator.")
    if avoid:  # phrasings already used for other creators -> forces genuinely different messages
        lines.append("\nOther creators already received messages using these phrasings. Do NOT reuse them, "
                     "write different openings and closing asks:\n- " + "\n- ".join(avoid))
    if feedback:
        lines.append("\nYour previous draft broke these rules, fix all of them:\n- " + "\n- ".join(feedback))
    return "\n".join(lines)


def words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) > 3 and w not in STOP}


def validate(msg: dict, rec: dict, campaign: dict) -> list[str]:
    problems = []
    ew, dw = words(msg["email_body"]), words(msg["instagram_dm"])
    if not 60 <= ew <= 90:
        problems.append(f"email_body has {ew} words, must be 60-90")
    if not 15 <= dw <= 30:
        problems.append(f"instagram_dm has {dw} words, must be 15-30")
    if re.search(r"\[[^\]]*\]|\{[^}]*\}", msg["email_body"] + msg["instagram_dm"]):
        problems.append("contains a placeholder in brackets")
    if msg["collaboration_angle"] not in campaign["collaboration_angles"]:
        problems.append(f"collaboration_angle must be one of: {', '.join(campaign['collaboration_angles'])}")
    greet = (msg["greeting_name"].split() or ["<none>"])[0].lower().strip(",!")
    if greet not in rec["name"].lower() or greet not in msg["email_body"].lower():
        problems.append(f"email must greet the creator by a name taken from the channel name '{rec['name']}'")
    if GENERIC_DM_OPENER.match(msg["instagram_dm"]):
        problems.append("DM opens generically (Hello!/Hi!/Loved your...); open with their name or their specific video")
    signals = _tokens(" ".join([rec["standout_video_title"], *rec["content_themes"],
                                *(v["title"] for v in rec["recent_videos"][:3])]))
    if len(_tokens(msg["email_body"]) & signals) < 2:
        problems.append("email does not reference the creator's actual content (recent video or theme)")
    if not _tokens(msg["instagram_dm"]) & signals:
        problems.append("DM does not reference the creator's actual content")
    if re.search(r"\d[\d,.]*\s*(k|subscribers|followers|%)\b", (msg["email_body"] + msg["instagram_dm"]).lower()):
        problems.append("must not quote follower counts or engagement numbers")
    return problems


def used_phrasings(m: dict) -> list[str]:
    """Opening of the email after the greeting, its closing ask, and the DM opening."""
    sentences = re.split(r"(?<=[.!?])\s+", m["email_body"])
    body = [s for s in sentences if not s.lower().startswith(("hi ", "hello ", "dear "))]
    picks = [" ".join(body[0].split()[:7])] if body else []
    asks = [s for s in sentences if s.endswith("?")]
    return picks + asks[-1:] + [" ".join(m["instagram_dm"].split()[:6])]


def personalize(rec: dict, campaign: dict, sender: str, attempts: int = 3, avoid: list[str] = (),
                angles_used: dict | None = None) -> dict:
    feedback, msg = None, None
    for attempt in range(1, attempts + 1):
        msg = llm.generate_json(system_prompt(campaign, sender), user_prompt(rec, campaign, feedback, avoid, angles_used), schema_for(campaign),
                                temperature=0.9)
        feedback = validate(msg, rec, campaign)
        if not feedback:
            break
    return {"channel_id": rec["channel_id"], "influencer": rec["name"], "email": rec["email"], **msg,
            "email_words": words(msg["email_body"]), "dm_words": words(msg["instagram_dm"]),
            "attempts": attempt, "validation_issues": feedback,
            "review_status": "approved" if not feedback else "needs_review",
            "model": env("GEMINI_MODEL", "gemini-3.5-flash-lite")}


def run(campaign: dict, enriched: list[dict], limit: int | None = None, keep: list[dict] | None = None,
        sender_name: str | None = None) -> list[dict]:
    """keep: existing messages to preserve as-is (human edits/approvals survive scheduled re-runs); only new creators are written."""
    if not llm.available():
        raise SystemExit("GEMINI_API_KEY is not set: personalization needs an LLM (see README).")
    sender = sender_name or env("SENDER_NAME", f"Partnerships Team, {campaign['brand']['name']}")
    kept = {m["channel_id"]: m for m in (keep or []) if m.get("review_status") != "generation_failed"}
    targets = [r for r in enriched if r["channel_id"] not in kept]
    targets = targets[:limit] if limit else targets
    print(f"Personalization: generating messages for {len(targets)} creators with {env('GEMINI_MODEL', 'gemini-2.5-flash')}")
    out = list(kept.values())
    avoid = [p for m in out if m.get("review_status") == "approved" for p in used_phrasings(m)]
    angles = Counter(m.get("collaboration_angle") for m in out if m.get("review_status") == "approved")
    for i, rec in enumerate(targets, 1):
        try:
            m = personalize(rec, campaign, sender, avoid=avoid[-12:], angles_used=dict(angles))
            if m["review_status"] == "approved":
                avoid += used_phrasings(m)
                angles[m["collaboration_angle"]] += 1
        except llm.LLMError as e:
            m = {"channel_id": rec["channel_id"], "influencer": rec["name"], "email": rec["email"],
                 "review_status": "generation_failed", "validation_issues": [str(e)]}
        print(f"  [{i}/{len(targets)}] {rec['name']}: {m['review_status']}")
        out.append(m)
    save_stage(campaign, "messages", out)
    ok = sum(m["review_status"] == "approved" for m in out)
    print(f"  {ok}/{len(out)} approved automatically, {len(out) - ok} need review")
    return out
