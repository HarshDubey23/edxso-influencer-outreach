# Model card: creator niche classifier

**Task:** given a YouTube channel's name, description and recent video titles, predict its content niche
(one of 8 campaign niches) or abstain ("other") when confidence < 0.3.

**Model (shipped):** a hybrid. TF-IDF (word 1-2 grams, 8k features, sublinear tf) + multinomial logistic regression
(class-balanced), averaged 0.5:0.5 with the campaigns' hand-written keyword rules turned into a distribution.
The learned model generalises beyond the keyword lists; the rules anchor niches with little training data.
It's small, explainable (per-word weights), trains in about a second, and is exported to JSON so the public dashboard
runs the same hybrid in the browser.

**Training data:** 385 real channels from this project's YouTube discovery. Weak ("silver") label = the one niche
whose searches found the channel, kept only when the channel's own text has keyword evidence for that niche.
Distribution: {'beauty_fashion': 44, 'crypto': 41, 'education_parenting': 96, 'fintech': 36, 'fitness': 43, 'gaming': 30, 'lifestyle': 42, 'technology': 53}.

**Evaluation data:** 199 channels sampled at random per niche and labelled independently by Gemini (temperature 0),
which was also allowed to answer "other". They were held out from training. Distribution: {'beauty_fashion': 23, 'other': 4, 'lifestyle': 33, 'crypto': 20, 'education_parenting': 26, 'technology': 26, 'fintech': 18, 'fitness': 24, 'gaming': 25}.

| Approach | 5-fold CV macro-F1 (silver) | Gold accuracy | Gold macro-F1 |
|---|---|---|---|
| keyword_rules | - | 0.809 | 0.752 |
| tfidf_logreg | 0.951 | 0.824 | 0.812 |
| hybrid_tfidf_plus_rules | - | 0.894 | 0.853 |

Per-class results of the shipped hybrid on the gold set:

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| beauty_fashion | 0.96 | 1.00 | 0.98 | 23 |
| crypto | 0.73 | 0.95 | 0.83 | 20 |
| education_parenting | 0.83 | 0.77 | 0.80 | 26 |
| fintech | 0.84 | 0.89 | 0.86 | 18 |
| fitness | 1.00 | 0.88 | 0.93 | 24 |
| gaming | 1.00 | 0.96 | 0.98 | 25 |
| lifestyle | 0.93 | 0.85 | 0.89 | 33 |
| technology | 0.96 | 0.96 | 0.96 | 26 |
| other | 0.40 | 0.50 | 0.44 | 4 |

Abstain threshold trade-off (gold accuracy / coverage = share of channels the model commits to). The threshold
0.3 was fixed before evaluation; this table shows the trade-off rather than being used to tune on test data.

| Threshold | TF-IDF + LR | Hybrid |
|---|---|---|
| 0.2 | 0.889 / 0.995 | 0.889 / 0.995 |
| 0.25 | 0.879 / 0.93 | 0.889 / 0.99 |
| 0.3 | 0.824 / 0.839 | 0.894 / 0.975 |
| 0.35 | 0.799 / 0.799 | 0.869 / 0.94 |
| 0.4 | 0.734 / 0.729 | 0.839 / 0.894 |
| 0.5 | 0.628 / 0.613 | 0.739 / 0.764 |

**How it's used:** in filtering, a creator must be predicted as the campaign's niche with probability ≥ the campaign's
`min_ml_confidence` (check `ml_niche_agreement`). This catches off-niche channels that keyword rules let through
(for example a skincare vlog that mentions "kids").

**Limitations:** the labels are weak and the judge is itself an LLM, not a human annotator, so treat these numbers as
indicative. Hindi/Devanagari text is ignored by the tokenizer. The data is India-focused, English-relevance YouTube only.
