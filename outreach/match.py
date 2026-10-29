"""Brand-brief engine: semantic match between a plain-English brand brief and every creator's real content.

Creator vectors (Gemini embeddings of name + description + recent titles) are computed once and stored in
data/embeddings.json, so scoring a new brief costs a single embedding call.
"""
import json

from . import llm
from .config import DATA, all_campaigns, load_stage
from .ml import creator_text

STORE = DATA / "embeddings.json"


def _load() -> dict[str, list[float]]:
    return json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {}


def ensure_embeddings(records: list[dict]) -> dict[str, list[float]]:
    store = _load()
    missing = sorted((r for r in records if r["channel_id"] not in store), key=lambda r: r["channel_id"])
    if missing:
        for r, v in zip(missing, llm.embed([creator_text(r) for r in missing])):
            store[r["channel_id"]] = [round(x, 5) for x in v]
        STORE.write_text(json.dumps(store), encoding="utf-8")
    return store


def brief_text(campaign: dict) -> str:
    b = campaign["brand"]
    segs = "; ".join(f"{s['label']}: {', '.join(s['keywords'][:6])}" for s in campaign["segments"].values())
    return f"{b['about']} We want creators who make content about: {segs}."


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # both unit length


def score_brief(brief: str, records: list[dict]) -> list[tuple[dict, float]]:
    store = ensure_embeddings(records)
    q = llm.embed([brief])[0]
    return sorted(((r, cosine(q, store[r["channel_id"]])) for r in records), key=lambda x: -x[1])


def brand_fit(campaign: dict, records: list[dict]) -> None:
    """Adds brand_similarity (cosine), brand_fit (0-100 rank within the shortlist) and final_score in place."""
    if not records:
        return
    ranked = score_brief(brief_text(campaign), records)
    n = len(ranked)
    for i, (r, sim) in enumerate(ranked):
        r["brand_similarity"] = round(sim, 4)
        r["brand_fit"] = round(100 * (n - 1 - i) / (n - 1)) if n > 1 else 100
        r["final_score"] = round(0.75 * r["fit_score"] + 0.25 * r["brand_fit"], 1)


def match_all(brief: str, top: int = 15, min_authenticity: int = 40) -> list[dict]:
    """Rank qualified creators from every niche campaign for an arbitrary brief."""
    pool = []
    for c in all_campaigns():
        try:
            pool += [{**r, "campaign": c["id"], "niche": c["niche"]} for r in load_stage(c, "enriched")]
        except SystemExit:
            continue
    pool = list({r["channel_id"]: r for r in pool}.values())
    out = []
    for r, sim in score_brief(brief, pool):
        if (r.get("authenticity") or 0) < min_authenticity:
            continue
        out.append({"channel_id": r["channel_id"], "name": r["name"], "niche": r["niche"], "segment": r["segment_label"],
                    "profile_url": r["profile_url"], "followers": r["followers"], "engagement_rate": r["engagement_rate"],
                    "email": r["email"], "similarity": round(sim, 4), "content_themes": r.get("content_themes", [])})
        if len(out) == top:
            break
    return out
