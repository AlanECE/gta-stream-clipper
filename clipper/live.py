"""Mode live : on enregistre le stream par morceaux de 20 s, on écoute le chat, et dès qu'un moment fort est passé
(avec quelques secondes après), on fabrique le clip. Un clip sort ~1 minute après le moment.

Fait pour tourner longtemps (un serveur branché jour et nuit) : le disque et la mémoire restent bornés, une coupure
du flux se rattrape toute seule, et le mode veille attend le prochain live de la chaîne.
"""
from __future__ import annotations

import contextlib
import csv
import datetime as dt
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from . import analyze, chat, facecam, render, source, transcribe
from .analyze import Moment, Word
from .pipeline import _words_in, write_clip
from .util import adopt, hms, log, run, slug, why

SEG = 20            # secondes par morceau
KEEP = 15 * 60      # vidéo gardée sur le disque : les 15 dernières minutes
WINDOW = 30 * 60    # son gardé en mémoire pour connaître son niveau « normal »
RETRIES = 12        # reconnexions de suite avant d'abandonner (environ 2 minutes)


class Recorder:
    def __init__(self, url: str, d: Path):
        self.url, self.d = url, d
        self.t0 = time.monotonic()
        self.runs: list[tuple[int, float]] = []  # (numéro, décalage depuis le début de la session)
        self.p = None
        self.err = None
        self.gone: set[str] = set()  # morceaux déjà effacés

    def start(self) -> bool:
        """lance (ou relance) l'enregistrement ; False si le flux ne répond pas"""
        self._close()
        try:
            urls = source.media_urls(self.url)
        except RuntimeError:
            return False
        k = len(self.runs)
        self.runs.append((k, time.monotonic() - self.t0))
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        for u in urls[:2]:
            cmd += ["-i", u]
        cmd += ["-map", "0:v:0", "-map", "1:a:0"] if len(urls) > 1 else ["-map", "0:v:0", "-map", "0:a:0?"]
        cmd += ["-c", "copy", "-f", "segment", "-segment_time", str(SEG), "-reset_timestamps", "1",
                "-segment_list", str(self.d / f"liste_{k}.csv"), "-segment_list_type", "csv",
                str(self.d / f"r{k}_%05d.ts")]
        self.err = open(self.d / f"ffmpeg_{k}.log", "w")
        self.p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self.err)
        adopt(self.p)  # si le programme est fermé d'un coup, l'enregistrement s'arrête avec lui
        return True

    def alive(self) -> bool:
        return self.p is not None and self.p.poll() is None

    def segments(self) -> list[tuple[Path, float, float]]:
        out = []
        for k, off in self.runs:
            f = self.d / f"liste_{k}.csv"
            if not f.exists():
                continue
            for row in csv.reader(f.read_text(encoding="utf-8").splitlines()):
                if len(row) >= 3 and row[0] not in self.gone and (self.d / row[0]).exists():
                    out.append((self.d / row[0], off + float(row[1]), off + float(row[2])))
        return out

    def purge(self, segs, before: float):
        """efface les morceaux finis avant `before` (secondes depuis le début de la session)"""
        for p, _, b in segs:
            if b < before:
                p.unlink(missing_ok=True)
                self.gone.add(p.name)

    def _close(self):
        if self.alive():
            self.p.terminate()
            try:
                self.p.wait(8)
            except subprocess.TimeoutExpired:
                self.p.kill()
        if self.err:
            self.err.close()
            self.err = None

    def stop(self):
        self._close()
        for pat in ("r*_*.ts", "liste_*.csv", "ffmpeg_*.log"):  # les extraits des clips, eux, restent
            for f in self.d.glob(pat):
                f.unlink(missing_ok=True)


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


def is_live(url: str) -> tuple[bool | None, dict]:
    """(en direct ?, infos). None = impossible de savoir (réseau, Twitch qui hésite)."""
    try:
        inf = source.info(url)
        return bool(inf.get("is_live")), inf
    except Exception as e:  # noqa: BLE001
        low = str(e).lower()
        if "offline" in low or "not currently live" in low or "does not exist" in low:
            return False, {}
        return None, {}


def clip_live(url: str, opts, inf: dict | None = None) -> list[Path]:
    """Écoute un live pendant `opts.minutes` (0 = sans limite). Avec `opts.veille`, attend que la chaîne passe en
    direct, et recommence à attendre quand le live se termine."""
    url = source.normalize(url)
    stop_event = getattr(opts, "stop_event", None)  # l'interface graphique peut arrêter l'écoute
    minutes = float(getattr(opts, "minutes", 60) or 0)
    stop_at = time.monotonic() + minutes * 60 if minutes > 0 else float("inf")
    veille = bool(getattr(opts, "veille", False))
    made: list[Path] = []

    def pause(sec: float) -> bool:
        """attend ; True s'il faut s'arrêter (bouton stop ou durée écoulée)"""
        sec = max(0.0, min(sec, stop_at - time.monotonic()))
        if stop_event is not None:
            if stop_event.wait(sec):
                return True
        else:
            time.sleep(sec)
        return time.monotonic() >= stop_at

    try:
        while True:
            live, got = (bool(inf.get("is_live")), inf) if inf else is_live(url)
            inf = None
            if live:
                made += _session(url, opts, got, stop_at, pause)
                if not veille or time.monotonic() >= stop_at or (stop_event is not None and stop_event.is_set()):
                    break
                log("veille : on attend le prochain live de la chaîne")
            elif not veille and live is None:
                raise SystemExit("impossible de lire ce stream (lien faux, chaîne introuvable ou connexion coupée)")
            elif not veille:
                raise SystemExit("ce stream n'est pas en direct. Pour une rediffusion : onglet « Depuis un lien » "
                                 "(ou python -m clipper lien <lien>). Pour attendre son prochain live : la veille.")
            elif live is False and not made:
                log("la chaîne n'est pas en direct : veille (un essai par minute)")
            if pause(60):
                break
    except KeyboardInterrupt:
        log("arrêt demandé")
    log(f"{len(made)} clip(s) dans {Path(opts.sortie)}")
    return made


def _session(url: str, opts, inf: dict, stop_at: float, pause) -> list[Path]:
    """un live, du branchement à la fin du stream (ou à l'arrêt)"""
    streamer = opts.streamer or source.streamer_name(inf)
    plat = source.platform(url)
    work = Path(opts.sortie) / ".travail" / f"live-{slug(streamer, 30)}-{dt.datetime.now():%Y%m%d-%H%M%S}"
    work.mkdir(parents=True, exist_ok=True)
    out_dir = Path(opts.sortie)
    lock = getattr(opts, "verrou", None) or contextlib.nullcontext()  # un seul rendu à la fois dans l'interface
    live_chat = None
    if plat == "twitch" and not getattr(opts, "sans_chat", False):
        login = inf.get("uploader_id") or url.rstrip("/").split("/")[-1]
        live_chat = chat.TwitchLiveChat(login)
        live_chat.start()
    rec = Recorder(url, work)
    made: list[Path] = []
    try:
        if not rec.start():
            log("le flux ne répond pas")
            return made
        transcribe.load(opts.modele)
        left = (stop_at - time.monotonic()) / 60
        log(f"live de {streamer} : écoute " + (f"pendant {left:.0f} min" if left < 1e6 else "jusqu'à la fin du live"))
        pre, post = opts.duree * 0.72, opts.duree * 0.28
        loud: dict[int, float] = {}
        done: set[str] = set()
        last_end = -1e9
        best_layout = None
        fails = n = 0
        while True:
            if pause(10):
                log("arrêt de l'écoute")
                break
            if not rec.alive():
                live, _ = is_live(url)
                if live is False:
                    log("le live est terminé")
                    break
                fails += 1
                if fails > RETRIES:
                    log("le flux ne revient pas : arrêt de l'écoute")
                    break
                log("le flux a coupé : reconnexion")
                rec.start()
                continue
            segs = rec.segments()
            for p, a, b in segs:
                if p.name in done:
                    continue
                for i, v in enumerate(analyze.loudness(p)):
                    loud[int(a) + i] = float(v)
                done.add(p.name)
                fails = 0
            if len(loud) < 90:
                continue
            last = max(loud)
            # disque et mémoire bornés, qu'un clip sorte ou non
            rec.purge(segs, last - KEEP)
            for k in [k for k in loud if k < last - WINDOW]:
                del loud[k]
            if live_chat:
                live_chat.forget(rec.t0 + last - WINDOW)
            base = max(0, last - WINDOW + 1)  # la seconde de session du début de la fenêtre
            arr = np.array([loud.get(i, -60.0) for i in range(base, last + 1)], dtype=np.float32)
            rate = live_chat.rate(rec.t0 + base, len(arr)) if live_chat else None
            score = analyze.hype(arr, rate)
            # un pic récent, assez fort, avec la suite déjà enregistrée
            lo = max(int(max(last_end, 0.0) + post), last - 150, base + int(pre) + 5)
            hi = int(last - post - 3)
            if hi <= lo:
                continue
            p = lo + int(np.argmax(score[lo - base:hi - base]))
            s = float(score[p - base])
            if s < opts.seuil or s < score[max(0, p - base - 20):p - base + 10].max() - 1e-6:
                continue
            a, b = max(0.0, p - pre - 4), p + post + 4
            segs = [x for x in segs if x[0].exists()]
            if not segs or a < min(x[1] for x in segs):
                continue
            n += 1
            log(f"moment fort à {hms(p)} (hype {s:.2f}) : on fabrique le clip")
            try:
                with lock:
                    section = cut(segs, a, b, work / f"section_{p}.mp4")
                    wav = analyze.slice_wav(section, 0, b - a, work / f"section_{p}.wav")
                    ws, lang = transcribe.words(wav, opts.langue)
                    wav.unlink(missing_ok=True)
                    ws = [Word(w.start + a, w.end + a, w.text) for w in ws]
                    st, en = analyze.snap(ws, p, pre, post, a, b)
                    inside = [w for w in ws if st - 0.05 <= w.start and w.end <= en + 0.3]
                    # la même note qu'en rediffusion : ce qu'il dit compte, une cinématique passe derrière
                    m = Moment(p, st, en, s, analyze.text_bonus(inside, en - st), ws, lang,
                               analyze.letterboxed(source.frames_span(str(section), st - a, en - st)))
                    last_end = en
                    if m.score < opts.seuil:
                        log(f"  pas assez fort une fois écouté (score {m.score:.2f}"
                            f"{', cinématique' if m.cutscene else ''}), on passe")
                        section.unlink(missing_ok=True)
                        continue
                    layout = facecam.detect(section, opts.cam, st - a, en - st)
                    if best_layout is not None:  # la webcam ne bouge pas : on garde le cadre le plus sûr de la session
                        layout = facecam.consensus([best_layout, layout])[1]
                    if layout.kind == "split" and (best_layout is None or layout.conf > best_layout.conf):
                        best_layout = layout
                    words = _words_in(ws, st, en, st)
                    title = render.fill_title(opts.titre, streamer, opts.jeu) if opts.titre \
                        else render.auto_title(streamer, opts.jeu, analyze.mood(words), n - 1, opts.titre_langue)
                    base_name = f"{slug(streamer, 30)}_live_{dt.datetime.now():%Y%m%d_%H%M%S}"
                    made.append(write_clip(opts, out_dir, base_name, section, layout, words, st - a, en - st, title,
                                           streamer, {"source": url, "source_link": url, "score": m.score}))
            except RuntimeError as e:  # un clip raté n'arrête pas l'écoute
                last_end = max(last_end, float(p))
                log(f"  clip raté ({why(e)}), on continue")
    finally:
        rec.stop()
        if live_chat:
            live_chat.stop = True
        if not made:  # rien à garder de cette session
            shutil.rmtree(work, ignore_errors=True)
    return made
