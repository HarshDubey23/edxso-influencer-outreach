"""CLI: python -m outreach <stage> [options]. Each stage reads the previous stage's JSON, so any stage can be re-run alone."""
import argparse
import sys

from . import classify, discover, enrich, export, personalize, sender
from .config import all_campaigns, load_campaign, load_stage

STAGES = ["discover", "classify", "train", "enrich", "personalize", "send", "followup", "export", "demo", "site", "run", "mark-dm"]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # creator names contain emoji; Windows consoles default to cp1252
    p = argparse.ArgumentParser(prog="outreach", description="Automated micro-influencer outreach pipeline")
    p.add_argument("stage", choices=STAGES)
    p.add_argument("--campaign", help="campaign JSON path, or \"all\" for every file in campaigns/ (default: EDXSO education)")
    p.add_argument("--limit", type=int, help="max creators to personalize / emails to send")
    p.add_argument("--mode", choices=["dry-run", "test", "live"], default="dry-run")
    p.add_argument("--via", choices=["smtp", "n8n"], default="smtp", help="transport for test/live sends")
    p.add_argument("--confirm-live", action="store_true", help="required for --mode live")
    p.add_argument("--days", type=int, default=4, help="follow-up after this many days without a reply")
    p.add_argument("--channel", help="channel_id for mark-dm")
    a = p.parse_args()
    if a.stage == "train":  # one model across every campaign's discovered data
        from . import ml
        return ml.train()
    if a.stage == "demo":  # capture real outputs of ask / match / reply triage for the public dashboard
        from . import demo
        return demo.run()
    if a.stage == "site":
        export.combined()
        return export.build_site()
    for c in (all_campaigns() if a.campaign == "all" else [load_campaign(a.campaign)]):
        print(f"\n=== {c['name']} ({c['id']}) ===")
        run_stage(a, p, c)
    if a.stage in ("export", "run", "send", "followup"):
        export.combined()


def run_stage(a, p, c):
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
    if a.stage == "followup":
        sender.followups(c, load_stage(c, "messages"), a.mode, a.via, a.days, a.limit)
    if a.stage in ("export", "run", "send", "followup"):
        export.run(c, load_stage(c, "classified"), load_stage(c, "enriched"), load_stage(c, "messages"))
    if a.stage == "mark-dm":
        if not a.channel:
            p.error("mark-dm needs --channel <channel_id>")
        print("marked as sent" if sender.mark_dm_sent(c, a.channel) else "no queued DM found for that channel")


if __name__ == "__main__":
    main()
