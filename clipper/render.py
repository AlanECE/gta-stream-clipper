"""Fabriquer le clip vertical : webcam en haut, gameplay en bas, titre façon TikTok posé sur la jonction,
sous-titres mot par mot (ou 2 par 2) avec le mot dit surligné."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from PIL import ImageFont

from . import title as title_mod
from .analyze import Word
from .facecam import OUT_H, OUT_W, Layout
from .util import ASSETS, log, run, video_info

SUB_FONT_FILE = ASSETS / "fonts" / "Montserrat-ExtraBold.ttf"
SUB_FONT_NAME = "Montserrat ExtraBold"
WIN_RATIO = 1.562   # (usWinAscent + usWinDescent) / unitsPerEm de Montserrat : libass dimensionne la police là-dessus
# styles de sous-titres : couleur du texte, couleur du mot dit, boîte derrière le mot dit (None = pas de boîte)
STYLES = {
    "jaune":          {"texte": "FFFFFF", "mot": "FFD200", "boite": None},
    "tout-jaune":     {"texte": "FFD200", "mot": "FFD200", "boite": None},
    "blanc":          {"texte": "FFFFFF", "mot": "FFFFFF", "boite": None},
    "boite-jaune":    {"texte": "FFFFFF", "mot": "111111", "boite": "FFD200"},
    "boite-violette": {"texte": "FFFFFF", "mot": "FFFFFF", "boite": "7B2FF7"},
    "boite-rouge":    {"texte": "FFFFFF", "mot": "FFFFFF", "boite": "FF2D55"},
    "boite-verte":    {"texte": "FFFFFF", "mot": "FFFFFF", "boite": "1DB954"},
}
DEFAULT_STYLE = "jaune"
ALIASES = {"violet": "boite-violette", "rouge": "boite-rouge", "vert": "boite-verte", "bleu": "boite-violette",
           "orange": "boite-jaune"}


def style_spec(name: str | None) -> dict:
    name = (name or DEFAULT_STYLE).strip().lower()
    name = ALIASES.get(name, name)
    if name in STYLES:
        return STYLES[name]
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", name):  # une couleur à soi : boîte de cette couleur
        return {"texte": "FFFFFF", "mot": "FFFFFF", "boite": name.lstrip("#").upper()}
    return STYLES[DEFAULT_STYLE]


def _ass(hex6: str) -> str:
    return f"&H00{hex6[4:6]}{hex6[2:4]}{hex6[0:2]}&"

TITRES = {
    "fr": {"rire": ["{s} est mort de rire sur {j} 😭", "{s} pleure de rire sur {j} 😂"],
           "rage": ["{s} pète un câble sur {j} 💀", "{s} devient fou sur {j} 😭"],
           "defaut": ["{s} se foire sur {j} 💀", "{s} n'y croit pas sur {j} 😳", "{s} fait n'importe quoi sur {j} 😂"]},
    "en": {"rire": ["{s} can't stop laughing in {j} 😭", "{s} is crying laughing in {j} 😂"],
           "rage": ["{s} loses it in {j} 💀", "{s} rages in {j} 😭"],
           "defaut": ["{s} fails in {j} 💀", "{s} can't believe it in {j} 😳", "{s} is done with {j} 😂"]},
}


def display_name(name: str) -> str:
    """« KaiCenat » → « Kai Cenat », « jolavanille » → « Jolavanille », « xQc » reste « xQc »"""
    name = re.sub(r"[_]+", " ", name).strip()
    parts = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).split()
    if len(parts) > 1 and all(len(p) >= 3 for p in parts):
        return " ".join(p[:1].upper() + p[1:] for p in parts)
    return name[:1].upper() + name[1:] if name.islower() else name


def auto_title(streamer: str, jeu: str, mood: str, index: int, lang: str = "fr") -> str:
    choix = TITRES.get(lang, TITRES["fr"])[mood]
    return choix[index % len(choix)].format(s=display_name(streamer), j=jeu)


def fill_title(t: str, streamer: str, jeu: str) -> str:
    return t.replace("{streamer}", display_name(streamer)).replace("{jeu}", jeu)


# ------------------------------------------------------------------ sous-titres (ASS)
def _ts(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def clean_word(w: str) -> str:
    w = re.sub(r"[^\w'?!\-%$€]", "", w.upper(), flags=re.UNICODE)
    return w.strip("-")


def merge_elisions(words: list[Word]) -> list[Word]:
    """Whisper coupe « c'est » en « c' » + « est » (ou « c » + « 'est ») : on recolle"""
    out: list[Word] = []
    for w in words:
        t = w.text.strip().replace("’", "'")
        if out and (t.startswith("'") or out[-1].text.endswith("'")):
            p = out[-1]
            out[-1] = Word(p.start, w.end, p.text + t)
        else:
            out.append(Word(w.start, w.end, t))
    return out


def groups(words: list[Word], max_words=2, max_chars=16) -> list[list[Word]]:
    words = merge_elisions(words)
    out, cur = [], []
    for i, w in enumerate(words):
        txt = clean_word(w.text)
        if not txt:
            continue
        w = Word(w.start, w.end, txt)
        if cur:
            n_chars = sum(len(x.text) + 1 for x in cur) + len(txt)
            gap = w.start - cur[-1].end
            if (len(cur) >= max_words or n_chars > max_chars or gap > 0.5
                    or re.search(r"[.?!,]$", words[i - 1].text.strip())):
                out.append(cur)
                cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def _rrect(w: float, h: float, r: float) -> str:
    """rectangle arrondi en dessin ASS (coin en courbe de Bézier)"""
    k = 0.5523 * r
    p = [("m", r, 0), ("l", w - r, 0), ("b", w - r + k, 0, w, r - k, w, r), ("l", w, h - r),
         ("b", w, h - r + k, w - r + k, h, w - r, h), ("l", r, h), ("b", r - k, h, 0, h - r + k, 0, h - r),
         ("l", 0, r), ("b", 0, r - k, r - k, 0, r, 0)]
    return " ".join(c[0] + " " + " ".join(str(int(round(v))) for v in c[1:]) for c in p)


def build_ass(path: Path, words: list[Word], clip_dur: float, y: int, max_words: int = 2,
              highlight: str = DEFAULT_STYLE, em: int = 60):
    F = int(round(em * WIN_RATIO))
    font = ImageFont.truetype(str(SUB_FONT_FILE), em)
    space = font.getlength(" ")
    cap = em * 0.70
    padx, pady = em * 0.22, em * 0.26
    box_h = cap + 2 * pady
    spec = style_spec(highlight)
    ass_box = _ass(spec["boite"]) if spec["boite"] else None
    c_text, c_word = _ass(spec["texte"]), _ass(spec["mot"])
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OUT_W}
PlayResY: {OUT_H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Mot,{SUB_FONT_NAME},{F},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,5,2,5,0,0,0,1
Style: Boite,{SUB_FONT_NAME},{F},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    gs = groups([w for w in words if w.start < clip_dur], max_words=max_words)
    pop = "\\t(0,70,\\fscx114\\fscy114)\\t(70,150,\\fscx100\\fscy100)"
    for k, g in enumerate(gs):
        g_end = min(clip_dur, g[-1].end + 0.5)
        if k + 1 < len(gs):  # jamais deux groupes à l'écran en même temps
            g_end = min(g_end, gs[k + 1][0].start - 0.03)
        widths = [font.getlength(x.text) for x in g]
        total = sum(widths) + space * (len(g) - 1)
        centers, x = [], OUT_W / 2 - total / 2
        for wd in widths:
            centers.append(x + wd / 2)
            x += wd + space
        for i, w in enumerate(g):
            st = w.start - (0.04 if i == 0 else 0)
            en = g[i + 1].start if i + 1 < len(g) else g_end
            if en - st < 0.04:
                continue
            for j, x2 in enumerate(g):
                active = j == i
                tags = f"\\an5\\pos({centers[j]:.0f},{y})"
                if active and ass_box:
                    ev.append(f"Dialogue: 1,{_ts(st)},{_ts(en)},Boite,,0,0,0,,{{{tags}\\1c{ass_box}\\p1{pop}}}"
                              f"{_rrect(widths[j] + 2 * padx, box_h, box_h * 0.3)}{{\\p0}}")
                    bord = "\\bord0" if spec["mot"] == "111111" else "\\bord3"
                    ev.append(f"Dialogue: 2,{_ts(st)},{_ts(en)},Mot,,0,0,0,,{{{tags}\\1c{c_word}{bord}\\shad0{pop}}}"
                              f"{x2.text}")
                elif active:
                    ev.append(f"Dialogue: 2,{_ts(st)},{_ts(en)},Mot,,0,0,0,,{{{tags}\\1c{c_word}{pop}}}{x2.text}")
                else:
                    ev.append(f"Dialogue: 2,{_ts(st)},{_ts(en)},Mot,,0,0,0,,{{{tags}\\1c{c_text}}}{x2.text}")
    path.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ ffmpeg
def positions(L: Layout, sub_y: float | None) -> tuple[int, int]:
    """(centre vertical du titre, ligne des sous-titres)"""
    if L.kind == "split":
        return L.top_h, int(OUT_H * (sub_y or 0.68))
    if L.kind == "plein":
        return int(OUT_H * 0.30), int(OUT_H * (sub_y or 0.68))
    return int((OUT_H - OUT_W * 9 / 16) / 2 - 110), int(OUT_H * (sub_y or 0.70))


def filter_graph(L: Layout, sep: int, title_xy: tuple[int, int] | None) -> str:
    if L.kind == "split":
        cx, cy, cw, ch = L.cam
        gx, gy, gw, gh = L.game
        bot = OUT_H - L.top_h
        g = (f"[0:v]split=2[a][b];"
             f"[a]crop={cw}:{ch}:{cx}:{cy},scale={OUT_W}:{L.top_h}:flags=lanczos,setsar=1[top];"
             f"[b]crop={gw}:{gh}:{gx}:{gy},scale={OUT_W}:{bot}:flags=lanczos,setsar=1[bot];"
             f"[top][bot]vstack=inputs=2[s0];")
        if sep:
            g += f"[s0]drawbox=x=0:y={L.top_h - sep // 2}:w={OUT_W}:h={sep}:color=0xFFD200@1:t=fill[s1];"
        else:
            g += "[s0]null[s1];"
    elif L.kind == "plein":
        cx, cy, cw, ch = L.cam
        g = f"[0:v]crop={cw}:{ch}:{cx}:{cy},scale={OUT_W}:{OUT_H}:flags=lanczos,setsar=1[s1];"
    else:
        g = (f"[0:v]split=2[a][b];[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
             f"crop={OUT_W}:{OUT_H},boxblur=24:2,eq=brightness=-0.08[bg];[b]scale={OUT_W}:-2[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[s1];")
    if title_xy:
        g += f"[s1][1:v]overlay=x={title_xy[0]}:y={title_xy[1]}:eof_action=repeat:format=auto[s2];"
    else:
        g += "[s1]null[s2];"
    return g + "[s2]subtitles=clip.ass:fontsdir=fonts[v]"


def render(section: Path, out: Path, layout: Layout, words: list[Word], t_in: float, dur: float,
           title: str, streamer: str = "", sep: int = 0, max_words: int = 2, highlight: str = DEFAULT_STYLE,
           sub_y: float | None = None, fps_max: float = 60.0):
    """`section` : extrait source ; le clip commence à `t_in` dans la section et dure `dur`.
    `words` : temps déjà ramenés au début du clip."""
    work = section.parent
    fonts = work / "fonts"
    fonts.mkdir(exist_ok=True)
    if not (fonts / SUB_FONT_FILE.name).exists():
        shutil.copy(SUB_FONT_FILE, fonts / SUB_FONT_FILE.name)
    _, _, fps, _ = video_info(section)
    fps = min(fps or 30.0, fps_max)
    title_y, sub_line = positions(layout, sub_y)
    build_ass(work / "clip.ass", words, dur, sub_line, max_words=max_words, highlight=highlight)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t_in:.3f}", "-i", section.name]
    title_xy = None
    if title:
        pattern, tw, th = title_mod.write_title_frames(title, work / "titre", fps)
        cmd += ["-framerate", f"{fps:g}", "-i", str(pattern.relative_to(work)).replace("\\", "/")]
        title_xy = ((OUT_W - tw) // 2, title_y - th // 2)
    cmd += ["-t", f"{dur:.3f}", "-filter_complex", filter_graph(layout, sep, title_xy), "-map", "[v]",
            "-map", "0:a:0?", "-r", f"{fps:g}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-movflags", "+faststart", str(out.resolve())]
    run(cmd, cwd=work)
    log(f"clip prêt : {out}")
    return out
