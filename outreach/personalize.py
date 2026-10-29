"""Stage 4 - AI personalization: one email pitch (60-90 words) + one Instagram DM (15-30 words) per creator.

Each message is generated from that creator's own signals (segment, themes, tone, a real recent video),
then checked by `validate`. Failures are fed back to the model (up to 3 attempts); anything still failing
is marked `needs_review` and is never auto-sent. That is the human Review gate.
"""
import re

from . import llm
from .config import env, save_stage

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


def system_prompt(campaign: dict, sender: str) -> str:
    b = campaign["brand"]
    return f"""You write creator-partnership outreach for {b['name']}.
About {b['name']}: {b['about']}
What creators get: {'; '.join(b['creator_value'])}.

Write like a thoughtful human partnerships manager, not a marketer. Rules:
- greeting_name: the creator's first name if the channel name clearly contains a person's name, else the channel name.
- email_body: 60-90 words TOTAL, including the greeting line and the sign-off "{sender}". Plain text, no emojis, no links.
  It must (1) open by referencing ONE specific recent video by its title or a concrete theme, in your own words,
  (2) say why their audience matters to {b['name']}, (3) propose the given collaboration angle concretely,
  (4) state what is in it for the creator, (5) end with a low-pressure ask (e.g. a 15-minute call).
- instagram_dm: 15-30 words, casual and warm, one specific content reference, the angle in a few words, no links,
  at most one emoji. It must NOT reuse the email's opening sentence.
- email_subject: under 9 words, specific to the creator, no clickbait.
- collaboration_angle: exactly one of the allowed angles.
- personalization_signals: the 2-4 creator-specific facts you used.
- Use ONLY facts given. Never invent numbers, past collaborations, awards, locations or personal details.
  Do not quote follower counts or engagement rates. No placeholders like [Name]."""


def user_prompt(rec: dict, campaign: dict, feedback: list[str] | None) -> str:
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
    if (msg["greeting_name"].split() or ["<none>"])[0].lower() not in msg["email_body"].lower():
        problems.append("email does not greet the creator by name")
    signals = _tokens(" ".join([rec["standout_video_title"], *rec["content_themes"],
                                *(v["title"] for v in rec["recent_videos"][:3])]))
    if len(_tokens(msg["email_body"]) & signals) < 2:
        problems.append("email does not reference the creator's actual content (recent video or theme)")
    if not _tokens(msg["instagram_dm"]) & signals:
        problems.append("DM does not reference the creator's actual content")
    if re.search(r"\d[\d,.]*\s*(k|subscribers|followers|%)", (msg["email_body"] + msg["instagram_dm"]).lower()):
        problems.append("must not quote follower counts or engagement numbers")
    return problems


def personalize(rec: dict, campaign: dict, sender: str, attempts: int = 3) -> dict:
    feedback, msg = None, None
    for attempt in range(1, attempts + 1):
        msg = llm.generate_json(system_prompt(campaign, sender), user_prompt(rec, campaign, feedback), SCHEMA,
                                temperature=0.9)
        feedback = validate(msg, rec, campaign)
        if not feedback:
            break
    return {"channel_id": rec["channel_id"], "influencer": rec["name"], "email": rec["email"], **msg,
            "email_words": words(msg["email_body"]), "dm_words": words(msg["instagram_dm"]),
            "attempts": attempt, "validation_issues": feedback,
            "review_status": "approved" if not feedback else "needs_review",
            "model": env("GEMINI_MODEL", "gemini-2.5-flash")}


def run(campaign: dict, enriched: list[dict], limit: int | None = None) -> list[dict]:
    if not llm.available():
        raise SystemExit("GEMINI_API_KEY is not set: personalization needs an LLM (see README).")
    sender = env("SENDER_NAME", "Partnerships Team, EDXSO")
    targets = enriched[:limit] if limit else enriched
    print(f"Personalization: generating messages for {len(targets)} creators with {env('GEMINI_MODEL', 'gemini-2.5-flash')}")
    out = []
    for i, rec in enumerate(targets, 1):
        try:
            m = personalize(rec, campaign, sender)
        except llm.LLMError as e:
            m = {"channel_id": rec["channel_id"], "influencer": rec["name"], "email": rec["email"],
                 "review_status": "generation_failed", "validation_issues": [str(e)]}
        print(f"  [{i}/{len(targets)}] {rec['name']}: {m['review_status']}")
        out.append(m)
    save_stage(campaign, "messages", out)
    ok = sum(m["review_status"] == "approved" for m in out)
    print(f"  {ok}/{len(out)} approved automatically, {len(out) - ok} need review")
    return out
