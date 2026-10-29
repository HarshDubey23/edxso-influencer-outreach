"""Stage 2 - Filtering & classification.

Every rule produces a check {passed, detail}. A profile is "qualified" only if every hard check passes;
otherwise it is "rejected" and `reasons` lists each failed check in plain English.
Segment = the brand-fit audience segment with the strongest keyword evidence.
"""
import re

from .config import save_stage


def _kw_regex(words):
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w.lower()) for w in words) + r")(?![a-z0-9])")


def relevance(rec: dict, segments: dict) -> dict[str, float]:
    """Keyword evidence per segment. Recent video titles count most: they show what the creator makes *now*."""
    title = rec["name"].lower()
    about = f"{rec['description']} {rec['channel_keywords']}".lower()
    titles = [v["title"].lower() for v in rec["recent_videos"]]
    scores = {}
    for key, seg in segments.items():
        rx = _kw_regex(seg["keywords"])
        s = 2 * bool(rx.search(title)) + min(4, len(set(rx.findall(about))))
        s += sum(1 for t in titles if rx.search(t))
        scores[key] = float(s)
    return scores


def classify(rec: dict, campaign: dict) -> dict:
    f, segments = campaign["filters"], campaign["segments"]
    checks = {}

    def check(name, passed, detail):
        checks[name] = {"passed": bool(passed), "detail": detail}

    n = rec["followers"]
    if n is None:
        check("followers", False, "subscriber count is hidden")
    else:
        check("followers", f["followers"]["min"] <= n <= f["followers"]["max"],
              f"{n:,} followers (range {f['followers']['min']:,}-{f['followers']['max']:,})")

    er = rec["engagement_rate"]
    if checks["followers"]["passed"]:
        check("engagement", er is not None and er >= f["min_engagement_rate"],
              "engagement not measurable (no recent videos with public likes)" if er is None
              else f"engagement {er}% (min {f['min_engagement_rate']}%)")
        check("sample_size", rec["videos_sampled"] >= f["min_videos_sampled"],
              f"{rec['videos_sampled']} recent videos sampled (min {f['min_videos_sampled']})")
        d = rec["days_since_upload"]
        check("active", d is not None and d <= f["max_days_since_upload"],
              "no uploads found" if d is None else f"last upload {d} days ago (max {f['max_days_since_upload']})")

    scores = relevance(rec, segments)
    weighted = {k: v * segments[k]["fit_weight"] for k, v in scores.items()}
    seg = max(weighted, key=weighted.get)
    rel = scores[seg]
    # Videos are only fetched near the follower range; judging niche without titles would mislabel the reason.
    if rec["recent_videos"]:
        check("niche_relevance", rel >= f["min_relevance"],
              f"relevance {rel:g} for '{segments[seg]['label']}' (min {f['min_relevance']})")

    if f.get("exclude_made_for_kids"):
        check("audience_not_children", not rec["made_for_kids"],
              "channel is 'made for kids' (audience is children, not parents/educators)" if rec["made_for_kids"]
              else "audience is not flagged as children")

    text = " ".join([rec["name"], rec["description"], rec["channel_keywords"]] + [v["title"] for v in rec["recent_videos"]]).lower()
    unsafe = sorted(set(_kw_regex(f["brand_safety_blocklist"]).findall(text)))
    check("brand_safety", not unsafe, f"blocklisted terms: {', '.join(unsafe)}" if unsafe else "no blocklisted terms")

    org = sorted(set(_kw_regex(f["organization_markers"]).findall(rec["name"].lower())))
    check("individual_creator", not org,
          f"name looks like an institution/media brand ({', '.join(org)})" if org else "individual creator")

    geo_pref = rec["country"] in f["preferred_countries"]
    qualified = all(c["passed"] for c in checks.values())

    # Fit score (0-100) ranks the shortlist; it never overrides a failed hard check.
    fit = 0.0
    if qualified:
        fit = (40 * min(rel / 10, 1) + 25 * min((er or 0) / 6, 1)
               + 15 * min((rec["views_to_followers"] or 0) / 40, 1)
               + 10 * segments[seg]["fit_weight"] + 10 * geo_pref)

    return {**rec,
            "status": "qualified" if qualified else "rejected",
            "segment": seg,
            "segment_label": segments[seg]["label"],
            "relevance_score": rel,
            "geo_preferred": geo_pref,
            "fit_score": round(fit, 1),
            "checks": checks,
            "reasons": [c["detail"] for c in checks.values() if not c["passed"]]}


def run(campaign: dict, discovered: list[dict]) -> list[dict]:
    out = sorted((classify(r, campaign) for r in discovered),
                 key=lambda r: (r["status"] != "qualified", -r["fit_score"], r["name"].lower()))
    save_stage(campaign, "classified", out)
    q = sum(r["status"] == "qualified" for r in out)
    print(f"Classification: {q} qualified, {len(out) - q} rejected (of {len(out)})")
    return out
