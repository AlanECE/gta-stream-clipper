"""Trouver les moments : le streameur crie plus fort que d'habitude, le chat s'emballe, il parle vite et réagit."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .util import run

SR = 8000
# il s'adresse à son public : là, c'est forcément lui qui parle (« bro », les personnages de GTA le disent aussi)
STREAMER_TALK = re.compile(r"\b(chat|y'?all|les gars)\b", re.I)


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Moment:
    peak: float
    start: float
    end: float
    hype: float
    bonus: float = 0.0
    words: list = field(default_factory=list)
    lang: str = "en"
    cutscene: bool = False

    @property
    def score(self):
        # le volume seul ne suffit pas (une cinématique est forte aussi) : ce qu'il dit compte davantage,
        # et une cinématique passe derrière (les paroles sont celles du jeu, pas du streameur)
        malus = 0.0
        if self.cutscene:  # sauf s'il parle à son chat pendant la cinématique : là, c'est bien lui
            malus = 0.4 if STREAMER_TALK.search(self.text_in) else 1.5
        return round(min(self.hype, 1.8) + 1.6 * self.bonus - malus, 2)

    @property
    def text(self):
        return " ".join(w.text for w in self.words)

    @property
    def text_in(self):
        return " ".join(w.text for w in self.words if self.start - 0.05 <= w.start and w.end <= self.end + 0.3)


def loudness(path: Path) -> np.ndarray:
    """volume en dB, une valeur par seconde"""
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                          "-f", "s16le", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    out, buf, step = [], b"", SR * 2
    while True:
        chunk = p.stdout.read(step * 60)
        if not chunk:
            break
        buf += chunk
        n = len(buf) // step
        if not n:
            continue
        a = np.frombuffer(buf[:n * step], np.int16).astype(np.float32).reshape(n, SR) / 32768
        buf = buf[n * step:]
        out.append(20 * np.log10(np.sqrt((a ** 2).mean(1)) + 1e-6))
    p.wait()
    return np.maximum(np.concatenate(out) if out else np.zeros(0, np.float32), -60)


def baseline(x: np.ndarray, win: int = 300, block: int = 15) -> np.ndarray:
    """niveau « normal » autour de chaque seconde (médiane glissante sur 5 min)"""
    n = len(x)
    nb = max(1, -(-n // block))
    blocks = np.array([np.median(x[i * block:(i + 1) * block]) for i in range(nb)])
    k = max(1, win // block) // 2
    base = np.array([np.median(blocks[max(0, i - k):i + k + 1]) for i in range(nb)])
    return np.repeat(base, block)[:n]


def smooth(x: np.ndarray, w: int) -> np.ndarray:
    return np.convolve(x, np.ones(w) / w, mode="same") if len(x) >= w else x


def hype(loud: np.ndarray, chat: np.ndarray | None = None, chat_lag: int = 6) -> np.ndarray:
    """score de hype par seconde : ~1 = moment fort, 2+ = énorme"""
    l = smooth(loud, 3) - baseline(loud)
    score = np.clip(l / 9.0, 0, 2.5)  # 9 dB au-dessus de son niveau normal = 1
    if chat is not None and len(chat):
        c = np.zeros_like(score)
        m = min(len(chat), len(score))
        c[:m] = chat[:m]
        c = np.concatenate([c[chat_lag:], np.zeros(chat_lag)])  # le chat réagit quelques secondes après
        c = smooth(c, 5)
        base = baseline(c) + 0.3
        score = score + np.clip((c / base - 1.0) / 1.5, 0, 2.5)
    return smooth(score, 3)


def peaks(score: np.ndarray, k: int, min_gap: int, margin: int = 0) -> list[tuple[int, float]]:
    s = score.copy()
    if margin:
        s[:margin] = 0
        s[len(s) - margin:] = 0
    res = []
    for _ in range(k):
        i = int(np.argmax(s))
        if s[i] <= 0.05:
            break
        res.append((i, float(score[i])))
        s[max(0, i - min_gap):i + min_gap] = -1
    return res


def slice_wav(audio: Path, start: float, dur: float, out: Path) -> Path:
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", audio, "-t", f"{dur:.3f}",
         "-ac", "1", "-ar", "16000", out])
    return out


def snap(words: list[Word], peak: float, pre: float, post: float, lo: float, hi: float) -> tuple[float, float]:
    """cale le début sur le début d'une phrase et la fin sur la fin d'une phrase"""
    st, en = peak - pre, peak + post
    starts = [w.start for i, w in enumerate(words)
              if st - 3 <= w.start <= st + 3 and (i == 0 or w.start - words[i - 1].end >= 0.35)]
    if starts:
        st = min(starts, key=lambda t: abs(t - st)) - 0.15
    ends = [w.end for i, w in enumerate(words)
            if en - 2 <= w.end <= en + 4 and (i == len(words) - 1 or words[i + 1].start - w.end >= 0.35)]
    if ends:
        en = min(ends, key=lambda t: abs(t - en)) + 0.35
    return max(lo, st), min(hi, en)


# des mots de streameur qui réagit (pas de dialogues de cinématique) : il parle à son chat, il jure, il crie
HYPE_WORDS = re.compile(
    r"\b(no way|bro+|bruh|chat|y'?all|dawg|yo+|nah+|hell no|hell nah|what the|wtf|fuck\w*|shit\w*|holy|"
    r"oh my god|omg|let'?s go+|oh no+|no no+|help|run+|(ha){2,}|lmao|lol|crazy|insane|dude|wait wait|why+|"
    r"putain|wesh|fr[eé]rot|mdr|ptdr|c'est quoi|oh la la|non non+)\b", re.I)


def text_bonus(words: list[Word], dur: float) -> float:
    txt = " ".join(w.text for w in words)
    hits = len(HYPE_WORDS.findall(txt))
    excl = min(0.2, 0.05 * (txt.count("!") + txt.count("?")))
    wps = len(words) / max(dur, 1.0)
    b = min(1.0, 0.12 * hits) + excl + (0.15 if wps > 2.8 else 0.0)
    if len(words) < 8:  # presque pas de parole : pas de sous-titres, moins intéressant
        b -= 0.5
    return round(b, 2)


def letterboxed(frames) -> bool:
    """cinématique : bandes noires en haut et en bas de l'image du jeu (on regarde la partie droite, là où il y a
    rarement la webcam ou le chat), sur au moins deux images sur trois"""
    hits = 0
    for g in frames:
        h, w = g.shape
        band = max(3, int(h * 0.03))  # les bandes des cinématiques de GTA font ~5 % de la hauteur
        cols = slice(int(w * 0.45), int(w * 0.95))
        top = np.percentile(g[1:band, cols], 80)
        bot = np.percentile(g[h - band:h - 1, cols], 80)
        mid = g[int(h * 0.3):int(h * 0.7), cols].mean()
        if top < 20 and bot < 20 and mid > 28:
            hits += 1
    return len(frames) >= 2 and hits >= max(2, int(len(frames) * 0.6))


LAUGH = re.compile(r"\b((ha){2,}|lmao|lol|laugh\w*|mdr|ptdr|dead)\b", re.I)
RAGE = re.compile(r"\b(fuck\w*|wtf|what the|shit|putain|no no|nah+|why+|bro+)\b", re.I)


def mood(words: list[Word]) -> str:
    txt = " ".join(w.text for w in words)
    if len(LAUGH.findall(txt)) >= 2:
        return "rire"
    if len(RAGE.findall(txt)) >= 2:
        return "rage"
    return "defaut"
