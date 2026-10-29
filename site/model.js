// In-browser port of outreach/ml.py predict(): TF-IDF + logistic regression blended with keyword rules.
// Same tokenizer, n-grams, sublinear tf, idf, l2 norm and softmax as scikit-learn, so results match Python.

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const kwRegexCache = new Map();
function kwRegex(words) {
  const key = words.join("\u0001");
  if (!kwRegexCache.has(key)) {
    kwRegexCache.set(key, new RegExp(`(?<![a-z0-9])(${words.map((w) => esc(w.toLowerCase())).join("|")})(?![a-z0-9])`, "g"));
  }
  const rx = kwRegexCache.get(key);
  rx.lastIndex = 0;
  return rx;
}

// mirrors classify.relevance(): channel name x2, up to 4 distinct hits in the description, +1 per matching title
function relevance(name, about, titles, words) {
  const hit = (t) => kwRegex(words).test(t);
  const distinct = new Set(about.match(kwRegex(words)) || []);
  return 2 * (hit(name) ? 1 : 0) + Math.min(4, distinct.size) + titles.filter(hit).length;
}

export function predict(web, text) {
  if (!web.index) web.index = new Map(web.vocab.map((t, i) => [t, i]));
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const name = (lines[0] || "").toLowerCase().slice(0, 80);
  const about = text.toLowerCase();
  const titles = lines.slice(1, 20).map((l) => l.toLowerCase());

  // TF-IDF features (sklearn builds n-grams from the token list joined by single spaces)
  const toks = about.match(/[a-z0-9]{2,}/g) || [];
  const counts = new Map();
  const add = (t) => web.index.has(t) && counts.set(t, (counts.get(t) || 0) + 1);
  toks.forEach((t, i) => { add(t); if (i + 1 < toks.length) add(t + " " + toks[i + 1]); });
  let norm = 0;
  const feats = [];
  for (const [t, c] of counts) {
    const i = web.index.get(t);
    const v = (1 + Math.log(c)) * web.idf[i];
    feats.push([i, v]); norm += v * v;
  }
  norm = Math.sqrt(norm) || 1;
  const z = web.coef.map((row, k) => feats.reduce((s, [i, v]) => s + row[i] * v / norm, web.intercept[k]));
  const m = Math.max(...z);
  const e = z.map((x) => Math.exp(x - m));
  const sum = e.reduce((a, b) => a + b, 0);
  const model = Object.fromEntries(web.classes.map((c, k) => [c, e[k] / sum]));

  // keyword rules as a distribution
  const kw = {};
  let tot = 0;
  for (const [niche, segs] of Object.entries(web.keywords)) {
    kw[niche] = Math.max(...segs.map((words) => relevance(name, about, titles, words)));
    tot += kw[niche];
  }
  const probs = {};
  for (const c of web.classes) probs[c] = tot ? web.blend * model[c] + (1 - web.blend) * (kw[c] || 0) / tot : model[c];
  const best = Object.keys(probs).reduce((a, b) => (probs[a] >= probs[b] ? a : b));
  return { niche: probs[best] >= web.uncertain ? best : "other", confidence: probs[best], probs, model, keywordHits: kw,
           matchedTerms: [...counts.keys()].sort((a, b) => Math.max(...web.coef.map((r) => r[web.index.get(b)])) -
                                                        Math.max(...web.coef.map((r) => r[web.index.get(a)]))).slice(0, 8) };
}
