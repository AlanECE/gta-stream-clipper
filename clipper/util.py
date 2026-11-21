"""Petits outils partagés : lancer ffmpeg / yt-dlp, lire les durées, convertir les temps."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

PKG = Path(__file__).resolve().parent
ASSETS = PKG / "assets"
FONT_FILE = ASSETS / "fonts" / "LuckiestGuy-Regular.ttf"
FONT_NAME = "Luckiest Guy"
YUNET = ASSETS / "models" / "face_detection_yunet_2023mar.onnx"


def log(*parts):
    print("»", *parts, flush=True)


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
