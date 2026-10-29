# EDXSO Micro-Influencer Outreach System

An automated pipeline that discovers education and parenting micro-influencers on YouTube, filters and classifies them against EDXSO's brand fit, enriches each shortlisted profile, writes a personalized email pitch and Instagram DM with an LLM, and sends (or simulates) the outreach with duplicate protection and a tracker.

```
YouTube Data API ─► Discovery (749 channels) ─► Filtering & classification (40 qualified)
   ─► Enrichment (email, links, themes, tone) ─► Gemini personalization ─► Validation / review gate
   ─► Sending layer (dry-run | test | live, via SMTP or n8n + Gmail) ─► SQLite outreach log ─► CSV + HTML report
```

**Campaign:** EDXSO (K-12 school consultancy) partnering with Indian-focused creators whose audience is teachers, school leaders and parents, the people who influence how schools are run and chosen.

## Results of the test run

| Stage | Result |
|---|---|
| Discovered (20 search queries) | **749** real YouTube channels, **173** of them in the 5k-100k range |
| Qualified after all filters | **40** (23 Teachers & Educators, 15 Parents & Family, 1 Early Childhood, 1 School Leaders); 21 based in India |
| Median of the shortlist | 19,150 subscribers, 2.46% engagement |
| Rejection reasons (a channel can fail several) | followers out of range 576 · off-niche 117 · low engagement 86 · made-for-kids 40 · too few videos 21 · institution/media account 19 · brand safety 4 · inactive 3 |
| Contact email found | **8 / 40**, all published by the creator in their channel description. The other 32 are marked `Not Found`. |
| Messages | **38 / 40** auto-approved, 2 held for review (word count / invalid angle). All six collaboration angles used across the batch |
| Sending | 8 simulated (dry-run), 38 Instagram DMs queued for manual sending, **1 real email sent through n8n + Gmail** to the operator's test inbox (Gmail id logged). A second run skipped all 8 as duplicates |

Each creator's metrics come straight from the YouTube API. Nothing is estimated or made up.

## Deliverables

| File | What it is |
|---|---|
| `output/influencers_dataset.csv` | All 749 discovered profiles: name, platform, followers, engagement, niche, email, profile URL, content theme, **PASS/FAIL status and the reason for every failure** |
| `output/shortlist_enriched.csv` | The 40 qualified creators with every enrichment field (mandatory and optional) |
| `output/personalized_messages.csv` | Email subject + 60-90 word pitch + 15-30 word DM, collaboration angle, signals used, review status |
| `output/outreach_tracker.csv` | Influencer, email, message generated, sent, date, status, mode, delivered to, transport, error |
| `output/report.html` | Review dashboard: stats, every message card, tracker, all profiles with reasons (open in a browser) |
| `n8n/edxso_outreach_sender.json` | Importable n8n workflow for the sending layer |

## Tech stack

- **Python 3.10+, standard library only** (`urllib`, `sqlite3`, `smtplib`, `csv`, `concurrent.futures`). There's no `pip install` step and no dependency drift.
- **YouTube Data API v3** for discovery and metrics.
- **Google Gemini API** (`gemini-3.5-flash-lite`, structured JSON output) for content themes, tone, and message writing.
- **n8n Cloud + Gmail node** (or plain SMTP) for delivery.
- **SQLite** for the outreach log; JSON files for each pipeline stage.

## How each stage works

### 1. Discovery (`outreach/discover.py`)
- Runs `search.list` on 20 long-tail queries from the campaign file (`teacher vlog india`, `nep 2020 for teachers`, `choosing the right school for your child`, ...). The search is limited to India, English-language results and videos from the last 365 days.
- Searching **videos** rather than channels surfaces creators who are actively posting on the topic now.
- `channels.list` pulls subscribers, total views, country, description, keywords, topic categories and the `madeForKids` flag for every channel.
- For channels near the follower range, it pulls the last 12 uploads (`playlistItems` + `videos.list`) to measure engagement.
- **Engagement rate** = (likes + comments) / views across recent uploads at least 3 days old. Brand-new uploads haven't collected engagement yet, and videos with hidden likes are skipped instead of counted as zero. It also stores average views and views-to-subscribers (reach).
- It's quota-aware. A full run costs about 2,600 of the 10,000 free daily units, and every response is cached on disk, so re-runs cost no quota and give the same results.

### 2. Filtering & classification (`outreach/classify.py`)
Every rule produces a check `{passed, detail}`. A creator qualifies only if **all** hard checks pass. Rejected creators list every failed check in plain English, for example `"250,000 followers (range 5,000-100,000)"`.

| Rule | Threshold (from `campaigns/*.json`) |
|---|---|
| Follower count | 5,000-100,000; hidden counts are rejected |
| Engagement rate | ≥ 1.5% over at least 3 sampled videos |
| Activity | last upload ≤ 120 days ago |
| Niche relevance | keyword evidence ≥ 6 for the best-matching audience segment (only judged when recent video titles were fetched, so a follower-count rejection is never mislabelled "off-niche") |
| Audience is not children | `madeForKids` channels rejected (their viewers are kids, not parents or educators) |
| Brand safety | blocklist: betting, casino, "earn money online", prank, ... |
| Individual creator | rejects names that mark an institution or media brand (Pvt, Ltd, Official, News, Public School, ...) |
| Geography | soft rule: India-based creators get a bonus in the fit score |

**Classification:** six brand-fit segments, each with its own keywords and weight: Teachers & Educators, School Leaders, Parents & Family, Early Childhood, EdTech, and Students (low weight because students don't choose schools).
- Relevance counts keyword matches in the channel title (×2), description and keywords, and each recent video title. Recent titles count most because they show what the creator makes *now*.
- A **fit score (0-100)** ranks the shortlist: relevance 40, engagement 25, reach 15, segment weight 10, preferred geography 10.

### 3. Enrichment (`outreach/enrich.py`)
- **Contact email**, only where the creator published it, in this priority order:
  1. The channel description (including de-obfuscating `name [at] site [dot] com`).
  2. Their own linked website (homepage plus `/contact`), fetched only where `robots.txt` allows it.
  3. A *business-intent* line ("for business/collab...") in a recent video description. Institutional domains (`.ac.in`, `.edu`, `.gov`) are dropped, because video descriptions often quote exam-board or sponsor emails.

  If none of these turns up an email, the field is `Not Found`. YouTube's "View email address" button sits behind a CAPTCHA and is deliberately not automated.
- **Links:** Instagram, TikTok, X, Facebook, LinkedIn and website, parsed from the channel and video descriptions.
- **Content themes, tone, inferred audience, standout video:** Gemini reads the real description and the last 12 titles. The "standout video" must exactly match a real title, otherwise it is replaced with the latest upload, so it can't invent a video.
- **Audience age, gender and geography:** marked `Not Available (private YouTube Analytics data)`, because only the creator can see them. The creator's own country is reported separately and labelled as such.

### 4. AI personalization (`outreach/personalize.py`)
**Prompt design:**
- **System prompt:** EDXSO's real services and what a creator gains, plus hard rules. Word limits; reference one specific recent video or theme; one collaboration angle from the brief's list (Sponsorship, Affiliate, UGC, Brand ambassador, Paid placement, Barter); a value proposition; a low-pressure ask. **No invented facts and no quoted metrics.**
- **User prompt:** that creator's own signals (segment, themes, tone, standout and latest video, country, segment-specific angle hint).
- **Variety:** phrasings already used for earlier creators are passed in as "do not reuse", and so is a running count of collaboration angles already pitched, so the batch spreads across angles instead of settling into one template. Generic DM openers ("Hello!", "Loved your…") are rejected by the validator.

**Validation (the review gate):**
- Email 60-90 words, DM 15-30 words.
- Greets the creator by name, with no `[placeholders]`.
- Must share real content words with the creator's titles or themes, so a generic "we'd like to collaborate" fails.
- Must not quote follower or engagement numbers.
- The angle must be one of the allowed ones.

Failures go back to the model with the exact violations, for up to 3 attempts. Anything still failing becomes `needs_review` and is **never sent automatically**.

### 5. Sending layer (`outreach/sender.py`, `n8n/`)
- **Selects** only approved messages with a syntactically valid email. `Not Found`, an invalid email or an unapproved message are each skipped with the reason.
- **Modes:**
  - `dry-run` (default): writes an `.eml` preview to `output/outbox/` and logs `simulated`.
  - `test`: really sends, but redirects every email to `TEST_RECIPIENT`, with the intended address in the subject.
  - `live`: requires `--confirm-live`.
- **Transports:** `--via smtp` (Gmail app password) or `--via n8n`. The n8n option POSTs the batch to the *EDXSO Outreach Sender* workflow (Webhook → Split Out → Gmail → result per email → Respond). That workflow returns per-email `sent`/`failed` statuses, which go into the log. The webhook only runs when the request carries a secret `X-Outreach-Token` header.
- **Duplicate prevention:** checked before sending (by creator *and* by email address, including within the same batch) and enforced by partial `UNIQUE` indexes in SQLite. A failed send stays retryable; a successful one can never be logged twice.
- **Write-ahead logging:** a `sending` row is written *before* anything leaves the machine and updated afterwards. If the process dies mid-send, that row blocks a resend instead of silently emailing the creator twice.
- **No blind retries:** the n8n call is never retried, because sending is not idempotent. If n8n doesn't reply, the batch is marked `unconfirmed` (blocked from resending; check Gmail's Sent folder) rather than `failed`.
- **Errors:** one failed email is logged as `failed` with the error and doesn't stop the batch.
- **Instagram DMs:** Meta's API doesn't allow cold DMs to creators, so nothing is automated or bypassed. Each approved DM is queued as `dm_queued_manual`, with the creator's Instagram link if they published one. A person sends it by hand and records it with `python -m outreach mark-dm --channel <id>`.

## Setup

```bash
git clone <repo> && cd edxso-influencer-outreach
cp .env.example .env        # then fill in the keys below
python -m unittest discover -s tests -v     # 19 offline tests, no keys needed
python -m outreach run                       # full pipeline, dry-run sending
```

`.env` keys:
- `YOUTUBE_API_KEY`: Google Cloud Console → enable *YouTube Data API v3* → Credentials → API key.
- `GEMINI_API_KEY`: aistudio.google.com/apikey (free tier). `GEMINI_MODEL` defaults to `gemini-3.5-flash-lite`.
- `TEST_RECIPIENT`: your own inbox for `--mode test`.
- SMTP transport: `SMTP_USER` / `SMTP_PASSWORD` (Gmail App Password).
- n8n transport: `N8N_WEBHOOK_URL` and `N8N_WEBHOOK_TOKEN`. Import `n8n/edxso_outreach_sender.json`, attach a Gmail OAuth2 credential, set the token in the webhook's *Only Run If* option, and publish.

Stages can be run one at a time, and each reads the previous stage's JSON in `data/<campaign-id>/`:

```bash
python -m outreach discover | classify | enrich | personalize | export
python -m outreach send --mode dry-run
python -m outreach send --mode test --via n8n      # real Gmail delivery to TEST_RECIPIENT
python -m outreach send --mode live --via smtp --confirm-live --limit 20
python -m outreach mark-dm --channel UCxxxx
```

**New niche:** copy `campaigns/edxso_parenting_education.json`, change the queries, segments, thresholds and brand, then run with `--campaign campaigns/your_file.json`. The code doesn't change.

## Scaling from 50 to 500+
- Add queries or set `pages_per_query: 3`: each page is 100 quota units, so about 90 pages per day fit in the free quota. Discovery fetches channels in groups of 50 and recent videos with 8 parallel workers.
- Stages are independent and cached, so a crash or quota stop resumes without re-spending quota or LLM calls.
- The LLM is throttled (`GEMINI_RPM`); on a paid tier, raise it or parallelise `personalize`.
- SQLite works fine at this scale. The log schema maps directly onto Postgres if several senders share it.
- Sending supports `--limit` for daily warm-up caps.

## Limitations (stated honestly)
- **Email coverage is 8/40.** Most creators keep their business email behind YouTube's CAPTCHA-protected button or in an Instagram bio. Bypassing those would break the platforms' terms, so those creators are marked `Not Found`. Paid enrichment tools (Hunter, Apollo) or a manual check could close this gap.
- **Audience age, gender and geography** are private YouTube Analytics data. They would come from the creator's media kit after first contact.
- **Only YouTube** is used for discovery. Instagram and TikTok handles are captured when creators publish them, but those platforms aren't scraped.
- **YouTube rounds subscriber counts** to 3 significant figures (for example 19,150 shows as 19.1K).
- **Niche relevance is keyword-based**: explainable and free, but a creator can slip through on vocabulary alone. The fit-score ranking and the human review gate reduce this.
- **Email validity** is checked by format only; there's no MX lookup or verification service.
- **Test sends:** with test mode on, messages go only to the operator's inbox. No real creator was emailed during this assignment.
