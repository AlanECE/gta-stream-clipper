"""Récupérer les streams : infos, audio de la rediffusion, extraits vidéo précis, liste des rediffusions d'une chaîne."""
from __future__ import annotations

import json
import re
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .util import log, run, ytdlp

VIDEO_FMT = "best[height<=1080][vcodec!=none][acodec!=none]/bv*[height<=1080]+ba/best"
AUDIO_FMT = "Audio_Only/bestaudio/worst"


def normalize(target: str) -> str:
    """« kaicenat » → lien Twitch ; un lien ou un fichier reste tel quel"""
    t = target.strip().split("#")[0]
    if Path(t).exists():
        return str(Path(t).resolve())
    if t.lower().startswith("kick:"):  # « kick:jolavanille » → chaîne Kick
        return f"https://kick.com/{t[5:].strip()}"
    if "://" not in t and "." not in t and "/" not in t:
        return f"https://www.twitch.tv/{t}"
    if not t.startswith("http"):
        return "https://" + t
    return t


def is_local(url: str) -> bool:
    return Path(url).exists()


def platform(url: str) -> str:
    if is_local(url):
        return "fichier"
    for p in ("twitch", "youtube", "youtu.be", "kick"):
        if p in url:
            return "youtube" if p == "youtu.be" else p
    return "autre"


def info(url: str) -> dict:
    if is_local(url):
        from .util import video_info
        w, h, fps, dur = video_info(url)
        return {"id": Path(url).stem, "title": Path(url).stem, "duration": dur, "is_live": False,
                "uploader": None, "webpage_url": url, "extractor_key": "fichier"}
    return json.loads(ytdlp("-J", "--no-playlist", url).stdout)


def streamer_name(inf: dict) -> str:
    return (inf.get("uploader") or inf.get("channel") or inf.get("uploader_id") or "STREAMER").strip()


def twitch_vod_id(url: str, inf: dict | None = None) -> str | None:
    m = re.search(r"twitch\.tv/videos/(\d+)", url)
    if m:
        return m.group(1)
    if inf and str(inf.get("id", "")).startswith("v") and "twitch" in url:
        return str(inf["id"])[1:]
    return None


def media_urls(url: str, audio=False) -> list[str]:
    if is_local(url):
        return [url]
    out = ytdlp("-g", "-f", AUDIO_FMT if audio else VIDEO_FMT, "--no-playlist", url).stdout
    urls = [x.strip() for x in out.splitlines() if x.strip().startswith("http")]
    if not urls:
        raise RuntimeError("impossible de récupérer le flux (stream privé, réservé aux abonnés ou supprimé ?)")
    return urls


AUDIO_SR = 16000   # ce que Whisper attend
AUDIO_CHUNK = 300  # secondes par morceau : les morceaux se téléchargent en même temps


def get_audio(url: str, work: Path, start: float, end: float, full: bool = False) -> Path:
    """Son seul de la plage [start, end], en WAV mono. Le t=0 du fichier correspond au temps `start` du stream.

    La plage est coupée en morceaux de 5 minutes téléchargés en parallèle (bien plus vite qu'à la suite), puis
    recollés à l'échantillon près : un morceau trop court (trou dans le flux) est complété par du silence, pour que
    les temps restent justes jusqu'au bout."""
    out = work / f"audio_{int(start)}_{int(end)}.wav"  # une plage = un fichier (sinon on relirait une autre plage)
    if out.exists() and out.stat().st_size > 10_000:
        return out
    src = url if is_local(url) else media_urls(url, audio=True)[0]
    total = max(1.0, end - start)
    spans = [(start + i * AUDIO_CHUNK, min(AUDIO_CHUNK, total - i * AUDIO_CHUNK))
             for i in range(int((total - 1e-6) // AUDIO_CHUNK) + 1)]

    def part(k: int) -> Path:
        t, d = spans[k]
        f = work / f"audio_part_{int(start)}_{k}.pcm"
        for _ in range(3):
            r = run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", src, "-t", f"{d:.3f}", "-vn", "-ac", "1",
                     "-ar", str(AUDIO_SR), "-f", "s16le", f], check=False)
            if r.returncode == 0 and f.exists() and f.stat().st_size > 0:
                break
        return f

    with ThreadPoolExecutor(4 if is_local(url) else 12) as ex:
        parts = list(ex.map(part, range(len(spans))))
    tmp, size, got_any = out.with_suffix(".tmp"), 0, False
    with open(tmp, "wb") as w:
        w.write(b"\0" * 44)
        for f, (_, d) in zip(parts, spans):
            want, got = int(round(d * AUDIO_SR)) * 2, 0
            if f.exists():
                with open(f, "rb") as r:
                    while got < want:
                        chunk = r.read(min(1 << 20, want - got))
                        if not chunk:
                            break
                        w.write(chunk)
                        got += len(chunk)
                f.unlink(missing_ok=True)
                got_any = got_any or got > 0
            if got < want:
                w.write(b"\0" * (want - got))
            size += want
        w.seek(0)
        w.write(b"RIFF" + struct.pack("<I", 36 + size) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, AUDIO_SR,
                                                                                     AUDIO_SR * 2, 2, 16)
                + b"data" + struct.pack("<I", size))
    if not got_any:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("impossible de lire le son de ce stream (plage hors de la vidéo, ou flux indisponible)")
    tmp.replace(out)
    return out


def grab(url: str, out: Path, start: float, dur: float) -> Path:
    """Extrait vidéo précis : le t=0 de `out` correspond exactement au temps `start` du stream."""
    urls = media_urls(url)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for u in urls[:2]:
        cmd += ["-ss", f"{max(0.0, start):.3f}", "-i", u]
    cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-map", "0:v:0", "-map", "1:a:0"] if len(urls) > 1 else ["-map", "0:v:0", "-map", "0:a:0?"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", out]
    for essai in range(2):
        try:
            run(cmd)
            return out
        except RuntimeError:
            if essai:
                raise
            log("le flux a coupé, nouvel essai…")
    return out


def fetch(url: str, out: Path, dur: float = 60.0) -> Path:
    """Un clip (Twitch…) tel quel : c'est déjà un MP4 complet, on le copie sans le réencoder."""
    urls = media_urls(url)
    if len(urls) == 1:
        try:
            run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", urls[0], "-map", "0:v:0", "-map", "0:a:0?",
                 "-c", "copy", out])
            if out.exists() and out.stat().st_size > 50_000:
                return out
        except RuntimeError:
            pass
    return grab(url, out, 0.0, dur + 1.0)


def low_video_url(url: str) -> str | None:
    """le flux vidéo le plus léger (160p sur Twitch) : assez pour regarder quelques images"""
    if is_local(url):
        return url
    try:
        out = ytdlp("-g", "-f", "worst[height>=144][vcodec!=none]/worst", "--no-playlist", url).stdout
        return next((x.strip() for x in out.splitlines() if x.strip().startswith("http")), None)
    except RuntimeError:
        return None


def frames_span(src: str, start: float, dur: float, n: int = 3, w: int = 256, h: int = 144) -> list:
    """n petites images en niveaux de gris réparties sur [start, start + dur], en une seule lecture du flux"""
    import subprocess

    import numpy as np
    a, d = max(0.0, start + 0.2 * dur), max(1.0, 0.75 * dur)
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a:.2f}", "-t", f"{d:.2f}", "-i", src, "-an",
                        "-vf", f"fps={n / d:.5f},scale={w}:{h}", "-frames:v", str(n), "-f", "rawvideo",
                        "-pix_fmt", "gray", "-"], capture_output=True, timeout=120)
    k = len(r.stdout) // (w * h)
    return [np.frombuffer(r.stdout[i * w * h:(i + 1) * w * h], np.uint8).reshape(h, w) for i in range(k)]


def channel_vods(channel: str, n: int = 10) -> list[dict]:
    """Dernières rediffusions d'une chaîne Twitch (ou vidéos d'une chaîne YouTube)"""
    c = normalize(channel)
    if "twitch.tv" in c and "/videos" not in c:
        c = c.rstrip("/") + "/videos?filter=archives&sort=time"
    elif ("youtube.com/@" in c or "youtube.com/channel" in c) and "/streams" not in c:
        c = c.rstrip("/") + "/streams"
    elif "kick.com" in c and "/videos" not in c:
        c = c.rstrip("/") + "/videos"
    r = ytdlp("--flat-playlist", "--playlist-end", str(n), "-J", c)
    entries = json.loads(r.stdout).get("entries") or []
    out = []
    for e in entries:
        u = (e.get("url") or e.get("webpage_url") or "").split("#")[0]
        if u and not u.startswith("http"):
            u = f"https://www.youtube.com/watch?v={u}" if "youtube" in c else u
        out.append({"url": u, "title": e.get("title") or "", "duration": e.get("duration"),
                    "live": e.get("live_status") == "is_live"})
    return out
