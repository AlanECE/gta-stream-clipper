"""Le chat sert seulement à mesurer la hype : combien de messages par seconde. Aucun message n'est lu ni gardé.

- rediffusion Twitch : l'API publique du lecteur Twitch (la même que celle du site), échantillonnée toutes les 15 s ;
- rediffusion YouTube : le chat du replay via yt-dlp ;
- live Twitch : connexion anonyme au chat (IRC, en lecture seule, sans compte).
"""
from __future__ import annotations

import json
import random
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


def _twitch_page(video_id: str, offset: int) -> list[float] | None:
    body = [{"operationName": "VideoCommentsByOffsetOrCursor",
             "variables": {"videoID": video_id, "contentOffsetSeconds": int(offset)},
             "extensions": {"persistedQuery": {"version": 1, "sha256Hash": COMMENTS_HASH}}}]
    req = urllib.request.Request(GQL, data=json.dumps(body).encode(),
                                 headers={"Client-Id": WEB_CLIENT_ID, "Content-Type": "application/json"})
    for essai in range(3):
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())
            edges = data[0]["data"]["video"]["comments"]["edges"]
            return sorted(float(e["node"]["contentOffsetSeconds"]) for e in edges)
        except Exception:
            time.sleep(1 + essai)
    return None


def twitch_vod_rate(video_id: str, start: float, end: float, step: int = 15) -> np.ndarray | None:
    """messages par seconde, une valeur par seconde de [start, end)"""
    n = int(end - start)
    rate = np.full(n, np.nan, dtype=np.float32)
    offsets = list(range(int(start), int(end), step))
    log(f"chat Twitch : {len(offsets)} points de mesure…")
    with ThreadPoolExecutor(8) as ex:
        pages = list(ex.map(lambda o: (o, _twitch_page(video_id, o)), offsets))
    for o, offs in pages:
        if offs is None:
            continue
        offs = [x for x in offs if x >= o - 2]
        if len(offs) >= 5:
            r = len(offs) / max(offs[-1] - offs[0], 1.0)
        else:
            r = len(offs) / step
        i0 = int(o - start)
        rate[i0:i0 + step] = r
    if np.isnan(rate).all():
        return None
    idx = np.arange(n)
    ok = ~np.isnan(rate)
    return np.interp(idx, idx[ok], rate[ok]).astype(np.float32)


def youtube_replay_rate(url: str, start: float, end: float, work: Path) -> np.ndarray | None:
    ytdlp("--skip-download", "--write-subs", "--sub-langs", "live_chat", "--no-playlist",
          "-o", str(work / "chat"), url, check=False)
    f = next(iter(work.glob("chat*.live_chat.json")), None)
    if not f:
        return None
    n = int(end - start)
    counts = np.zeros(n, dtype=np.float32)
    with open(f, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                t = int(json.loads(line)["replayChatItemAction"]["videoOffsetTimeMsec"]) / 1000 - start
            except Exception:
                continue
            if 0 <= t < n:
                counts[int(t)] += 1
    f.unlink(missing_ok=True)
    return counts if counts.sum() > 20 else None


def for_vod(url: str, inf: dict, start: float, end: float, work: Path, plat: str) -> np.ndarray | None:
    try:
        if plat == "twitch":
            from .source import twitch_vod_id
            vid = twitch_vod_id(url, inf)
            return twitch_vod_rate(vid, start, end) if vid else None
        if plat == "youtube":
            return youtube_replay_rate(url, start, end, work)
    except Exception as e:  # le chat est un bonus : sans lui, on se fie au son
        log(f"chat indisponible ({e}), on se fie au son seul")
    return None


class TwitchLiveChat(threading.Thread):
    """Compte les messages du chat d'un live Twitch, en anonyme."""

    def __init__(self, channel: str):
        super().__init__(daemon=True)
        self.channel = channel.lower().lstrip("#")
        self.times: list[float] = []
        self.stop = False

    def run(self):
        while not self.stop:
            try:
                raw = socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=30)
                s = ssl.create_default_context().wrap_socket(raw, server_hostname="irc.chat.twitch.tv")
                s.sendall(f"PASS SCHMOOPIIE\r\nNICK justinfan{random.randint(10000, 99999)}\r\n"
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
                            self.times.append(now)
            except Exception:
                time.sleep(3)

    def rate(self, t0: float, n: int) -> np.ndarray:
        counts = np.zeros(n, dtype=np.float32)
        for t in list(self.times):
            i = int(t - t0)
            if 0 <= i < n:
                counts[i] += 1
        return counts
