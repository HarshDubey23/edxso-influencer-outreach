"""Run: python -m unittest discover -s tests -v   (no network, no API keys needed)"""
import tempfile
import unittest
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

    def test_hidden_subscribers_rejected(self):
        r = classify.classify(record(followers=None), CAMPAIGN)
        self.assertEqual(r["reasons"][0], "subscriber count is hidden")


class Enrichment(unittest.TestCase):
    def test_email_extraction(self):
        text = "Biz: Priya.T@gmail.com, also priya [at] priyateaches [dot] in. logo@2x.png you@example.com PRIYA.T@GMAIL.COM"
        self.assertEqual(extract_emails(text), ["priya.t@gmail.com", "priya@priyateaches.in"])

    def test_no_email_is_not_guessed(self):
        self.assertEqual(extract_emails("Contact me on Instagram"), [])
        self.assertEqual(NOT_FOUND, "Not Found")

    def test_links(self):
        socials, sites = find_links("IG https://instagram.com/priya.teaches site https://priyateaches.in/ "
                                    "buy https://amzn.to/x https://www.netflix.com/title")
        self.assertEqual(socials, {"instagram": "https://instagram.com/priya.teaches"})
        self.assertEqual(sites, ["https://priyateaches.in/", "https://www.netflix.com/title"])


class MessageValidation(unittest.TestCase):
    rec = {**record(), "content_themes": ["classroom management", "lesson planning"],
           "standout_video_title": "Classroom management tips for new teachers"}

    def msg(self, body_words=70, dm="Loved your classroom management tips video! Would you be open to an EDXSO teacher ambassador collab this term?"):
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

    def test_dry_run_selects_valid_and_prevents_duplicates(self):
        s1 = sender.run(CAMPAIGN, self.msgs, [], db=self.db)
        self.assertEqual((s1["sent"], s1["ineligible"], s1["duplicates_skipped"]), (1, 2, 1))
        s2 = sender.run(CAMPAIGN, self.msgs, [], db=self.db)
        self.assertEqual((s2["sent"], s2["duplicates_skipped"], s2["dms_queued"]), (0, 2, 0))
        rows = self.db.execute("SELECT status FROM outreach_log WHERE kind='email'").fetchall()
        self.assertEqual([r["status"] for r in rows], ["simulated"])

    def test_live_requires_confirmation(self):
        with self.assertRaises(SystemExit):
            sender.run(CAMPAIGN, self.msgs, [], mode="live", db=self.db)

    def test_manual_dm_flow(self):
        sender.run(CAMPAIGN, self.msgs, [], db=self.db)
        self.assertTrue(sender.mark_dm_sent(CAMPAIGN, "UC1", db=self.db))
        self.assertFalse(sender.mark_dm_sent(CAMPAIGN, "UC1", db=self.db))


if __name__ == "__main__":
    unittest.main()
