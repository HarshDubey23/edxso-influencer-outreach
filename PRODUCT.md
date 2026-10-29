# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Primary: the reviewers at EDXSO (HR and engineers) evaluating an AI Engineer Intern assignment. They open one link, have
minutes, and must decide whether this work clears the bar for the next round. (Inferred from the request; the user asked
that the page carry no personal details and let the project speak for itself.)

Secondary: an operator running outreach (the person who reviews messages, sends, and handles replies), served by the
working dashboard.

## Product Purpose
An end-to-end micro-influencer outreach engine: discovers creators on YouTube across 8 niches, filters them with rules,
a trained niche classifier and an audience-authenticity score, enriches only published contact data, writes a
personalised email + Instagram DM per creator with Gemini, gates them through validation and human review, sends via
n8n + Gmail with duplicate-proof logging, triages replies and schedules follow-ups. Success: a reviewer believes the
system is real, rigorous and production-minded within one visit.

## Positioning
Every number comes from a real run on real public data, and every decision is explainable: each creator carries an
audit trail of the exact rule outcomes, the classifier is evaluated against held-out labels and runs live in the
visitor's browser, and nothing (emails, metrics, audience data) is invented.

## Operating Context
Reviewers arrive from a Google Form link, usually on a laptop, sometimes a phone. The public site is static (Vercel),
read-only, emails masked; the full interactive mode runs locally via FastAPI.

## Capabilities and Constraints
- Static HTML/CSS/JS, no build step; dashboard modes: live (local API) and public (static data.json).
- In-browser classifier (dashboard/model.js) must keep matching Python predictions.
- All creator text is untrusted (YouTube): escape before rendering.
- Must work at phone width.

## Brand Commitments
- No personal details on the page (user's explicit instruction).
- EDXSO appears by name only, never its logo or styling; the page must not read as an official EDXSO property.
- Brands other than EDXSO are fictional demo briefs and are labelled as such.

## Evidence on Hand
Real run (29 Oct 2026): 2,629 unique channels, 743 in 5k-100k, 161 qualified, 66 published emails, 158/161 messages
approved, 65 simulated sends, 2 real test sends via n8n + Gmail, 160 DMs queued; classifier 89.4% held-out accuracy vs
80.9% keyword rules. Source: dashboard/data.json, models/metrics.json, MODEL_CARD.md. No testimonials, customers or
business results exist; none may be implied.

## Product Principles
- Show the mechanism working, not claims about it.
- Every figure traceable to the dataset.
- Honesty labels are part of the design, not fine print.
- Rigor over decoration.
