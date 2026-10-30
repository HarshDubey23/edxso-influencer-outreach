const h = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (s) => document.querySelector(s);
const ORDER = ["planning", "discovering", "filtering", "enriching", "writing", "sending", "done"];
const fmt = (n) => (n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : String(n));
let view = "qualified", data = null, refreshing = null;

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (r.status === 401) { location.href = "/login"; throw new Error("login required"); }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : r.statusText);
  return body;
}

function renderStages(st) {
  const at = ORDER.indexOf(st.stage);
  document.querySelectorAll("#stages li").forEach((li) => {
    const i = ORDER.indexOf(li.dataset.s);
    li.className = st.status === "running" && i === at ? "now" : at > i || st.status === "done" ? "done" : "";
  });
  const set = (id, v) => ($(id).textContent = v ?? "–");
  set("#k-queries", st.queries); set("#k-discovered", st.discovered); set("#k-qualified", st.qualified);
  set("#k-emails", st.emails); set("#k-messages", st.messages); set("#k-sent", st.sent);
  const running = st.status === "running";
  $("#go-btn").disabled = running;
  $("#go-btn").textContent = running ? "Running…" : "Search and run";
  if (st.status === "error") $("#go-msg").textContent = `Stopped: ${st.error}`;
}

function creator(r) {
  const m = r.message, s = r.sent;
  const status = r.status === "qualified"
    ? (s ? `<span class="pill good">${h(s.status.replace("_", " "))} → ${h(s.delivered_to)}</span>` : m ? `<span class="pill ${m.review === "approved" ? "accent" : "warn"}">${m.review === "approved" ? "message ready" : "needs review"}</span>` : "")
    : `<span class="pill bad">rejected</span>`;
  const email = r.status !== "qualified" ? "" : r.email && r.email !== "Not Found"
    ? `<div class="small">✉ <b>${h(r.email)}</b> <span class="muted">from ${h(r.email_source)}</span></div>`
    : r.email ? `<div class="small muted">No published email; the DM is the way in.</div>` : "";
  const msg = m ? `<details><summary>Email and DM</summary><div class="text"><b>${h(m.subject)}</b>\n\n${h(m.body)}</div><div class="text">${h(m.dm)}</div>${m.issues?.length ? `<p class="issues">${m.issues.map(h).join("; ")}</p>` : ""}</details>` : "";
  return `<article class="creator"><header><a href="${h(r.url)}" target="_blank" rel="noopener">${h(r.name)}</a>${status}</header>
    <div class="meta">${fmt(r.followers)} subscribers · ${Number(r.engagement_rate).toFixed(1)}% engagement${r.segment ? " · " + h(r.segment) : ""}</div>
    ${r.status === "qualified" ? email + msg : `<ul>${r.reasons.map((x) => `<li>${h(x)}</li>`).join("")}</ul>`}</article>`;
}

function renderRows() {
  if (!data?.campaign) return;
  $("#camp").textContent = `· ${data.campaign.name}`;
  const rows = (data.rows || []).filter((r) => (view === "qualified" ? r.status === "qualified" : r.status !== "qualified"));
  $("#rows").innerHTML = rows.length ? rows.slice(0, 150).map(creator).join("")
    : `<p class="empty">${data.state.status === "running" ? '<span class="spin"></span> Working on it…' : "Nothing here for this search."}</p>`;
}

async function refresh() {
  data = await api("/api/live/results").catch(() => data);
  if (data) { renderStages(data.state); renderRows(); }
}
const soon = () => { clearTimeout(refreshing); refreshing = setTimeout(refresh, 600); };

document.querySelectorAll(".filters .pill").forEach((b) => b.addEventListener("click", () => {
  view = b.dataset.f;
  document.querySelectorAll(".filters .pill").forEach((x) => { x.setAttribute("aria-pressed", x === b); x.classList.toggle("accent", x === b); });
  renderRows();
}));

$("#go").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = { name: f.name.value.trim(), brief: f.brief.value.trim(), region: f.region.value, language: f.language.value, send: Number(f.send.value) };
  $("#go-msg").textContent = "Starting…";
  try { renderStages(await api("/api/live/run", { method: "POST", body: JSON.stringify(body) })); $("#go-msg").textContent = "Running. Discovery takes a minute or two; watch the feed."; $("#log").innerHTML = ""; }
  catch (err) { $("#go-msg").textContent = err.message; }
});

function addEvent(e) {
  const log = $("#log");
  log.querySelector(".empty")?.remove();
  const li = document.createElement("li");
  li.innerHTML = `<time>${h(new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }))}</time><span class="${h(e.level)}">${h(e.message)}</span>`;
  log.prepend(li);
  while (log.children.length > 400) log.lastChild.remove();
}

async function start() {
  const ws = await api("/api/workspace");
  const s = ws.status;
  $("#gm-badge").textContent = s.gmail_connected ? `Gmail: ${s.gmail_email}` : "Gmail not connected";
  $("#gm-badge").className = `mode ${s.gmail_connected ? "on" : ""}`;
  if (!s.gmail_connected) $("#go-msg").innerHTML = 'Gmail is not connected, so nothing can be sent. <a href="control.html">Connect it in the Control room</a>; finding and writing still work.';
  await refresh();
  const past = (await api("/api/events?after=0").catch(() => [])).slice(-60);
  if (!past.length) $("#log").innerHTML = '<li class="empty">Nothing yet.</li>';
  past.forEach(addEvent);
  const es = new EventSource(`/api/events/stream?after=${past.at(-1)?.id || 0}`);
  es.onmessage = (m) => { addEvent(JSON.parse(m.data)); soon(); };
}
start();
