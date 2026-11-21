"""Fabriquer le clip vertical : mise en page, titre cartoon qui rebondit, sous-titres 2-3 mots qui pop."""
from __future__ import annotations

import random
import re
import shutil
from pathlib import Path

from .analyze import Word
from .facecam import OUT_H, OUT_W, Layout
from .util import FONT_FILE, FONT_NAME, log, run

YELLOW = "&H0000D2FF&"   # #FFD200 (l'ASS écrit les couleurs en BGR)
WHITE = "&H00FFFFFF&"

TITRES = {
    "fr": {"rire": ["{s} EST MORT DE RIRE SUR {j}", "{s} PLEURE DE RIRE SUR {j}"],
           "rage": ["{s} PÈTE UN CÂBLE SUR {j}", "{s} DEVIENT FOU SUR {j}"],
           "defaut": ["{s} SE FOIRE SUR {j}", "{s} N'Y CROIT PAS SUR {j}", "{s} FAIT N'IMPORTE QUOI SUR {j}"]},
    "en": {"rire": ["{s} CAN'T STOP LAUGHING IN {j}", "{s} IS CRYING LAUGHING IN {j}"],
           "rage": ["{s} LOSES IT IN {j}", "{s} RAGES IN {j}"],
           "defaut": ["{s} FAILS IN {j}", "{s} CAN'T BELIEVE IT IN {j}", "{s} IS DONE WITH {j}"]},
}


def display_name(name: str) -> str:
    """« KaiCenat » → « KAI CENAT », « xQc » reste « XQC »"""
    parts = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).split()
    if len(parts) > 1 and all(len(p) >= 3 for p in parts):
        name = " ".join(parts)
    return re.sub(r"[_]+", " ", name).upper().strip()


def auto_title(streamer: str, jeu: str, mood: str, index: int, lang: str = "fr") -> str:
    choix = TITRES.get(lang, TITRES["fr"])[mood]
    return choix[index % len(choix)].format(s=display_name(streamer), j=jeu.upper())


# ------------------------------------------------------------------ ASS
def _ass_escape(t: str) -> str:
    return t.replace("\\", "").replace("{", "(").replace("}", ")")


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _lines(text: str, maxc: int) -> list[str]:
    words = text.split()
    if len(text) <= maxc or len(words) == 1:
        return [text]
    best = None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        k = max(len(a), len(b))
        if best is None or k < best[0]:
            best = (k, [a, b])
    if best[0] > maxc * 1.25 and len(words) > 3:  # trois lignes
        best3 = None
        for i in range(1, len(words) - 1):
            for j in range(i + 1, len(words)):
                ls = [" ".join(words[:i]), " ".join(words[i:j]), " ".join(words[j:])]
                k = max(map(len, ls))
                if best3 is None or k < best3[0]:
                    best3 = (k, ls)
        return best3[1]
    return best[1]


def clean_word(w: str) -> str:
    w = re.sub(r"[^\w'?!\-%$€]", "", w.upper(), flags=re.UNICODE)
    return w.strip("-")


def groups(words: list[Word], max_words=3, max_chars=14) -> list[list[Word]]:
    out, cur = [], []
    for i, w in enumerate(words):
        txt = clean_word(w.text)
        if not txt:
            continue
        w = Word(w.start, w.end, txt)
        if cur:
            n_chars = sum(len(x.text) + 1 for x in cur) + len(txt)
            gap = w.start - cur[-1].end
            long_word = any(len(x.text) > 8 for x in cur + [w])
            if (len(cur) >= (2 if long_word else max_words) or n_chars > max_chars or gap > 0.5
                    or re.search(r"[.?!,]$", words[i - 1].text.strip())):
                out.append(cur)
                cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def build_ass(path: Path, layout: Layout, words: list[Word], title: str, title_dur: float, clip_dur: float,
              streamer: str):
    seam = layout.seam_y
    title_y = seam if layout.kind == "split" else (560 if layout.kind == "jeu" else 1180)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OUT_W}
PlayResY: {OUT_H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{FONT_NAME},86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,7,5,5,30,30,0,1
Style: Titre,{FONT_NAME},100,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,10,8,5,30,30,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    # ---- titre : arrive de nulle part, rebondit, gigote, puis se replie
    if title and title_dur > 0:
        t = _ass_escape(title.upper()).strip()
        name = display_name(streamer)
        if name and t.startswith(name) and len(t) > len(name) + 3:
            # le nom seul sur la première ligne, en jaune ; la suite en blanc dessous
            rest = _lines(t[len(name):].strip(), 16)
            lines = [name] + rest
            txt = "{\\c" + YELLOW + "}" + name + "{\\c" + WHITE + "}\\N" + r"\N".join(rest)
        else:
            lines = _lines(t, 14)
            txt = r"\N".join(lines)
            if name and name in txt:
                txt = txt.replace(name, "{\\c" + YELLOW + "}" + name + "{\\c" + WHITE + "}", 1)
        size = int(min(112, 980 / (max(map(len, lines)) * 0.6)))
        d = int(title_dur * 1000)
        anim = (f"\\an5\\pos(540,{title_y})\\fs{size}\\fscx0\\fscy0\\frz-8"
                f"\\t(0,170,\\fscx124\\fscy124\\frz4)\\t(170,280,\\fscx90\\fscy90\\frz-2)"
                f"\\t(280,370,\\fscx107\\fscy107\\frz1)\\t(370,450,\\fscx100\\fscy100\\frz0)"
                f"\\t(450,900,\\frz2)\\t(900,1400,\\frz-2)\\t(1400,{max(1500, d - 260)},\\frz0)"
                f"\\t({d - 240},{d - 110},\\fscx114\\fscy114)\\t({d - 110},{d},\\fscx0\\fscy0)")
        ev.append(f"Dialogue: 2,{_ts(0)},{_ts(title_dur)},Titre,,0,0,0,,{{{anim}}}{txt}")
    # ---- sous-titres : 2-3 mots, le premier événement de chaque groupe fait « pop », le mot dit passe en jaune
    rnd = random.Random(7)
    cap_y = seam
    gs = groups([w for w in words if w.start >= title_dur - 0.05 and w.start < clip_dur])
    for k, g in enumerate(gs):
        rot = rnd.choice([-3, -2, 2, 3])
        g_end = min(clip_dur, g[-1].end + 0.6)
        if k + 1 < len(gs):  # jamais deux groupes à l'écran en même temps
            g_end = min(g_end, gs[k + 1][0].start - 0.04)
        for i, w in enumerate(g):
            st = w.start if i else max(w.start - 0.04, title_dur if title else 0)
            en = g[i + 1].start if i + 1 < len(g) else g_end
            if en - st < 0.04:
                continue
            body = " ".join(("{\\c" + YELLOW + "}" + x.text + "{\\c" + WHITE + "}") if j == i else x.text
                            for j, x in enumerate(g))
            tags = f"\\an5\\pos(540,{cap_y})\\frz{rot}"
            if i == 0:
                tags += "\\fscx45\\fscy45\\t(0,90,\\fscx114\\fscy114)\\t(90,170,\\fscx100\\fscy100)"
            ev.append(f"Dialogue: 1,{_ts(st)},{_ts(en)},Cap,,0,0,0,,{{{tags}}}{body}")
    path.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ ffmpeg
def filter_graph(L: Layout, sep: int) -> str:
    if L.kind == "split":
        cx, cy, cw, ch = L.cam
        gx, gy, gw, gh = L.game
        bot = OUT_H - L.top_h
        g = (f"[0:v]split=2[a][b];"
             f"[a]crop={cw}:{ch}:{cx}:{cy},scale={OUT_W}:{L.top_h}:flags=lanczos,setsar=1[top];"
             f"[b]crop={gw}:{gh}:{gx}:{gy},scale={OUT_W}:{bot}:flags=lanczos,setsar=1[bot];"
             f"[top][bot]vstack=inputs=2[st];")
        if sep:
            g += f"[st]drawbox=x=0:y={L.top_h - sep // 2}:w={OUT_W}:h={sep}:color=0xFFD200@1:t=fill[st2];"
            return g + "[st2]subtitles=clip.ass:fontsdir=fonts[v]"
        return g + "[st]subtitles=clip.ass:fontsdir=fonts[v]"
    if L.kind == "plein":
        cx, cy, cw, ch = L.cam
        return (f"[0:v]crop={cw}:{ch}:{cx}:{cy},scale={OUT_W}:{OUT_H}:flags=lanczos,setsar=1[st];"
                f"[st]subtitles=clip.ass:fontsdir=fonts[v]")
    return (f"[0:v]split=2[a][b];[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{OUT_H},boxblur=24:2,eq=brightness=-0.08[bg];[b]scale={OUT_W}:-2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[st];[st]subtitles=clip.ass:fontsdir=fonts[v]")


def render(section: Path, out: Path, layout: Layout, words: list[Word], t_in: float, dur: float,
           title: str, streamer: str, title_dur: float = 2.4, sep: int = 8, fps_max: float = 60.0):
    """`section` : extrait source ; le clip commence à `t_in` dans la section et dure `dur`.
    `words` : temps déjà ramenés au début du clip."""
    work = section.parent
    fonts = work / "fonts"
    fonts.mkdir(exist_ok=True)
    if not (fonts / FONT_FILE.name).exists():
        shutil.copy(FONT_FILE, fonts / FONT_FILE.name)
    build_ass(work / "clip.ass", layout, words, title, title_dur, dur, streamer)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t_in:.3f}", "-i", section.name,
           "-t", f"{dur:.3f}", "-filter_complex", filter_graph(layout, sep), "-map", "[v]", "-map", "0:a:0?",
           "-fpsmax", str(fps_max), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-movflags", "+faststart", str(out.resolve())]
    run(cmd, cwd=work)
    log(f"clip prêt : {out}")
    return out
