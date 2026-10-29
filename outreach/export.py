"""Stage 6 - Exports: dataset CSV, shortlist CSV, messages CSV, outreach tracker CSV and an HTML review report."""
import csv
import html
from collections import Counter

from .config import OUTPUT
from .sender import connect


def _csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel opens UTF-8 names correctly
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _na(v, suffix=""):
    return "Not Available" if v is None else f"{v}{suffix}"


def run(campaign: dict, classified: list[dict], enriched: list[dict], messages: list[dict]) -> None:
    by_id = {r["channel_id"]: r for r in enriched}
    msg_by_id = {m["channel_id"]: m for m in messages}

    dataset = [{
        "Name": r["name"], "Platform": r["platform"], "Profile URL": r["profile_url"],
        "Followers": _na(r["followers"]), "Engagement Rate (%)": _na(r["engagement_rate"]),
        "Avg Views (recent)": _na(r["avg_views"]), "Niche / Segment": r["segment_label"],
        "Relevance Score": r["relevance_score"], "Country": r["country"] or "Not Available",
        "Email": by_id.get(r["channel_id"], {}).get("email", "Not enriched (rejected)"),
        "Content Themes": "; ".join(by_id.get(r["channel_id"], {}).get("content_themes", [])) or
                          "; ".join(v["title"] for v in r["recent_videos"][:2]) or "Not Available",
        "Status": r["status"].upper(), "Fit Score": r["fit_score"],
        "Reasons (if rejected)": " | ".join(r["reasons"]), "Last Upload": _na(r["last_upload"]),
        "Discovered Via": "; ".join(r["discovered_via"]),
    } for r in classified]
    _csv(OUTPUT / "influencers_dataset.csv", dataset, list(dataset[0]) if dataset else ["Name"])

    shortlist = [{
        "Influencer Name": r["name"], "Platform": r["platform"], "Profile URL": r["profile_url"],
        "Follower Count": r["followers"], "Engagement Rate (%)": r["engagement_rate"],
        "Category / Niche": r["segment_label"], "Content Themes": "; ".join(r["content_themes"]),
        "Tone": r["tone"], "Contact Email": r["email"], "Email Source": r["email_source"] or "-",
        "Instagram": r["socials"].get("instagram", "Not Found"), "TikTok": r["socials"].get("tiktok", "Not Found"),
        "YouTube": r["profile_url"], "Website": r["website"] or "Not Found",
        "Audience Age": r["audience_age"], "Audience Gender": r["audience_gender"],
        "Audience Geography": r["audience_geography"], "Inferred Audience": r["inferred_audience"],
        "Standout Video": r["standout_video_title"], "Fit Score": r["fit_score"],
    } for r in enriched]
    _csv(OUTPUT / "shortlist_enriched.csv", shortlist, list(shortlist[0]) if shortlist else ["Influencer Name"])

    msgs = [{
        "Influencer": m["influencer"], "Email": m.get("email"), "Angle": m.get("collaboration_angle"),
        "Subject": m.get("email_subject"), "Email Pitch": m.get("email_body"), "Email Words": m.get("email_words"),
        "Instagram DM": m.get("instagram_dm"), "DM Words": m.get("dm_words"),
        "Signals Used": "; ".join(m.get("personalization_signals", [])), "Review Status": m["review_status"],
        "Issues": " | ".join(m.get("validation_issues") or []),
    } for m in messages]
    _csv(OUTPUT / "personalized_messages.csv", msgs, list(msgs[0]) if msgs else ["Influencer"])

    db = connect()
    log = [dict(r) for r in db.execute("SELECT * FROM outreach_log WHERE campaign_id=? ORDER BY id", (campaign["id"],))]
    tracker = [{
        "Influencer": r["influencer"], "Email": r["email"] or "-", "Channel": r["kind"],
        "Message Generated": "Yes" if r["channel_id"] in msg_by_id else "No",
        "Sent": "Yes" if r["status"] in ("sent", "test_sent", "dm_sent_manual") else
                "Simulated" if r["status"] == "simulated" else "No",
        "Date": r["created_at"], "Status": r["status"], "Mode": r["mode"], "Delivered To": r["delivered_to"],
        "Transport": r["transport"], "Error": r["error"] or "",
    } for r in log]
    _csv(OUTPUT / "outreach_tracker.csv", tracker, list(tracker[0]) if tracker else ["Influencer"])

    _report(campaign, classified, enriched, messages, log)
    print(f"Exports written to {OUTPUT}")


def _report(campaign, classified, enriched, messages, log):
    e = html.escape
    rej = [r for r in classified if r["status"] == "rejected"]
    reason_counts = Counter(k for r in rej for k, c in r["checks"].items() if not c["passed"])
    emails = sum(r["email"] != "Not Found" for r in enriched)
    approved = sum(m["review_status"] == "approved" for m in messages)
    status_counts = Counter(r["status"] for r in log)
    by_id = {r["channel_id"]: r for r in enriched}

    cards = []
    for m in messages:
        r = by_id.get(m["channel_id"], {})
        cards.append(f"""<article class="card">
<header><a href="{e(r.get('profile_url', '#'))}">{e(m['influencer'])}</a>
<span class="pill">{e(r.get('segment_label', ''))}</span><span class="pill {e(m['review_status'])}">{e(m['review_status'])}</span></header>
<p class="meta">{_na(r.get('followers'))} followers &middot; ER {_na(r.get('engagement_rate'), '%')} &middot; {e(r.get('email', ''))}
&middot; themes: {e(', '.join(r.get('content_themes', [])))}</p>
<h4>{e(m.get('email_subject') or '')} <small>({m.get('email_words', '-')} words &middot; {e(m.get('collaboration_angle') or '')})</small></h4>
<pre>{e(m.get('email_body') or '')}</pre>
<h4>Instagram DM <small>({m.get('dm_words', '-')} words)</small></h4><pre>{e(m.get('instagram_dm') or '')}</pre>
{'<p class="warn">' + e(' | '.join(m['validation_issues'])) + '</p>' if m.get('validation_issues') else ''}
</article>""")

    rows = "".join(f"<tr><td><a href='{e(r['profile_url'])}'>{e(r['name'])}</a></td><td>{_na(r['followers'])}</td>"
                   f"<td>{_na(r['engagement_rate'])}</td><td>{e(r['segment_label'])}</td>"
                   f"<td class='{r['status']}'>{r['status']}</td><td>{e(' | '.join(r['reasons']) or 'all checks passed')}</td></tr>"
                   for r in classified)
    logrows = "".join(f"<tr><td>{e(r['influencer'] or '')}</td><td>{e(r['kind'])}</td><td>{e(r['mode'])}</td>"
                      f"<td>{e(r['status'])}</td><td>{e(r['delivered_to'] or '')}</td><td>{e(r['created_at'])}</td></tr>" for r in log)
    stats = [("Discovered", len(classified)), ("Qualified", len(enriched)), ("Emails found", f"{emails}/{len(enriched)}"),
             ("Messages approved", f"{approved}/{len(messages)}"),
             *((k.replace('_', ' ').title(), v) for k, v in status_counts.items())]
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Outreach Review Report</title><style>
:root{{--bg:#f7f7f5;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#e3e3de;--ok:#1f7a4d;--bad:#b3261e;--acc:#2f4fd8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ececea;--mut:#a3a39e;--card:#1f1f1d;--line:#33332f;--ok:#5fcf98;--bad:#ff8a80;--acc:#8ea2ff}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}main{{max-width:1100px;margin:auto;padding:24px 16px}}
h1{{margin:0 0 4px}}.sub{{color:var(--mut);margin:0 0 20px}}.stats{{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:24px}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}}.stat b{{display:block;font-size:22px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:14px}}
.card header{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-weight:600}}a{{color:var(--acc)}}
.pill{{font-size:12px;border:1px solid var(--line);border-radius:99px;padding:1px 8px;font-weight:500}}
.approved,.qualified{{color:var(--ok)}}.needs_review,.rejected,.generation_failed,.warn{{color:var(--bad)}}
.meta{{color:var(--mut);font-size:13px;margin:6px 0}}pre{{white-space:pre-wrap;font:inherit;background:var(--bg);padding:10px;border-radius:8px;margin:4px 0}}
h4{{margin:12px 0 2px}}small{{color:var(--mut);font-weight:400}}.scroll{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;background:var(--card);font-size:13px}}td,th{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
</style></head><body><main>
<h1>{e(campaign['name'])}</h1><p class="sub">Discovery &rarr; Filtering &rarr; Enrichment &rarr; AI Personalization &rarr; Review &rarr; Sending &rarr; Tracking.
Rejections by rule: {e(', '.join(f'{k}: {v}' for k, v in reason_counts.most_common()))}</p>
<div class="stats">{''.join(f'<div class="stat"><b>{v}</b>{e(str(k))}</div>' for k, v in stats)}</div>
<h2>Personalized messages</h2>{''.join(cards) or '<p>No messages yet.</p>'}
<h2>Outreach tracker</h2><div class="scroll"><table><tr><th>Influencer</th><th>Channel</th><th>Mode</th><th>Status</th><th>Delivered to</th><th>Date (UTC)</th></tr>{logrows}</table></div>
<h2>All discovered profiles ({len(classified)})</h2><div class="scroll"><table><tr><th>Name</th><th>Followers</th><th>ER %</th><th>Segment</th><th>Status</th><th>Why</th></tr>{rows}</table></div>
</main></body></html>"""
    (OUTPUT / "report.html").write_text(page, encoding="utf-8")
