"""Stage 1 - Discovery: find candidate creators via the YouTube Data API v3 and collect real metrics.

Quota (10,000 units/day free): search.list = 100 units/page, channels/playlistItems/videos = 1 unit/call.
Recent videos are only fetched for channels inside (or near) the follower range, because the
others are rejected on follower count anyway - this keeps a 20-query run around ~2,600 units.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from .config import env, save_stage
from .http import HttpError, request_json

API = "https://www.googleapis.com/youtube/v3"


def _get(endpoint: str, **params):
    return request_json(f"{API}/{endpoint}", params=params,
                        headers={"X-Goog-Api-Key": env("YOUTUBE_API_KEY", required=True)})


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def search_channels(cfg: dict) -> dict[str, set[str]]:
    """Return {channel_id: {queries that surfaced it}}."""
    after = (datetime.now(timezone.utc) - timedelta(days=cfg["published_within_days"])).strftime("%Y-%m-%dT00:00:00Z")
    found: dict[str, set[str]] = {}
    for q in cfg["queries"]:
        token = None
        for _ in range(cfg["pages_per_query"]):
            params = dict(part="snippet", q=q, type="video", maxResults=cfg["results_per_query"],
                          regionCode=cfg["region_code"], relevanceLanguage=cfg["relevance_language"],
                          publishedAfter=after, order="relevance")
            if token:
                params["pageToken"] = token
            try:
                r = _get("search", **params)
            except HttpError as e:
                if e.status == 403 and "quota" in e.body.lower():
                    print("  ! YouTube quota exhausted - continuing with what was found so far")
                    return found
                raise
            for it in r.get("items", []):
                found.setdefault(it["snippet"]["channelId"], set()).add(q)
            token = r.get("nextPageToken")
            if not token:
                break
        print(f"  search '{q}': {len(found)} unique channels so far")
    return found


def channel_details(ids: list[str]) -> dict[str, dict]:
    out = {}
    ids = sorted(ids)  # stable chunks -> cache hits on re-runs
    for i in range(0, len(ids), 50):
        r = _get("channels", part="snippet,statistics,contentDetails,brandingSettings,topicDetails,status",
                 id=",".join(ids[i:i + 50]), maxResults=50)
        for c in r.get("items", []):
            out[c["id"]] = c
    return out


def recent_videos(uploads_playlist: str, n: int) -> list[dict]:
    try:
        r = _get("playlistItems", part="contentDetails", playlistId=uploads_playlist, maxResults=n)
    except HttpError as e:
        if e.status == 404:  # channel with no public uploads
            return []
        raise
    ids = [it["contentDetails"]["videoId"] for it in r.get("items", [])]
    if not ids:
        return []
    v = _get("videos", part="snippet,statistics", id=",".join(ids))
    vids = []
    for it in v.get("items", []):
        st = it.get("statistics", {})
        vids.append({
            "video_id": it["id"],
            "url": f"https://www.youtube.com/watch?v={it['id']}",
            "title": it["snippet"]["title"],
            "published_at": it["snippet"]["publishedAt"],
            "description": it["snippet"].get("description", "")[:2000],
            "tags": it["snippet"].get("tags", [])[:15],
            "views": int(st["viewCount"]) if "viewCount" in st else None,
            "likes": int(st["likeCount"]) if "likeCount" in st else None,  # None = creator hid likes
            "comments": int(st["commentCount"]) if "commentCount" in st else None,
        })
    return sorted(vids, key=lambda x: x["published_at"], reverse=True)


def engagement(videos: list[dict], followers: int | None, min_age_days: int = 3) -> dict:
    """ER = (likes + comments) / views over recent videos older than `min_age_days`
    (brand-new uploads haven't accumulated engagement yet). Videos with hidden likes are skipped."""
    now = datetime.now(timezone.utc)
    last = max((parse_ts(v["published_at"]) for v in videos), default=None)
    sample = [v for v in videos if v["views"] and v["likes"] is not None
              and (now - parse_ts(v["published_at"])).days >= min_age_days]
    base = {"last_upload": last.date().isoformat() if last else None,
            "days_since_upload": (now - last).days if last else None,
            "videos_sampled": len(sample)}
    if not sample:
        return {**base, "engagement_rate": None, "avg_views": None, "views_to_followers": None}
    views = sum(v["views"] for v in sample)
    interactions = sum(v["likes"] + (v["comments"] or 0) for v in sample)
    avg_views = views / len(sample)
    return {**base,
            "engagement_rate": round(interactions / views * 100, 2),
            "avg_views": round(avg_views),
            "views_to_followers": round(avg_views / followers * 100, 1) if followers else None}


def build_record(ch: dict, videos: list[dict], queries: set[str]) -> dict:
    sn, st = ch["snippet"], ch.get("statistics", {})
    branding = ch.get("brandingSettings", {}).get("channel", {})
    followers = None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0))
    handle = sn.get("customUrl")
    return {
        "channel_id": ch["id"],
        "name": sn["title"],
        "platform": "YouTube",
        "handle": handle,
        "profile_url": f"https://www.youtube.com/{handle}" if handle else f"https://www.youtube.com/channel/{ch['id']}",
        "followers": followers,
        "total_views": int(st.get("viewCount", 0)),
        "video_count": int(st.get("videoCount", 0)),
        "country": sn.get("country") or branding.get("country"),
        "channel_created": sn.get("publishedAt", "")[:10],
        "description": sn.get("description", ""),
        "channel_keywords": branding.get("keywords", ""),
        "topics": [u.rsplit("/", 1)[-1].replace("_", " ") for u in ch.get("topicDetails", {}).get("topicCategories", [])],
        "made_for_kids": bool(ch.get("status", {}).get("madeForKids", False)),
        "discovered_via": sorted(queries),
        "recent_videos": videos,
        **engagement(videos, followers),
    }


def run(campaign: dict) -> list[dict]:
    cfg, f = campaign["discovery"], campaign["filters"]["followers"]
    print("Discovery: searching YouTube...")
    found = search_channels(cfg)
    details = channel_details(list(found))
    print(f"  fetched details for {len(details)} channels")

    def needs_videos(c):
        s = c.get("statistics", {})
        n = None if s.get("hiddenSubscriberCount") else int(s.get("subscriberCount", 0))
        return n is not None and f["min"] * 0.8 <= n <= f["max"] * 1.2

    def one(cid):
        ch = details[cid]
        vids = recent_videos(ch["contentDetails"]["relatedPlaylists"]["uploads"], cfg["recent_videos"]) if needs_videos(ch) else []
        return build_record(ch, vids, found[cid])

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(one, details))
    save_stage(campaign, "discovered", records)
    print(f"  saved {len(records)} discovered profiles")
    return records
