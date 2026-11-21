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
    return o >= 0x1F000 or 0x2600 <= o <= 0x27BF or o in (0x2B50, 0x2B55, 0x203C, 0x2049, 0x2122, 0x2139)


def _is_regional(ch: str) -> bool:
    return 0x1F1E6 <= ord(ch) <= 0x1F1FF


def _is_skin(ch: str) -> bool:
    return 0x1F3FB <= ord(ch) <= 0x1F3FF


def _clean(text: str) -> str:
    return text.replace("​", "")


def cache_dir() -> Path:
    from .util import data_dir
    d = data_dir() / "emoji-apple"
    d.mkdir(parents=True, exist_ok=True)
    return d


APPLE_CDN = "https://cdn.jsdelivr.net/npm/emoji-datasource-apple@15.1.2/img/apple/64/{}.png"


class _Emoji:
    """Emojis Apple (téléchargés une fois depuis le paquet public emoji-datasource-apple, puis gardés en cache ;
    rien n'est fourni dans le dépôt). Sans connexion : la police d'emojis du système."""

    def __init__(self):
        self.path = _emoji_font_path()
        self.cache: dict[tuple[str, int], Image.Image | None] = {}

    @property
    def available(self) -> bool:
        return True

    def _apple(self, seq: str) -> Image.Image | None:
        import urllib.request
        names = ["-".join(f"{ord(c):x}" for c in seq)]
        names.append("-".join(f"{ord(c):x}" for c in seq if ord(c) != 0xFE0F))
        if "️" not in seq and len(seq) == 1:
            names.append(f"{ord(seq):x}-fe0f")
        for n in dict.fromkeys(names):
            f = cache_dir() / f"{n}.png"
            if not f.exists():
                try:
                    data = urllib.request.urlopen(APPLE_CDN.format(n), timeout=8).read()
                    if data[:4] != b"\x89PNG":
                        continue
                    f.write_bytes(data)
                except Exception:
                    continue
            try:
                return Image.open(f).convert("RGBA")
            except Exception:
                continue
        return None

    def _system(self, seq: str) -> Image.Image | None:
        if not self.path:
            return None
        for size in (109, 160, 96, 64, 137, 48):  # les polices bitmap n'acceptent que certaines tailles
            try:
                f = ImageFont.truetype(self.path, size)
                im = Image.new("RGBA", (size * 3, size * 2), (0, 0, 0, 0))
                ImageDraw.Draw(im).text((size // 2, size // 2), seq, font=f, embedded_color=True)
                bb = im.getbbox()
                if bb:
                    return im.crop(bb)
            except OSError:
                continue
        return None

    def glyph(self, seq: str, h: int) -> Image.Image | None:
        key = (seq, h)
        if key not in self.cache:
            im = self._apple(seq) or self._system(seq)
            self.cache[key] = im.resize((max(1, int(im.width * h / im.height)), h), Image.LANCZOS) if im else None
        return self.cache[key]


EMOJI = _Emoji()


def _runs(text: str):
    """découpe en morceaux texte / emoji (un emoji peut faire plusieurs caractères : drapeaux, teintes, ZWJ)"""
    out, cur, i = [], "", 0
    while i < len(text):
        ch = text[i]
        if is_emoji(ch) or _is_regional(ch):
            if cur:
                out.append(("t", cur))
                cur = ""
            seq = ch
            i += 1
            if _is_regional(ch) and i < len(text) and _is_regional(text[i]):
                seq += text[i]
                i += 1
            while i < len(text):
                c = text[i]
                if c == "️" or _is_skin(c) or 0xE0020 <= ord(c) <= 0xE007F:
                    seq += c
                    i += 1
                elif c == "‍" and i + 1 < len(text):
                    seq += c + text[i + 1]
                    i += 2
                else:
                    break
            out.append(("e", seq))
        elif ch == "️":
            i += 1
        else:
            cur += ch
            i += 1
    if cur:
        out.append(("t", cur))
    return out


def _width(text: str, font, eh: int) -> float:
    return sum(font.getlength(r) if k == "t" else eh * 1.08 for k, r in _runs(text))


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
