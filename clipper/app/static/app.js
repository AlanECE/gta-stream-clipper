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
    <div class="row"><button class="primary" id="mGo">Créer le clip vertical</button><span class="muted">Le clip est repris tel quel (le moment exact, avec son vrai son) et remis en vertical : 20 à 40 secondes.</span></div>`);
  bindPicker($(".styles", $("#modalBox")), (s) => { style = s; currentStyle = s; localStorage.setItem("style", s); });
  $("#mGo").onclick = async () => {
    $("#mGo").disabled = true;
    try {
      const job = await api("/api/jobs", { type: "viral", clip: c, style, titre: $("#mTitre").value.trim() });
      closeModal();
      track(job, (j) => j.status === "fini" && j.result?.clip ? (loadLibraryCount(), editClip(j.result.clip)) : null);
    } catch (e) { $("#mGo").disabled = false; alert("Erreur : " + e.message); }
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
      <div class="s">${m.debut} → ${m.fin} · score ${m.score}${m.cinematique ? '<span class="pill warn">cinématique</span>' : ""}${m.chat ? `<span class="pill chat">💬 ${esc(m.chat)}</span>` : ""}</div></div>
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
  const min = Math.max(0, parseFloat($("#dMin").value) || 0), veille = $("#dVeille").checked;
  const combien = min ? `pendant ${min} minutes` : (veille ? "sans limite de durée" : "jusqu'à la fin du live");
  const quoi = veille ? `Mettre ${who} en veille ${combien} ? L'outil attend qu'il passe en direct, clippe, puis attend son live suivant.`
    : `Surveiller le live de ${who} ${combien} ?`;
  if (!confirm(quoi + " Les clips arriveront dans la bibliothèque.")) return;
  try {
    const job = await api("/api/jobs", { type: "live", url, minutes: min, veille, style: currentStyle });
    track(job, () => loadLibraryCount());
  } catch (e) { alert("Erreur : " + e.message); }
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
// ---------- timeline : début et fin du clip dans le stream d'origine (comme l'éditeur vidéo de l'iPhone)
const pad2 = (n) => String(n).padStart(2, "0");
function fmtCut(sec, info, coarse) {
  // l'heure du live (13:42:05,3), sinon le temps du stream (1:02:03,4), sinon le temps de l'extrait
  if (info.heure) {
    const d = new Date(new Date(info.heure).getTime() + sec * 1000);
    const hms = `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
    return coarse ? hms : `${hms},${Math.floor(d.getMilliseconds() / 100)}`;
  }
  const t = Math.max(0, (info.origine ?? 0) + sec);
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  const ss = coarse ? pad2(Math.floor(s)) : s.toFixed(1).padStart(4, "0").replace(".", ",");
  return h ? `${h}:${pad2(m)}:${ss}` : `${m}:${ss}`;
}
const fmtDelta = (d) => Math.abs(d) < 0.05 ? "" : ` <em>${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(1).replace(".", ",")} s</em>`;

async function mountTrim(id, c, state) {
  const info = c.coupe;
  const wrap = $("#tWrap"), strip = $("#tStrip"), vid = $("#tVid"), sel = $("#tSel");
  const dimL = $("#tDimL"), dimR = $("#tDimR"), ph = $("#tPh"), msg = $("#tMsg");
  const MIN = 2, MAX = 180;
  let total = info.total, inT = info.t_in, outT = info.t_in + info.dur, z = 1, playing = false, pending = null;
  let active = "in", stripN = 0, stripTimer = null;
  const orig = [inT, outT];
  const changed = () => Math.abs(inT - orig[0]) > 0.04 || Math.abs(outT - orig[1]) > 0.04;
  state.get = () => ({ t_in: Math.round(inT * 1000) / 1000, dur: Math.round((outT - inT) * 1000) / 1000, changed: changed() });

  if (info.elargir) {
    const b = $("#tWiden");
    b.textContent = info.elargir === "viral" ? "⟷ Chercher 2 min avant et après dans la rediffusion" : "⟷ Charger 2 min avant et après";
    b.classList.remove("hidden");
    b.onclick = async () => {
      b.disabled = true; msg.innerHTML = '<span class="spin"></span> On va chercher le stream autour du clip (une à deux minutes)…';
      try {
        const job = await api("/api/jobs", { type: "elargir", id });
        track(job, (j) => { if (j.status === "fini") editClip(id); else { msg.textContent = "Impossible : " + j.error; b.disabled = false; } });
      } catch (e) { msg.textContent = "Erreur : " + e.message; b.disabled = false; }
    };
  }
  if (info.live && !info.complet) msg.textContent = "Le live est encore enregistré autour de ce clip : les 2 minutes d'après arrivent dès qu'elles sont passées (rouvre le clip dans un moment).";

  let r;
  try { r = await api(`/api/clip/${encodeURIComponent(id)}/timeline`, {}); }
  catch (e) { $("#tLoad").textContent = "Timeline indisponible : " + e.message; return; }
  if (!document.body.contains(strip)) return; // fenêtre fermée pendant la préparation
  total = r.total || total;
  outT = Math.min(outT, total);
  vid.src = r.proxy;
  vid.addEventListener("loadeddata", () => { $("#tLoad").classList.add("hidden"); vid.currentTime = inT; }, { once: true });
  vid.addEventListener("seeked", () => { if (pending !== null) { const p = pending; pending = null; vid.currentTime = p; } });
  const seek = (t) => { if (vid.seeking) pending = t; else vid.currentTime = t; };
  const zmax = Math.max(1, total / 12); // au plus zoomé : 12 secondes dans la largeur
  const pps = () => strip.clientWidth / total;

  function place() {
    const k = pps();
    sel.style.left = inT * k + "px"; sel.style.width = (outT - inT) * k + "px";
    dimL.style.width = inT * k + "px";
    dimR.style.left = outT * k + "px"; dimR.style.width = Math.max(0, (total - outT) * k) + "px";
    $("#tTc").innerHTML = `<span>Début <b>${fmtCut(inT, info)}</b>${fmtDelta(inT - orig[0])}</span>` +
      `<span>Fin <b>${fmtCut(outT, info)}</b>${fmtDelta(outT - orig[1])}</span>` +
      `<span>Durée <b>${(outT - inT).toFixed(1).replace(".", ",")} s</b></span>`;
    $("#eSave").classList.toggle("glow", changed());
    if (changed()) msg.textContent = "Nouvelles coupes : clique sur « Mettre à jour l'aperçu » pour refaire le clip.";
  }
  function ruler() {
    const k = pps(), step = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600].find((s) => s * k >= 90) || 600;
    let html = "";
    for (let t = 0; t <= total + 0.01; t += step) html += `<span style="left:${t * k}px">${fmtCut(t, info, true)}</span>`;
    $("#tRuler").style.width = strip.clientWidth + "px";
    $("#tRuler").innerHTML = html;
  }
  function film() { // la bande de vignettes : plus il y a de place, plus il y a de vignettes
    clearTimeout(stripTimer);
    stripTimer = setTimeout(() => {
      const n = Math.max(8, Math.min(400, Math.round(strip.clientWidth / 96)));
      if (stripN && Math.abs(n - stripN) / stripN < 0.25) return;
      stripN = n;
      const img = new Image();
      img.onload = () => { strip.style.backgroundImage = `url(${img.src})`; };
      img.src = `/filmstrip/${encodeURIComponent(id)}?n=${n}&v=${info.version}`;
    }, stripN ? 350 : 0);
  }
  function layout(keepCenter) {
    const center = keepCenter ?? (inT + outT) / 2;
    strip.style.width = Math.max(200, (wrap.clientWidth - 40) * z) + "px";
    place(); ruler(); film();
    wrap.scrollLeft = center * pps() + 20 - wrap.clientWidth / 2;
  }
  const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
  function autoscroll(x) {
    const rc = wrap.getBoundingClientRect();
    if (x > rc.right - 30) wrap.scrollLeft += 10;
    else if (x < rc.left + 30) wrap.scrollLeft -= 10;
  }
  const timeAt = (x) => clamp((x - strip.getBoundingClientRect().left) / pps(), 0, total);

  // les deux poignées
  for (const [el, which] of [[$("#tHL"), "in"], [$("#tHR"), "out"]]) {
    el.addEventListener("pointerdown", (e) => {
      e.preventDefault(); e.stopPropagation();
      el.setPointerCapture(e.pointerId); vid.pause(); playing = false; $("#tPlay").textContent = "▶ Lire la sélection";
      active = which; el.classList.add("on");
      const move = (ev) => {
        const t = Math.round(timeAt(ev.clientX) * 10) / 10;
        if (which === "in") inT = clamp(t, Math.max(0, outT - MAX), outT - MIN);
        else outT = clamp(t, inT + MIN, Math.min(total, inT + MAX));
        place(); seek(which === "in" ? inT : outT); autoscroll(ev.clientX);
      };
      const up = () => { el.classList.remove("on"); el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up); };
      el.addEventListener("pointermove", move); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
    });
  }
  // cliquer ou glisser ailleurs sur la bande : on se déplace dans le stream (sans toucher aux coupes)
  strip.addEventListener("pointerdown", (e) => {
    strip.setPointerCapture(e.pointerId); vid.pause(); playing = false; $("#tPlay").textContent = "▶ Lire la sélection";
    seek(timeAt(e.clientX));
    const move = (ev) => seek(timeAt(ev.clientX));
    const up = () => { strip.removeEventListener("pointermove", move); strip.removeEventListener("pointerup", up); };
    strip.addEventListener("pointermove", move); strip.addEventListener("pointerup", up);
  });
  // la tête de lecture suit l'aperçu
  const tick = () => {
    if (!document.body.contains(strip)) return;
    ph.style.left = vid.currentTime * pps() + "px";
    if (playing && vid.currentTime >= outT) { vid.pause(); playing = false; $("#tPlay").textContent = "▶ Lire la sélection"; vid.currentTime = inT; }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  $("#tPlay").onclick = () => {
    if (playing) { vid.pause(); playing = false; $("#tPlay").textContent = "▶ Lire la sélection"; return; }
    if (vid.currentTime < inT || vid.currentTime >= outT - 0.05) vid.currentTime = inT;
    vid.play(); playing = true; $("#tPlay").textContent = "❚❚ Pause";
  };
  $("#tReset").onclick = () => { [inT, outT] = orig; place(); seek(inT); msg.textContent = ""; };
  // zoom : le curseur, les boutons, ou Ctrl + molette
  const zoomTo = (v) => { $("#tZoom").value = clamp(v, 0, 100); z = Math.pow(zmax, $("#tZoom").value / 100); layout(); };
  $("#tZoom").oninput = () => zoomTo(+$("#tZoom").value);
  $("#tZm").onclick = () => zoomTo(+$("#tZoom").value - 15);
  $("#tZp").onclick = () => zoomTo(+$("#tZoom").value + 15);
  wrap.addEventListener("wheel", (e) => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); zoomTo(+$("#tZoom").value + (e.deltaY < 0 ? 8 : -8)); } }, { passive: false });
  // flèches du clavier : la dernière poignée touchée bouge de 0,1 s (1 s avec Maj)
  const key = (e) => {
    if (!document.body.contains(strip)) { document.removeEventListener("keydown", key); return; }
    if (e.target.closest("input, textarea, select") || !["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    e.preventDefault();
    const d = (e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 1 : 0.1);
    if (active === "in") inT = clamp(Math.round((inT + d) * 10) / 10, Math.max(0, outT - MAX), outT - MIN);
    else outT = clamp(Math.round((outT + d) * 10) / 10, inT + MIN, Math.min(total, inT + MAX));
    place(); seek(active === "in" ? inT : outT);
  };
  document.addEventListener("keydown", key);
  new ResizeObserver(() => { if (document.body.contains(strip)) layout(); }).observe(wrap);
  layout();
}

async function editClip(id) {
  const c = await api("/api/clip/" + encodeURIComponent(id));
  const cad = c.cadrage || {};
  const trim = {};
  let style = c.style, mots = c.mots, cadrage = "", cam = null; // cadrage : "" = inchangé, "auto", "jeu", "main"
  const NOMS = { split: "webcam en haut, jeu en bas", jeu: "pas de webcam : le jeu au centre", plein: "streameur en plein écran" };
  const hasTrim = !!(c.coupe && c.section_ok);
  openModal(`<div class="edit2">
    <div class="ed-top"><div class="ed-prev"><video id="eVid" src="${c.mp4}" controls autoplay playsinline></video></div>
      <div class="ed-side">
        <h2>Modifier le clip</h2>
        ${c.chat ? `<p class="hint chatline">💬 Le chat a réagi : ${esc(c.chat)}</p>` : ""}
        ${hasTrim ? `<div class="srcbox"><video id="tVid" playsinline preload="auto"></video><div class="srcload" id="tLoad"><span class="spin"></span> Préparation de la timeline…</div></div>
        <div class="tcrow"><div class="tc" id="tTc"></div><button id="tPlay">▶ Lire la sélection</button></div>` : ""}
        <div class="row"><button class="primary" id="eSave"${c.section_ok ? "" : " disabled title=\"l'extrait source a été supprimé\""}>Mettre à jour l'aperçu</button>
          <a href="/download/${encodeURIComponent(id)}"><button class="yellow">⬇ Télécharger le MP4</button></a>
          <button id="eDel">Supprimer</button>${c.lien ? `<a href="${esc(c.lien)}" target="_blank" style="color:var(--muted);font-size:13px">voir sur Twitch</a>` : ""}</div>
        <p class="hint" id="eMsg" style="margin-top:8px"></p>
      </div></div>
    ${hasTrim ? `<div class="trim">
      <div class="trimbar"><b>Début et fin du clip</b><span class="hint">Fais glisser les poignées jaunes · flèches ← → pour 0,1 s · Ctrl + molette pour zoomer</span>
        <span class="grow"></span>
        <span class="zoom"><button id="tZm" title="Dézoomer">−</button><input type="range" id="tZoom" min="0" max="100" value="0"><button id="tZp" title="Zoomer">+</button></span>
        <button id="tReset">Revenir au clip d'origine</button><button id="tWiden" class="hidden"></button></div>
      <div class="stripwrap" id="tWrap"><div class="strip" id="tStrip"><div class="dim" id="tDimL"></div><div class="dim" id="tDimR"></div>
        <div class="sel" id="tSel"><div class="h l" id="tHL"><i></i></div><div class="h r" id="tHR"><i></i></div></div><div class="ph" id="tPh"></div></div>
        <div class="ruler" id="tRuler"></div></div>
      <p class="hint" id="tMsg"></p></div>` : ""}
    <div class="ed-fields">
      <div>
        <div class="field"><span class="l">Titre (emojis acceptés)</span><input type="text" id="eTitre" value="${esc(c.titre)}"></div>
        <div class="field"><span class="l">Style des sous-titres</span>${stylePicker(style)}</div>
        <div class="field"><span class="l">Mots affichés à la fois</span><select id="eMots"><option value="1">1 (mot par mot)</option><option value="2">2</option><option value="3">3</option></select></div>
      </div>
      <div>
        <div class="field"><span class="l">Sous-titres (corrige un mot, vide-le pour l'enlever ; les temps restent les mêmes)</span>
          <div class="words">${c.words.map((w, i) => `<input data-i="${i}" value="${esc(w.text)}" size="${Math.max(3, w.text.length)}" title="${w.start.toFixed(1)} s">`).join("")}</div></div>
        <div class="field"><span class="l">Cadrage : ${NOMS[cad.type] || "automatique"}</span>
          <div class="row" id="eCad"><button data-c="main">✏️ Tracer la webcam</button><button data-c="jeu">Pas de webcam</button><button data-c="auto">Détection automatique</button></div>
          <div id="eDraw" class="draw hidden"><img id="eFrame" draggable="false" alt=""><div id="eBox" class="rect hidden"></div></div>
          <p class="hint" id="eCadMsg" style="margin:6px 0 0"></p></div>
      </div>
    </div></div>`);
  $("#eMots").value = String(mots || 2);
  bindPicker($(".styles", $("#modalBox")), (s) => { style = s; });
  if (hasTrim) mountTrim(id, c, trim);

  // --- cadrage : trois boutons ; « tracer » montre l'image d'origine, on y dessine le cadre de la webcam
  const draw = $("#eDraw"), img = $("#eFrame"), box = $("#eBox"), msg = $("#eCadMsg");
  const showBox = () => {
    if (!cam || !img.naturalWidth || !cad.l) { box.classList.add("hidden"); return; }
    const k = img.clientWidth / cad.l;
    Object.assign(box.style, { left: cam[0] * k + "px", top: cam[1] * k + "px", width: cam[2] * k + "px", height: cam[3] * k + "px" });
    box.classList.remove("hidden");
  };
  $$("#eCad button").forEach((b) => b.onclick = () => {
    if (!c.section_ok) { msg.textContent = "L'extrait source a été supprimé : le cadrage ne peut plus changer."; return; }
    cadrage = b.dataset.c;
    $$("#eCad button").forEach((x) => x.classList.toggle("primary", x === b));
    draw.classList.toggle("hidden", cadrage !== "main");
    if (cadrage === "main") {
      cam = cad.type === "split" && cad.cam ? cad.cam.map(Number) : null;
      img.onload = () => { showBox(); draw.scrollIntoView({ block: "nearest", behavior: "smooth" }); };
      img.src = "/frame/" + encodeURIComponent(id);
      msg.textContent = "Clique et glisse pour entourer la webcam du streameur, puis « Mettre à jour l'aperçu ».";
    } else msg.textContent = cadrage === "jeu" ? "Le jeu sera au centre, sur un fond flouté." : "La webcam sera recherchée de nouveau.";
  });
  let from = null;
  const at = (e) => { const r = img.getBoundingClientRect(); return [Math.min(Math.max(e.clientX - r.left, 0), r.width), Math.min(Math.max(e.clientY - r.top, 0), r.height)]; };
  draw.onpointerdown = (e) => { if (!cad.l) return; from = at(e); draw.setPointerCapture(e.pointerId); e.preventDefault(); };
  draw.onpointermove = (e) => {
    if (!from) return;
    const [x, y] = at(e), k = cad.l / img.clientWidth;
    cam = [Math.min(from[0], x) * k, Math.min(from[1], y) * k, Math.abs(x - from[0]) * k, Math.abs(y - from[1]) * k].map(Math.round);
    showBox();
  };
  draw.onpointerup = () => { from = null; if (cam && (cam[2] < 60 || cam[3] < 40)) { cam = null; showBox(); msg.textContent = "Cadre trop petit : recommence en entourant toute la webcam."; } };

  $("#eSave").onclick = async () => {
    if (cadrage === "main" && !cam) { msg.textContent = "Trace d'abord le cadre de la webcam sur l'image."; return; }
    const words = c.words.map((w, i) => ({ ...w, text: $(`.words input[data-i="${i}"]`).value }));
    $("#eSave").disabled = true; $("#eMsg").innerHTML = '<span class="spin"></span> Nouveau rendu…';
    const body = { type: "rerender", id, titre: $("#eTitre").value, words, style, mots: +$("#eMots").value };
    if (cadrage === "main") body.cam = cam; else if (cadrage) body.mise_en_page = cadrage;
    const t = trim.get ? trim.get() : null;
    if (t && t.changed) { body.t_in = t.t_in; body.dur = t.dur; $("#eMsg").innerHTML = '<span class="spin"></span> Nouveau rendu avec les nouvelles coupes (les mots ajoutés sont transcrits)…'; }
    try {
      const job = await api("/api/jobs", body);
      track(job, (j) => { if (j.status === "fini") editClip(id); else { $("#eMsg").textContent = "Erreur : " + j.error; $("#eSave").disabled = false; } });
    } catch (e) { $("#eMsg").textContent = "Erreur : " + e.message; $("#eSave").disabled = false; }
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
