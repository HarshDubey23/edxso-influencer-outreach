import { predict } from "./model.js";

// Creator names and titles come from YouTube: escape before they touch innerHTML.
const h = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (s) => document.querySelector(s);
const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString("en-IN"));
const NICHE = { education_parenting: "Education", fitness: "Fitness", fintech: "Fintech", beauty_fashion: "Beauty & Fashion",
  crypto: "Crypto", gaming: "Gaming", lifestyle: "Lifestyle", technology: "Technology", other: "Unsure" };
const CHECK = { followers: "Follower range", niche_relevance: "Niche relevance (rules)", engagement: "Engagement rate",
  ml_niche_agreement: "Niche classifier (ML)", sample_size: "Too few videos", audience_not_children: "Made for kids",
  individual_creator: "Institution, not a creator", brand_safety: "Brand safety", active: "Inactive channel", audience_authenticity: "Audience authenticity" };
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
document.documentElement.classList.add("js");

async function load() {
  try { const r = await fetch("/api/data"); if (r.ok) return r.json(); } catch {}
  return (await fetch("data.json")).json();
}

function countUp(el, to) {
  if (reduce) { el.textContent = fmt(to); return; }
  const t0 = performance.now(), dur = 1400;
  const tick = (t) => { const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(2, -10 * k);
    el.textContent = fmt(Math.round(to * (k === 1 ? 1 : e))); if (k < 1) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}

function render(D) {
  const C = D.creators, uniq = new Map(C.map((c) => [c.id, c]));
  const q = C.filter((c) => c.status === "qualified");
  const notFound = q.filter((c) => !c.email || c.email === "Not Found").length;
  const approved = D.messages.filter((m) => m.status === "approved").length;
  const sent = D.tracker.filter((t) => t.kind === "email" && ["simulated", "test_sent", "sent"].includes(t.status));
  const tests = sent.filter((t) => t.status === "test_sent").length;
  const dms = D.tracker.filter((t) => t.kind === "instagram_dm").length;
  const inRange = D.campaigns.reduce((s, c) => s + c.funnel.in_range, 0);
  const rej = {};
  D.campaigns.forEach((c) => Object.entries(c.rejections).forEach(([k, v]) => (rej[k] = (rej[k] || 0) + v)));
  const flagged = q.filter((c) => c.auth_flags?.length).length;
  const ex = D.model?.experiments || {};
  const hyb = ex.hybrid_tfidf_plus_rules?.gold, kw = ex.keyword_rules?.gold;

  const vals = { qualified: q.length, discovered: uniq.size, "qualified-n": q.length, approved, notfound: notFound, dms };
  document.querySelectorAll("[data-k]").forEach((el) => {
    const v = vals[el.dataset.k]; if (v == null) return;
    el.classList.contains("count") ? countUp(el, v) : (el.textContent = fmt(v));
  });
  if (hyb) { $("#acc").textContent = `${(hyb.accuracy * 100).toFixed(1)}%`; $("#gold-n").textContent = hyb.n; }
  if (kw) $("#kw-acc").textContent = `${(kw.accuracy * 100).toFixed(1)}%`;
  // the run date is when its sends were logged, not when this page was last rebuilt
  const runDate = D.tracker.map((t) => t.created_at).sort().pop() || D.generated_at;
  $("#sheet-date").textContent = `Declared ${new Date(runDate).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })}`;
  $("#generated").textContent = `Data generated ${new Date(D.generated_at).toUTCString()}`;

  // merit list: top of the ranked shortlist, then real withheld rows with their single failed rule
  const top = [...q].sort((a, b) => b.score - a.score).slice(0, 6);
  $("#merit-rows").innerHTML = top.map((c, i) => `<div class="merit-row" role="row" data-rank="${i + 1}">
    <span class="rank" role="cell">${i + 1}</span><span class="roll" role="cell">${h(c.id.slice(-6))}</span>
    <span class="name" role="cell"><a href="${h(c.url)}" target="_blank" rel="noopener">${h(c.name)}</a></span>
    <span class="niche" role="cell">${h(NICHE[c.niche])}</span><span class="num" role="cell">${fmt(c.followers)}</span>
    <span class="num er" role="cell">${c.er?.toFixed(1)}%</span><span class="marks" role="cell">${Math.round(c.score)}</span></div>`).join("");
  const single = C.filter((c) => c.status === "rejected" && c.titles?.length && c.reasons.length === 1);
  const pickBy = (k) => single.find((c) => !c.checks[k]?.passed);
  const held = ["ml_niche_agreement", "brand_safety", "engagement"].map(pickBy).filter(Boolean);
  $("#withheld-rows").innerHTML = held.map((c) => `<div class="merit-row struck" role="row">
    <span class="rank" role="cell">—</span><span class="roll" role="cell">${h(c.id.slice(-6))}</span>
    <span class="name" role="cell">${h(c.name)}</span><span class="niche" role="cell">${h(NICHE[c.niche])}</span>
    <span class="num" role="cell">${fmt(c.followers)}</span><span class="num er" role="cell">${c.er != null ? c.er.toFixed(1) + "%" : "—"}</span>
    <span class="marks" role="cell"></span><span class="reason" role="cell">Withheld: ${h(c.reasons[0])}</span></div>`).join("");

  // the nine steps, each with the run's own count
  const passes = (c, ks) => ks.every((k) => !c.checks[k] || c.checks[k].passed);
  const RULES = ["followers", "engagement", "sample_size", "active", "niche_relevance", "audience_not_children", "brand_safety", "individual_creator"];
  const afterRules = C.filter((c) => passes(c, RULES)).length;
  const afterML = C.filter((c) => passes(c, [...RULES, "ml_niche_agreement"])).length;
  const steps = [
    ["Discover", "YouTube Data API search over long-tail queries for 8 niches, then full channel and video statistics.", `<b>${fmt(uniq.size)}</b> channels found`, "across 8 niche campaigns"],
    ["Range", "Micro-influencers only: 5,000 to 100,000 subscribers; hidden counts rejected.", `<b>${fmt(inRange)}</b> channels left`, `${fmt(rej.followers || 0)} outside the range`],
    ["Rules", "Engagement, activity, video sample, niche keywords, brand safety, made-for-kids and institution checks.", `<b>${fmt(afterRules)}</b> channels left`, `${fmt(rej.engagement || 0)} low engagement, ${fmt(rej.niche_relevance || 0)} off-niche`],
    ["Classify", "A trained TF-IDF + logistic-regression model blended with keyword rules confirms the niche.", `<b>${fmt(afterML)}</b> channels left`, hyb ? `${(hyb.accuracy * 100).toFixed(1)}% accurate on held-out channels` : ""],
    ["Authenticity", "Reach, like-rate outliers and comment ratios screen for inflated audiences.", `<b>${fmt(q.length)}</b> qualified`, `${fmt(flagged)} flagged for a closer look`],
    ["Enrich", "Contact email only where the creator published it; links, themes, tone and standout video.", `<b>${fmt(q.length - notFound)}</b> reachable by email`, `${fmt(notFound)} marked Not Found, none guessed`],
    ["Write", "Gemini writes a 60–90 word email and a 15–30 word DM from the creator's own videos, re-checked up to 3 times.", `<b>${fmt(approved)}</b> messages approved`, `${fmt(q.length - approved)} held for human review`],
    ["Send", "n8n + Gmail, write-ahead logged, duplicate-locked; test mode redirects every email to the operator.", `<b>${fmt(sent.length)}</b> emails logged`, `${tests} real test sends, the rest simulated`],
    ["Follow through", "Reply intent triage, do-not-contact list, one follow-up when due, Instagram DMs by hand.", `<b>${fmt(dms)}</b> DMs queued`, "for a person to send"],
  ];
  $("#steps").innerHTML = steps.map(([t, p, m, sub], i) => `<li class="step" data-settle><span class="step-n" aria-hidden="true">${i + 1}</span>
    <h3>${t}</h3><p>${p}</p><div class="mark">${m}${sub ? `<div class="sub">${h(sub)}</div>` : ""}</div></li>`).join("");

  // withheld tally
  const rows = Object.entries(rej).sort((a, b) => b[1] - a[1]), max = rows[0]?.[1] || 1;
  $("#rej-total").textContent = `${fmt(C.filter((c) => c.status === "rejected").length)} withheld across 8 niches`;
  $("#tally").innerHTML = rows.map(([k, v]) => `<div class="tally-row${k === "ml_niche_agreement" ? " ml" : ""}">
    <span>${h(CHECK[k] || k)}</span><div class="bar" style="--w:${((v / max) * 100).toFixed(2)}%"></div><span class="num">${fmt(v)}</span></div>`).join("");

  // case file: real in-range channels that failed exactly one rule, one per rule type
  const shown = new Set(held.map((c) => c.id));  // never repeat a channel already shown in the first viewport
  const cases = ["ml_niche_agreement", "brand_safety", "audience_not_children", "individual_creator", "sample_size", "engagement"]
    .map((k) => single.find((c) => !shown.has(c.id) && !c.checks[k]?.passed)).filter(Boolean);
  $("#cases").innerHTML = cases.map((c) => `<li><span class="who"><b>${h(c.name)}</b><span>${fmt(c.followers)} · ${h(NICHE[c.niche])}</span></span>
    <span class="why">${h(CHECK[Object.keys(c.checks).find((k) => !c.checks[k].passed)] || "")}: ${h(c.reasons[0])}</span></li>`).join("");

  // two real letters: the EDXSO pitch first, then the strongest other niche with a published email
  const demo = new Set(D.campaigns.filter((c) => c.brand.demo_brand).map((c) => c.id));
  const withEmail = D.messages.filter((m) => m.status === "approved" && m.email && m.email !== "Not Found");
  const letters = [withEmail.find((m) => m.niche === "education_parenting"), withEmail.find((m) => m.niche === "gaming") || withEmail.find((m) => m.niche !== "education_parenting")].filter(Boolean);
  $("#letters-list").innerHTML = letters.map((m) => `<article class="letter" data-settle><svg class="pin pin-l"><use href="#pin"/></svg>
    <span class="wc">${m.email_words} words · DM ${m.dm_words}</span>
    <div class="to">To <b>${h(m.influencer)}</b> &lt;${h(m.email)}&gt;<br>From ${h(m.brand)} · ${h(m.angle)}${demo.has(m.campaign) ? '<span class="demo">Demo brief</span>' : ""}</div>
    <p class="subj">${h(m.subject)}</p><p class="body">${h(m.body)}</p>
    <div class="dm"><span class="dm-label">Instagram DM</span>${h(m.dm)}</div>
    ${m.signals?.length ? `<p class="margin">Drawn from: ${m.signals.map(h).join(" · ")}</p>` : ""}</article>`).join("");

  observe();
}

// the examiner: the in-browser model re-stamps on every edit
const PRESETS = [
  "Ms. Kavya Teaches\nClassroom management tips for new teachers\nLesson plan for Class 6 science\nCBSE competency based questions explained",
  "RushGod Gaming\nBGMI 1v4 clutch in new map\nBest sensitivity settings for mobile\nFree Fire rank push live",
  "Glow with Ira\nMy 3 step skincare routine for oily skin\nSunscreen under 500 rupees tested\nNiacinamide serum honest review",
  "Daily Bhakti Songs\nMorning aarti 108 times\nShiv bhajan non stop\nKrishna flute meditation music",
];
async function examiner() {
  let web;
  try { web = await (await fetch(location.pathname.endsWith("/app.html") ? "/api/model-web" : "niche_classifier_web.json")).json(); }
  catch { try { web = await (await fetch("/api/model-web")).json(); } catch { $("#exam-terms").textContent = "Model file unavailable."; return; } }
  const stamp = $("#exam-stamp"), input = $("#exam-in");
  let last = "";
  const run = () => {
    const p = predict(web, input.value);
    const label = NICHE[p.niche] || p.niche;
    $("#exam-niche").textContent = label;
    $("#exam-conf").textContent = `${Math.round(p.confidence * 100)}% confident`;
    stamp.classList.toggle("uncertain", p.niche === "other");
    if (label !== last && !reduce) { stamp.classList.remove("press"); void stamp.offsetWidth; stamp.classList.add("press"); }
    last = label;
    const entries = Object.entries(p.probs).sort((a, b) => b[1] - a[1]);
    $("#exam-probs").innerHTML = entries.map(([k, v], i) => `<div class="prob${i === 0 ? " top" : ""}"><span>${h(NICHE[k] || k)}</span>
      <div class="track"><div class="fill" style="--p:${(v * 100).toFixed(1)}%"></div></div><span class="num">${Math.round(v * 100)}%</span></div>`).join("");
    $("#exam-terms").textContent = p.niche === "other" ? "Below the 30% confidence bar, so the examiner abstains instead of guessing."
      : p.matchedTerms.length ? `Weighed most: ${p.matchedTerms.slice(0, 6).join(", ")}` : "";
  };
  input.addEventListener("input", run);
  document.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => { input.value = PRESETS[b.dataset.preset]; run(); }));
  run();
}

function observe() {
  const settle = (el) => {
    el.classList.add("in");
    el.querySelectorAll?.("[data-stamp]").forEach((s) => !reduce && s.classList.add("press"));
  };
  const targets = document.querySelectorAll("[data-settle]");
  if (!("IntersectionObserver" in window)) return targets.forEach(settle);
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { settle(e.target); io.unobserve(e.target); } }), { threshold: 0.15 });
  targets.forEach((t) => io.observe(t));
  setTimeout(() => targets.forEach(settle), 4000); // never leave anything un-settled
}

load().then(render).catch((e) => { console.error(e); observe(); });
examiner();
