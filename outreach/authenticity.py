"""Audience-authenticity score (0-100) from public video stats.

Bought followers or likes leave statistical traces we can see without private analytics:
  - reach: real audiences watch; inflated subscriber counts give tiny views-per-subscriber
  - like rate far above the niche norm suggests purchased likes
  - likes with almost no comments is a classic engagement-pod / bot pattern
  - one viral outlier hides that a typical video gets few views
Each signal costs points and leaves a human-readable flag. Thresholds are deliberately conservative:
flags mean "look closer", the hard filter only removes clear outliers.
"""
from statistics import mean, median, pstdev


def like_rate(v: dict) -> float | None:
    return v["likes"] / v["views"] if v["views"] and v["likes"] is not None else None


def niche_like_rate(records: list[dict]) -> float | None:
    """Median per-video like rate across the campaign; the baseline for 'unusually high'."""
    rates = [r for rec in records for v in rec["recent_videos"] if (r := like_rate(v)) is not None]
    return median(rates) if len(rates) >= 20 else None


def score(rec: dict, niche_median_like_rate: float | None) -> dict:
    vids = [v for v in rec["recent_videos"] if v["views"]]
    if len(vids) < 3 or not rec["followers"]:
        return {"authenticity": None, "authenticity_flags": ["not enough public data to assess"], "median_views": None}
    views = [v["views"] for v in vids]
    med = median(views)
    flags, pts = [], 100

    reach = med / rec["followers"] * 100
    if reach < 1:
        pts -= 40
        flags.append(f"typical video reaches only {reach:.1f}% of subscribers (possible inactive or inflated audience)")
    elif reach < 3:
        pts -= 15
        flags.append(f"low reach: typical video gets {reach:.1f}% of subscriber count")

    rates = [r for v in vids if (r := like_rate(v)) is not None]
    if rates and niche_median_like_rate and mean(rates) > 4 * niche_median_like_rate:
        pts -= 25
        flags.append(f"like rate {mean(rates) * 100:.1f}% is {mean(rates) / niche_median_like_rate:.0f}x the niche norm")

    likes = sum(v["likes"] or 0 for v in vids)
    comments = sum(v["comments"] or 0 for v in vids)
    if likes >= 500 and comments / likes < 0.004:
        pts -= 20
        flags.append(f"almost no conversation: {comments} comments for {likes:,} likes")

    if len(views) >= 4 and pstdev(views) / mean(views) > 1.8:
        pts -= 10
        flags.append(f"views driven by one outlier; median video gets {med:,.0f} views")

    return {"authenticity": max(pts, 0), "authenticity_flags": flags, "median_views": round(med)}
