"""Mode live : on enregistre le stream par morceaux de 20 s, on écoute le chat, et dès qu'un moment fort est passé
(avec quelques secondes après), on fabrique le clip. Un clip sort ~1 minute après le moment."""
from __future__ import annotations

import csv
import datetime as dt
import subprocess
import time
from pathlib import Path

import numpy as np

from . import analyze, chat, facecam, render, source, transcribe
from .analyze import Word
from .pipeline import _words_in, write_clip
from .util import hms, log, run, slug

SEG = 20          # secondes par morceau
KEEP = 15 * 60    # on garde les 15 dernières minutes


class Recorder:
    def __init__(self, url: str, d: Path):
        self.url, self.d = url, d
        self.t0 = time.monotonic()
        self.runs: list[tuple[int, float]] = []  # (numéro, décalage depuis le début de la session)
        self.p = None

    def start(self):
        urls = source.media_urls(self.url)
        k = len(self.runs)
        self.runs.append((k, time.monotonic() - self.t0))
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        for u in urls[:2]:
            cmd += ["-i", u]
        cmd += ["-map", "0:v:0", "-map", "1:a:0"] if len(urls) > 1 else ["-map", "0:v:0", "-map", "0:a:0?"]
        cmd += ["-c", "copy", "-f", "segment", "-segment_time", str(SEG), "-reset_timestamps", "1",
                "-segment_list", str(self.d / f"liste_{k}.csv"), "-segment_list_type", "csv",
                str(self.d / f"r{k}_%05d.ts")]
        self.p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=open(self.d / f"ffmpeg_{k}.log", "w"))

    def alive(self) -> bool:
        return self.p is not None and self.p.poll() is None

    def segments(self) -> list[tuple[Path, float, float]]:
        out = []
        for k, off in self.runs:
            f = self.d / f"liste_{k}.csv"
            if not f.exists():
                continue
            for row in csv.reader(f.read_text(encoding="utf-8").splitlines()):
                if len(row) >= 3 and (self.d / row[0]).exists():
                    out.append((self.d / row[0], off + float(row[1]), off + float(row[2])))
        return out

    def stop(self):
        if self.alive():
            self.p.terminate()


def cut(segs, a: float, b: float, out: Path) -> Path:
    """recolle les morceaux qui couvrent [a, b] ; t=0 de `out` = temps a de la session"""
    use = [s for s in segs if s[2] > a and s[1] < b]
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.name}'\n" for p, _, _ in use), encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst.name, "-ss", f"{a - use[0][1]:.3f}",
         "-t", f"{b - a:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", out.name], cwd=out.parent)
    lst.unlink(missing_ok=True)
    return out


def clip_live(url: str, opts, inf: dict | None = None) -> list[Path]:
    url = source.normalize(url)
    inf = inf or source.info(url)
    if not inf.get("is_live"):
        raise SystemExit("ce stream n'est pas en direct. Pour une rediffusion : python -m clipper rediff <lien>")
    streamer = opts.streamer or source.streamer_name(inf)
    plat = source.platform(url)
    work = Path(opts.sortie) / ".travail" / f"live-{slug(streamer, 30)}-{dt.datetime.now():%Y%m%d-%H%M}"
    work.mkdir(parents=True, exist_ok=True)
    out_dir = Path(opts.sortie)
    live_chat = None
    if plat == "twitch" and not getattr(opts, "sans_chat", False):
        login = inf.get("uploader_id") or url.rstrip("/").split("/")[-1]
        live_chat = chat.TwitchLiveChat(login)
        live_chat.start()
    rec = Recorder(url, work)
    rec.start()
    transcribe.load(opts.modele)
    log(f"live de {streamer} : enregistrement pendant {opts.minutes} min (Ctrl+C pour arrêter)")
    pre, post = opts.duree * 0.72, opts.duree * 0.28
    loud: dict[int, float] = {}
    done: set[Path] = set()
    last_end = -1e9
    best_layout = None
    made: list[Path] = []
    stop_at = time.monotonic() + opts.minutes * 60
    n = 0
    try:
        stop_event = getattr(opts, "stop_event", None)  # l'interface graphique peut arrêter l'écoute
        while time.monotonic() < stop_at:
            if stop_event is not None:
                if stop_event.wait(10):
                    log("arrêt demandé")
                    break
            else:
                time.sleep(10)
            if not rec.alive():
                try:
                    if not source.info(url).get("is_live"):
                        log("le live est terminé")
                        break
                except Exception:
                    pass
                log("le flux a coupé : reconnexion")
                rec.start()
            segs = rec.segments()
            for p, a, b in segs:
                if p in done:
                    continue
                l = analyze.loudness(p)
                for i, v in enumerate(l):
                    loud[int(a) + i] = float(v)
                done.add(p)
            if len(loud) < 90:
                continue
            last = max(loud)
            arr = np.array([loud.get(i, -60.0) for i in range(last + 1)], dtype=np.float32)
            rate = live_chat.rate(rec.t0, len(arr)) if live_chat else None
            score = analyze.hype(arr, rate)
            # un pic récent, assez fort, avec la suite déjà enregistrée
            lo = max(int(max(last_end, 0.0) + post), last - 150, int(pre) + 5)
            hi = int(last - post - 3)
            if hi <= lo:
                continue
            p = lo + int(np.argmax(score[lo:hi]))
            s = float(score[p])
            if s < opts.seuil or score[p] < score[max(0, p - 20):p + 10].max() - 1e-6:
                continue
            a, b = max(0.0, p - pre - 4), p + post + 4
            if a < min(x[1] for x in segs):
                continue
            n += 1
            log(f"moment fort à {hms(p)} (hype {s:.2f}) : on fabrique le clip")
            section = cut(segs, a, b, work / f"section_{p}.mp4")
            wav = analyze.slice_wav(section, 0, b - a, work / f"section_{p}.wav")
            ws, lang = transcribe.words(wav, opts.langue)
            wav.unlink(missing_ok=True)
            ws = [Word(w.start + a, w.end + a, w.text) for w in ws]
            st, en = analyze.snap(ws, p, pre, post, a, b)
            inside = [w for w in ws if st - 0.05 <= w.start and w.end <= en + 0.3]
            bonus = analyze.text_bonus(inside, en - st)
            last_end = en
            if s + bonus < opts.seuil:
                log(f"  pas assez fort une fois écouté (score {s + bonus:.2f}), on passe")
                continue
            layout = facecam.detect(section, opts.cam)
            if best_layout is not None:  # la webcam ne bouge pas : on garde le cadre le plus sûr de la session
                layout = facecam.consensus([best_layout, layout])[1]
            if layout.kind == "split" and (best_layout is None or layout.conf > best_layout.conf):
                best_layout = layout
            words = _words_in(ws, st, en, st)
            title = render.fill_title(opts.titre, streamer, opts.jeu) if opts.titre \
                else render.auto_title(streamer, opts.jeu, analyze.mood(words), n - 1, opts.titre_langue)
            base = f"{slug(streamer, 30)}_live_{dt.datetime.now():%Y%m%d_%H%M%S}"
            made.append(write_clip(opts, out_dir, base, section, layout, words, st - a, en - st, title, streamer,
                                   {"source": url, "source_link": url, "score": round(s + bonus, 2)}))
            # ménage : on ne garde que les 15 dernières minutes
            for p2, a2, b2 in segs:
                if b2 < last - KEEP:
                    p2.unlink(missing_ok=True)
    except KeyboardInterrupt:
        log("arrêt demandé")
    finally:
        rec.stop()
        if live_chat:
            live_chat.stop = True
    log(f"{len(made)} clip(s) dans {out_dir}")
    return made
