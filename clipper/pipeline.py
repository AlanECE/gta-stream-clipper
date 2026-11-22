"""Rediffusion → moments forts → clips verticaux."""
from __future__ import annotations

import datetime as dt
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from . import analyze, chat, facecam, render, source, transcribe
from .analyze import Moment, Word
from .util import hms, log, parse_time, same_job, slug, twitch_t, video_info, why

MAX_FULL = 10 * 3600  # au-delà, on n'analyse que les 10 premières heures (sauf --de / --a)


def _words_in(ws: list[Word], a: float, b: float, shift: float) -> list[Word]:
    return [Word(w.start - shift, w.end - shift, w.text) for w in ws if w.start >= a - 0.05 and w.end <= b + 0.3]


def style_of(opts) -> dict:
    return {"sep": 8 if getattr(opts, "separateur", False) else 0, "max_words": int(getattr(opts, "mots", 2) or 2),
            "highlight": getattr(opts, "style", None) or getattr(opts, "surlignage", None) or "jaune", "sub_y": getattr(opts, "sous_titres_y", None)}


def write_clip(opts, out_dir: Path, base: str, section: Path, layout, words, t_in, dur, title, streamer,
               meta: dict) -> Path:
    mp4 = out_dir / f"{base}.mp4"
    words = render.merge_elisions(words)  # « c' » + « est » → « c'est » (aussi dans l'éditeur)
    st = style_of(opts)
    if getattr(opts, "sans_titre", False):
        title = ""
    render.render(section, mp4, layout, words, t_in, dur, title, streamer, **st)
    tag = slug(streamer, 30).replace("-", "")
    jeu_tag = slug(opts.jeu, 20).replace("-", "")
    (out_dir / f"{base}.txt").write_text(
        f"{title}\n\n"
        f"Légende : {title} #{jeu_tag} #{tag} #clips #twitch #fyp\n\n"
        f"Source : {meta.get('source_link', meta.get('source'))}\n"
        f"Ce qu'il dit : {' '.join(w.text for w in words)}\n", encoding="utf-8")
    meta = {**meta, "title": title, "streamer": streamer, "section": str(section.resolve()), "t_in": t_in,
            "dur": dur, "layout": layout.to_dict(), "words": [asdict(w) for w in words], "style": st}
    (out_dir / f"{base}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return mp4


def clip_stream(url: str, opts) -> list[Path]:
    url = source.normalize(url)
    plat = source.platform(url)
    log(f"lecture du stream : {url}")
    inf = source.info(url)
    # la rediffusion d'un live encore en cours s'annonce « en direct » elle aussi : un lien de rediffusion
    # (ou une plage demandée) s'analyse comme une rediffusion ; seul un lien de chaîne passe en mode live
    vod = "/videos/" in url or "/video/" in url or bool(opts.de or opts.a) or plat == "fichier"
    if inf.get("is_live") and not vod:
        if getattr(opts, "pas_de_live", False):  # onglet « Depuis un lien » de l'interface
            raise SystemExit("Ce lien est un live en cours. Pour le surveiller : onglet « En direct ». Pour le "
                             "clipper ici : colle le lien de sa rediffusion (twitch.tv/videos/…) avec une plage.")
        log("ce stream est en direct : passage en mode live")
        from .live import clip_live
        return clip_live(url, opts, inf)
    streamer = opts.streamer or source.streamer_name(inf)
    total = float(inf.get("duration") or 0)
    start = parse_time(opts.de) or 0.0
    end = parse_time(opts.a) or total
    if not end:
        raise SystemExit("durée du stream inconnue : précise --a (ex. --a 2:00:00)")
    if not opts.a and end - start > MAX_FULL:
        log(f"stream de {hms(total)} : on analyse les 10 premières heures (choisis une plage avec --de et --a)")
        end = start + MAX_FULL
    end = min(end, total) if total else end
    full = start == 0 and (not total or end >= total - 1)
    work = Path(opts.sortie) / ".travail" / slug(f"{streamer}-{inf.get('id', 'stream')}", 60)
    work.mkdir(parents=True, exist_ok=True)
    out_dir = Path(opts.sortie)
    log(f"{streamer} · « {inf.get('title', '')[:70]} » · analyse de {hms(start)} à {hms(end)}")

    moments = find_moments(url, inf, plat, work, start, end, full, opts)
    moments.sort(key=lambda m: -m.score)
    write_moments(work, moments, start)
    opts.moments_file = str(work / "moments.json")  # l'interface graphique relit la liste ici
    opts.analyse_info = {"streamer": streamer, "titre": inf.get("title", ""), "debut": start, "fin": end}
    if getattr(opts, "analyse", False):
        print(f"\nMoments candidats (du plus fort au plus faible) : {work / 'moments.json'}")
        for i, m in enumerate(moments, 1):
            print(f"  {i}. {hms(start + m.start)} · score {m.score:.2f} · « {said(m)[:110]} »")
        print("\nPour clipper ceux que tu veux : la même commande avec --choix 1,3")
        return []
    titles: dict[int, str] = {}
    if getattr(opts, "choix", None):
        idx = [int(x) - 1 for x in str(opts.choix).split(",") if x.strip()]
        keep = [moments[i] for i in idx if 0 <= i < len(moments)]
        for m, t in zip(keep, [t.strip() for t in (getattr(opts, "titres", None) or "").split("|")]):
            if t:
                titles[id(m)] = t
    else:
        keep = [m for m in moments if m.score >= opts.seuil][:opts.nb] or moments[:1]

    # les extraits vidéo, puis la webcam (le même cadre pour tout le stream)
    keep.sort(key=lambda m: m.start)
    sections, layouts, leads = [], [], []
    for n, m in enumerate(keep, 1):
        t0 = start + m.start
        lead = min(1.0, t0)  # une seconde de marge avant le moment (moins s'il est tout au début du stream)
        section = work / f"section_{int(t0)}.mp4"
        log(f"extrait {n}/{len(keep)} : {hms(t0)} → {hms(start + m.end)} ({m.end - m.start:.0f} s)")
        if not section.exists():
            source.grab(url, section, t0 - lead, m.end - m.start + lead + 1.0)
        sections.append(section)
        leads.append(lead)
        layouts.append(facecam.detect(section, opts.cam, lead, m.end - m.start))
    layouts = facecam.consensus(layouts)

    made = []
    day = dt.date.today().strftime("%Y%m%d")
    for n, (m, section, layout, lead) in enumerate(zip(keep, sections, layouts, leads), 1):
        t0 = start + m.start
        dur = m.end - m.start
        words = _words_in(m.words, m.start, m.end, m.start)
        title = titles.get(id(m)) or opts.titre
        title = render.fill_title(title, streamer, opts.jeu) if title \
            else render.auto_title(streamer, opts.jeu, analyze.mood(words), n - 1, opts.titre_langue)
        link = url
        if plat == "twitch" and "/videos/" in url:
            link = f"{url}?t={twitch_t(t0)}"
        elif plat == "youtube":
            link = f"{url}{'&' if '?' in url else '?'}t={int(t0)}"
        base = f"{slug(streamer, 30)}_{day}_{int(t0)}"
        made.append(write_clip(opts, out_dir, base, section, layout, words, lead, dur, title, streamer,
                               {"source": url, "source_link": link, "debut_stream": t0, "score": m.score,
                                "section_debut": t0 - lead, "langue": m.lang, "chat": m.chat}))
    if not opts.garder:
        for f in [*work.glob("audio_*.wav"), *work.glob("audio_*.ogg")]:
            f.unlink(missing_ok=True)
    return made


def find_moments(url, inf, plat, work: Path, start, end, full, opts) -> list[Moment]:
    """son + chat → pics de hype → chaque pic transcrit et noté. Gardé en cache pour relancer sans tout refaire.

    Ce qui attend le réseau tourne en même temps : le chat pendant que le son se télécharge, les images du jeu
    (repérage des cinématiques) pendant que les paroles sont transcrites."""
    pre, post = opts.duree * 0.72, opts.duree * 0.28
    cache = work / f"candidats_{int(start)}_{int(end)}_{int(opts.duree)}.json"
    if cache.exists():
        log("moments déjà analysés : on reprend le cache")
        data = json.loads(cache.read_text(encoding="utf-8"))
        return [Moment(d["peak"], d["start"], d["end"], d["hype"], d["bonus"], [Word(**w) for w in d["words"]],
                       d["lang"], d.get("cutscene", False), d.get("chat", ""), d.get("chat_bonus", 0.0))
                for d in data]
    ex = ThreadPoolExecutor(13)
    try:
        chat_job = None if getattr(opts, "sans_chat", False) else \
            ex.submit(same_job(chat.for_vod), url, inf, start, end, work, plat)
        low_job = ex.submit(source.low_video_url, url)
        audio = source.get_audio(url, work, start, end)
        loud = analyze.loudness(audio)
        rate, reacts = chat_job.result() if chat_job else (None, [])
        log(f"son analysé ({hms(len(loud))})" + (" + chat" if rate is not None else ", sans chat"))
        score = analyze.hype(loud, rate)
        cands = analyze.peaks(score, k=max(opts.nb * 4, 8), min_gap=int(opts.duree * 1.5), margin=int(pre) + 2)
        if not cands:
            raise SystemExit("aucun moment fort trouvé sur cette plage")

        def look(p) -> bool:  # cinématique ? quelques images basse définition autour du pic
            low = low_job.result()
            return bool(low) and analyze.letterboxed(source.frames_span(low, start + p - pre, pre + post))
        looks = [ex.submit(look, p) for p, _ in cands]
        transcribe.load(opts.modele)
        moments: list[Moment] = []
        for p, sc in cands:
            a0, a1 = max(0.0, p - pre - 6), min(float(len(loud)), p + post + 6)
            wav = analyze.slice_wav(audio, a0, a1 - a0, work / f"cand_{p}.wav")
            ws, lang = transcribe.words(wav, opts.langue)
            wav.unlink(missing_ok=True)
            ws = [Word(w.start + a0, w.end + a0, w.text) for w in ws]
            st, en = analyze.snap(ws, p, pre, post, a0, a1)
            inside = [w for w in ws if st - 0.05 <= w.start and w.end <= en + 0.3]
            moments.append(Moment(p, st, en, sc, analyze.text_bonus(inside, en - st), ws, lang))
        for m, job in zip(moments, looks):
            try:
                m.cutscene = job.result(timeout=150)
            except Exception:  # noqa: BLE001 (le repérage des cinématiques est un plus : sans lui, on continue)
                m.cutscene = False
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    per_sec = len(reacts) / max(1.0, end - start)  # réactions par seconde, d'habitude, sur ce stream
    for m in moments:  # le chat réagit quelques secondes après : on regarde jusqu'à 12 s après la fin du moment
        m.chat = chat.summary(reacts, start + m.start, start + m.end + 12)
        m.chat_bonus = analyze.chat_bonus(reacts, start + m.start, start + m.end + 12, per_sec)
    for i, m in enumerate(moments, 1):
        log(f"  candidat {i}/{len(moments)} à {hms(start + m.peak)} · score {m.score:.2f} (son+chat {m.hype:.2f}, "
            f"paroles {m.bonus:+.2f}{', cinématique' if m.cutscene else ''}"
            f"{f', réactions du chat {m.chat_bonus:+.2f} (' + m.chat + ')' if m.chat_bonus else ''}) · « {said(m)[:70]} »")
    cache.write_text(json.dumps([{**asdict(m), "words": [asdict(w) for w in m.words]} for m in moments],
                                ensure_ascii=False), encoding="utf-8")
    if not opts.garder:  # tout ce qu'il faut est dans le cache : le son (115 Mo par heure) peut partir
        audio.unlink(missing_ok=True)
    return moments


def said(m: Moment) -> str:
    """ce qu'il dit pendant le moment, mots recollés (« c'est », « vas-y »)"""
    inside = [w for w in m.words if m.start - 0.05 <= w.start and w.end <= m.end + 0.3]
    return " ".join(w.text for w in render.merge_elisions(inside))


def write_moments(work: Path, moments: list[Moment], start: float):
    (work / "moments.json").write_text(json.dumps(
        [{"n": i, "debut": hms(start + m.start), "fin": hms(start + m.end), "score": m.score,
          "cinematique": m.cutscene, "chat": m.chat, "texte": said(m)} for i, m in enumerate(moments, 1)], ensure_ascii=False, indent=1), encoding="utf-8")


def redo(json_path: str, opts) -> Path:
    meta = json.loads(Path(json_path).read_text(encoding="utf-8"))
    section = Path(meta["section"])
    if not section.exists():
        raise SystemExit("l'extrait source a été supprimé : relance la commande d'origine")
    L = facecam.Layout(**{k: tuple(v) if isinstance(v, list) else v for k, v in meta["layout"].items()})
    if opts.cam:
        L = facecam.detect(section, opts.cam, meta["t_in"], meta["dur"])
    words = [Word(**w) for w in meta["words"]]
    title = render.fill_title(opts.titre, meta["streamer"], opts.jeu) if opts.titre else meta["title"]
    out = Path(json_path).with_suffix(".mp4")
    st = dict(meta.get("style", {}))  # on garde le style d'origine, sauf ce qui est redemandé
    if opts.mots:
        st["max_words"] = int(opts.mots)
    if getattr(opts, "style", None) or opts.surlignage:
        st["highlight"] = getattr(opts, "style", None) or opts.surlignage
    if opts.sous_titres_y:
        st["sub_y"] = opts.sous_titres_y
    if opts.separateur:
        st["sep"] = 8
    render.render(section, out, L, words, meta["t_in"], meta["dur"], "" if opts.sans_titre else title,
                  meta["streamer"], **st)
    meta.update({"title": title, "layout": L.to_dict(), "style": st})
    Path(json_path).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    txt = Path(json_path).with_suffix(".txt")
    if txt.exists():
        lines = txt.read_text(encoding="utf-8").split("\n")
        lines[0] = title
        txt.write_text("\n".join(lines), encoding="utf-8")
    return out


def redo_with(json_path: str | Path, title: str | None = None, words: list[dict] | None = None,
              style: str | None = None, mots: int | None = None, sub_y: float | None = None,
              cam: list | None = None, mise_en_page: str | None = None,
              t_in: float | None = None, dur: float | None = None) -> Path:
    """refaire un clip avec un titre, des sous-titres (mots aux mêmes temps), un style ou un cadrage modifiés
    (interface). `cam` : cadre de la webcam tracé à la main (x, y, largeur, hauteur dans l'image source) ;
    `mise_en_page` : « auto » (détection), « jeu » (pas de webcam : le jeu au centre)."""
    jp = Path(json_path)
    meta = json.loads(jp.read_text(encoding="utf-8"))
    section = Path(meta["section"])
    if not section.exists():
        raise RuntimeError("l'extrait source a été supprimé : il faut refaire le clip depuis le début")
    L = facecam.Layout(**{k: tuple(v) if isinstance(v, list) else v for k, v in meta["layout"].items()})
    if cam:
        L = facecam.detect(section, [float(v) for v in cam], meta["t_in"], meta["dur"])
    elif mise_en_page == "jeu":
        L = facecam.Layout("jeu", L.src_w, L.src_h, seam_y=1420)
    elif mise_en_page == "auto":
        L = facecam.detect(section, None, meta["t_in"], meta["dur"])
    if words is not None:
        meta["words"] = [{"start": float(w["start"]), "end": float(w["end"]), "text": str(w["text"]).strip()}
                         for w in words if str(w.get("text", "")).strip()]
    if title is not None:
        meta["title"] = title
    if t_in is not None and dur is not None:
        new_in, new_dur = clamp_trim(section, float(t_in), float(dur))
        if abs(new_in - meta["t_in"]) > 0.04 or abs(new_dur - meta["dur"]) > 0.04:
            log(f"nouvelles coupes : début {new_in - meta['t_in']:+.1f} s, fin "
                f"{(new_in + new_dur) - (meta['t_in'] + meta['dur']):+.1f} s")
            meta["words"] = retime_words(meta, section, new_in, new_dur)
            meta["t_in"], meta["dur"] = new_in, new_dur
    st = dict(meta.get("style", {}))
    if style:
        st["highlight"] = style
    if mots:
        st["max_words"] = int(mots)
    if sub_y:
        st["sub_y"] = float(sub_y)
    meta["style"] = st
    meta["layout"] = L.to_dict()
    render.render(section, jp.with_suffix(".mp4"), L, [Word(**w) for w in meta["words"]], meta["t_in"], meta["dur"],
                  meta["title"], meta.get("streamer", ""), **st)
    jp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    txt = jp.with_suffix(".txt")
    if txt.exists():
        lines = txt.read_text(encoding="utf-8").split("\n")
        lines[0] = meta["title"]
        txt.write_text("\n".join(lines), encoding="utf-8")
    return jp.with_suffix(".mp4")


MIN_CLIP, MAX_CLIP = 2.0, 180.0


def clamp_trim(section: Path, t_in: float, dur: float) -> tuple[float, float]:
    """un début et une durée qui tiennent dans l'extrait (2 s à 3 min)"""
    total = video_info(section)[3]
    t_in = min(max(0.0, t_in), max(0.0, total - MIN_CLIP))
    dur = min(max(MIN_CLIP, dur), MAX_CLIP, total - t_in)
    return round(t_in, 3), round(dur, 3)


def retime_words(meta: dict, section: Path, new_in: float, new_dur: float) -> list[dict]:
    """Les sous-titres d'un clip dont le début ou la fin ont bougé : les mots déjà là (corrigés ou non) sont gardés,
    les morceaux ajoutés avant ou après sont transcrits."""
    old_in, old_out = meta["t_in"], meta["t_in"] + meta["dur"]
    new_out = new_in + new_dur
    words = [(w["start"] + old_in, w["end"] + old_in, w["text"]) for w in meta.get("words", [])]
    keep = [w for w in words if w[0] >= new_in - 0.05 and w[1] <= new_out + 0.3]
    if new_in < old_in - 0.2 or new_out > old_out + 0.2:
        a0 = max(0.0, new_in - 0.5)
        a1 = min(video_info(section)[3], new_out + 0.5)
        transcribe.load()
        wav = analyze.slice_wav(section, a0, a1 - a0, section.with_name(f"coupe_{int(a0)}.wav"))
        ws, _ = transcribe.words(wav, meta.get("langue"))
        wav.unlink(missing_ok=True)
        for w in ws:
            s0, e0 = w.start + a0, w.end + a0
            mid = (s0 + e0) / 2
            if (mid < old_in or mid > old_out) and s0 >= new_in - 0.05 and e0 <= new_out + 0.3:
                keep.append((s0, e0, w.text))
    keep.sort()
    merged = render.merge_elisions([Word(a - new_in, b - new_in, t) for a, b, t in keep])  # « c » + « 'est »
    return [{"start": round(w.start, 3), "end": round(w.end, 3), "text": w.text} for w in merged]


def section_debut(meta: dict) -> float | None:
    """où commence l'extrait dans le stream d'origine (secondes), si on le sait"""
    if meta.get("section_debut") is not None:
        return float(meta["section_debut"])
    if meta.get("debut_stream") is not None and not meta.get("live"):  # clips faits avant la 1.4
        return float(meta["debut_stream"]) - float(meta.get("t_in", 0))
    return None


def widen_kind(meta: dict) -> str | None:
    """comment aller chercher plus de stream autour du clip : « lien » (rediffusion, fichier), « viral » (via la
    rediffusion du clip Twitch), None (live : c'est automatique ; ou rien à faire)"""
    if meta.get("live"):
        return None
    if section_debut(meta) is not None and meta.get("source") and not meta.get("viral"):
        return "lien"
    v = meta.get("viral") or {}
    if v.get("vod") and v.get("offset") is not None:
        return "viral"
    return None


def _envelope(src, ss=None, t=None, hz=50):
    import subprocess

    import numpy as np
    sr = 8000
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", f"{ss:.3f}"] if ss is not None else []) + ["-i", str(src)] + \
          (["-t", f"{t:.3f}"] if t else []) + ["-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=600).stdout
    a = np.frombuffer(raw[:len(raw) // 2 * 2], np.int16).astype(np.float32) / 32768
    k = sr // hz
    n = len(a) // k
    return np.log10(np.sqrt((a[:n * k].reshape(n, k) ** 2).mean(1)) + 1e-4)


def align(clip: Path, wide: Path, hz: int = 50) -> tuple[float, float]:
    """où le son du clip se trouve dans `wide` : (secondes, corrélation de 0 à 1)"""
    import numpy as np
    k, v = _envelope(clip, hz=hz), _envelope(wide, hz=hz)
    if len(k) < hz * 2 or len(v) <= len(k):
        return 0.0, 0.0
    kn = (k - k.mean()) / (k.std() + 1e-6)
    best = (-9.0, 0)
    win = np.lib.stride_tricks.sliding_window_view(v, len(k))
    mu, sd = win.mean(1), win.std(1) + 1e-6
    corr = ((win - mu[:, None]) / sd[:, None] * kn).mean(1)
    i = int(np.argmax(corr))
    best = (float(corr[i]), i)
    return best[1] / hz, best[0]


def widen(json_path: str | Path, avant: float = 120.0, apres: float = 120.0) -> Path:
    """Va chercher le stream autour du clip (2 min avant et après) pour pouvoir en déplacer le début et la fin."""
    jp = Path(json_path)
    meta = json.loads(jp.read_text(encoding="utf-8"))
    old = Path(meta["section"])
    if not old.exists():
        raise RuntimeError("l'extrait source a été supprimé : il faut refaire le clip depuis le début")
    kind = widen_kind(meta)
    t_in, dur = float(meta["t_in"]), float(meta["dur"])
    if kind == "lien":
        url, s0 = meta["source"], section_debut(meta)
        a = s0 + t_in
        ws = max(0.0, a - avant)
        out = old.with_name(f"large_{int(ws)}_{int(a + dur + apres)}.mp4")
        log(f"le stream de {hms(ws)} à {hms(a + dur + apres)} (2 min avant et après le clip)…")
        source.grab(url, out, ws, (a + dur + apres) - ws)
        meta.update(section=str(out.resolve()), t_in=round(a - ws, 3), section_debut=ws)
    elif kind == "viral":
        c = meta["viral"]
        off, d = float(c["offset"]), float(c.get("duree") or dur)
        ws = max(0.0, off - d - avant - 15)
        we = off + apres + 15
        out = old.with_name(f"large_{int(ws)}_{int(we)}.mp4")
        log("le clip Twitch vient d'une rediffusion : on y va chercher 2 min avant et après…")
        try:
            source.grab(c["vod"], out, ws, we - ws)
        except RuntimeError as e:
            raise RuntimeError(f"la rediffusion de ce clip n'est pas accessible ({why(e)}) : impossible d'aller "
                               "plus loin que le clip Twitch lui-même") from None
        log("on retrouve le clip dans la rediffusion (par le son)…")
        pos, corr = align(old, out)
        if corr < 0.5:
            out.unlink(missing_ok=True)
            raise RuntimeError("impossible de retrouver ce clip dans la rediffusion (le son ne correspond pas)")
        log(f"clip retrouvé à {pos:.2f} s (correspondance {corr:.0%})")
        meta.update(section=str(out.resolve()), t_in=round(pos + t_in, 3), section_debut=ws)
    else:
        raise RuntimeError("pour ce clip, l'outil n'a pas accès au stream d'origine")
    jp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log("prêt : tu peux déplacer le début et la fin du clip")
    return out


def clip_from_viral(c: dict, opts, index: int = 0) -> Path:
    """un clip viral (dict de viral.top_clips) → clip vertical.

    On part du clip Twitch lui-même : c'est le moment exact qui a buzzé, avec son vrai son. (La rediffusion, elle,
    peut être réservée aux abonnés, supprimée, ou muette là où passait une musique protégée ; et la position que
    Twitch donne pour y retrouver le clip tombe à la fin du clip, à quelques secondes près.)"""
    out_dir = Path(opts.sortie)
    work = out_dir / ".travail" / slug(f"viral-{c.get('login')}-{c.get('id')}", 70)
    work.mkdir(parents=True, exist_ok=True)
    streamer = c.get("streamer") or c.get("login") or "streamer"
    section = work / "clip.mp4"
    if not (section.exists() and section.stat().st_size > 50_000):
        log(f"« {c.get('titre', '')[:50]} » ({streamer}) : téléchargement du clip")
        try:
            source.fetch(c["url"], section, float(c.get("duree") or 60))
        except RuntimeError as e:
            raise RuntimeError(f"clip indisponible : {why(e)}") from None
    dur = video_info(section)[3] - 0.05
    lang = opts.langue or (c.get("langue") if c.get("langue") in ("fr", "en", "es", "de", "it", "pt") else None)
    transcribe.load(opts.modele)
    wav = analyze.slice_wav(section, 0, dur, work / "clip.wav")
    ws, lang = transcribe.words(wav, lang)
    wav.unlink(missing_ok=True)
    layout = facecam.detect(section, opts.cam, 0.0, dur)
    words = _words_in(ws, 0.0, dur, 0.0)
    title = render.fill_title(opts.titre, streamer, opts.jeu) if opts.titre \
        else render.auto_title(streamer, opts.jeu, analyze.mood(words), index, opts.titre_langue)
    name = f"{slug(c.get('login') or streamer, 30)}_viral_{slug(c.get('id') or 'clip', 12)}"
    out = write_clip(opts, out_dir, name, section, layout, words, 0.0, dur, title, streamer,
                     {"source": c.get("url"), "source_link": c.get("url"), "viral": c, "langue": lang})
    for old in ("section.mp4", "section.json"):  # extrait de la version 1.2.0, remplacé par le clip lui-même
        (work / old).unlink(missing_ok=True)
    return out


def clean_work(sortie: str):
    w = Path(sortie) / ".travail"
    if w.exists():
        shutil.rmtree(w, ignore_errors=True)
