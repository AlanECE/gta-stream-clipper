"""Rediffusion → moments forts → clips verticaux."""
from __future__ import annotations

import datetime as dt
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from . import analyze, chat, facecam, render, source, transcribe
from .analyze import Moment, Word
from .util import hms, log, parse_time, slug, twitch_t

MAX_FULL = 10 * 3600  # au-delà, on n'analyse que les 10 premières heures (sauf --de / --a)


def _words_in(ws: list[Word], a: float, b: float, shift: float) -> list[Word]:
    return [Word(w.start - shift, w.end - shift, w.text) for w in ws if w.start >= a - 0.05 and w.end <= b + 0.3]


def write_clip(opts, out_dir: Path, base: str, section: Path, layout, words, t_in, dur, title, streamer,
               meta: dict) -> Path:
    mp4 = out_dir / f"{base}.mp4"
    render.render(section, mp4, layout, words, t_in, dur, title, streamer, title_dur=opts.titre_duree,
                  sep=0 if opts.sans_separateur else 8)
    tag = slug(streamer, 30).replace("-", "")
    jeu_tag = slug(opts.jeu, 20).replace("-", "")
    name = render.display_name(streamer)
    legende = title[:1] + title[1:].lower()
    legende = legende.replace(name.lower(), name.title()).replace(name[:1] + name[1:].lower(), name.title())
    legende = legende.replace(opts.jeu.lower(), opts.jeu)
    (out_dir / f"{base}.txt").write_text(
        f"{title}\n\n"
        f"Légende : {legende} 😭 #{jeu_tag} #{tag} #clips #twitch #fyp\n\n"
        f"Source : {meta.get('source_link', meta.get('source'))}\n"
        f"Ce qu'il dit : {' '.join(w.text for w in words)}\n", encoding="utf-8")
    meta = {**meta, "title": title, "streamer": streamer, "section": str(section.resolve()), "t_in": t_in,
            "dur": dur, "layout": layout.to_dict(), "words": [asdict(w) for w in words],
            "titre_duree": opts.titre_duree, "sep": 0 if opts.sans_separateur else 8}
    (out_dir / f"{base}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return mp4


def clip_stream(url: str, opts) -> list[Path]:
    url = source.normalize(url)
    plat = source.platform(url)
    log(f"lecture du stream : {url}")
    inf = source.info(url)
    if inf.get("is_live"):
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
    if getattr(opts, "analyse", False):
        print(f"\nMoments candidats (du plus fort au plus faible) : {work / 'moments.json'}")
        for i, m in enumerate(moments, 1):
            print(f"  {i}. {hms(start + m.start)} · score {m.score:.2f} · « {m.text_in[:110]} »")
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
    sections, layouts = [], []
    for n, m in enumerate(keep, 1):
        t0 = start + m.start
        section = work / f"section_{int(t0)}.mp4"
        log(f"extrait {n}/{len(keep)} : {hms(t0)} → {hms(start + m.end)} ({m.end - m.start:.0f} s)")
        if not section.exists():
            source.grab(url, section, t0 - 1.0, m.end - m.start + 2.0)
        sections.append(section)
        layouts.append(facecam.detect(section, opts.cam))
    layouts = facecam.consensus(layouts)

    made = []
    day = dt.date.today().strftime("%Y%m%d")
    for n, (m, section, layout) in enumerate(zip(keep, sections, layouts), 1):
        t0 = start + m.start
        dur = m.end - m.start
        words = _words_in(m.words, m.start, m.end, m.start)
        title = titles.get(id(m)) or opts.titre
        title = title.format(streamer=render.display_name(streamer), jeu=opts.jeu.upper()) if title \
            else render.auto_title(streamer, opts.jeu, analyze.mood(words), n - 1, opts.titre_langue)
        link = url
        if plat == "twitch" and "/videos/" in url:
            link = f"{url}?t={twitch_t(t0)}"
        elif plat == "youtube":
            link = f"{url}{'&' if '?' in url else '?'}t={int(t0)}"
        base = f"{slug(streamer, 30)}_{day}_{int(t0)}"
        made.append(write_clip(opts, out_dir, base, section, layout, words, 1.0, dur, title, streamer,
                               {"source": url, "source_link": link, "debut_stream": t0, "score": m.score}))
    if not opts.garder:
        (work / "audio.ogg").unlink(missing_ok=True)
    return made


def find_moments(url, inf, plat, work: Path, start, end, full, opts) -> list[Moment]:
    """son + chat → pics de hype → chaque pic transcrit et noté. Gardé en cache pour relancer sans tout refaire."""
    pre, post = opts.duree * 0.72, opts.duree * 0.28
    cache = work / f"candidats_{int(start)}_{int(end)}_{int(opts.duree)}.json"
    if cache.exists():
        log("moments déjà analysés : on reprend le cache")
        data = json.loads(cache.read_text(encoding="utf-8"))
        return [Moment(d["peak"], d["start"], d["end"], d["hype"], d["bonus"], [Word(**w) for w in d["words"]],
                       d["lang"], d.get("cutscene", False)) for d in data]
    audio = source.get_audio(url, work, start, end, full)
    loud = analyze.loudness(audio)
    rate = chat.for_vod(url, inf, start, start + len(loud), work, plat)
    log(f"son analysé ({hms(len(loud))})" + (" + chat" if rate is not None else ", sans chat"))
    score = analyze.hype(loud, rate)
    cands = analyze.peaks(score, k=max(opts.nb * 4, 8), min_gap=int(opts.duree * 1.5), margin=int(pre) + 2)
    if not cands:
        raise SystemExit("aucun moment fort trouvé sur cette plage")
    transcribe.load(opts.modele)
    moments: list[Moment] = []
    for i, (p, s) in enumerate(cands, 1):
        a0, a1 = max(0.0, p - pre - 6), min(float(len(loud)), p + post + 6)
        wav = analyze.slice_wav(audio, a0, a1 - a0, work / f"cand_{p}.wav")
        ws, lang = transcribe.words(wav, opts.langue)
        wav.unlink(missing_ok=True)
        ws = [Word(w.start + a0, w.end + a0, w.text) for w in ws]
        st, en = analyze.snap(ws, p, pre, post, a0, a1)
        inside = [w for w in ws if st - 0.05 <= w.start and w.end <= en + 0.3]
        moments.append(Moment(p, st, en, s, analyze.text_bonus(inside, en - st), ws, lang))
    # cinématiques : quelques images basse définition de chaque candidat
    low = source.low_video_url(url)
    if low:
        from concurrent.futures import ThreadPoolExecutor

        def look(m):
            d = m.end - m.start
            return analyze.letterboxed(source.frames_at(low, [start + m.start + d * k for k in (0.2, 0.5, 0.8)]))
        with ThreadPoolExecutor(6) as ex:
            for m, cut in zip(moments, ex.map(look, moments)):
                m.cutscene = cut
    for i, m in enumerate(moments, 1):
        log(f"  candidat {i}/{len(moments)} à {hms(start + m.peak)} · score {m.score:.2f} (son+chat {m.hype:.2f}, "
            f"paroles {m.bonus:+.2f}{', cinématique' if m.cutscene else ''}) · « {m.text_in[:70]} »")
    cache.write_text(json.dumps([{**asdict(m), "words": [asdict(w) for w in m.words]} for m in moments],
                                ensure_ascii=False), encoding="utf-8")
    return moments


def write_moments(work: Path, moments: list[Moment], start: float):
    (work / "moments.json").write_text(json.dumps(
        [{"n": i, "debut": hms(start + m.start), "fin": hms(start + m.end), "score": m.score,
          "cinematique": m.cutscene, "texte": m.text_in} for i, m in enumerate(moments, 1)], ensure_ascii=False, indent=1), encoding="utf-8")


def redo(json_path: str, opts) -> Path:
    meta = json.loads(Path(json_path).read_text(encoding="utf-8"))
    section = Path(meta["section"])
    if not section.exists():
        raise SystemExit("l'extrait source a été supprimé : relance la commande d'origine")
    L = facecam.Layout(**{k: tuple(v) if isinstance(v, list) else v for k, v in meta["layout"].items()})
    if opts.cam:
        L = facecam.detect(section, opts.cam)
    words = [Word(**w) for w in meta["words"]]
    title = opts.titre.format(streamer=render.display_name(meta["streamer"]), jeu=opts.jeu.upper()) \
        if opts.titre else meta["title"]
    out = Path(json_path).with_suffix(".mp4")
    opts.titre_duree = opts.titre_duree if opts.titre_duree is not None else meta.get("titre_duree", 2.4)
    render.render(section, out, L, words, meta["t_in"], meta["dur"], title, meta["streamer"],
                  title_dur=opts.titre_duree, sep=meta.get("sep", 8))
    meta.update({"title": title, "layout": L.to_dict(), "titre_duree": opts.titre_duree})
    Path(json_path).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    txt = Path(json_path).with_suffix(".txt")
    if txt.exists():
        lines = txt.read_text(encoding="utf-8").split("\n")
        lines[0] = title
        txt.write_text("\n".join(lines), encoding="utf-8")
    return out


def clean_work(sortie: str):
    w = Path(sortie) / ".travail"
    if w.exists():
        shutil.rmtree(w, ignore_errors=True)
