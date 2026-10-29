"""Stage 6 - Exports: per-campaign CSVs, combined all-niche CSVs, and the dashboard payload (dashboard/data.json)."""
import csv
import json
from collections import Counter
from datetime import datetime, timezone

from .config import OUTPUT, ROOT, all_campaigns, load_stage
from .sender import connect

DASH_DATA = ROOT / "dashboard" / "data.json"


def _csv(path, rows, fallback):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel opens UTF-8 names correctly
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else fallback, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _na(v, suffix=""):
    return "Not Available" if v is None else f"{v}{suffix}"


def dataset_rows(c, classified, enriched):
    by_id = {r["channel_id"]: r for r in enriched}
    return [{
        "Name": r["name"], "Platform": r["platform"], "Profile URL": r["profile_url"], "Campaign Niche": c["niche"],
        "Followers": _na(r["followers"]), "Engagement Rate (%)": _na(r["engagement_rate"]),
        "Median Views (recent)": _na(r.get("median_views")), "Segment": r["segment_label"],
        "ML Niche (hybrid)": r.get("ml_niche") or "Not Available", "ML Confidence": _na(r.get("ml_confidence")),
        "Authenticity (0-100)": _na(r.get("authenticity")), "Authenticity Flags": " | ".join(r.get("authenticity_flags") or []),
        "Country": r["country"] or "Not Available",
        "Email": by_id.get(r["channel_id"], {}).get("email", "Not enriched (rejected)"),
        "Content Themes": "; ".join(by_id.get(r["channel_id"], {}).get("content_themes", [])) or
                          "; ".join(v["title"] for v in r["recent_videos"][:2]) or "Not Available",
        "Status": r["status"].upper(), "Final Score": by_id.get(r["channel_id"], {}).get("final_score", r["fit_score"]),
        "Reasons (if rejected)": " | ".join(r["reasons"]), "Last Upload": _na(r["last_upload"]),
        "Discovered Via": "; ".join(r["discovered_via"]),
    } for r in classified]


def shortlist_rows(c, enriched):
    return [{
        "Influencer Name": r["name"], "Platform": r["platform"], "Profile URL": r["profile_url"], "Campaign Niche": c["niche"],
        "Follower Count": r["followers"], "Engagement Rate (%)": r["engagement_rate"],
        "Category / Niche": r["segment_label"], "Content Themes": "; ".join(r["content_themes"]), "Tone": r["tone"],
        "Contact Email": r["email"], "Email Source": r["email_source"] or "-",
        "Instagram": r["socials"].get("instagram", "Not Found"), "TikTok": r["socials"].get("tiktok", "Not Found"),
        "YouTube": r["profile_url"], "Website": r["website"] or "Not Found",
        "Audience Age": r["audience_age"], "Audience Gender": r["audience_gender"],
        "Audience Geography": r["audience_geography"], "Inferred Audience": r["inferred_audience"],
        "Standout Video": r["standout_video_title"], "Authenticity": _na(r.get("authenticity")),
        "Brand Fit (semantic, 0-100)": _na(r.get("brand_fit")), "Final Score": r.get("final_score", r["fit_score"]),
    } for r in enriched]


def message_rows(c, messages):
    return [{
        "Influencer": m["influencer"], "Campaign Niche": c["niche"], "Brand": c["brand"]["name"], "Email": m.get("email"),
        "Angle": m.get("collaboration_angle"), "Subject": m.get("email_subject"), "Email Pitch": m.get("email_body"),
        "Email Words": m.get("email_words"), "Instagram DM": m.get("instagram_dm"), "DM Words": m.get("dm_words"),
        "Signals Used": "; ".join(m.get("personalization_signals", [])), "Review Status": m["review_status"],
        "Issues": " | ".join(m.get("validation_issues") or []),
    } for m in messages]


def tracker_rows(log, msg_ids):
    return [{
        "Influencer": r["influencer"], "Campaign": r["campaign_id"], "Email": r["email"] or "-", "Channel": r["kind"],
        "Message Generated": "Yes" if r["channel_id"] in msg_ids else "No",
        "Sent": "Yes" if r["status"] in ("sent", "test_sent", "dm_sent_manual") else
                "Simulated" if r["status"] == "simulated" else "No",
        "Date": r["created_at"], "Status": r["status"], "Mode": r["mode"], "Delivered To": "operator's test inbox" if r["mode"] == "test" else r["delivered_to"],
        "Transport": r["transport"], "Error": r["error"] or "",
    } for r in log]


def _stages(c):
    out = []
    for s in ("classified", "enriched", "messages"):
        try:
            out.append(load_stage(c, s))
        except SystemExit:
            out.append([])
    return out


def run(campaign: dict, classified: list[dict], enriched: list[dict], messages: list[dict]) -> None:
    d = OUTPUT / campaign["id"]
    log = [dict(r) for r in connect().execute("SELECT * FROM outreach_log WHERE campaign_id=? ORDER BY id", (campaign["id"],))]
    _csv(d / "influencers_dataset.csv", dataset_rows(campaign, classified, enriched), ["Name"])
    _csv(d / "shortlist_enriched.csv", shortlist_rows(campaign, enriched), ["Influencer Name"])
    _csv(d / "personalized_messages.csv", message_rows(campaign, messages), ["Influencer"])
    _csv(d / "outreach_tracker.csv", tracker_rows(log, {m["channel_id"] for m in messages}), ["Influencer"])
    print(f"Exports written to {d}")


def combined() -> None:
    """All niches in one place: output/ALL_*.csv and the dashboard payload."""
    rows = {"dataset": [], "shortlist": [], "messages": []}
    msg_ids = set()
    for c in all_campaigns():
        classified, enriched, messages = _stages(c)
        rows["dataset"] += dataset_rows(c, classified, enriched)
        rows["shortlist"] += shortlist_rows(c, enriched)
        rows["messages"] += message_rows(c, messages)
        msg_ids |= {m["channel_id"] for m in messages}
    log = [dict(r) for r in connect().execute("SELECT * FROM outreach_log ORDER BY id")]
    _csv(OUTPUT / "ALL_influencers_dataset.csv", rows["dataset"], ["Name"])
    _csv(OUTPUT / "ALL_shortlist_enriched.csv", rows["shortlist"], ["Influencer Name"])
    _csv(OUTPUT / "ALL_personalized_messages.csv", rows["messages"], ["Influencer"])
    _csv(OUTPUT / "ALL_outreach_tracker.csv", tracker_rows(log, msg_ids), ["Influencer"])
    DASH_DATA.write_text(json.dumps(dashboard_data(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Combined exports written to {OUTPUT} and {DASH_DATA}")


def _mask(email):
    if not email or "@" not in email:
        return email
    user, domain = email.split("@", 1)
    return f"{user[:2]}{'*' * max(len(user) - 2, 3)}@{domain}"


def build_site() -> None:
    """Static public build in site/: same dashboard, read-only, emails masked so the page can't be scraped for contacts."""
    import shutil
    site = ROOT / "site"
    shutil.rmtree(site, ignore_errors=True)
    site.mkdir()
    for f in ("index.html", "landing.css", "landing.js", "app.html", "app.js", "model.js", "style.css"):
        shutil.copy(ROOT / "dashboard" / f, site / f)
    shutil.copy(ROOT / "models" / "niche_classifier_web.json", site / "niche_classifier_web.json")
    d = dashboard_data()
    for c in d["creators"]:
        c["email"] = _mask(c["email"])
    for m in d["messages"]:
        m["email"] = _mask(m["email"])
    for t in d["tracker"]:
        t["delivered_to"] = "operator's test inbox" if t["mode"] == "test" else _mask(t["delivered_to"])
    for ex in d["examples"].get("ask", []) + d["examples"].get("match", []):
        for r in ex["results"]:
            r["email"] = _mask(r.get("email"))
    (site / "data.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Static site written to {site}")


def dashboard_data() -> dict:
    db = connect()
    log = [dict(r) for r in db.execute("SELECT campaign_id, channel_id, influencer, kind, mode, status, delivered_to, "
                                       "transport, created_at, error FROM outreach_log ORDER BY id")]
    for t in log:  # the operator's own inbox never needs to be in an exported file
        if t["mode"] == "test":
            t["delivered_to"] = "operator's test inbox"
    reply_rows = [dict(r) for r in db.execute("SELECT campaign_id, channel_id, intent, summary, created_at FROM replies")]
    camps, creators, messages = [], [], []
    for c in all_campaigns():
        classified, enriched, msgs = _stages(c)
        en = {r["channel_id"]: r for r in enriched}
        statuses = Counter(r["status"] for r in log if r["campaign_id"] == c["id"])
        camps.append({
            "id": c["id"], "niche": c["niche"], "name": c["name"],
            "brand": {k: c["brand"].get(k) for k in ("name", "about", "demo_brand", "website")},
            "funnel": {"discovered": len(classified),
                       "in_range": sum(r["checks"]["followers"]["passed"] for r in classified),
                       "qualified": len(enriched), "with_email": sum(r["email"] != "Not Found" for r in enriched),
                       "messages_approved": sum(m["review_status"] == "approved" for m in msgs),
                       "emails_logged": sum(v for k, v in statuses.items() if k in ("simulated", "test_sent", "sent")),
                       "dms_queued": statuses.get("dm_queued_manual", 0)},
            "rejections": Counter(k for r in classified if r["status"] == "rejected"
                                  for k, ch in r["checks"].items() if not ch["passed"]),
            "segments": {k: s["label"] for k, s in c["segments"].items()},
        })
        for r in classified:
            e = en.get(r["channel_id"], {})
            creators.append({
                "id": r["channel_id"], "campaign": c["id"], "niche": c["niche"], "name": r["name"], "url": r["profile_url"],
                "followers": r["followers"], "er": r["engagement_rate"], "median_views": r.get("median_views"),
                "reach": r["views_to_followers"], "country": r["country"], "status": r["status"], "reasons": r["reasons"],
                "checks": r["checks"], "segment": r["segment_label"], "ml_niche": r.get("ml_niche"),
                "ml_conf": r.get("ml_confidence"), "ml_probs": r.get("ml_probs", {}),
                "auth": r.get("authenticity"), "auth_flags": r.get("authenticity_flags", []),
                "last_upload": r["last_upload"], "titles": [v["title"] for v in r["recent_videos"][:4]],
                "score": e.get("final_score", r["fit_score"]), "brand_fit": e.get("brand_fit"),
                "email": e.get("email"), "email_source": e.get("email_source"), "socials": e.get("socials", {}),
                "website": e.get("website"), "themes": e.get("content_themes", []), "tone": e.get("tone"),
                "standout": e.get("standout_video_title"), "audience": e.get("inferred_audience"),
            })
        for m in msgs:
            messages.append({"campaign": c["id"], "niche": c["niche"], "brand": c["brand"]["name"], "id": m["channel_id"],
                             "influencer": m["influencer"], "email": m.get("email"), "subject": m.get("email_subject"),
                             "body": m.get("email_body"), "dm": m.get("instagram_dm"), "angle": m.get("collaboration_angle"),
                             "signals": m.get("personalization_signals", []), "status": m["review_status"],
                             "issues": m.get("validation_issues") or [], "email_words": m.get("email_words"),
                             "dm_words": m.get("dm_words"), "edited": m.get("edited_by_human", False)})
    metrics_path = ROOT / "models" / "metrics.json"
    examples_path = ROOT / "data" / "demo_examples.json"
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "campaigns": camps, "creators": creators, "messages": messages, "tracker": log, "replies": reply_rows,
            "model": json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else None,
            "examples": json.loads(examples_path.read_text(encoding="utf-8")) if examples_path.exists() else {}}
