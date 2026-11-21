"""Trouver la webcam du streameur et décider de la mise en page.

La webcam, c'est un visage qui reste au même endroit pendant que le jeu bouge. Autour de lui, le décor de sa pièce
ne bouge presque pas : la zone calme qui entoure le visage donne le cadre de la webcam.

Trois mises en page :
- « split » : webcam en haut, gameplay en bas (le cas normal) ;
- « plein » : le streameur est en plein écran (pas de jeu) → recadrage vertical sur lui ;
- « jeu »   : pas de webcam → le jeu au milieu sur un fond flouté.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from .util import YUNET, even, log

OUT_W, OUT_H = 1080, 1920


@dataclass
class Layout:
    kind: str                    # split | plein | jeu
    src_w: int
    src_h: int
    cam: tuple | None = None     # recadrage du haut (x, y, w, h) dans l'image source
    game: tuple | None = None    # recadrage du bas
    top_h: int = 0               # hauteur du panneau webcam dans la vidéo verticale
    seam_y: int = 960            # où vont les sous-titres et le titre
    face: tuple | None = None    # visage du streameur (x, y, w, h)
    box: tuple | None = None     # cadre complet de la webcam
    conf: float = 0.0            # confiance dans ce cadre

    def to_dict(self):
        return asdict(self)


def sample_frames(video, n=14, t0=None, dur=None):
    """n images réparties sur l'extrait, ou seulement sur la plage [t0, t0 + dur] (celle du clip)"""
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    a, b = 0, total
    if t0 is not None and dur:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        a2, b2 = int(max(0.0, t0) * fps), int((max(0.0, t0) + dur) * fps)
        if min(b2, total) - a2 >= n:
            a, b = a2, min(b2, total)
    frames = []
    for i in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, a + int((i + 0.5) * (b - a) / n))
        ok, f = cap.read()
        if ok:
            frames.append(f)
    cap.release()
    return frames


def faces(frame, det):
    h, w = frame.shape[:2]
    s = 1280 / w if w > 1280 else 1.0
    img = cv2.resize(frame, (int(w * s), int(h * s))) if s != 1.0 else frame
    det.setInputSize((img.shape[1], img.shape[0]))
    _, f = det.detect(img)
    if f is None:
        return []
    return [(x / s, y / s, fw / s, fh / s, float(sc)) for x, y, fw, fh, *_, sc in f]


def stable_faces(frames, det) -> list:
    """les visages qui restent au même endroit : [(visage, part des images où il est là)], du plus présent au moins
    présent. Plusieurs candidats : la webcam, mais aussi un personnage du jeu ou un dessin posé sur le stream."""
    W = frames[0].shape[1]
    clusters = []  # [cx, cy, liste de boîtes, ensemble d'images]
    for i, fr in enumerate(frames):
        for (x, y, w, h, sc) in faces(fr, det):
            cx, cy = x + w / 2, y + h / 2
            for c in clusters:
                if abs(c[0] - cx) < 0.05 * W and abs(c[1] - cy) < 0.05 * W and 0.6 < w / np.median([b[2] for b in c[2]]) < 1.6:
                    c[2].append((x, y, w, h))
                    c[3].add(i)
                    break
            else:
                clusters.append([cx, cy, [(x, y, w, h)], {i}])
    out = []
    for c in sorted(clusters, key=lambda c: -len(c[3])):
        if len(c[3]) >= max(3, 0.3 * len(frames)):
            out.append((tuple(float(np.median([b[k] for b in c[2]])) for k in range(4)), len(c[3]) / len(frames)))
    return out


def calm_box(frames, face):
    """cadre de la webcam = zone calme (décor de la pièce) reliée au visage"""
    H, W = frames[0].shape[:2]
    s = 480 / W
    small = [cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (480, int(H * s))) for f in frames]
    std = np.stack(small).astype(np.float32).std(0)
    mask = (std < 9).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    x, y, w, h = face
    cv2.rectangle(mask, (int((x - 0.2 * w) * s), int((y - 0.2 * h) * s)),
                  (int((x + 1.2 * w) * s), int((y + 1.4 * h) * s)), 1, -1)
    _, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
    L = lab[min(lab.shape[0] - 1, int((y + h / 2) * s)), min(lab.shape[1] - 1, int((x + w / 2) * s))]
    bx, by, bw, bh, _ = stats[L]
    box = (bx / s, by / s, bw / s, bh / s)
    # trop grande (le jeu calme s'y est collé), trop petite ou bizarre : on retombe sur un cadre autour du visage
    if bw * bh / s / s > 0.4 * W * H or bw / s < 2.0 * w or bh / s < 1.8 * h or not 0.6 < bw / max(bh, 1) < 2.6:
        return None
    return box


def measure(frames) -> tuple:
    """ce qui bouge (écart-type) et les lignes nettes (contours de l'image médiane), une fois pour toutes"""
    gray = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]).astype(np.float32)
    med = np.median(gray[::2], axis=0)
    return (gray.std(0), np.abs(cv2.Sobel(med, cv2.CV_32F, 1, 0, ksize=3)),
            np.abs(cv2.Sobel(med, cv2.CV_32F, 0, 1, ksize=3)))


def refine(frames, box, face, measured=None):
    """cale chaque côté du cadre sur une vraie bordure : une ligne nette, continue sur toute la hauteur (ou largeur)
    de la webcam, qui reste en place pendant que le jeu bouge"""
    H, W = frames[0].shape[:2]
    std, gx, gy = measured or measure(frames)
    x, y, w, h = box
    fx, fy, fw, fh = face
    thr = 40

    def calm_vs_busy(inside, outside):
        """une bordure de webcam sépare sa pièce (calme) du jeu ou du chat (qui bougent)"""
        si, so = float(inside.mean()) if inside.size else 0.0, float(outside.mean()) if outside.size else 0.0
        return float(np.clip((so - si) / (si + 4.0), 0.0, 1.0))

    def col(c, a, b, side):
        a, b = int(max(0, a)), int(min(H, b))
        line = float((gx[a:b, max(0, c - 1):c + 2].max(1) > thr).mean()) if b > a else 0.0
        ins, out = (std[a:b, c + 3:c + 16], std[a:b, max(0, c - 16):max(0, c - 3)]) if side < 0 else \
            (std[a:b, max(0, c - 16):max(0, c - 3)], std[a:b, c + 3:c + 16])
        return line * (0.6 + 0.4 * calm_vs_busy(ins, out))

    def row(r, a, b, side):
        a, b = int(max(0, a)), int(min(W, b))
        line = float((gy[max(0, r - 1):r + 2, a:b].max(0) > thr).mean()) if b > a else 0.0
        ins, out = (std[r + 3:r + 16, a:b], std[max(0, r - 16):max(0, r - 3), a:b]) if side < 0 else \
            (std[max(0, r - 16):max(0, r - 3), a:b], std[r + 3:r + 16, a:b])
        return line * (0.6 + 0.4 * calm_vs_busy(ins, out))

    def edge_calm(strip):
        """la webcam touche le bord de l'image seulement si la bande juste à l'intérieur du bord est calme"""
        if strip is None or not strip.size:
            return 0.3
        return 0.3 + 0.7 * float(np.clip(1 - strip.mean() / 18.0, 0, 1))

    def cands(lo, hi, score, limit, start, strip_lo, strip_hi):
        """lignes candidates (maxima locaux) entre lo et hi ; le bord de l'image s'il est à portée ;
        la valeur de départ (zone calme) en dernier recours, avec un score faible"""
        lo, hi = int(max(2, lo)), int(min(limit - 2, hi))
        vals = [(score(c), c) for c in range(lo, hi)]
        out = [(s, c) for i, (s, c) in enumerate(vals)
               if s >= 0.45 and s >= max(v[0] for v in vals[max(0, i - 3):i + 4])]
        if lo <= 3:
            out.append((edge_calm(strip_lo), 0))
        if hi >= limit - 3:
            out.append((edge_calm(strip_hi), limit))
        out.append((0.2, int(start)))
        return out

    def shape_bonus(wd, ht):  # une webcam, c'est presque toujours du 16:9 ou du 4:3
        r = wd / max(ht, 1)
        return max(0.0, 1 - min(abs(r - 16 / 9), abs(r - 4 / 3)) / 0.2)

    # colonnes mesurées à hauteur du visage, lignes mesurées au-dessus et en dessous de lui : toujours dans la webcam
    ca, cb = fy - 0.3 * fh, fy + 1.5 * fh
    ia, ib = int(max(0, ca)), int(min(H, cb))
    lefts = cands(fx - 7 * fw, fx - 0.3 * fw, lambda c: col(c, ca, cb, -1), W, x, std[ia:ib, 0:12], None)
    rights = cands(fx + 1.3 * fw, fx + 8 * fw, lambda c: col(c, ca, cb, 1), W, x + w, None, std[ia:ib, W - 12:W])
    lefts = sorted(lefts, key=lambda v: -v[0])[:4]
    rights = sorted(rights, key=lambda v: -v[0])[:4]
    rows_cache: dict = {}

    def rows_for(l, r):
        """haut et bas mesurés sur toute la largeur du cadre essayé (le bas de la webcam peut être sombre
        juste sous le visage, mais pas sur toute la largeur)"""
        k = (l, r)
        if k not in rows_cache:
            a, b = l + 0.08 * (r - l), r - 0.08 * (r - l)
            ja2, jb2 = int(max(0, a)), int(min(W, b))
            rows_cache[k] = (
                cands(fy - 3.5 * fh, fy - 0.1 * fh, lambda q: row(q, a, b, -1), H, y, std[0:12, ja2:jb2], None),
                cands(fy + 1.3 * fh, fy + 5 * fh, lambda q: row(q, a, b, 1), H, y + h, None, std[H - 12:H, ja2:jb2]))
        return rows_cache[k]

    best = None
    for l in lefts:
        for r in rights:
            if r[1] - l[1] <= 2 * fw:
                continue
            tops, bottoms = rows_for(l[1], r[1])
            for t in tops:
                for bo in bottoms:
                    wd, ht = r[1] - l[1], bo[1] - t[1]
                    if wd <= 2 * fw or ht <= 1.8 * fh:
                        continue
                    k = l[0] + r[0] + t[0] + bo[0] + 1.2 * shape_bonus(wd, ht)
                    if best is None or k > best[0]:
                        best = (k, l[1], r[1], t[1], bo[1])
    if best is None:
        return box, 0.0
    conf, L, R, T, B = best
    nb = (float(L), float(T), float(R - L), float(B - T))
    cx, cy = fx + fw / 2, fy + fh / 2
    if not (nb[0] <= cx <= nb[0] + nb[2] and nb[1] <= cy <= nb[1] + nb[3]) or not 0.6 < nb[2] / max(nb[3], 1) < 2.6 \
            or nb[2] * nb[3] > 0.45 * W * H:
        return box, 0.0
    return nb, float(conf)


def face_box(face, W, H):
    x, y, w, h = face
    bw, bh = 3.4 * w, 2.9 * h
    cx, cy = x + w / 2, y + h * 0.95
    x0, y0 = max(0, cx - bw / 2), max(0, cy - bh / 2)
    return (x0, y0, min(W, x0 + bw) - x0, min(H, y0 + bh) - y0)


def crop_in(box, aspect, focus):
    """plus grand recadrage de rapport `aspect` (l/h) dans `box`, centré sur `focus`"""
    x, y, w, h = box
    if w / h > aspect:
        ch, cw = h, h * aspect
    else:
        cw, ch = w, w / aspect
    cx = min(max(focus[0] - cw / 2, x), x + w - cw)
    cy = min(max(focus[1] - ch * 0.42, y), y + h - ch)
    return (even(cx), even(cy), even(cw), even(ch))


def overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0, min(ay + ah, by + bh) - max(ay, by))


def game_crop(W, H, aspect, cam):
    """le plus grand cadre de jeu, le plus centré possible, qui ne mord pas sur la webcam"""
    best = None
    for scale in (1.0, 0.92, 0.84, 0.76, 0.68):
        ch = H * scale
        cw = min(W, ch * aspect)
        ch = cw / aspect
        xs, ys = list(np.linspace(0, W - cw, 21)), list(np.linspace(0, H - ch, 9))
        if cam:  # et les positions collées à la webcam : juste à côté, sans un pixel d'elle
            bx, by, bw, bh = cam
            xs += [v for v in (bx + bw, bx - cw) if 0 <= v <= W - cw]
            ys += [v for v in (by + bh, by - ch) if 0 <= v <= H - ch]
        for x in xs:
            for y in ys:
                cand = (x, y, cw, ch)
                ov = overlap(cand, cam) / (cw * ch) if cam else 0.0
                if ov > 0.02:
                    continue
                d = abs(x + cw / 2 - W / 2) / W + abs(y + ch / 2 - H / 2) / H
                key = (-scale, d + 6 * ov)  # un petit décalage vaut mieux qu'une bande de webcam dans le jeu
                if best is None or key < best[0]:
                    best = (key, cand)
        if best:
            break
    if best is None:  # aucun cadre propre : on prend le centre tant pis
        cw = min(W, H * aspect)
        return (even((W - cw) / 2), 0, even(cw), even(cw / aspect))
    x, y, cw, ch = best[1]
    return (even(x), even(y), even(cw), even(ch))


SURE = 2.85      # au-dessus : une vraie bordure de webcam a été trouvée
PRESENT = 0.7    # en dessous : il faut que le visage soit là sur presque toutes les images pour y croire


def detect(video, forced_cam=None, t0=None, dur=None) -> Layout:
    """`t0`, `dur` : la plage du clip dans l'extrait (la mise en page peut changer juste avant ou juste après)"""
    frames = sample_frames(video, t0=t0, dur=dur)
    H, W = frames[0].shape[:2]
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.75, 0.3, 50)
    found = stable_faces(frames, det)
    conf = 9.0
    if forced_cam:
        box = tuple(float(v) for v in forced_cam)
        inside = [f for f, _ in found if box[0] <= f[0] + f[2] / 2 <= box[0] + box[2]
                  and box[1] <= f[1] + f[3] / 2 <= box[1] + box[3]]
        face = inside[0] if inside else (box[0] + box[2] * 0.35, box[1] + box[3] * 0.2, box[2] * 0.3, box[3] * 0.35)
    elif not found:
        log("pas de webcam trouvée : le jeu au centre, fond flouté")
        return Layout("jeu", W, H, seam_y=1420)
    else:
        face, presence = found[0]
        if face[3] > 0.2 * H:
            log("streameur en plein écran : recadrage vertical sur lui")
            cx = face[0] + face[2] / 2
            cw = H * OUT_W / OUT_H
            x0 = min(max(cx - cw / 2, 0), W - cw)
            return Layout("plein", W, H, cam=(even(x0), 0, even(cw), even(H)), seam_y=1380)
        # chaque visage stable est essayé : la webcam est celui qui a un vrai cadre autour de lui
        measured, tries = measure(frames), []
        for f, pres in found[:3]:
            if f[3] > 0.2 * H:
                continue
            around = calm_box(frames, f) or face_box(f, W, H)
            b, c = refine(frames, around, f, measured)
            tries.append((c, b, f, pres, around))
        conf, box, face, presence, around = max(tries, key=lambda t: t[0])
        if conf < SURE:
            conf, box, face, presence, around = tries[0]  # pas de cadre net : on s'en remet au visage le plus présent
            if presence < PRESENT:  # un visage de passage, sans cadre autour : un personnage du jeu
                log(f"visage sans cadre de webcam autour (confiance {conf:.1f}) : le jeu au centre, fond flouté")
                return Layout("jeu", W, H, seam_y=1420)
            # webcam sans bordure (détourée, ou sombre sur un jeu sombre) : on cadre autour du visage
            box = face_box(face, W, H)
            log(f"webcam sans bordure nette (visage présent sur {presence:.0%} des images) : cadrage autour du visage")
    L = split_layout(W, H, box, face, conf)
    log(f"webcam trouvée : {int(box[2])}x{int(box[3])} à ({int(box[0])}, {int(box[1])}) → haut {L.top_h} px, "
        f"jeu {OUT_H - L.top_h} px")
    return L


def split_layout(W, H, box, face, conf=0.0) -> Layout:
    bx, by, bw, bh = box
    top_h = even(min(740, max(620, OUT_W * bh / bw)))  # la webcam prend environ un tiers de la hauteur
    focus = (face[0] + face[2] / 2, face[1] + face[3] / 2)
    cam = crop_in(box, OUT_W / top_h, focus)
    game = game_crop(W, H, OUT_W / (OUT_H - top_h), box)
    return Layout("split", W, H, cam=cam, game=game, top_h=top_h, seam_y=top_h, face=tuple(face),
                  box=tuple(box), conf=conf)


def consensus(layouts: list[Layout]) -> list[Layout]:
    """la webcam ne bouge pas pendant un stream : le cadre le plus sûr sert à tous les clips où le visage est dedans"""
    splits = [l for l in layouts if l.kind == "split" and l.box]
    if len(splits) < 2:
        return layouts
    best = max(splits, key=lambda l: l.conf)
    bx, by, bw, bh = best.box
    out = []
    for l in layouts:
        f = l.face
        if l.kind == "split" and f and bx <= f[0] + f[2] / 2 <= bx + bw and by <= f[1] + f[3] / 2 <= by + bh \
                and l.conf < best.conf:
            out.append(split_layout(l.src_w, l.src_h, best.box, f, best.conf))
        else:
            out.append(l)
    return out
