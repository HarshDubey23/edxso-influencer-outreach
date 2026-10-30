"""Run: python -m unittest discover -s tests -v   (no network, no API keys needed)"""
import json
import os
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from outreach import classify, personalize, sender
from outreach.config import load_campaign
from outreach.discover import engagement
from outreach.enrich import NOT_FOUND, extract_emails, find_links

CAMPAIGN = load_campaign()


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")


def video(title, days, views=1000, likes=40, comments=10):
    return {"video_id": title[:5], "url": "u", "title": title, "published_at": ago(days), "description": "",
            "tags": [], "views": views, "likes": likes, "comments": comments}


def record(**kw):
    vids = kw.pop("videos", [video("Classroom management tips for new teachers", 10),
                             video("Lesson plan ideas for B.Ed teachers", 20),
                             video("Activity based learning in my classroom", 30),
                             video("Teacher training: NEP explained", 40)])
    base = {"channel_id": "UC1", "name": "Priya Teaches", "platform": "YouTube", "handle": "@priya",
            "profile_url": "https://www.youtube.com/@priya", "followers": 25000, "total_views": 1, "video_count": 50,
            "country": "IN", "description": "Teacher sharing classroom ideas", "channel_keywords": "",
            "topics": [], "made_for_kids": False, "discovered_via": ["q"], "recent_videos": vids}
    base.update(kw)
    return {**base, **engagement(base["recent_videos"], base["followers"])}


class Engagement(unittest.TestCase):
    def test_rate_excludes_fresh_and_hidden_like_videos(self):
        vids = [video("a", 10, views=1000, likes=30, comments=20),  # 5%
                video("b", 1, views=10, likes=10, comments=0),       # too new: excluded
                {**video("c", 12), "likes": None}]                   # hidden likes: excluded
        m = engagement(vids, 10000)
        self.assertEqual(m["engagement_rate"], 5.0)
        self.assertEqual(m["videos_sampled"], 1)
        self.assertEqual(m["views_to_followers"], 10.0)
        self.assertEqual(m["days_since_upload"], 1)

    def test_no_videos(self):
        self.assertIsNone(engagement([], 5000)["engagement_rate"])


class Classification(unittest.TestCase):
    def test_good_teacher_creator_qualifies(self):
        r = classify.classify(record(), CAMPAIGN)
        self.assertEqual(r["status"], "qualified", r["reasons"])
        self.assertEqual(r["segment"], "teachers_educators")
        self.assertEqual(r["reasons"], [])
        self.assertGreater(r["fit_score"], 50)

    def test_each_hard_rule_rejects_with_reason(self):
        cases = {
            "followers": record(followers=250000),
            "audience_not_children": record(made_for_kids=True),
            "brand_safety": record(description="Teacher tips and online casino bonus"),
            "individual_creator": record(name="Sunrise Public School Official"),
            "active": record(videos=[video(t, 200 + i) for i, t in enumerate(
                ["Classroom tips for teachers", "Lesson plan for teachers", "Teacher training", "Teaching ideas"])]),
            "niche_relevance": record(description="Car reviews", videos=[video(f"Car review {i}", 5 + i) for i in range(5)]),
        }
        for rule, rec in cases.items():
            with self.subTest(rule=rule):
                r = classify.classify(rec, CAMPAIGN)
                self.assertEqual(r["status"], "rejected")
                self.assertFalse(r["checks"][rule]["passed"])
                self.assertIn(r["checks"][rule]["detail"], r["reasons"])
                self.assertEqual(r["fit_score"], 0)

    def test_niche_not_judged_without_video_titles(self):
        r = classify.classify(record(followers=900000, videos=[]), CAMPAIGN)
        self.assertNotIn("niche_relevance", r["checks"])
        self.assertEqual(len(r["reasons"]), 1)
        self.assertIn("followers", r["reasons"][0])

    def test_hidden_subscribers_rejected(self):
        r = classify.classify(record(followers=None), CAMPAIGN)
        self.assertEqual(r["reasons"][0], "subscriber count is hidden")


class Authenticity(unittest.TestCase):
    def test_healthy_audience_scores_full(self):
        from outreach.authenticity import score
        vids = [video(f"t{i}", 10 + i, views=3000, likes=120, comments=20) for i in range(5)]
        s = score(record(followers=20000, videos=vids), 0.04)
        self.assertEqual((s["authenticity"], s["authenticity_flags"], s["median_views"]), (100, [], 3000))

    def test_inflated_audience_and_bot_likes_flagged(self):
        from outreach.authenticity import score
        vids = [video(f"t{i}", 10 + i, views=100, likes=60, comments=0) for i in range(5)]  # 0.1% reach, 60% like rate
        s = score(record(followers=90000, videos=vids), 0.04)
        self.assertLess(s["authenticity"], 40)
        self.assertEqual(len(s["authenticity_flags"]), 2)
        self.assertIn("reaches only", s["authenticity_flags"][0])

    def test_too_little_data_is_not_scored(self):
        from outreach.authenticity import score
        self.assertIsNone(score(record(videos=[video("a", 5)]), 0.04)["authenticity"])


class HybridClassifier(unittest.TestCase):
    def test_blend_and_abstain(self):
        from outreach import ml
        model = {"fitness": 0.5, "gaming": 0.5}
        self.assertEqual(ml.blend(model, {"fitness": 1.0}), {"fitness": 0.75, "gaming": 0.25})
        self.assertEqual(ml.blend(model, {}), model)  # no keyword evidence: model alone
        self.assertEqual(ml.decide({"fitness": 0.75, "gaming": 0.25}), "fitness")
        self.assertEqual(ml.decide({"fitness": 0.2, "gaming": 0.18}), "other")  # below threshold: abstain
        self.assertEqual(ml.decide({}), "other")


class Workspace(unittest.TestCase):
    """Settings, secrets and signed links live in SQLite; these tests run on a throwaway database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from outreach import workspace
        path, real = Path(self.tmp.name) / "w.db", sender.connect
        self.patch = mock.patch.object(workspace, "connect", lambda p=None: real(path))  # workspace binds connect by name
        self.patch.start()
        os.environ["SECRET_KEY"] = "test-secret"

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_secret_roundtrip_and_wrong_key(self):
        from outreach import workspace
        workspace.put_secret("gmail_refresh", "1//refresh-token")
        self.assertEqual(workspace.get_secret("gmail_refresh"), "1//refresh-token")
        self.assertNotIn("refresh-token", json.dumps(workspace.get("secret:gmail_refresh")))  # stored encrypted
        os.environ["SECRET_KEY"] = "another-key"
        self.assertIsNone(workspace.get_secret("gmail_refresh"))  # key changed: reconnect, never crash
        self.assertNotIn("secret:gmail_refresh", workspace.all_settings())

    def test_signed_tokens_reject_tampering(self):
        from outreach import workspace
        t = workspace.sign("creator@example.com")
        self.assertEqual(workspace.unsign(t), "creator@example.com")
        raw, mac = t.split(".")
        self.assertIsNone(workspace.unsign(raw[:-1] + ("A" if raw[-1] != "A" else "B") + "." + mac))
        self.assertIsNone(workspace.unsign("garbage"))

    def test_settings_defaults_and_events(self):
        from outreach import workspace
        self.assertFalse(workspace.get("send_live"))
        workspace.put(daily_cap=5)
        self.assertEqual(workspace.all_settings()["daily_cap"], 5)
        workspace.event("hello")
        self.assertEqual([e["message"] for e in workspace.events_after(0)], ["hello"])


class EmailCompliance(unittest.TestCase):
    def test_unsubscribe_header_and_footer(self):
        m = sender.build_email({"email_subject": "Hi", "email_body": "Body text"}, "c@x.com", "c@x.com", "live",
                               "Brand <me@x.com>", "https://app.example/u/tok", "12 Road, Delhi")
        self.assertEqual(m["List-Unsubscribe"], "<https://app.example/u/tok>")
        self.assertEqual(m["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        body = m.get_content()
        self.assertIn("12 Road, Delhi", body)
        self.assertIn("https://app.example/u/tok", body)
        self.assertEqual(m["From"], "Brand <me@x.com>")

    def test_test_mode_marks_subject(self):
        m = sender.build_email({"email_subject": "Hi", "email_body": "B"}, "me@x.com", "c@x.com", "test")
        self.assertTrue(m["Subject"].startswith("[TEST -> c@x.com]"))


class AutopilotGuards(unittest.TestCase):
    def test_send_next_respects_window_live_footer_and_review_gate(self):
        from outreach import autopilot
        base = {"send_live": False, "postal_address": "", "window_start": 0, "window_end": 24, "utc_offset_min": 0,
                "daily_cap": 5, "review_first": 2, "followup_days": 4, "gmail_email": "me@x.com"}
        self.assertIn("postal address", autopilot.send_next(CAMPAIGN, {**base, "send_live": True}))
        hour = autopilot._local_now(base).hour
        self.assertIn("outside the sending window", autopilot.send_next(CAMPAIGN, {**base, "window_start": (hour + 1) % 24, "window_end": (hour + 1) % 24 + 1}))
        calls = {}
        with mock.patch.object(autopilot, "sent_today", return_value=0), \
             mock.patch.object(autopilot, "_stage", side_effect=lambda c, n: [{"channel_id": "A", "human_approved": False}, {"channel_id": "B", "human_approved": True}] if n == "messages" else []), \
             mock.patch.object(autopilot.sender, "run", side_effect=lambda c, pool, *a, **k: calls.setdefault("pool", pool) and {"sent": 1, "failed": 0}), \
             mock.patch.object(autopilot.sender, "connect") as conn:
            conn.return_value.execute.return_value.fetchone.return_value = [0]  # nothing sent yet: review gate applies
            autopilot.send_next(CAMPAIGN, base)
        self.assertEqual([m["channel_id"] for m in calls["pool"]], ["B"])  # only the human-approved message

    def test_daily_cap(self):
        from outreach import autopilot
        s = {"send_live": False, "window_start": 0, "window_end": 24, "utc_offset_min": 0, "daily_cap": 3}
        with mock.patch.object(autopilot, "sent_today", return_value=3):
            self.assertIn("daily cap", autopilot.send_next(CAMPAIGN, s))

    def test_poll_replies_skips_own_mail_and_bounces(self):
        from outreach import autopilot
        thread = [{"id": "1", "from": "Me <me@x.com>", "text": "hi"},
                  {"id": "2", "from": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "text": "Message blocked"},
                  {"id": "3", "from": "Creator <c@y.com>", "text": "What's the budget?", "subject": "Re: hi", "message_id": "<m3>"}]
        triaged = []
        with mock.patch.object(autopilot.gmail, "thread", return_value=thread), \
             mock.patch.object(autopilot, "_stage", return_value=[]), \
             mock.patch.object(autopilot.sender, "connect") as conn, \
             mock.patch.object(autopilot.workspace, "get", return_value=[]), \
             mock.patch.object(autopilot.workspace, "put"), mock.patch.object(autopilot.workspace, "event"), \
             mock.patch.object(autopilot.replies, "classify", side_effect=lambda t, *a: triaged.append(t) or
                               {"intent": "rate_negotiation", "suppress": False, "suggested_reply": ""}), \
             mock.patch.object(autopilot.replies, "record"):
            conn.return_value.execute.return_value.fetchall.return_value = [{"channel_id": "A", "email": "c@y.com", "thread_id": "t"}]
            self.assertEqual(autopilot.poll_replies(CAMPAIGN, {"gmail_email": "me@x.com"}), 1)
        self.assertEqual(triaged, ["What's the budget?"])  # only the creator's message reaches the classifier


class PublicSite(unittest.TestCase):
    def test_email_masking(self):
        from outreach.export import _mask
        self.assertEqual(_mask("priya.t@gmail.com"), "pr*****@gmail.com")
        self.assertEqual(_mask("ab@x.in"), "ab***@x.in")
        self.assertEqual(_mask("Not Found"), "Not Found")
        self.assertIsNone(_mask(None))


class Enrichment(unittest.TestCase):
    def test_email_extraction(self):
        text = "Biz: Priya.T@gmail.com, also priya [at] priyateaches [dot] in. logo@2x.png you@example.com PRIYA.T@GMAIL.COM"
        self.assertEqual(extract_emails(text), ["priya.t@gmail.com", "priya@priyateaches.in"])
        self.assertEqual(extract_emails("Email:-creator.biz@gmail.com"), ["creator.biz@gmail.com"])

    def test_no_email_is_not_guessed(self):
        self.assertEqual(extract_emails("Contact me on Instagram"), [])
        self.assertEqual(NOT_FOUND, "Not Found")

    def test_video_description_ignores_third_party_emails(self):
        from outreach.enrich import find_contact
        rec = record()
        rec["recent_videos"][0]["description"] = "📧 Email: eligibilitysection@tnteu.ac.in\nContact the board office"
        self.assertEqual(find_contact(rec)["email"], NOT_FOUND)
        rec["recent_videos"][1]["description"] = "For business/collab: priya.collabs@gmail.com"
        self.assertEqual(find_contact(rec)["email"], "priya.collabs@gmail.com")

    def test_links(self):
        socials, sites = find_links("IG https://instagram.com/priya.teaches site https://priyateaches.in/ "
                                    "buy https://amzn.to/x https://www.netflix.com/title")
        self.assertEqual(socials, {"instagram": "https://instagram.com/priya.teaches"})
        self.assertEqual(sites, ["https://priyateaches.in/", "https://www.netflix.com/title"])


class MessageValidation(unittest.TestCase):
    rec = {**record(), "content_themes": ["classroom management", "lesson planning"],
           "standout_video_title": "Classroom management tips for new teachers"}

    def msg(self, body_words=70, dm="Priya, your classroom management tips video was spot on! Would you be open to an EDXSO teacher ambassador collab this term?"):
        body = "Hi Priya, your classroom management tips for new teachers were practical. " + "word " * (body_words - 10)
        return {"greeting_name": "Priya", "collaboration_angle": "Brand ambassador program",
                "personalization_signals": [], "email_subject": "s", "email_body": body.strip(), "instagram_dm": dm}

    def test_valid_message(self):
        self.assertEqual(personalize.validate(self.msg(), self.rec, CAMPAIGN), [])

    def test_length_and_generic_failures(self):
        self.assertTrue(any("email_body has" in p for p in personalize.validate(self.msg(40), self.rec, CAMPAIGN)))
        bad_dm = self.msg(dm="Hi, we would like to collaborate with you.")
        problems = personalize.validate(bad_dm, self.rec, CAMPAIGN)
        self.assertTrue(any("instagram_dm has" in p for p in problems))
        self.assertTrue(any("DM does not reference" in p for p in problems))
        self.assertTrue(personalize.validate({**self.msg(), "instagram_dm": "Hi [Name], loved your classroom tips! " * 3},
                                             self.rec, CAMPAIGN))

    def test_generic_dm_opener_rejected(self):
        dm = "Loved your classroom management tips video! Would you be open to an EDXSO teacher ambassador collab this term?"
        self.assertTrue(any("opens generically" in p for p in personalize.validate(self.msg(dm=dm), self.rec, CAMPAIGN)))

    def test_greeting_must_come_from_channel_name(self):
        m = self.msg()
        m["greeting_name"] = "there"
        m["email_body"] = m["email_body"].replace("Hi Priya", "Hi there")
        self.assertTrue(any("greet the creator" in p for p in personalize.validate(m, self.rec, CAMPAIGN)))

    def test_number_check_ignores_words_starting_with_k(self):
        m = self.msg()
        m["email_body"] += " Your 5 kindergarten ideas"
        self.assertFalse(any("follower counts" in p for p in personalize.validate(m, self.rec, CAMPAIGN)))
        m["email_body"] += " and 10k subscribers"
        self.assertTrue(any("follower counts" in p for p in personalize.validate(m, self.rec, CAMPAIGN)))


class Sending(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = sender.connect(Path(self.tmp.name) / "t.db")
        base = {"review_status": "approved", "email_subject": "Hello", "email_body": "Body", "instagram_dm": "dm"}
        self.msgs = [{**base, "channel_id": "UC1", "influencer": "A", "email": "a@x.com"},
                     {**base, "channel_id": "UC2", "influencer": "B", "email": NOT_FOUND},
                     {**base, "channel_id": "UC3", "influencer": "C", "email": "a@x.com"},  # same inbox as A
                     {**base, "channel_id": "UC4", "influencer": "D", "email": "d@x.com", "review_status": "needs_review"}]

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def send(self, **kw):
        return sender.run(CAMPAIGN, self.msgs, [], db=self.db, outbox=Path(self.tmp.name) / "outbox", **kw)

    def test_dry_run_selects_valid_and_prevents_duplicates(self):
        s1 = self.send()
        self.assertEqual((s1["sent"], s1["ineligible"], s1["duplicates_skipped"]), (1, 2, 1))
        self.assertTrue((Path(self.tmp.name) / "outbox" / "UC1.eml").exists())
        s2 = self.send()
        self.assertEqual((s2["sent"], s2["duplicates_skipped"], s2["dms_queued"]), (0, 2, 0))
        rows = self.db.execute("SELECT status FROM outreach_log WHERE kind='email'").fetchall()
        self.assertEqual([r["status"] for r in rows], ["simulated"])

    def test_live_requires_confirmation(self):
        with self.assertRaises(SystemExit):
            self.send(mode="live")

    def test_n8n_no_reply_is_unconfirmed_and_never_resent(self):
        calls = []

        def lost_reply(items):
            calls.append(items)
            raise OSError("timed out")

        os.environ["TEST_RECIPIENT"] = "me@x.com"
        with mock.patch.object(sender, "send_n8n", lost_reply):
            s1 = self.send(mode="test", transport="n8n")
            s2 = self.send(mode="test", transport="n8n")
        self.assertEqual(len(calls), 1)  # second run did not re-send the batch
        self.assertEqual((s1["failed"], s2["duplicates_skipped"]), (1, 2))  # A, and C (same inbox as A)
        row = self.db.execute("SELECT status, delivered_to FROM outreach_log WHERE kind='email'").fetchone()
        self.assertEqual(tuple(row), ("unconfirmed", "me@x.com"))

    def test_do_not_contact_list_blocks_send(self):
        self.db.execute("INSERT INTO suppression (email, reason, created_at) VALUES ('a@x.com', 'unsubscribe', 'now')")
        s = self.send()
        self.assertEqual(s["sent"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outreach_log WHERE kind='email'").fetchone()[0], 0)

    def test_followup_only_when_due_once_and_not_after_reply(self):
        self.msgs.append({**self.msgs[0], "channel_id": "UC5", "influencer": "E", "email": "e@x.com"})
        self.send()
        out = Path(self.tmp.name) / "outbox"
        fu = lambda **kw: sender.followups(CAMPAIGN, self.msgs, db=self.db, outbox=out,
                                           writer=lambda m: "Just following up on my note.", **kw)
        self.assertEqual(fu()["followups_sent"], 0)  # not due yet
        self.db.execute("UPDATE outreach_log SET created_at='2020-01-01T00:00:00+00:00' WHERE kind='email'")
        self.db.execute("INSERT INTO replies (campaign_id, channel_id, email, intent, created_at) "
                        "VALUES (?, 'UC5', 'e@x.com', 'interested', 'now')", (CAMPAIGN["id"],))
        self.assertEqual(fu()["followups_sent"], 1)  # A only: E already replied
        self.assertEqual(fu()["followups_sent"], 0)  # never twice

    def test_manual_dm_flow(self):
        self.send()
        self.assertTrue(sender.mark_dm_sent(CAMPAIGN, "UC1", db=self.db))
        self.assertFalse(sender.mark_dm_sent(CAMPAIGN, "UC1", db=self.db))


if __name__ == "__main__":
    unittest.main()
