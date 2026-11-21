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

import collections

RECENT: collections.deque = collections.deque(maxlen=50)  # dernières lignes du journal (fenêtre de l'appli sur Mac)
_children: list = []  # processus lancés pour durer (enregistreur d'un live) : arrêtés quand l'appli se ferme

_tls = threading.local()  # l'interface graphique y range la tâche en cours pour en afficher le journal


def log(*parts):
    msg = " ".join(str(p) for p in parts)
    RECENT.append(msg)
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


_job_handle = None  # gardé en vie tant que le programme tourne


def data_dir() -> Path:
    """dossier des données de l'appli (modèle de transcription, emojis) : %LOCALAPPDATA%\\gta-stream-clipper sous
    Windows, ~/Library/Application Support/GTA Stream Clipper sur Mac, ~/.local/share/gta-stream-clipper ailleurs"""
    import os
    if sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / "GTA Stream Clipper"
    elif os.environ.get("LOCALAPPDATA"):
        d = Path(os.environ["LOCALAPPDATA"]) / "gta-stream-clipper"
    else:
        d = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "gta-stream-clipper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def kill_children():
    """arrête les processus encore lancés par l'appli (à sa fermeture)"""
    for proc in list(_children):
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:  # noqa: BLE001
            pass


def die_together():
    """Windows : quand le programme s'arrête (fenêtre fermée, plantage), ffmpeg et yt-dlp s'arrêtent avec lui.
    Sans ça, l'enregistrement d'un live continuerait tout seul et remplirait le disque. On range le programme
    dans un « job » Windows réglé pour tuer tout son contenu à la fermeture."""
    global _job_handle
    if sys.platform != "win32" or _job_handle:
        return
    try:
        import ctypes
        from ctypes import wintypes

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOp", "WriteOp", "OtherOp", "ReadTr", "WriteTr", "OtherTr")]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.GetCurrentProcess.restype = wintypes.HANDLE
        job = k.CreateJobObjectW(None, None)
        if not job:
            return
        info = EXTENDED()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            _job_handle = job
            k.AssignProcessToJobObject(job, k.GetCurrentProcess())
    except Exception:  # noqa: BLE001 (un confort : sans lui, tout marche comme avant)
        pass


def adopt(proc):
    """range un processus qu'on vient de lancer (l'enregistreur d'un live) dans le même « job » : certains Python
    (celui du Microsoft Store) laissent leurs enfants en dehors, il faut donc le faire à la main"""
    _children[:] = [c for c in _children if c.poll() is None] + [proc]
    if not _job_handle:
        return
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.AssignProcessToJobObject(_job_handle, int(proc._handle))
    except Exception:  # noqa: BLE001
        pass


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
