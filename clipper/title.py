"""Le titre façon texte TikTok : boîte blanche arrondie, texte noir, emojis en couleur. Dessiné image par image
(un « pop » à l'entrée), puis posé sur la vidéo par ffmpeg et gardé jusqu'à la fin du clip."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .util import ASSETS

TITLE_FONT = ASSETS / "fonts" / "Montserrat-Bold.ttf"
SS = 3  # suréchantillonnage : bords lisses


def _emoji_font_path() -> str | None:
    cands = {"win32": [r"C:\Windows\Fonts\seguiemj.ttf"],
             "darwin": ["/System/Library/Fonts/Apple Color Emoji.ttc"]}.get(sys.platform, [])
    cands += ["/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", "/usr/share/fonts/noto/NotoColorEmoji.ttf",
              "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf"]
    return next((c for c in cands if os.path.exists(c)), None)


def is_emoji(ch: str) -> bool:
    o = ord(ch)
    return o >= 0x1F000 or 0x2600 <= o <= 0x27BF or o in (0x2B50, 0x2B55, 0x203C, 0x2049)


def _clean(text: str) -> str:
    # sélecteurs de variante, liaisons et drapeaux (lettres régionales) : on les retire
    return "".join(ch for ch in text if ord(ch) not in (0xFE0F, 0x200D) and not 0x1F1E6 <= ord(ch) <= 0x1F1FF)


class _Emoji:
    def __init__(self):
        self.path = _emoji_font_path()
        self.cache: dict[tuple[str, int], Image.Image] = {}

    def glyph(self, ch: str, h: int) -> Image.Image | None:
        if not self.path:
            return None
        key = (ch, h)
        if key in self.cache:
            return self.cache[key]
        img = None
        for size in (109, 160, 96, 64, 137, 48):  # les polices bitmap n'acceptent que certaines tailles
            try:
                f = ImageFont.truetype(self.path, size)
                im = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
                ImageDraw.Draw(im).text((size // 2, size // 2), ch, font=f, embedded_color=True)
                bb = im.getbbox()
                if bb:
                    im = im.crop(bb)
                    img = im.resize((max(1, int(im.width * h / im.height)), h), Image.LANCZOS)
                    break
            except OSError:
                continue
        self.cache[key] = img
        return img


EMOJI = _Emoji()


def _runs(text: str):
    """découpe en morceaux texte / emoji"""
    out, cur = [], ""
    for ch in text:
        if is_emoji(ch):
            if cur:
                out.append(("t", cur))
                cur = ""
            out.append(("e", ch))
        else:
            cur += ch
    if cur:
        out.append(("t", cur))
    return out


def _width(text: str, font, eh: int) -> float:
    return sum(font.getlength(r) if k == "t" else (eh * 1.08 if EMOJI.path else 0) for k, r in _runs(text))


def _wrap(text: str, font, eh: int, max_w: float) -> list[str]:
    words = text.split()
    if _width(text, font, eh) <= max_w:
        return [text]
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if _width(t, font, eh) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) == 2:  # équilibre les deux lignes
        best = None
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            wa, wb = _width(a, font, eh), _width(b, font, eh)
            if max(wa, wb) <= max_w and (best is None or abs(wa - wb) < best[0]):
                best = (abs(wa - wb), [a, b])
        if best:
            lines = best[1]
    return lines


def render_title(text: str, size: int = 52, max_w: int = 860) -> Image.Image:
    """le titre fini, au repos (RGBA)"""
    text = _clean(text).strip()
    if not EMOJI.path:
        text = "".join(ch for ch in text if not is_emoji(ch)).strip()
    S = size * SS
    font = ImageFont.truetype(str(TITLE_FONT), S)
    eh = int(S * 0.95)
    lines = _wrap(text, font, eh, max_w * SS)
    asc, desc = font.getmetrics()
    lh = int(S * 1.30)
    padx, pady, r = int(S * 0.45), int(S * 0.16), int(S * 0.36)
    widths = [_width(l, font, eh) for l in lines]
    bw = int(max(widths) + 2 * padx)
    bh = int(lh * len(lines) + 2 * pady)
    m = int(S * 0.2)
    im = Image.new("RGBA", (bw + 2 * m, bh + 2 * m), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # une boîte par ligne, qui se touchent (comme le texte « fond blanc » de TikTok)
    for i, w in enumerate(widths):
        x0 = m + (bw - (w + 2 * padx)) / 2
        y0 = m + i * lh + (0 if i == 0 else 0)
        y1 = m + (i + 1) * lh + 2 * pady
        d.rounded_rectangle((x0, y0, x0 + w + 2 * padx, y1), radius=r, fill=(255, 255, 255, 255))
    for i, (line, w) in enumerate(zip(lines, widths)):
        x = m + (bw - w) / 2
        y = m + pady + i * lh + (lh - (asc + desc)) / 2
        for k, run in _runs(line):
            if k == "t":
                d.text((x, y), run, font=font, fill=(18, 18, 18, 255))
                x += font.getlength(run)
            else:
                g = EMOJI.glyph(run, eh)
                if g is not None:
                    im.alpha_composite(g, (int(x + eh * 0.04), int(y + (asc + desc - eh) / 2 + S * 0.02)))
                x += eh * 1.08
    return im.resize((im.width // SS, im.height // SS), Image.LANCZOS)


def _ease_pop(t: float) -> float:
    """0 → 1 avec un petit dépassement (rebond)"""
    c1, c3 = 2.2, 3.2
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def write_title_frames(text: str, out_dir: Path, fps: float, size: int = 52, pop: float = 0.32) -> tuple[Path, int, int]:
    """images du titre : l'entrée en « pop », puis la dernière image reste. Renvoie (motif, largeur, hauteur)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("t_*.png"):
        f.unlink()
    base = render_title(text, size)
    W, H = int(base.width * 1.16) // 2 * 2, int(base.height * 1.16) // 2 * 2
    n = max(2, int(round(pop * fps)))
    for i in range(n + 1):
        t = i / n
        s = max(0.05, 0.55 + 0.45 * _ease_pop(t))
        a = min(1.0, t / 0.35)
        im = base.resize((max(1, int(base.width * s)), max(1, int(base.height * s))), Image.LANCZOS)
        if a < 1:
            im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        canvas.alpha_composite(im, ((W - im.width) // 2, (H - im.height) // 2))
        canvas.save(out_dir / f"t_{i:03d}.png")
    return out_dir / "t_%03d.png", W, H
