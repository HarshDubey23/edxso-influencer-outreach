const h = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (s) => document.querySelector(s);
const OK = '<svg viewBox="0 0 16 16" aria-label="ready"><path d="M3 8.5 6.5 12 13 4.5" fill="none" stroke="currentColor" stroke-width="2.2"/></svg>';
const NO = '<svg viewBox="0 0 16 16" aria-label="missing"><path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="2.2"/></svg>';
let W, plan;

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (r.status === 401) { location.href = "/login"; throw new Error("login required"); }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || r.statusText);
  return body;
}

function renderStatus() {
  const s = W.status, st = W.settings;
  const row = (ok, label, text) => `<div class="check-row ${ok ? "ok" : "no"}">${ok ? OK : NO}<b>${h(label)}</b><span>${text}</span></div>`;
  $("#checks").innerHTML = [
    row(s.gmail_connected, "Gmail", s.gmail_connected ? `sending as <b>${h(s.gmail_email)}</b>` : s.gmail_configured ? "not connected yet" : "Google OAuth client not set on this install"),
    row(s.youtube_key, "YouTube Data API", s.youtube_key ? "key present" : "set YOUTUBE_API_KEY on the server"),
    row(s.gemini_key, "Gemini", s.gemini_key ? "key present" : "set GEMINI_API_KEY on the server"),
    row(s.has_campaign, "Campaign", s.has_campaign ? h(W.campaign.name) : "write your brand brief below"),
  ].join("");
  $("#gmail-actions").innerHTML = s.gmail_connected
    ? `<button class="btn ghost" id="gm-off">Disconnect Gmail</button>`
    : s.gmail_configured ? `<a class="btn" href="/auth/google/start">Connect Gmail</a>` : "";
  $("#gmail-help").innerHTML = s.gmail_configured ? "" :
    `In Google Cloud Console create an OAuth client (Web application) with redirect URI <code>${h(s.redirect_uri)}</code>, then set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET. Steps are in the README.`;
  $("#gm-off")?.addEventListener("click", async () => { if (confirm("Disconnect Gmail? Autopilot will stop sending.")) { await api("/api/gmail/disconnect", { method: "POST" }); load(); } });
  const badge = $("#ap-badge");
  badge.textContent = st.autopilot ? (st.send_live ? "autopilot · LIVE" : "autopilot · test mode") : "autopilot off";
  badge.className = `mode ${st.autopilot ? (st.send_live ? "live-on" : "on") : ""}`;
}

function fillSettings() {
  const f = $("#settings"), st = W.settings;
  for (const el of f.elements) {
    if (!el.name || !(el.name in st)) continue;
    if (el.type === "checkbox") el.checked = !!st[el.name]; else el.value = st[el.name] ?? "";
  }
  if (W.campaign) {
    const b = W.campaign.brand, bf = $("#brand-form");
    bf.name.value = b.name || ""; bf.about.value = b.about || ""; bf.website.value = b.website || "";
    bf.creator_value.value = (b.creator_value || []).join("\n");
    showPlan(W.campaign);
  }
}

function showPlan(c) {
  plan = structuredClone(c);
  $("#plan").hidden = false;
  $("#queries").value = (c.discovery.queries || []).join("\n");
  $("#segments").innerHTML = Object.entries(c.segments).map(([k, s]) => `<div class="seg" data-k="${h(k)}">
    <label class="block">Segment<input data-f="label" value="${h(s.label)}"></label>
    <label class="block">Weight (0.3–1)<input data-f="fit_weight" type="number" step="0.1" min="0.3" max="1" value="${h(s.fit_weight)}"></label>
    <label class="block wide">Keywords, comma separated<textarea data-f="keywords" rows="2">${h((s.keywords || []).join(", "))}</textarea></label>
    <label class="block wide">Collaboration idea<input data-f="angle_hint" value="${h(s.angle_hint)}"></label></div>`).join("");
}

function brandFields() {
  const f = $("#brand-form");
  return { name: f.name.value.trim(), about: f.about.value.trim(), website: f.website.value.trim(), audience: f.audience.value.trim(),
           creator_value: f.creator_value.value.split("\n").map((s) => s.trim()).filter(Boolean), region: f.region.value, language: f.language.value };
}

$("#brand-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("#draft-btn"); btn.disabled = true; $("#draft-msg").textContent = "Drafting queries and segments…";
  try { showPlan(await api("/api/workspace/plan", { method: "POST", body: JSON.stringify(brandFields()) })); $("#draft-msg").textContent = "Draft ready. Review it below."; }
  catch (err) { $("#draft-msg").textContent = err.message; }
  btn.disabled = false;
});

$("#save-plan").addEventListener("click", async () => {
  const b = brandFields();
  plan.brand = { ...plan.brand, name: b.name, about: b.about, website: b.website, creator_value: b.creator_value };
  plan.discovery.queries = $("#queries").value.split("\n").map((q) => q.trim()).filter(Boolean);
  document.querySelectorAll(".seg").forEach((el) => {
    const s = plan.segments[el.dataset.k];
    el.querySelectorAll("[data-f]").forEach((i) => {
      s[i.dataset.f] = i.dataset.f === "keywords" ? i.value.split(",").map((k) => k.trim().toLowerCase()).filter(Boolean)
        : i.dataset.f === "fit_weight" ? Number(i.value) : i.value.trim();
    });
  });
  try { await api("/api/workspace/campaign", { method: "PUT", body: JSON.stringify(plan) }); $("#save-msg").textContent = "Saved."; load(); }
  catch (err) { $("#save-msg").textContent = err.message; }
});

async function saveSettings(values) {
  try { W.settings = await api("/api/workspace", { method: "PUT", body: JSON.stringify({ values }) }); $("#set-msg").textContent = "Saved."; renderStatus(); fillSettings(); }
  catch (err) { $("#set-msg").textContent = err.message; fillSettings(); }
}

$("#settings").addEventListener("submit", (e) => {
  e.preventDefault();
  const values = {};
  for (const el of e.target.elements) {
    if (!el.name || el.name === "send_live") continue;  // live sending has its own confirmation
    values[el.name] = el.type === "checkbox" ? el.checked : el.type === "number" || el.name === "utc_offset_min" ? Number(el.value) : el.value;
  }
  saveSettings(values);
});

$("#settings").send_live.addEventListener("change", (e) => {
  if (!e.target.checked) return saveSettings({ send_live: false });
  e.target.checked = false;
  $("#cl-email").textContent = W.status.gmail_email || "your Gmail"; $("#cl-cap").textContent = W.settings.daily_cap;
  $("#cl-word").value = ""; $("#confirm-live").showModal();
});
$("#cl-no").addEventListener("click", () => $("#confirm-live").close());
$("#cl-yes").addEventListener("click", () => {
  if ($("#cl-word").value.trim() !== "SEND") return $("#cl-word").focus();
  $("#confirm-live").close(); saveSettings({ send_live: true });
});

$("#run-now").addEventListener("click", async () => {
  $("#set-msg").textContent = "Run started; watch the live activity.";
  await api("/api/autopilot/run", { method: "POST" }).catch((e) => ($("#set-msg").textContent = e.message));
});

function addEvent(e) {
  const log = $("#log");
  log.querySelector(".empty")?.remove();
  const li = document.createElement("li");
  li.innerHTML = `<time>${h(new Date(e.at).toLocaleString())}</time><span class="${h(e.level)}">${h(e.message)}</span>`;
  log.prepend(li);
  while (log.children.length > 300) log.lastChild.remove();
}

async function listen() {
  const past = await api("/api/events?after=0").catch(() => []);
  const recent = past.slice(-100);
  if (!recent.length) $("#log").innerHTML = '<li class="empty">Nothing yet. Save a campaign and press Run now.</li>';
  recent.forEach(addEvent);
  const es = new EventSource(`/api/events/stream?after=${recent.at(-1)?.id || 0}`);
  es.onmessage = (m) => { const e = JSON.parse(m.data); addEvent(e); if (/connected|Settings changed|Campaign saved/.test(e.message)) load(); };
}

async function load() { W = await api("/api/workspace"); renderStatus(); fillSettings(); }
load().then(listen);
