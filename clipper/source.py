"""Récupérer les streams : infos, audio de la rediffusion, extraits vidéo précis, liste des rediffusions d'une chaîne."""
from __future__ import annotations

import json
import re
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


def get_audio(url: str, work: Path, start: float, end: float, full: bool) -> Path:
    """Audio seul de la rediffusion. Le t=0 du fichier correspond au temps `start` du stream."""
    out = work / f"audio_{int(start)}_{int(end)}.ogg"  # une plage = un fichier (sinon on relirait une autre plage)
    if out.exists() and out.stat().st_size > 10_000:
        return out
    if is_local(url):
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", url, "-t", f"{end - start:.3f}",
             "-vn", "-ac", "1", "-c:a", "libopus", "-b:a", "32k", out])
        return out
    if full:
        # rediffusion entière : le téléchargeur de yt-dlp va beaucoup plus vite (fragments en parallèle)
        ytdlp("-f", AUDIO_FMT, "-N", "16", "--no-playlist", "--no-part", "-o", str(work / "audio_src.%(ext)s"), url)
        src = next(p for p in work.glob("audio_src.*"))
        run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-ac", "1", "-c:a", "libopus", "-b:a", "32k", out])
        src.unlink(missing_ok=True)
        return out
    # une plage : ffmpeg coupe à la seconde près (yt-dlp, lui, coupe sur une image clé)
    u = media_urls(url, audio=True)[0]
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", u, "-t", f"{end - start:.3f}",
         "-vn", "-ac", "1", "-c:a", "libopus", "-b:a", "32k", out])
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


def low_video_url(url: str) -> str | None:
    """le flux vidéo le plus léger (160p sur Twitch) : assez pour regarder quelques images"""
    if is_local(url):
        return url
    try:
        out = ytdlp("-g", "-f", "worst[height>=144][vcodec!=none]/worst", "--no-playlist", url).stdout
        return next((x.strip() for x in out.splitlines() if x.strip().startswith("http")), None)
    except RuntimeError:
        return None


def frames_at(src: str, times: list[float], w: int = 256, h: int = 144) -> list:
    """quelques images en niveaux de gris, petites, aux temps donnés"""
    import numpy as np
    import subprocess
    out = []
    for t in times:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", src, "-frames:v", "1",
                            "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                           capture_output=True, timeout=60)
        if len(r.stdout) == w * h:
            out.append(np.frombuffer(r.stdout, np.uint8).reshape(h, w))
    return out


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
