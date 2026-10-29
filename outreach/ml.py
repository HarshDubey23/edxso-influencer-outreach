"""Niche classifier: TF-IDF + logistic regression, trained on weak labels from discovery.

Labels (no hand-labelling needed, and no label leakage into the gold set):
  silver  a channel found by exactly ONE niche's searches AND showing keyword evidence for that niche
          (search results alone are noisy: a "fitness" query also returns news and comedy channels)
  gold    an independent judge: Gemini labels a stratified random sample (incl. an "other" option);
          those channels are held out from training entirely

Experiments reported in models/metrics.json and MODEL_CARD.md:
  1. keyword rules (argmax of campaign keyword scores)   - the hand-written baseline
  2. TF-IDF (word 1-2 grams) + logistic regression        - shipped model (also runs in the browser)
  3. Gemini embeddings + logistic regression             - semantic alternative
"""
import json
import random
from collections import Counter

from . import llm
from .classify import relevance
from .config import ROOT, all_campaigns, load_stage

MODELS = ROOT / "models"
TOKEN = r"[a-z0-9]{2,}"  # identical tokenizer in the browser (dashboard/model.js), so web == python predictions
SILVER_MIN = 4
GOLD_PER_NICHE = 25
UNCERTAIN = 0.30  # fixed before looking at gold results; the full sweep is reported, not tuned on gold
BLEND = 0.5


def creator_text(rec: dict) -> str:
    titles = " | ".join(v["title"] for v in rec["recent_videos"])
    return f"{rec['name']}. {rec['description'][:1500]} {rec.get('channel_keywords', '')} Videos: {titles}"


def build_corpus(campaigns: list[dict]) -> list[dict]:
    by_niche = {c["niche"]: c for c in campaigns}
    found: dict[str, dict] = {}
    for c in campaigns:
        try:
            recs = load_stage(c, "discovered")
        except SystemExit:
            continue
        for r in recs:
            if r["recent_videos"]:  # text-rich channels only (in or near the follower range)
                found.setdefault(r["channel_id"], {"rec": r, "niches": set()})["niches"].add(c["niche"])
    rows = []
    for cid, e in found.items():
        silver = None
        if len(e["niches"]) == 1:
            n = next(iter(e["niches"]))
            if max(relevance(e["rec"], by_niche[n]["segments"]).values()) >= SILVER_MIN:
                silver = n
        rows.append({"channel_id": cid, "name": e["rec"]["name"], "text": creator_text(e["rec"]),
                     "found_in": sorted(e["niches"]), "silver": silver,
                     "titles": [v["title"] for v in e["rec"]["recent_videos"][:8]], "description": e["rec"]["description"][:400]})
    return rows


GOLD_SCHEMA = {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "channel_id": {"type": "STRING"}, "niche": {"type": "STRING"}}, "required": ["channel_id", "niche"]}}


def gemini_gold(rows: list[dict], campaigns: list[dict], seed: int = 7) -> dict[str, str]:
    """Stratified random sample labelled by Gemini (temperature 0, cached). Returns {channel_id: niche|other}."""
    rng = random.Random(seed)
    sample = []
    for c in campaigns:
        pool = [r for r in rows if c["niche"] in r["found_in"]]
        sample += rng.sample(pool, min(GOLD_PER_NICHE, len(pool)))
    sample = list({r["channel_id"]: r for r in sample}.values())
    options = {c["niche"]: ", ".join(s["label"] for s in c["segments"].values()) for c in campaigns}
    system = ("You label YouTube channels by their MAIN content niche. Options:\n" +
              "\n".join(f"- {k}: {v}" for k, v in options.items()) +
              "\n- other: none of the above is the main topic (news, comedy, devotional, music, general entertainment, ...)\n"
              "Judge only from the given titles and description. Return one label per channel_id.")
    gold = {}
    for i in range(0, len(sample), 10):
        batch = sample[i:i + 10]
        prompt = "\n\n".join(f"channel_id: {r['channel_id']}\nname: {r['name']}\ndescription: {r['description']}\n"
                             f"recent titles: {' | '.join(r['titles'])}" for r in batch)
        try:
            out = llm.generate_json(system, prompt, GOLD_SCHEMA, temperature=0.0)
        except llm.LLMError as e:
            print(f"  ! gold batch skipped: {e}")
            continue
        valid = set(options) | {"other"}
        gold.update({o["channel_id"]: o["niche"] for o in out if o["niche"] in valid})
    return gold


def keyword_probs(rec: dict, campaigns: list[dict]) -> dict[str, float]:
    """Hand-written rules as a distribution: each niche's best segment keyword score, normalised."""
    s = {c["niche"]: max(relevance(rec, c["segments"]).values()) for c in campaigns}
    tot = sum(s.values())
    return {k: v / tot for k, v in s.items()} if tot else {}


def blend(model_probs: dict[str, float], kw: dict[str, float]) -> dict[str, float]:
    """Hybrid: the model generalises beyond the keyword lists, the rules anchor thin classes."""
    return {k: BLEND * p + (1 - BLEND) * kw.get(k, 0.0) for k, p in model_probs.items()} if kw else model_probs


def decide(probs: dict[str, float], threshold: float = None) -> str:
    if not probs:
        return "other"
    best = max(probs, key=probs.get)
    return best if probs[best] >= (UNCERTAIN if threshold is None else threshold) else "other"


def _pipeline():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    return Pipeline([
        ("tfidf", TfidfVectorizer(lowercase=True, token_pattern=TOKEN, ngram_range=(1, 2), sublinear_tf=True,
                                  min_df=2, max_features=8000)),
        ("clf", LogisticRegression(C=8.0, max_iter=2000, class_weight="balanced")),
    ])


def _as_dicts(probs, classes) -> list[dict[str, float]]:
    return [dict(zip(classes, map(float, p))) for p in probs]


def _sweep(yg, prob_dicts) -> list[dict]:
    """Accuracy vs coverage (share not abstained) per threshold: the abstain trade-off made visible."""
    out = []
    for t in (0.2, 0.25, 0.3, 0.35, 0.4, 0.5):
        pred = [decide(p, t) for p in prob_dicts]
        out.append({"threshold": t, "accuracy": round(sum(a == b for a, b in zip(yg, pred)) / len(yg), 3),
                    "coverage": round(sum(p != "other" for p in pred) / len(pred), 3)})
    return out


def _gold_report(y_true, y_pred, labels) -> dict:
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
    return {"n": len(y_true), "accuracy": round(accuracy_score(y_true, y_pred), 3),
            "report": classification_report(y_true, y_pred, labels=labels, output_dict=True, zero_division=0),
            "labels": labels, "confusion": confusion_matrix(y_true, y_pred, labels=labels).tolist()}


def train() -> dict:
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.metrics import f1_score

    campaigns = all_campaigns()
    rows = build_corpus(campaigns)
    recs = {}
    for c in campaigns:
        try:
            recs.update({r["channel_id"]: r for r in load_stage(c, "discovered") if r["recent_videos"]})
        except SystemExit:
            pass
    print(f"Corpus: {len(rows)} channels with video text, {sum(r['silver'] is not None for r in rows)} silver-labelled")

    gold = gemini_gold(rows, campaigns)
    print(f"Gold (Gemini judge): {len(gold)} channels, {Counter(gold.values())}")
    train_rows = [r for r in rows if r["silver"] and r["channel_id"] not in gold]
    gold_rows = [r for r in rows if r["channel_id"] in gold]
    X, y = [r["text"] for r in train_rows], [r["silver"] for r in train_rows]
    niches = sorted(set(y))
    labels = niches + ["other"]

    cv = StratifiedKFold(5, shuffle=True, random_state=7)
    cv_pred = cross_val_predict(_pipeline(), X, y, cv=cv)
    model = _pipeline().fit(X, y)
    classes = list(model.classes_)
    yg = [gold[r["channel_id"]] for r in gold_rows]
    model_p = _as_dicts(model.predict_proba([r["text"] for r in gold_rows]), classes)
    kw_p = [keyword_probs(recs[r["channel_id"]], campaigns) for r in gold_rows]
    hybrid_p = [blend(m, k) for m, k in zip(model_p, kw_p)]

    experiments = {
        "keyword_rules": {"gold": _gold_report(yg, [decide(k, 0.0) for k in kw_p], labels)},
        "tfidf_logreg": {"cv_macro_f1": round(f1_score(y, cv_pred, average="macro"), 3),
                         "gold": _gold_report(yg, [decide(p) for p in model_p], labels), "sweep": _sweep(yg, model_p)},
        "hybrid_tfidf_plus_rules": {"gold": _gold_report(yg, [decide(p) for p in hybrid_p], labels),
                                    "sweep": _sweep(yg, hybrid_p)},
    }
    try:  # semantic experiment: same classifier on Gemini embeddings
        emb = np.array(llm.embed(X + [r["text"] for r in gold_rows]))
        Xe, Ge = emb[:len(X)], emb[len(X):]
        lr = lambda: LogisticRegression(C=4.0, max_iter=2000, class_weight="balanced")
        cv_e = cross_val_predict(lr(), Xe, y, cv=cv)
        m_e = lr().fit(Xe, y)
        experiments["embedding_logreg"] = {"cv_macro_f1": round(f1_score(y, cv_e, average="macro"), 3),
                                           "gold": _gold_report(yg, [decide(p) for p in _as_dicts(m_e.predict_proba(Ge), list(m_e.classes_))], labels)}
    except llm.LLMError as e:
        print(f"  ! embedding experiment skipped: {e}")

    MODELS.mkdir(exist_ok=True)
    joblib.dump(model, MODELS / "niche_classifier.joblib")
    _export_web(model)
    metrics = {"train_size": len(X), "train_distribution": Counter(y), "gold_size": len(gold_rows),
               "gold_distribution": Counter(yg), "uncertain_threshold": UNCERTAIN, "experiments": experiments}
    (MODELS / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    _model_card(metrics)
    for k, v in experiments.items():
        print(f"  {k:<17} gold accuracy {v['gold']['accuracy']:.3f}" +
              (f"   CV macro-F1 {v['cv_macro_f1']:.3f}" if "cv_macro_f1" in v else ""))
    return metrics


def _export_web(model) -> None:
    """Vocabulary, idf and weights as JSON so the dashboard can classify text in the browser."""
    tf, clf = model.named_steps["tfidf"], model.named_steps["clf"]
    vocab = sorted(tf.vocabulary_, key=tf.vocabulary_.get)
    web = {"token": TOKEN, "ngram": [1, 2], "sublinear_tf": True, "classes": list(clf.classes_),
           "vocab": vocab, "idf": [round(float(x), 4) for x in tf.idf_],
           "coef": [[round(float(x), 4) for x in row] for row in clf.coef_],
           "intercept": [round(float(x), 4) for x in clf.intercept_], "uncertain": UNCERTAIN, "blend": BLEND,
           "keywords": {c["niche"]: [s["keywords"] for s in c["segments"].values()] for c in all_campaigns()},
           "labels": {c["niche"]: c["name"].split(" x ")[-1] for c in all_campaigns()}}
    (MODELS / "niche_classifier_web.json").write_text(json.dumps(web, separators=(",", ":")), encoding="utf-8")


def _model_card(m: dict) -> None:
    ex = m["experiments"]
    rows = "\n".join(f"| {k} | {v.get('cv_macro_f1', '-')} | {v['gold']['accuracy']} | "
                     f"{v['gold']['report']['macro avg']['f1-score']:.3f} |" for k, v in ex.items())
    ship = "hybrid_tfidf_plus_rules"
    per = ex[ship]["gold"]["report"]
    per_rows = "\n".join(f"| {k} | {per[k]['precision']:.2f} | {per[k]['recall']:.2f} | {per[k]['f1-score']:.2f} | {int(per[k]['support'])} |"
                         for k in ex[ship]["gold"]["labels"] if k in per)
    sweep = "\n".join(f"| {a['threshold']} | {a['accuracy']} / {a['coverage']} | {b['accuracy']} / {b['coverage']} |"
                      for a, b in zip(ex["tfidf_logreg"]["sweep"], ex[ship]["sweep"]))
    (ROOT / "MODEL_CARD.md").write_text(f"""# Model card: creator niche classifier

**Task:** given a YouTube channel's name, description and recent video titles, predict its content niche
(one of {len(m['train_distribution'])} campaign niches) or abstain ("other") when confidence < {m['uncertain_threshold']}.

**Model (shipped):** a hybrid. TF-IDF (word 1-2 grams, 8k features, sublinear tf) + multinomial logistic regression
(class-balanced), averaged {BLEND}:{1 - BLEND} with the campaigns' hand-written keyword rules turned into a distribution.
The learned model generalises beyond the keyword lists; the rules anchor niches with little training data.
It's small, explainable (per-word weights), trains in about a second, and is exported to JSON so the public dashboard
runs the same hybrid in the browser.

**Training data:** {m['train_size']} real channels from this project's YouTube discovery. Weak ("silver") label = the one niche
whose searches found the channel, kept only when the channel's own text has keyword evidence for that niche.
Distribution: {dict(m['train_distribution'])}.

**Evaluation data:** {m['gold_size']} channels sampled at random per niche and labelled independently by Gemini (temperature 0),
which was also allowed to answer "other". They were held out from training. Distribution: {dict(m['gold_distribution'])}.

| Approach | 5-fold CV macro-F1 (silver) | Gold accuracy | Gold macro-F1 |
|---|---|---|---|
{rows}

Per-class results of the shipped hybrid on the gold set:

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
{per_rows}

Abstain threshold trade-off (gold accuracy / coverage = share of channels the model commits to). The threshold
{m['uncertain_threshold']} was fixed before evaluation; this table shows the trade-off rather than being used to tune on test data.

| Threshold | TF-IDF + LR | Hybrid |
|---|---|---|
{sweep}

**How it's used:** in filtering, a creator must be predicted as the campaign's niche with probability ≥ the campaign's
`min_ml_confidence` (check `ml_niche_agreement`). This catches off-niche channels that keyword rules let through
(for example a skincare vlog that mentions "kids").

**Limitations:** the labels are weak and the judge is itself an LLM, not a human annotator, so treat these numbers as
indicative. Hindi/Devanagari text is ignored by the tokenizer. The data is India-focused, English-relevance YouTube only.
""", encoding="utf-8")


_model, _campaigns = None, None


def predict(rec: dict) -> dict:
    """Hybrid prediction {'ml_niche', 'ml_confidence', 'ml_probs'}; empty when no model has been trained yet."""
    global _model, _campaigns
    path = MODELS / "niche_classifier.joblib"
    if _model is None:
        if not path.exists():
            return {"ml_niche": None, "ml_confidence": None, "ml_probs": {}}
        import joblib
        _model, _campaigns = joblib.load(path), all_campaigns()
    p = dict(zip(_model.classes_, map(float, _model.predict_proba([creator_text(rec)])[0])))
    probs = {k: round(v, 3) for k, v in blend(p, keyword_probs(rec, _campaigns)).items()}
    niche = decide(probs)
    return {"ml_niche": niche, "ml_confidence": probs.get(niche, max(probs.values())), "ml_probs": probs}
