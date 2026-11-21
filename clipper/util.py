"""Petits outils partagés : lancer ffmpeg / yt-dlp, lire les durées, convertir les temps."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path

PKG = Path(__file__).resolve().parent
ASSETS = PKG / "assets"
YUNET = ASSETS / "models" / "face_detection_yunet_2023mar.onnx"

_tls = threading.local()  # l'interface graphique y range la tâche en cours pour en afficher le journal


def log(*parts):
    msg = " ".join(str(p) for p in parts)
    try:
        print("»", msg, flush=True)
    except Exception:
        pass
    job = getattr(_tls, "job", None)
    if job is not None:
        job.lines.append(msg)


def same_job(fn):
    """pour lancer `fn` dans un autre fil sans perdre le journal du travail en cours (interface graphique)"""
    job = getattr(_tls, "job", None)

    def wrap(*a, **k):
        _tls.job = job
        return fn(*a, **k)
    return wrap


def need(*tools):
    for tool in tools:
        if not shutil.which(tool):
            sys.exit(f"{tool} est introuvable. Installe FFmpeg (Windows : winget install Gyan.FFmpeg, "
                     f"Mac : brew install ffmpeg, Linux : apt install ffmpeg) puis rouvre ton terminal.")


def run(cmd, cwd=None, check=True):
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"la commande a échoué : {' '.join(map(str, cmd[:5]))} …\n{(r.stderr or '')[-1500:]}")
    return r


def why(e: Exception) -> str:
    """la raison d'un échec en une phrase (yt-dlp et ffmpeg sont bavards)"""
    txt = str(e)
    low = txt.lower()
    if "subscriber-only" in low or "must be logged" in low:
        return "réservé aux abonnés de la chaîne"
    if "does not exist" in low or "404" in low or "not found" in low:
        return "supprimé ou introuvable"
    if "private" in low:
        return "privé"
    if "offline" in low or "not currently live" in low:
        return "la chaîne n'est pas en direct"
    for ln in reversed(txt.splitlines()):
        if "ERROR" in ln:
            return ln.split("ERROR:")[-1].strip()[:160]
    return (txt.strip().splitlines() or ["erreur inconnue"])[-1][:160]


def ytdlp(*args, check=True):
    return run([sys.executable, "-m", "yt_dlp", "--no-warnings", *args], check=check)


def probe(path) -> dict:
    return json.loads(run(["ffprobe", "-v", "error", "-print_format", "json",
                           "-show_format", "-show_streams", path]).stdout)


def video_info(path) -> tuple[int, int, float, float]:
    """largeur, hauteur, images/s, durée"""
    p = probe(path)
    v = next(s for s in p["streams"] if s["codec_type"] == "video")
    num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    return int(v["width"]), int(v["height"]), fps, float(p["format"].get("duration") or 0)


def parse_time(s) -> float | None:
    """« 1:02:03 », « 62:03 », « 3723 », « 1h02m03s » → secondes"""
    if s is None or s == "":
        return None
    s = str(s).strip().lower()
    m = re.fullmatch(r"(?:(\d+)h)?\s*(?:(\d+)m(?:in)?)?\s*(?:(\d+(?:\.\d+)?)s)?", s)
    if m and any(m.groups()):
        h, mi, se = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(se or 0)
    parts = [float(x) for x in s.split(":")]
    t = 0.0
    for x in parts:
        t = t * 60 + x
    return t


def hms(t: float, sep=":") -> str:
    t = int(round(t))
    return f"{t // 3600}{sep}{t % 3600 // 60:02d}{sep}{t % 60:02d}"


def twitch_t(t: float) -> str:
    t = int(t)
    return f"{t // 3600}h{t % 3600 // 60}m{t % 60}s"


def slug(s: str, n=40) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:n] or "clip"


def even(x) -> int:
    return int(round(x / 2)) * 2
