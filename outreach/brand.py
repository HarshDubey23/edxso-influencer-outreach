"""Brand plan: turn a plain-English brief into a working campaign (search queries + audience segments).

The owner edits the draft before saving; nothing runs until they switch autopilot on.
"""
import json
import re

from . import llm, workspace
from .config import ROOT, _mirror

SCHEMA = {"type": "OBJECT", "properties": {
    "niche": {"type": "STRING"},
    "queries": {"type": "ARRAY", "items": {"type": "STRING"}},
    "segments": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "label": {"type": "STRING"}, "keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
        "angle_hint": {"type": "STRING"}, "fit_weight": {"type": "NUMBER"}},
        "required": ["label", "keywords", "angle_hint", "fit_weight"]}},
}, "required": ["niche", "queries", "segments"]}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "brand"


def draft(brand: dict, region: str = "IN", language: str = "en") -> dict:
    """brand: {name, about, creator_value: [..], audience}. Returns an unsaved campaign dict."""
    system = ("You plan micro-influencer discovery on YouTube for a brand. Return: niche (2-3 word topic name); "
              "12 long-tail YouTube search queries a creator in this niche would title videos with (specific, in the "
              f"region's common phrasing, region {region}, language {language}); 4-5 audience segments, each with 8-12 "
              "lowercase keywords that appear in such creators' video titles, an angle_hint (one concrete collaboration "
              "idea for that segment using the brand's real offer, no invented numbers) and fit_weight 0.4-1.0 "
              "(how directly that segment's audience buys from the brand).")
    prompt = json.dumps(brand, ensure_ascii=False)
    plan = llm.generate_json(system, prompt, SCHEMA, temperature=0.4)
    niche = slug(plan["niche"])
    return {
        "id": f"{niche}-workspace", "niche": niche, "name": f"{brand['name']} x {plan['niche']} creators",
        "brand": {"name": brand["name"], "about": brand["about"], "creator_value": brand.get("creator_value") or [],
                  "website": brand.get("website", ""), "demo_brand": False},
        "discovery": {"queries": [q.strip() for q in plan["queries"] if q.strip()][:20], "region_code": region,
                      "relevance_language": language},
        "segments": {slug(s["label"]): {"label": s["label"], "keywords": [k.lower() for k in s["keywords"]],
                                         "angle_hint": s["angle_hint"], "fit_weight": max(.3, min(1.0, s["fit_weight"]))}
                     for s in plan["segments"]},
    }


def validate(c: dict) -> list[str]:
    errs = []
    for k in ("id", "niche", "name", "brand", "discovery", "segments"):
        if k not in c:
            errs.append(f"missing {k}")
    if errs:
        return errs
    if not c["brand"].get("name") or not c["brand"].get("about"):
        errs.append("brand needs a name and an about line")
    if not 3 <= len(c["discovery"].get("queries", [])) <= 40:
        errs.append("between 3 and 40 search queries")
    if not c["segments"]:
        errs.append("at least one segment")
    for key, s in c["segments"].items():
        if not s.get("keywords"):
            errs.append(f"segment {key} has no keywords")
    if not re.fullmatch(r"[a-z0-9_-]{3,60}", c["id"]):
        errs.append("id must be lowercase letters, digits, - or _")
    return errs


def save(c: dict) -> str:
    errs = validate(c)
    if errs:
        raise ValueError("; ".join(errs))
    path = ROOT / workspace.get("campaign_file")
    path.write_text(json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")
    _mirror(path)
    workspace.event(f"Campaign saved: {c['name']} ({len(c['discovery']['queries'])} queries, {len(c['segments'])} segments)")
    return str(path)


def load() -> dict | None:
    path = ROOT / workspace.get("campaign_file")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
