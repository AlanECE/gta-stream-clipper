"""Le chat sert seulement à mesurer la hype : combien de messages par seconde, et combien sont des RÉACTIONS
(emotes, emojis, onomatopées : KEKW, 😂, MDR, hahaha, « ????? »). Un message de réaction compte triple : c'est
quand le chat réagit en masse qu'il y a un clip à faire. Aucun message n'est gardé.

- rediffusion Twitch : l'API publique du lecteur Twitch (la même que celle du site), échantillonnée toutes les 15 s ;
- rediffusion YouTube : le chat du replay via yt-dlp ;
- live Twitch : connexion anonyme au chat (IRC, en lecture seule, sans compte).
"""
from __future__ import annotations

import collections
import json
import random
import re
import socket
import ssl
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .util import log, ytdlp

GQL = "https://gql.twitch.tv/gql"
WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # identifiant public du lecteur web Twitch (celui qu'utilise yt-dlp)
COMMENTS_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"


# emotes Twitch, BTTV, 7TV et FFZ les plus courantes (les natives sont aussi reconnues par Twitch lui-même)
EMOTES = set("""LUL LULW KEKW KEKL OMEGALUL ICANT xdd XD xD Pog PogChamp POGGERS PogU Poggers POGGIES monkaS monkaW monkaOMEGA
Sadge Kappa 4Head Jebaited EZ Clap catJAM Aware Clueless WAYTOODANK BatChest Kreygasm ResidentSleeper NotLikeThis
BibleThump WutFace DansGame HUH Stare Susge pepeLaugh PepeLaugh peepoGiggles OMEGADANCE GIGACHAD Copium Prayge D: WICKED
NOWAYING Deadge Bedge KomodoHype SeemsGood PepeHands FeelsBadMan FeelsGoodMan monkaHmm widepeepoHappy Wokege Okayge
Pepega 5Head LuL EleGiggle TriHard SwiftRage haHAA ratJAM ppL Nerdge Erm ome44 xqcL forsenE Kekw Saved Classic
RIPBOZO ratirl COPIUM BASED SCHIZO Cinema catKISS peepoClap PogO FeelsStrongMan OOOO AYAYA ResidentSleeper""".split())
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\u2600-\u27BF\U0001F900-\U0001F9FF]")
_LAUGH = re.compile(r"(?:a?h+a+){2,}h*|(?:h+e+){2,}|(?:h+i+){2,}|(?:j+a+){2,}|(?:x+a+){2,}|a?(?:h+a+h+)+a*", re.I)
_ONOMATO = re.compile(
    r"m+d+r+|p+t+d+r+|x+p+t+d+r*|j+p+p+|l+o+l+|l+m+f?a+o+|r+o+f+l+|k+e+k+w?|x+d+|w+t+f+|o+m+g+|o+u+f+|w+e*s+h+|a+i+e+|"
    r"o+u+i+l+l+e+|w+o+w+|w+a+w+|b+r+u+h+|n+o{3,}n*|n+o+n{2,}|o+u+i{3,}|a+y+a+a+|s+h+e+e+s+h+|g+g+|p+t+n+|p+u+t+a+i+n+|"
    r"o+h{2,}|o{3,}h*|a+h{2,}|o+s+k+o+u+r+|w|l|e+z+|w+h+a+t+|o+u+a+h+|y+o+o+|l+e+t+s+g+o+|s+u+s+", re.I)


def reaction(text: str, emotes: int = 0) -> str | None:
    """le libellé d'un message de réaction (emote, emoji, onomatopée), « ! » pour un cri sans libellé, None sinon"""
    text = (text or "").strip()
    if not text:
        return None
    for tok in text.split():
        if tok in EMOTES:
            return tok
        m = _EMOJI.search(tok)
        if m:
            return m.group()
        w = tok.strip(".,;:!?…'\"()[]*~").lower()
        if not w:
            continue
        if _LAUGH.fullmatch(w):
            return "haha"
        if _ONOMATO.fullmatch(w):
            w = re.sub(r"(.)\1{2,}", r"\1", w)  # « mdrrr » → « mdr » (mais « gg » et « jpp » restent)
            return w.upper() if len(w) <= 4 else w
    if emotes:
        return "emote"
    if re.fullmatch(r"[?!.…]{3,}", text):
        return text[:3]
    letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", text)
    if len(letters) >= 4 and letters.isupper():  # il crie en majuscules
        return "!"
    return None


def weight(label: str | None) -> float:
    return 3.0 if label else 1.0


def summary(reacts: list[tuple[float, str]], a: float, b: float, top: int = 3) -> str:
    """« KEKW ×6 · 😂 ×3 · haha ×2 » : les réactions du chat entre a et b (secondes)"""
    c = collections.Counter(lab for t, lab in reacts if a <= t <= b and lab not in ("!", "emote"))
    return " · ".join(f"{lab} ×{k}" for lab, k in c.most_common(top) if k >= 2)


def _twitch_page(video_id: str, offset: int) -> list[tuple[float, str | None]] | None:
    body = [{"operationName": "VideoCommentsByOffsetOrCursor",
             "variables": {"videoID": video_id, "contentOffsetSeconds": int(offset)},
             "extensions": {"persistedQuery": {"version": 1, "sha256Hash": COMMENTS_HASH}}}]
    req = urllib.request.Request(GQL, data=json.dumps(body).encode(),
                                 headers={"Client-Id": WEB_CLIENT_ID, "Content-Type": "application/json"})
    for essai in range(3):
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())
            edges = data[0]["data"]["video"]["comments"]["edges"]
            out = []
            for e in edges:
                node = e["node"]
                frs = ((node.get("message") or {}).get("fragments")) or []
                text = "".join(f.get("text") or "" for f in frs)
                out.append((float(node["contentOffsetSeconds"]), reaction(text, sum(1 for f in frs if f.get("emote")))))
            return sorted(out, key=lambda x: x[0])
        except Exception:
            time.sleep(1 + essai)
    return None


def twitch_vod_rate(video_id: str, start: float, end: float, step: int = 15):
    """(messages pondérés par seconde pour chaque seconde de [start, end), réactions [(temps, libellé)])"""
    n = int(end - start)
    rate = np.full(n, np.nan, dtype=np.float32)
    offsets = list(range(int(start), int(end), step))
    log(f"chat Twitch : {len(offsets)} points de mesure…")
    with ThreadPoolExecutor(16) as ex:
        pages = list(ex.map(lambda o: (o, _twitch_page(video_id, o)), offsets))
    reacts: list[tuple[float, str]] = []
    seen = set()
    for o, msgs in pages:
        if msgs is None:
            continue
        msgs = [m for m in msgs if m[0] >= o - 2]
        for t, lab in msgs:
            if lab and (t, lab) not in seen:
                seen.add((t, lab))
                reacts.append((t, lab))
        w = sum(weight(lab) for _, lab in msgs)
        if len(msgs) >= 5:
            r = w / max(msgs[-1][0] - msgs[0][0], 1.0)
        else:
            r = w / step
        i0 = int(o - start)
        rate[i0:i0 + step] = r
    if np.isnan(rate).all():
        return None, []
    idx = np.arange(n)
    ok = ~np.isnan(rate)
    share = sum(1 for _ in reacts) / max(1, sum(len(m or []) for _, m in pages))
    log(f"chat : {len(reacts)} réactions repérées ({share:.0%} des messages lus)")
    return np.interp(idx, idx[ok], rate[ok]).astype(np.float32), sorted(reacts)


def youtube_replay_rate(url: str, start: float, end: float, work: Path):
    ytdlp("--skip-download", "--write-subs", "--sub-langs", "live_chat", "--no-playlist",
          "-o", str(work / "chat"), url, check=False)
    f = next(iter(work.glob("chat*.live_chat.json")), None)
    if not f:
        return None, []
    n = int(end - start)
    counts = np.zeros(n, dtype=np.float32)
    reacts: list[tuple[float, str]] = []
    with open(f, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)["replayChatItemAction"]
                t = int(d["videoOffsetTimeMsec"]) / 1000 - start
                item = d["actions"][0]["addChatItemAction"]["item"]
                runs = (item.get("liveChatTextMessageRenderer") or {}).get("message", {}).get("runs", [])
            except Exception:
                continue
            text = "".join(r.get("text") or "" for r in runs)
            lab = reaction(text, sum(1 for r in runs if "emoji" in r))
            if 0 <= t < n:
                counts[int(t)] += weight(lab)
                if lab:
                    reacts.append((t + start, lab))
    f.unlink(missing_ok=True)
    return (counts, reacts) if counts.sum() > 20 else (None, [])


def for_vod(url: str, inf: dict, start: float, end: float, work: Path, plat: str):
    """(débit pondéré du chat par seconde ou None, réactions [(temps du stream, libellé)])"""
    try:
        if plat == "twitch":
            from .source import twitch_vod_id
            vid = twitch_vod_id(url, inf)
            return twitch_vod_rate(vid, start, end) if vid else (None, [])
        if plat == "youtube":
            return youtube_replay_rate(url, start, end, work)
    except Exception as e:  # le chat est un bonus : sans lui, on se fie au son
        log(f"chat indisponible ({e}), on se fie au son seul")
    return None, []


class TwitchLiveChat(threading.Thread):
    """Écoute le chat d'un live Twitch, en anonyme : l'heure de chaque message et sa réaction éventuelle."""

    def __init__(self, channel: str):
        super().__init__(daemon=True)
        self.channel = channel.lower().lstrip("#")
        self.times: list[float] = []
        self.labels: list[str | None] = []
        self.stop = False

    def run(self):
        while not self.stop:
            try:
                raw = socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=30)
                s = ssl.create_default_context().wrap_socket(raw, server_hostname="irc.chat.twitch.tv")
                # les « tags » disent combien d'emotes Twitch contient chaque message
                s.sendall(f"CAP REQ :twitch.tv/tags\r\nPASS SCHMOOPIIE\r\nNICK justinfan{random.randint(10000, 99999)}\r\n"
                          f"JOIN #{self.channel}\r\n".encode())
                buf = b""
                while not self.stop:
                    data = s.recv(65536)
                    if not data:
                        break
                    buf += data
                    *lines, buf = buf.split(b"\r\n")
                    now = time.monotonic()
                    for ln in lines:
                        if ln.startswith(b"PING"):
                            s.sendall(b"PONG :tmi.twitch.tv\r\n")
                        elif b" PRIVMSG " in ln:
                            line = ln.decode("utf-8", "replace")
                            tags = line[1:line.index(" ")] if line.startswith("@") else ""
                            em = re.search(r"(?:^|;)emotes=([^;]*)", tags)
                            n_em = len(re.findall(r"\d+-\d+", em.group(1))) if em else 0
                            text = line.split(" PRIVMSG ", 1)[1].split(" :", 1)[1] if " :" in line.split(" PRIVMSG ", 1)[1] else ""
                            self.times.append(now)
                            self.labels.append(reaction(text, n_em))
            except Exception:
                time.sleep(3)

    def forget(self, before: float):
        """oublie les messages plus vieux que `before` (les temps sont rangés dans l'ordre)"""
        import bisect
        k = bisect.bisect_left(self.times, before)
        if k:
            del self.times[:k]
            del self.labels[:k]

    def rate(self, t0: float, n: int) -> np.ndarray:
        counts = np.zeros(n, dtype=np.float32)
        for t, lab in zip(list(self.times), list(self.labels)):
            i = int(t - t0)
            if 0 <= i < n:
                counts[i] += weight(lab)
        return counts

    def reactions(self, t0: float) -> list[tuple[float, str]]:
        """[(secondes depuis t0, libellé)] des réactions encore en mémoire"""
        return [(t - t0, lab) for t, lab in zip(list(self.times), list(self.labels)) if lab]
