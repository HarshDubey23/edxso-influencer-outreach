"""CLI: python -m outreach <stage> [options]. Each stage reads the previous stage's JSON, so any stage can be re-run alone."""
import argparse

from . import classify, discover, enrich, export, personalize, sender
from .config import load_campaign, load_stage


def main():
    p = argparse.ArgumentParser(prog="outreach", description="Automated micro-influencer outreach pipeline")
    p.add_argument("stage", choices=["discover", "classify", "enrich", "personalize", "send", "export", "run", "mark-dm"])
    p.add_argument("--campaign", help="campaign JSON (default: campaigns/edxso_parenting_education.json)")
    p.add_argument("--limit", type=int, help="max creators to personalize / emails to send")
    p.add_argument("--mode", choices=["dry-run", "test", "live"], default="dry-run")
    p.add_argument("--via", choices=["smtp", "n8n"], default="smtp", help="transport for test/live sends")
    p.add_argument("--confirm-live", action="store_true", help="required for --mode live")
    p.add_argument("--channel", help="channel_id for mark-dm")
    a = p.parse_args()
    c = load_campaign(a.campaign)

    if a.stage in ("discover", "run"):
        discover.run(c)
    if a.stage in ("classify", "run"):
        classify.run(c, load_stage(c, "discovered"))
    if a.stage in ("enrich", "run"):
        enrich.run(c, load_stage(c, "classified"))
    if a.stage in ("personalize", "run"):
        personalize.run(c, load_stage(c, "enriched"), a.limit)
    if a.stage in ("send", "run"):
        sender.run(c, load_stage(c, "messages"), load_stage(c, "enriched"), a.mode, a.via, a.limit, a.confirm_live)
    if a.stage in ("export", "run", "send"):
        export.run(c, load_stage(c, "classified"), load_stage(c, "enriched"), load_stage(c, "messages"))
    if a.stage == "mark-dm":
        if not a.channel:
            p.error("mark-dm needs --channel <channel_id>")
        print("marked as sent" if sender.mark_dm_sent(c, a.channel) else "no queued DM found for that channel")


if __name__ == "__main__":
    main()
