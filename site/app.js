import { predict } from "./model.js";

// Creator names, titles and descriptions come from YouTube: always escape before inserting into HTML.
const h = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (s, el = document) => el.querySelector(s);
const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString("en-IN"));
const pct = (n, d = 1) => (n == null ? "—" : `${Number(n).toFixed(d)}%`);
const NICHE = {
  education_parenting: "Education & Parenting", fitness: "Fitness", fintech: "Fintech", beauty_fashion: "Beauty & Fashion",
  crypto: "Crypto & Web3", gaming: "Gaming", lifestyle: "Lifestyle", technology: "Technology", other: "Other / unsure",
};
const nicheName = (k) => NICHE[k] || k;
const CHECK = {
  followers: "Follower range", engagement: "Engagement rate", sample_size: "Enough videos", active: "Recently active",
  niche_relevance: "Niche relevance (rules)", ml_niche_agreement: "Niche classifier (ML)", audience_authenticity: "Audience authenticity",
  audience_not_children: "Not made for kids", brand_safety: "Brand safety", individual_creator: "Individual creator",
};

let D, WEB, LIVE = false;

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

async function boot() {
  try { D = await api("/api/data"); LIVE = true; } catch { D = await (await fetch("data.json")).json(); }
  try { WEB = await (await fetch(LIVE ? "/api/model-web" : "niche_classifier_web.json")).json(); } catch { WEB = null; }
  $("#mode").textContent = LIVE ? "live · local API" : "public demo · read-only";
  $("#mode").classList.toggle("live", LIVE);
  $("#generated").textContent = `Data generated ${new Date(D.generated_at).toLocaleString()}.`;
  const sections = { overview: renderOverview, creators: renderCreators, messages: renderMessages, match: renderMatch,
                     ask: renderAsk, model: renderModel, replies: renderReplies, tracker: renderTracker };
  for (const [id, fn] of Object.entries(sections)) {
    try { fn(); } catch (e) { console.error(id, e); $(`#${id}`).innerHTML = `<p class="issues">This section failed to render: ${h(e.message)}</p>`; }
  }
  const tab = location.hash.slice(1);
  if (tab) show(tab);
}

function show(tab) {
  document.querySelectorAll("nav.tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab));
  document.querySelectorAll("main > section").forEach((s) => (s.hidden = s.id !== tab));
  history.replaceState(null, "", `#${tab}`);
  scrollTo({ top: 0 });
}
document.querySelectorAll("nav.tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
addEventListener("hashchange", () => { const t = location.hash.slice(1); if (document.getElementById(t)) show(t); });

const liveOnly = (what) => `<p class="note">${h(what)} calls Gemini through the local FastAPI service, so it's live only when you run
  <span class="mono">uvicorn outreach.api:app</span>. The examples below are real outputs captured from that service.</p>`;

/* ---------- Overview ---------- */
function renderOverview() {
  const C = D.creators, q = C.filter((c) => c.status === "qualified");
  const uniq = new Set(C.map((c) => c.id)).size;
  const emails = q.filter((c) => c.email && c.email !== "Not Found").length;
  const approved = D.messages.filter((m) => m.status === "approved").length;
  const sent = D.tracker.filter((t) => ["simulated", "test_sent", "sent"].includes(t.status) && t.kind.startsWith("email")).length;
  const gold = D.model?.experiments?.hybrid_tfidf_plus_rules?.gold?.accuracy;
  const rej = {};
  D.campaigns.forEach((c) => Object.entries(c.rejections).forEach(([k, v]) => (rej[k] = (rej[k] || 0) + v)));
  const rejMax = Math.max(...Object.values(rej), 1);
  const maxDisc = Math.max(...D.campaigns.map((c) => c.funnel.discovered), 1);

  $("#overview").innerHTML = `
    <h1>From ${fmt(uniq)} real YouTube channels to personalised, reviewed outreach.</h1>
    <p class="lede">Eight niches, one engine. Creators are discovered through the YouTube Data API, filtered by explainable rules,
      a trained niche classifier and an audience-authenticity score, enriched only with what they published themselves,
      then pitched with Gemini-written messages that must pass validation and human review before anything is sent.</p>
    <div class="kpis">
      <div class="kpi"><b>${fmt(uniq)}</b><span>channels discovered</span></div>
      <div class="kpi"><b>${fmt(q.length)}</b><span>qualified micro-influencers</span></div>
      <div class="kpi"><b>${D.campaigns.length}</b><span>niches / brand briefs</span></div>
      <div class="kpi"><b>${fmt(emails)}</b><span>published contact emails</span></div>
      <div class="kpi"><b>${fmt(approved)}</b><span>messages approved</span></div>
      <div class="kpi"><b>${gold != null ? Math.round(gold * 100) + "%" : "—"}</b><span>classifier accuracy (held-out)</span></div>
    </div>
    <div class="flow" aria-label="Pipeline">
      <span>YouTube Data API</span><i>→</i><span>Filter: rules</span><i>+</i><span class="ai">ML niche classifier</span><i>+</i>
      <span>Authenticity score</span><i>→</i><span>Enrich (email, links)</span><i>→</i><span class="ai">Gemini themes &amp; tone</span><i>→</i>
      <span class="ai">Semantic brand fit</span><i>→</i><span class="ai">Gemini email + DM</span><i>→</i><span>Validate &amp; review</span><i>→</i>
      <span>n8n + Gmail</span><i>→</i><span>Tracker</span><i>→</i><span class="ai">Reply triage</span><i>→</i><span>Follow-up</span>
    </div>

    <h2>Funnel by niche</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>Niche</th><th>Brand brief</th><th class="num">Discovered</th><th></th><th class="num">5k–100k</th>
        <th class="num">Qualified</th><th class="num">Email found</th><th class="num">Approved</th><th class="num">Emails logged</th></tr></thead>
      <tbody>${D.campaigns.map((c) => `<tr>
        <td><b>${h(nicheName(c.niche))}</b></td>
        <td>${h(c.brand.name)} ${c.brand.demo_brand ? '<span class="pill">demo brand</span>' : '<span class="pill accent">real brand</span>'}</td>
        <td class="num">${fmt(c.funnel.discovered)}</td><td style="width:18%"><div class="bar"><i style="width:${(c.funnel.discovered / maxDisc) * 100}%"></i></div></td>
        <td class="num">${fmt(c.funnel.in_range)}</td><td class="num"><b>${fmt(c.funnel.qualified)}</b></td>
        <td class="num">${fmt(c.funnel.with_email)}</td><td class="num">${fmt(c.funnel.messages_approved)}</td>
        <td class="num">${fmt(c.funnel.emails_logged)}</td></tr>`).join("")}</tbody>
    </table></div>

    <div class="grid2" style="margin-top:16px">
      <div class="card"><h3>Why creators were rejected</h3><p class="muted small">Every rejected profile carries its exact reasons. A creator can fail several rules.</p>
        <div class="hbars">${Object.entries(rej).sort((a, b) => b[1] - a[1]).map(([k, v]) => `
          <div class="hbar"><span>${h(CHECK[k] || k)}</span><div class="bar"><i style="width:${(v / rejMax) * 100}%"></i></div><span class="num">${fmt(v)}</span></div>`).join("")}</div>
      </div>
      <div class="card"><h3>What makes this different</h3>
        <ul class="small" style="margin:0;padding-left:18px;display:grid;gap:6px">
          <li><b>A trained, evaluated model</b> decides niche fit, not just keywords: hybrid TF-IDF + logistic regression, ${gold != null ? Math.round(gold * 100) + "%" : ""} accurate on an independently labelled held-out set. <a href="#model">Try it.</a></li>
          <li><b>Fake-engagement screening</b>: reach, like-rate outliers and like-to-comment ratios flag inflated audiences.</li>
          <li><b>Brand-brief engine</b>: any brand describes itself in plain English; embeddings rank every creator. <a href="#match">See it.</a></li>
          <li><b>Zero fabrication</b>: emails only where the creator published them; private audience data is marked unavailable.</li>
          <li><b>Safe sending</b>: write-ahead log, duplicate blocking, do-not-contact list, no blind retries, manual-only DMs.</li>
          <li><b>Closed loop</b>: replies are triaged by intent, unsubscribes are honoured, and follow-ups go out only when due.</li>
        </ul></div>
    </div>`;
}

/* ---------- Creators ---------- */
function renderCreators() {
  const el = $("#creators");
  el.innerHTML = `<h2 style="margin-top:0">Creators</h2>
    <p class="lede">All ${fmt(D.creators.length)} profiles with pass/fail and the reason for every failed rule. Click a row for the full audit trail.</p>
    <div class="filters">
      <input type="search" id="cq" placeholder="Search name, segment, video title…" aria-label="Search creators">
      <select id="cn" aria-label="Niche"><option value="">All niches</option>${D.campaigns.map((c) => `<option value="${h(c.niche)}">${h(nicheName(c.niche))}</option>`).join("")}</select>
      <select id="cs" aria-label="Status"><option value="qualified">Qualified</option><option value="rejected">Rejected</option><option value="">All</option></select>
      <select id="ce" aria-label="Email"><option value="">Email: any</option><option value="yes">Has email</option></select>
    </div>
    <div class="table-wrap"><table><thead><tr><th>Creator</th><th>Niche · segment</th><th class="num">Followers</th><th class="num">ER</th>
      <th class="num">Auth.</th><th>Classifier</th><th class="num">Score</th><th>Email / reason</th></tr></thead><tbody id="ct"></tbody></table></div>
    <p class="muted small" id="cc"></p>`;
  const draw = () => {
    const q = $("#cq").value.toLowerCase(), n = $("#cn").value, s = $("#cs").value, e = $("#ce").value;
    const rows = D.creators.filter((c) => (!n || c.niche === n) && (!s || c.status === s) &&
      (!e || (c.email && c.email !== "Not Found")) &&
      (!q || `${c.name} ${c.segment} ${c.titles.join(" ")}`.toLowerCase().includes(q)))
      .sort((a, b) => (b.status === "qualified") - (a.status === "qualified") || b.score - a.score);
    $("#ct").innerHTML = rows.slice(0, 400).map((c) => `<tr class="click" data-id="${h(c.id)}" data-c="${h(c.campaign)}" tabindex="0">
      <td><b>${h(c.name)}</b><div class="muted small">${h(c.country || "country n/a")}</div></td>
      <td>${h(nicheName(c.niche))}<div class="muted small">${h(c.segment)}</div></td>
      <td class="num">${fmt(c.followers)}</td><td class="num">${pct(c.er, 2)}</td>
      <td class="num">${c.auth == null ? "—" : `<span class="pill ${c.auth >= 70 ? "good" : c.auth >= 40 ? "warn" : "bad"}">${c.auth}</span>`}</td>
      <td>${c.ml_niche ? `${h(nicheName(c.ml_niche))} <span class="muted small">${Math.round(c.ml_conf * 100)}%</span>` : '<span class="muted">—</span>'}</td>
      <td class="num">${c.status === "qualified" ? Number(c.score).toFixed(0) : "—"}</td>
      <td>${c.status === "qualified" ? (c.email && c.email !== "Not Found" ? `<span class="mono">${h(c.email)}</span>` : '<span class="pill">Not Found</span>')
        : `<span class="pill bad">rejected</span> <span class="small">${h(c.reasons[0] || "")}</span>`}</td></tr>`).join("") || `<tr><td colspan="8" class="empty">No creators match.</td></tr>`;
    $("#cc").textContent = `${rows.length} matching${rows.length > 400 ? " (showing first 400)" : ""}.`;
  };
  ["#cq", "#cn", "#cs", "#ce"].forEach((s) => $(s).addEventListener("input", draw));
  $("#ct").addEventListener("click", (ev) => { const tr = ev.target.closest("tr[data-id]"); if (tr) openCreator(tr.dataset.id, tr.dataset.c); });
  $("#ct").addEventListener("keydown", (ev) => { if (ev.key === "Enter") ev.target.closest("tr[data-id]")?.click(); });
  draw();
}

function probBars(probs) {
  const e = Object.entries(probs || {}).sort((a, b) => b[1] - a[1]);
  return `<div class="hbars">${e.map(([k, v]) => `<div class="hbar"><span>${h(nicheName(k))}</span><div class="bar"><i style="width:${v * 100}%"></i></div><span class="num">${Math.round(v * 100)}%</span></div>`).join("")}</div>`;
}

function openCreator(id, campaign) {
  const c = D.creators.find((x) => x.id === id && x.campaign === campaign);
  const m = D.messages.find((x) => x.id === id && x.campaign === campaign);
  $("#detail-body").innerHTML = `<button class="close" onclick="this.closest('dialog').close()">Close</button>
    <h2 style="margin-top:0">${h(c.name)}</h2>
    <p class="row"><span class="pill ${c.status === "qualified" ? "good" : "bad"}">${h(c.status)}</span><span class="pill">${h(nicheName(c.niche))}</span>
      <span class="pill">${h(c.segment)}</span><a href="${h(c.url)}" target="_blank" rel="noopener">Open channel ↗</a></p>
    <div class="kpis"><div class="kpi"><b>${fmt(c.followers)}</b><span>followers</span></div><div class="kpi"><b>${pct(c.er, 2)}</b><span>engagement rate</span></div>
      <div class="kpi"><b>${fmt(c.median_views)}</b><span>median views</span></div><div class="kpi"><b>${c.auth ?? "—"}</b><span>authenticity / 100</span></div></div>
    <h3>Filter audit trail</h3><ul class="checks">${Object.entries(c.checks).map(([k, v]) => `<li><span class="${v.passed ? "ok" : "no"}">${v.passed ? "✓" : "✕"}</span><span>${h(CHECK[k] || k)}</span><span>${h(v.detail)}</span></li>`).join("")}</ul>
    ${c.auth_flags?.length ? `<h3 style="margin-top:16px">Authenticity flags</h3><ul class="small">${c.auth_flags.map((f) => `<li>${h(f)}</li>`).join("")}</ul>` : ""}
    ${Object.keys(c.ml_probs || {}).length ? `<h3 style="margin-top:16px">Niche classifier (hybrid)</h3>${probBars(c.ml_probs)}` : ""}
    <h3 style="margin-top:16px">Recent videos</h3><ul class="small">${c.titles.map((t) => `<li>${h(t)}</li>`).join("") || "<li>Not fetched (outside the follower range)</li>"}</ul>
    ${c.status === "qualified" ? `<h3>Enrichment</h3><ul class="checks">
      <li><span>@</span><span>Email</span><span>${h(c.email)}${c.email_source ? ` <span class="muted">(${h(c.email_source)})</span>` : ""}</span></li>
      <li><span>#</span><span>Themes</span><span>${h((c.themes || []).join(", "))}</span></li>
      <li><span>~</span><span>Tone</span><span>${h(c.tone)}</span></li>
      <li><span>★</span><span>Standout video</span><span>${h(c.standout)}</span></li>
      <li><span>◎</span><span>Inferred audience</span><span>${h(c.audience)}</span></li>
      <li><span>↗</span><span>Links</span><span>${[c.website, ...Object.values(c.socials || {})].filter(Boolean).map((u) => `<a href="${h(u)}" target="_blank" rel="noopener">${h(u)}</a>`).join(" · ") || "None published"}</span></li>
      <li><span>⚖</span><span>Audience age / gender</span><span>Not Available (private YouTube Analytics)</span></li>
      <li><span>%</span><span>Brand fit (semantic)</span><span>${c.brand_fit ?? "—"} / 100</span></li></ul>` : ""}
    ${m ? `<h3 style="margin-top:16px">Generated outreach</h3>${messageCard(m)}` : ""}`;
  $("#detail").showModal();
}

/* ---------- Messages ---------- */
function messageCard(m) {
  const c = D.creators.find((x) => x.id === m.id && x.campaign === m.campaign) || {};
  return `<article class="card msg" data-id="${h(m.id)}" data-c="${h(m.campaign)}">
    <header><a href="${h(c.url || "#")}" target="_blank" rel="noopener">${h(m.influencer)}</a>
      <span class="pill">${h(nicheName(m.niche))}</span><span class="pill">${h(m.brand)}</span>
      <span class="pill ${m.status === "approved" ? "good" : "warn"}">${h(m.status.replace("_", " "))}</span>
      ${m.edited ? '<span class="pill accent">human-edited</span>' : ""}</header>
    <div class="muted small">${h(m.angle || "")} · ${h(m.email && m.email !== "Not Found" ? m.email : "no public email (DM / manual only)")}</div>
    <div class="label"><span>Email pitch</span><span>${m.email_words ?? "—"} words</span></div>
    <div class="text"><div class="subject">${h(m.subject || "")}</div>${h(m.body || "")}</div>
    <div class="label"><span>Instagram DM</span><span>${m.dm_words ?? "—"} words</span></div>
    <div class="text">${h(m.dm || "")}</div>
    ${m.signals?.length ? `<div class="label"><span>Personalisation signals used</span></div><div class="chips">${m.signals.map((s) => `<span class="pill">${h(s)}</span>`).join("")}</div>` : ""}
    ${m.issues?.length ? `<p class="issues">Held for review: ${h(m.issues.join("; "))}</p>` : ""}
    ${LIVE ? `<div class="row" style="margin-top:10px"><button class="btn ghost" data-act="edit">Edit</button>
      ${m.status !== "approved" ? '<button class="btn" data-act="approve">Re-validate &amp; approve</button>' : ""}</div>` : ""}
  </article>`;
}

function renderMessages() {
  const el = $("#messages");
  el.innerHTML = `<h2 style="margin-top:0">Personalised messages</h2>
    <p class="lede">A 60–90 word email and a 15–30 word Instagram DM for every qualified creator, written by Gemini from that creator's own content.
      Each must pass automatic checks (length, real content reference, no invented numbers, no generic opener) or it's held for human review.</p>
    <div class="filters"><select id="mn" aria-label="Niche"><option value="">All niches</option>${D.campaigns.map((c) => `<option value="${h(c.niche)}">${h(nicheName(c.niche))}</option>`).join("")}</select>
      <select id="ms" aria-label="Status"><option value="">Any status</option><option value="approved">Approved</option><option value="needs_review">Needs review</option></select>
      <select id="me" aria-label="Email"><option value="">Email: any</option><option value="yes">Has email</option></select></div>
    <div class="msgs" id="ml"></div>`;
  const draw = () => {
    const n = $("#mn").value, s = $("#ms").value, e = $("#me").value;
    const rows = D.messages.filter((m) => (!n || m.niche === n) && (!s || m.status === s) && (!e || (m.email && m.email !== "Not Found")));
    $("#ml").innerHTML = rows.map(messageCard).join("") || '<p class="empty">No messages match.</p>';
  };
  ["#mn", "#ms", "#me"].forEach((s) => $(s).addEventListener("input", draw));
  el.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button[data-act]"); if (!btn) return;
    const card = btn.closest(".msg"), m = D.messages.find((x) => x.id === card.dataset.id && x.campaign === card.dataset.c);
    if (btn.dataset.act === "edit") {
      const texts = card.querySelectorAll(".text");
      texts[0].innerHTML = `<input class="field" style="width:100%;margin-bottom:6px" value="${h(m.subject)}" aria-label="Subject"><textarea aria-label="Email body">${h(m.body)}</textarea>`;
      texts[1].innerHTML = `<textarea style="min-height:70px" aria-label="DM">${h(m.dm)}</textarea>`;
      btn.outerHTML = '<button class="btn" data-act="save">Save &amp; approve</button>';
      return;
    }
    const inputs = card.querySelectorAll("input, textarea");
    const body = btn.dataset.act === "save" ? { email_subject: inputs[0].value, email_body: inputs[1].value, instagram_dm: inputs[2].value } : {};
    btn.disabled = true;
    try {
      const out = await api(`/api/campaigns/${encodeURIComponent(m.campaign)}/messages/${encodeURIComponent(m.id)}`, { method: "PATCH", body: JSON.stringify({ ...body, approve: true }) });
      Object.assign(m, { subject: out.email_subject, body: out.email_body, dm: out.instagram_dm, status: out.review_status,
                         issues: out.validation_issues, email_words: out.email_words, dm_words: out.dm_words, edited: true });
      card.outerHTML = messageCard(m);
    } catch (e) { alert(e.message); btn.disabled = false; }
  });
  draw();
}

/* ---------- Brand match ---------- */
function resultsTable(rows, extra) {
  return `<div class="table-wrap"><table><thead><tr><th>Creator</th><th>Niche</th><th class="num">Followers</th><th class="num">ER</th><th>Email</th>${extra ? `<th class="num">${h(extra[0])}</th>` : ""}</tr></thead><tbody>
    ${rows.map((r) => `<tr><td><a href="${h(r.profile_url)}" target="_blank" rel="noopener">${h(r.name)}</a><div class="muted small">${h(r.segment || "")}</div></td>
      <td>${h(nicheName(r.niche))}</td><td class="num">${fmt(r.followers)}</td><td class="num">${pct(r.engagement_rate, 2)}</td>
      <td class="mono">${h(r.email && r.email !== "Not Found" ? r.email : "Not Found")}</td>${extra ? `<td class="num">${h(extra[1](r))}</td>` : ""}</tr>`).join("") || '<tr><td colspan="6" class="empty">No results.</td></tr>'}</tbody></table></div>`;
}

function renderMatch() {
  const ex = D.examples.match || [];
  $("#match").innerHTML = `<h2 style="margin-top:0">Brand-brief engine</h2>
    <p class="lede">Describe any brand in plain English. Its brief is embedded with Gemini and compared with every qualified creator's real content
      (name, description, recent titles) across all eight niches, so one brief can surface creators from niches you didn't think of.</p>
    ${LIVE ? "" : liveOnly("Brand matching")}
    <textarea id="brief" placeholder="e.g. We are a Delhi-based coding bootcamp for school students and want creators whose audience is parents of teenagers…">${h(ex[0]?.brief || "")}</textarea>
    <div class="row" style="margin-top:8px"><button class="btn" id="runmatch" ${LIVE ? "" : "disabled"}>Find creators</button>
      ${ex.length ? `<span class="muted small">Captured examples:</span><div class="chips">${ex.map((e, i) => `<button data-i="${i}">${h(e.brief.slice(0, 70))}…</button>`).join("")}</div>` : ""}</div>
    <div class="answer" id="matchout"></div>`;
  const showRes = (res) => ($("#matchout").innerHTML = resultsTable(res, ["Similarity", (r) => r.similarity.toFixed(3)]));
  $("#match .chips")?.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; $("#brief").value = ex[b.dataset.i].brief; showRes(ex[b.dataset.i].results); });
  $("#runmatch").addEventListener("click", async () => {
    $("#matchout").innerHTML = '<span class="spin"></span> Embedding brief and ranking creators…';
    try { showRes((await api("/api/match", { method: "POST", body: JSON.stringify({ brief: $("#brief").value, top: 15 }) })).results); }
    catch (e) { $("#matchout").innerHTML = `<p class="issues">${h(e.message)}</p>`; }
  });
  if (ex[0]) showRes(ex[0].results);
}

/* ---------- Ask ---------- */
function renderAsk() {
  const ex = D.examples.ask || [];
  $("#ask").innerHTML = `<h2 style="margin-top:0">Ask the data</h2>
    <p class="lede">Ask in plain language. Gemini only translates your question into a typed filter; every row in the answer comes straight
      from the dataset, so the answer can't contain an invented creator or number.</p>
    ${LIVE ? "" : liveOnly("Ask the data")}
    <div class="row"><input class="field" id="q" style="flex:1;min-width:240px" value="${h(ex[0]?.question || "Indian fitness creators with a public email and engagement above 4%")}" aria-label="Question">
      <button class="btn" id="askbtn" ${LIVE ? "" : "disabled"}>Ask</button></div>
    ${ex.length ? `<div class="chips">${ex.map((e, i) => `<button data-i="${i}">${h(e.question)}</button>`).join("")}</div>` : ""}
    <div class="answer" id="askout"></div>`;
  const showAns = (a) => ($("#askout").innerHTML = `<p class="note"><b>Filter applied:</b> ${h(a.filter.explanation)}
      <span class="mono">${h(JSON.stringify(Object.fromEntries(Object.entries(a.filter).filter(([k, v]) => k !== "explanation" && v != null && !(Array.isArray(v) && !v.length)))))}</span>
      · ${a.total_matches} match${a.total_matches === 1 ? "" : "es"}</p>${resultsTable(a.results, ["Auth.", (r) => r.authenticity ?? "—"])}`);
  $("#ask .chips")?.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; $("#q").value = ex[b.dataset.i].question; showAns(ex[b.dataset.i]); });
  $("#askbtn").addEventListener("click", async () => {
    $("#askout").innerHTML = '<span class="spin"></span> Thinking…';
    try { showAns(await api("/api/ask", { method: "POST", body: JSON.stringify({ question: $("#q").value }) })); }
    catch (e) { $("#askout").innerHTML = `<p class="issues">${h(e.message)}</p>`; }
  });
  if (ex[0]) showAns(ex[0]);
}

/* ---------- Classifier ---------- */
function confusion(g) {
  const L = g.labels, max = Math.max(...g.confusion.flat(), 1);
  const cell = (v, diag) => `<div style="background:color-mix(in srgb, ${diag ? "var(--good)" : "var(--bad)"} ${v ? 12 + (v / max) * 70 : 0}%, var(--soft))">${v || ""}</div>`;
  return `<div class="cm" style="grid-template-columns:110px repeat(${L.length},1fr)"><div class="h"></div>${L.map((l) => `<div class="h" title="${h(nicheName(l))}">${h(nicheName(l).split(" ")[0])}</div>`).join("")}
    ${g.confusion.map((row, i) => `<div class="h" style="text-align:right" title="${h(nicheName(L[i]))}">${h(nicheName(L[i]))}</div>${row.map((v, j) => cell(v, i === j)).join("")}`).join("")}</div>
    <p class="muted small">Rows: Gemini's label (independent judge). Columns: the shipped hybrid model's prediction.</p>`;
}

function renderModel() {
  const M = D.model, ex = M?.experiments || {};
  const names = { keyword_rules: "Keyword rules (baseline)", tfidf_logreg: "TF-IDF + logistic regression", hybrid_tfidf_plus_rules: "Hybrid: TF-IDF LR + rules (shipped)", embedding_logreg: "Gemini embeddings + LR" };
  const sample = "Fit With Riya\nDiet plan for weight loss | Indian vegetarian\n20 min home workout no equipment\nMy protein breakfast ideas\nGym transformation 90 days";
  $("#model").innerHTML = `<h2 style="margin-top:0">Niche classifier</h2>
    <p class="lede">A scikit-learn model trained on ${fmt(M?.train_size)} real channels with weak labels from discovery, evaluated on ${fmt(M?.gold_size)} held-out
      channels labelled independently by Gemini. The same model runs right here in your browser: no server, no API key.</p>
    <div class="grid2">
      <div class="card"><h3>Try it</h3><p class="muted small">First line = channel name, other lines = video titles.</p>
        <textarea id="clsin">${h(sample)}</textarea><div id="clsout" style="margin-top:12px"></div></div>
      <div class="card"><h3>Experiments (held-out gold set)</h3>
        <div class="table-wrap" style="box-shadow:none"><table><thead><tr><th>Approach</th><th class="num">Accuracy</th><th class="num">Macro-F1</th><th class="num">CV F1</th></tr></thead>
        <tbody>${Object.entries(ex).map(([k, v]) => `<tr${k === "hybrid_tfidf_plus_rules" ? ' style="font-weight:600"' : ""}><td>${h(names[k] || k)}</td>
          <td class="num">${(v.gold.accuracy * 100).toFixed(1)}%</td><td class="num">${v.gold.report["macro avg"]["f1-score"].toFixed(3)}</td>
          <td class="num">${v.cv_macro_f1 ?? "—"}</td></tr>`).join("")}</tbody></table></div>
        <p class="muted small">CV F1 is 5-fold cross-validation on the weak labels; it's optimistic because those labels partly come from keywords.
          The gold set is the honest number. Full write-up in MODEL_CARD.md.</p></div>
    </div>
    ${ex.hybrid_tfidf_plus_rules ? `<div class="grid2" style="margin-top:16px"><div class="card"><h3>Confusion matrix (shipped model)</h3>${confusion(ex.hybrid_tfidf_plus_rules.gold)}</div>
      <div class="card"><h3>Abstain threshold trade-off</h3><p class="muted small">Accuracy vs coverage (share of channels the model commits to).</p>
      <div class="table-wrap" style="box-shadow:none"><table><thead><tr><th class="num">Threshold</th><th class="num">TF-IDF LR</th><th class="num">Hybrid</th></tr></thead><tbody>
      ${ex.hybrid_tfidf_plus_rules.sweep.map((s, i) => `<tr><td class="num">${s.threshold}</td><td class="num">${pct(ex.tfidf_logreg.sweep[i].accuracy * 100)} / ${pct(ex.tfidf_logreg.sweep[i].coverage * 100, 0)}</td>
        <td class="num">${pct(s.accuracy * 100)} / ${pct(s.coverage * 100, 0)}</td></tr>`).join("")}</tbody></table></div></div></div>` : ""}`;
  const run = () => {
    if (!WEB) { $("#clsout").innerHTML = '<p class="muted">Model file not available.</p>'; return; }
    const p = predict(WEB, $("#clsin").value);
    $("#clsout").innerHTML = `<p><b>${h(nicheName(p.niche))}</b> <span class="muted">${Math.round(p.confidence * 100)}% confidence</span></p>${probBars(p.probs)}
      ${p.matchedTerms.length ? `<p class="muted small">Strongest known terms: ${p.matchedTerms.map(h).join(", ")}</p>` : ""}`;
  };
  $("#clsin").addEventListener("input", run);
  run();
}

/* ---------- Replies ---------- */
function renderReplies() {
  const ex = D.examples.replies || [];
  const withMsg = D.messages.filter((m) => m.status === "approved");
  $("#replies").innerHTML = `<h2 style="margin-top:0">Reply intelligence</h2>
    <p class="lede">When a creator answers, Gemini classifies the intent, pulls out their questions and any rate they quoted, and drafts a reply
      that uses only facts from the brand brief. "Not interested" and "unsubscribe" go straight onto the do-not-contact list, which every send checks.</p>
    ${LIVE ? "" : liveOnly("Reply triage")}
    <div class="row"><select class="field" id="rc" aria-label="Creator">${withMsg.map((m) => `<option value="${h(m.campaign)}|${h(m.id)}">${h(m.influencer)} · ${h(m.brand)}</option>`).join("")}</select></div>
    <textarea id="rt" style="margin-top:8px">${h(ex[0]?.reply || "Hi! Thanks for reaching out. I'd love to know more. What's the budget, and do you need a dedicated video or an integration? I usually charge ₹15,000 for a 60-second integration.")}</textarea>
    <div class="row" style="margin-top:8px"><button class="btn" id="rbtn" ${LIVE ? "" : "disabled"}>Triage reply</button>
      ${ex.length ? `<div class="chips">${ex.map((e, i) => `<button data-i="${i}">${h(e.label)}</button>`).join("")}</div>` : ""}</div>
    <div class="answer" id="rout"></div>`;
  const showR = (o) => ($("#rout").innerHTML = `<div class="card"><p class="row"><span class="pill ${o.suppress ? "bad" : o.intent === "interested" ? "good" : "warn"}">${h(o.intent.replaceAll("_", " "))}</span>
      <span class="pill">${h(o.sentiment)}</span>${o.quoted_rate ? `<span class="pill accent">quoted: ${h(o.quoted_rate)}</span>` : ""}${o.suppress ? '<span class="pill bad">added to do-not-contact</span>' : ""}</p>
      <p>${h(o.summary)}</p>${o.questions_asked?.length ? `<p class="small"><b>Questions:</b> ${o.questions_asked.map(h).join(" · ")}</p>` : ""}
      <p class="small"><b>Next action:</b> ${h(o.next_action)}</p>${o.suggested_reply ? `<div class="label">Suggested reply</div><div class="text" style="white-space:pre-wrap;background:var(--soft);padding:10px;border-radius:8px">${h(o.suggested_reply)}</div>` : ""}</div>`);
  $("#replies .chips")?.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; $("#rt").value = ex[b.dataset.i].reply; showR(ex[b.dataset.i].result); });
  $("#rbtn").addEventListener("click", async () => {
    const [campaign_id, channel_id] = $("#rc").value.split("|");
    $("#rout").innerHTML = '<span class="spin"></span> Reading the reply…';
    try { showR(await api("/api/replies", { method: "POST", body: JSON.stringify({ campaign_id, channel_id, reply: $("#rt").value }) })); }
    catch (e) { $("#rout").innerHTML = `<p class="issues">${h(e.message)}</p>`; }
  });
  if (ex[0]) showR(ex[0].result);
}

/* ---------- Tracker ---------- */
function renderTracker() {
  const T = D.tracker;
  const counts = T.reduce((a, t) => ((a[t.status] = (a[t.status] || 0) + 1), a), {});
  $("#tracker").innerHTML = `<h2 style="margin-top:0">Outreach tracker</h2>
    <p class="lede">Every send attempt is logged before it happens (write-ahead), so a crash can never cause a duplicate email.
      Instagram DMs are queued for manual sending; Meta's API doesn't permit automated cold DMs, and this system doesn't bypass that.</p>
    <div class="kpis">${Object.entries(counts).map(([k, v]) => `<div class="kpi"><b>${fmt(v)}</b><span>${h(k.replaceAll("_", " "))}</span></div>`).join("")}</div>
    ${LIVE ? `<div class="card" style="margin:12px 0"><h3>Send (dry-run or test)</h3><div class="row">
      <select class="field" id="sc">${D.campaigns.map((c) => `<option value="${h(c.id)}">${h(nicheName(c.niche))} · ${h(c.brand.name)}</option>`).join("")}</select>
      <select class="field" id="sm"><option value="dry-run">dry-run (simulate)</option><option value="test">test (redirect to my inbox via n8n)</option></select>
      <button class="btn" id="sbtn">Run</button><span id="sout" class="small"></span></div></div>` : ""}
    <div class="filters"><select id="tk" aria-label="Kind"><option value="">All channels</option><option value="email">Email</option><option value="email_followup">Follow-up</option><option value="instagram_dm">Instagram DM</option></select></div>
    <div class="table-wrap"><table><thead><tr><th>Influencer</th><th>Campaign</th><th>Channel</th><th>Mode</th><th>Status</th><th>Delivered to</th><th>Date (UTC)</th></tr></thead><tbody id="tt"></tbody></table></div>`;
  const draw = () => {
    const k = $("#tk").value;
    $("#tt").innerHTML = T.filter((t) => !k || t.kind === k).slice().reverse().map((t) => `<tr><td>${h(t.influencer)}</td><td class="small">${h(t.campaign_id)}</td><td>${h(t.kind.replace("_", " "))}</td>
      <td>${h(t.mode)}</td><td><span class="pill ${["test_sent", "sent", "dm_sent_manual"].includes(t.status) ? "good" : t.status === "failed" ? "bad" : ""}">${h(t.status.replaceAll("_", " "))}</span>${t.error ? `<div class="issues">${h(t.error)}</div>` : ""}</td>
      <td class="small">${h(t.delivered_to)}</td><td class="small mono">${h(t.created_at.replace("+00:00", ""))}</td></tr>`).join("") || '<tr><td colspan="7" class="empty">Nothing sent yet.</td></tr>';
  };
  $("#tk").addEventListener("input", draw);
  $("#sbtn")?.addEventListener("click", async () => {
    $("#sout").innerHTML = '<span class="spin"></span>';
    try { const s = await api(`/api/campaigns/${encodeURIComponent($("#sc").value)}/send`, { method: "POST", body: JSON.stringify({ mode: $("#sm").value, via: "n8n" }) });
      $("#sout").textContent = JSON.stringify(s); D = await api("/api/data"); renderTracker(); }
    catch (e) { $("#sout").textContent = e.message; }
  });
  draw();
}

boot();
