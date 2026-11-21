// GTA Stream Clipper : l'interface (sans bibliothèque externe)
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n || 0).toLocaleString("fr-FR");
const LANG_NAMES = { "": "toutes", fr: "français", en: "anglais", es: "espagnol", de: "allemand", it: "italien", pt: "portugais" };
const STYLE_NAMES = { "jaune": "Jaune", "tout-jaune": "Tout jaune", "blanc": "Blanc", "boite-jaune": "Boîte jaune",
  "boite-violette": "Boîte violette", "boite-rouge": "Boîte rouge", "boite-verte": "Boîte verte" };
let CONFIG = { styles: {} };
let currentStyle = localStorage.getItem("style") || "jaune";
const watched = {}; // travaux lancés depuis cette page : id → callback de fin

async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.erreur || r.statusText);
  return j;
}

// ---------- onglets
$$("nav button").forEach((b) => b.onclick = () => showTab(b.dataset.tab));
function showTab(t) {
  $$("nav button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  $$(".tab").forEach((s) => s.classList.toggle("on", s.id === "tab-" + t));
  if (t === "biblio") loadLibrary();
}

// ---------- fenêtre
function openModal(html) { $("#modalBox").innerHTML = `<button class="close" onclick="closeModal()">✕</button>` + html; $("#modal").classList.remove("hidden"); }
function closeModal() { $("#modal").classList.add("hidden"); $("#modalBox").innerHTML = ""; }
$("#modal").onclick = (e) => { if (e.target.id === "modal") closeModal(); };

// ---------- styles de sous-titres (aperçu en CSS)
function chip(name, spec, on) {
  const box = spec.boite ? `background:#${spec.boite};` : "";
  const word = `color:#${spec.mot};${box}${spec.mot === "111111" ? "-webkit-text-stroke:0;" : ""}`;
  return `<div class="chip ${on ? "on" : ""}" data-style="${name}"><span class="w" style="color:#${spec.texte}">OH </span><span class="w" style="${word}">MY</span><span class="nm">${STYLE_NAMES[name] || name}</span></div>`;
}
function stylePicker(sel) {
  return `<div class="styles">${Object.entries(CONFIG.styles).map(([k, v]) => chip(k, v, k === sel)).join("")}</div>`;
}
function bindPicker(root, onPick) {
  $$(".chip", root).forEach((c) => c.onclick = () => { $$(".chip", root).forEach((x) => x.classList.remove("on")); c.classList.add("on"); onPick(c.dataset.style); });
}

// ---------- travaux
function track(job, onDone) { watched[job.id] = onDone; pollJobs(); }
async function pollJobs() {
  let jobs = [];
  try { jobs = await api("/api/jobs"); } catch { return; }
  const now = Date.now() / 1000;
  const shown = jobs.filter((j) => j.status === "en cours" || j.status === "en attente" || now - j.created < 600).slice(0, 5);
  $("#jobs").innerHTML = shown.map((j) => `<div class="job ${j.status}"><div class="h"><span>${j.status === "en cours" ? '<span class="spin"></span> ' : ""}${esc(j.label)}</span>
    ${j.kind === "live" && j.status === "en cours" ? `<button class="x" title="Arrêter" onclick="stopJob('${j.id}')">■</button>` : ""}</div>
    <div class="l">${esc(j.status === "erreur" ? "Erreur : " + j.error : (j.lines.slice(-1)[0] || j.status))}</div></div>`).join("");
  for (const j of jobs) {
    if (watched[j.id] && (j.status === "fini" || j.status === "erreur")) { const cb = watched[j.id]; delete watched[j.id]; cb(j); }
  }
  if (jobs.some((j) => j.kind === "live" && j.status === "en cours")) loadLibraryCount();
}
async function stopJob(id) { await api(`/api/jobs/${id}/stop`, {}); pollJobs(); }
setInterval(pollJobs, 2000);

// ---------- clips viraux
$("#vGo").onclick = searchViral;
async function searchViral() {
  const q = new URLSearchParams({ periode: $("#vPeriode").value, langue: $("#vLangue").value, chaine: $("#vChaine").value.trim(), jeu: $("#vJeu").value.trim() });
  $("#vRes").innerHTML = `<div class="empty"><span class="spin"></span> Recherche des clips…</div>`;
  try {
    const clips = await api("/api/viral?" + q);
    if (!clips.length) { $("#vRes").innerHTML = `<div class="empty">Aucun clip pour ces filtres.</div>`; return; }
    $("#vRes").innerHTML = clips.map((c, i) => `<div class="card" data-i="${i}"><div class="th" style="background-image:url('${esc(c.vignette)}')">
      <span class="tag">👁 ${fmt(c.vues)}</span><span class="dur">${Math.round(c.duree)} s</span></div>
      <div class="meta"><div class="t">${esc(c.titre || "(sans titre)")}</div><div class="s">${esc(c.streamer)} · ${LANG_NAMES[c.langue] || c.langue || ""}</div></div></div>`).join("");
    $$("#vRes .card").forEach((el) => el.onclick = () => viralModal(clips[+el.dataset.i]));
  } catch (e) { $("#vRes").innerHTML = `<div class="empty">Erreur : ${esc(e.message)}</div>`; }
}
function viralModal(c) {
  const slug = (c.url || "").split("/clip/")[1] || "";
  const embed = slug ? `<iframe class="embed" allowfullscreen src="https://clips.twitch.tv/embed?clip=${encodeURIComponent(slug)}&parent=${location.hostname}&autoplay=true"></iframe>` : "";
  let style = currentStyle;
  openModal(`<h2>${esc(c.titre || "Clip")}</h2><p class="lead">${esc(c.streamer)} · ${fmt(c.vues)} vues · ${Math.round(c.duree)} s ·
    <a href="${esc(c.url)}" target="_blank" style="color:var(--accent)">ouvrir sur Twitch</a></p>${embed}
    <div class="field" style="margin-top:14px"><span class="l">Titre du clip vertical (vide = un titre automatique ; emojis acceptés)</span><input type="text" id="mTitre" placeholder="${esc(c.streamer)} se foire sur GTA 6 💀"></div>
    <div class="field"><span class="l">Style des sous-titres</span>${stylePicker(style)}</div>
    <div class="row"><button class="primary" id="mGo">Créer le clip vertical</button><span class="muted">Il remonte le moment depuis la rediffusion (quelques secondes avant et après), environ 1 minute.</span></div>`);
  bindPicker($("#modalBox"), (s) => { style = s; currentStyle = s; localStorage.setItem("style", s); });
  $("#mGo").onclick = async () => {
    const job = await api("/api/jobs", { type: "viral", clip: c, style, titre: $("#mTitre").value.trim() });
    closeModal();
    track(job, (j) => j.status === "fini" && j.result?.clip ? (loadLibraryCount(), editClip(j.result.clip)) : null);
  };
}

// ---------- lien
$("#lGo").onclick = async () => {
  const url = $("#lUrl").value.trim();
  if (!url) return;
  $("#lRes").innerHTML = `<div class="empty"><span class="spin"></span> Analyse du stream (son, paroles, scènes du jeu)… compte 1 à 3 minutes pour une heure de stream.</div>`;
  const job = await api("/api/jobs", { type: "analyse", url, de: $("#lDe").value.trim(), a: $("#lA").value.trim(), langue: $("#lLangue").value });
  track(job, (j) => j.status === "fini" ? showMoments(j.result) : ($("#lRes").innerHTML = `<div class="empty">Erreur : ${esc(j.error)}</div>`));
};
function showMoments(r) {
  const info = r.info || {};
  $("#lRes").innerHTML = `<h2>${esc(info.streamer || "")} · ${esc(info.titre || "")}</h2>
    <p class="hint">Du plus fort au plus faible. Garde ceux où le streameur réagit lui-même (pas les dialogues du jeu).</p>` +
    r.moments.map((m) => `<div class="moment"><div class="n">${m.n}</div><div class="txt"><div>« ${esc(m.texte || "…")} »</div>
      <div class="s">${m.debut} → ${m.fin} · score ${m.score}${m.cinematique ? '<span class="pill warn">cinématique</span>' : ""}</div></div>
      <div class="act"><input type="text" placeholder="Titre (vide = automatique)" data-t="${m.n}"><button class="primary" data-n="${m.n}">Monter ce moment</button></div></div>`).join("");
  $$("#lRes button[data-n]").forEach((b) => b.onclick = async () => {
    const n = +b.dataset.n;
    b.disabled = true; b.textContent = "En cours…";
    const job = await api("/api/jobs", { type: "moment", url: r.url, de: r.de, a: r.a, langue: r.langue, n, style: currentStyle, titre: $(`#lRes input[data-t="${n}"]`).value.trim() });
    track(job, (j) => { b.disabled = false; b.textContent = j.status === "fini" ? "Refaire" : "Erreur"; if (j.result?.clip) { loadLibraryCount(); editClip(j.result.clip); } });
  });
}

// ---------- en direct
$("#dGo").onclick = async () => {
  $("#dRes").innerHTML = `<div class="empty"><span class="spin"></span> Recherche des lives…</div>`;
  try {
    const lives = await api("/api/lives?" + new URLSearchParams({ langue: $("#dLangue").value, jeu: $("#dJeu").value.trim() }));
    if (!lives.length) { $("#dRes").innerHTML = `<div class="empty">Aucun live pour ces filtres.</div>`; return; }
    $("#dRes").innerHTML = lives.map((s, i) => `<div class="card" data-i="${i}"><div class="th" style="background-image:url('${esc(s.vignette)}')">
      <span class="tag live">● ${fmt(s.spectateurs)}</span></div><div class="meta"><div class="t">${esc(s.titre)}</div>
      <div class="s">${esc(s.streamer)} · ${LANG_NAMES[s.langue] || s.langue}</div></div></div>`).join("");
    $$("#dRes .card").forEach((el) => el.onclick = () => watchLive(lives[+el.dataset.i].url, lives[+el.dataset.i].streamer));
  } catch (e) { $("#dRes").innerHTML = `<div class="empty">Erreur : ${esc(e.message)}</div>`; }
};
$("#dWatch").onclick = () => { const u = $("#dUrl").value.trim(); if (u) watchLive(u, u); };
async function watchLive(url, who) {
  if (!confirm(`Surveiller le live de ${who} pendant ${$("#dMin").value} minutes ? Les clips arriveront dans la bibliothèque.`)) return;
  const job = await api("/api/jobs", { type: "live", url, minutes: $("#dMin").value, style: currentStyle });
  track(job, () => loadLibraryCount());
}

// ---------- bibliothèque
async function loadLibraryCount() { try { const l = await api("/api/library"); $("#nbClips").textContent = l.length || ""; if ($("#tab-biblio").classList.contains("on")) renderLibrary(l); } catch {} }
async function loadLibrary() { renderLibrary(await api("/api/library")); }
function renderLibrary(items) {
  $("#nbClips").textContent = items.length || "";
  if (!items.length) { $("#bRes").innerHTML = `<div class="empty">Pas encore de clip. Commence par les clips viraux ou un lien.</div>`; return; }
  $("#bRes").innerHTML = items.map((c) => `<div class="card" data-id="${esc(c.id)}"><div class="th" style="background-image:url('${c.poster}')">
    ${c.viral ? '<span class="tag">🔥 viral</span>' : ""}<span class="dur">${Math.round(c.duree)} s</span></div>
    <div class="meta"><div class="t">${esc(c.titre)}</div><div class="s">${esc(c.streamer)}</div></div></div>`).join("");
  $$("#bRes .card").forEach((el) => el.onclick = () => editClip(el.dataset.id));
}
async function editClip(id) {
  const c = await api("/api/clip/" + encodeURIComponent(id));
  let style = c.style, mots = c.mots;
  openModal(`<div class="edit"><div><video id="eVid" src="${c.mp4}" controls autoplay playsinline></video></div><div>
    <h2>Modifier le clip</h2>
    <div class="field"><span class="l">Titre (emojis acceptés)</span><input type="text" id="eTitre" value="${esc(c.titre)}"></div>
    <div class="field"><span class="l">Style des sous-titres</span>${stylePicker(style)}</div>
    <div class="field"><span class="l">Mots affichés à la fois</span><select id="eMots"><option value="1">1 (mot par mot)</option><option value="2">2</option><option value="3">3</option></select></div>
    <div class="field"><span class="l">Sous-titres (corrige un mot, vide-le pour l'enlever ; les temps restent les mêmes)</span>
      <div class="words">${c.words.map((w, i) => `<input data-i="${i}" value="${esc(w.text)}" size="${Math.max(3, w.text.length)}" title="${w.start.toFixed(1)} s">`).join("")}</div></div>
    <div class="row"><button class="primary" id="eSave"${c.section_ok ? "" : " disabled title=\"l'extrait source a été supprimé\""}>Mettre à jour l'aperçu</button>
      <a href="/download/${encodeURIComponent(id)}"><button class="yellow">⬇ Télécharger le MP4</button></a>
      <button id="eDel">Supprimer</button>${c.lien ? `<a href="${esc(c.lien)}" target="_blank" style="color:var(--muted);font-size:13px">voir dans le stream</a>` : ""}</div>
    <p class="hint" id="eMsg" style="margin-top:10px"></p></div></div>`);
  $("#eMots").value = String(mots || 2);
  bindPicker($("#modalBox"), (s) => { style = s; });
  $("#eSave").onclick = async () => {
    const words = c.words.map((w, i) => ({ ...w, text: $(`.words input[data-i="${i}"]`).value }));
    $("#eSave").disabled = true; $("#eMsg").innerHTML = '<span class="spin"></span> Nouveau rendu…';
    const job = await api("/api/jobs", { type: "rerender", id, titre: $("#eTitre").value, words, style, mots: +$("#eMots").value });
    track(job, (j) => { if (j.status === "fini") editClip(id); else { $("#eMsg").textContent = "Erreur : " + j.error; $("#eSave").disabled = false; } });
  };
  $("#eDel").onclick = async () => { if (!confirm("Supprimer ce clip ?")) return; await api(`/api/clip/${encodeURIComponent(id)}/supprimer`, {}); closeModal(); loadLibrary(); };
}

// ---------- démarrage
(async () => {
  CONFIG = await api("/api/config");
  $("#version").textContent = "v" + CONFIG.version;
  $$("select.langs").forEach((s) => s.innerHTML = ["", ...CONFIG.langues].map((l) => `<option value="${l}">${LANG_NAMES[l] || l}</option>`).join(""));
  $("#vLangue").value = "fr"; $("#dLangue").value = "fr";
  loadLibraryCount();
  pollJobs();
  searchViral();
})();
