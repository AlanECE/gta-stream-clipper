"""Les moments viraux : les clips les plus vus sur Twitch (par jeu, par streameur, par langue), et les lives en cours.

Aucune clé : c'est l'accès public du site Twitch (le même que yt-dlp). Les viewers ont déjà choisi les meilleurs
moments ; on reprend chaque clip tel quel (le moment exact, avec son vrai son) et on le remet au format vertical.
"""
from __future__ import annotations

import json
import urllib.request

from .chat import GQL, WEB_CLIENT_ID

PERIODES = {"jour": "LAST_DAY", "semaine": "LAST_WEEK", "mois": "LAST_MONTH", "tout": "ALL_TIME"}
JEU_TWITCH = "Grand Theft Auto VI"
CLIP_FIELDS = ("id slug url title viewCount createdAt durationSeconds language thumbnailURL videoOffsetSeconds "
               "video { id } broadcaster { login displayName }")


def gql(query: str) -> dict:
    req = urllib.request.Request(GQL, data=json.dumps({"query": query}).encode(),
                                 headers={"Client-Id": WEB_CLIENT_ID, "Content-Type": "application/json"})
    data = json.loads(urllib.request.urlopen(req, timeout=25).read())
    if data.get("errors") and not data.get("data"):
        raise RuntimeError(f"Twitch a refusé la requête : {json.dumps(data['errors'])[:200]}")
    return data.get("data") or {}


def _q(s: str) -> str:
    return json.dumps(s)


def _clip(n: dict) -> dict:
    v = n.get("video") or {}
    b_ = n.get("broadcaster") or {}
    off = n.get("videoOffsetSeconds")
    dur = n.get("durationSeconds") or 30
    # Twitch donne la position de la FIN du clip dans la rediffusion (à quelques secondes près) : le début est
    # une durée de clip plus tôt. Mesuré en comparant le son de 22 clips à celui de leur rediffusion.
    debut = max(0, int(off - dur) - 3) if off is not None else None
    vod = f"https://www.twitch.tv/videos/{v['id']}" if v.get("id") else None
    return {"id": n.get("id"), "url": n.get("url"), "titre": n.get("title") or "", "vues": n.get("viewCount") or 0,
            "date": n.get("createdAt"), "duree": dur, "langue": (n.get("language") or "").lower(),
            "vignette": n.get("thumbnailURL"), "streamer": b_.get("displayName") or b_.get("login") or "?",
            "login": b_.get("login"), "vod": vod, "offset": off,
            "lien_vod": f"{vod}?t={debut}s" if vod and debut is not None else None}


def _retry(fn):
    """Twitch renvoie parfois une liste vide, de façon passagère : on réessaie deux fois"""
    import time

    def wrap(*a, **k):
        out = []
        for essai in range(3):
            out = fn(*a, **k)
            if out:
                return out
            time.sleep(0.8 * (essai + 1))
        return out
    return wrap


@_retry
def top_clips(jeu: str = JEU_TWITCH, periode: str = "jour", langue: str | None = None, streamer: str | None = None,
              n: int = 30) -> list[dict]:
    """les clips les plus vus. langue : « fr », « en »… ; streamer : un pseudo Twitch (alors jeu et langue ignorés)"""
    per = PERIODES.get(periode, periode)
    if streamer:
        q = (f"query {{ user(login: {_q(streamer.lower())}) {{ clips(criteria: {{period: {per}, sort: VIEWS_DESC}}, "
             f"first: {n}) {{ edges {{ node {{ {CLIP_FIELDS} }} }} }} }} }}")
        node = gql(q).get("user") or {}
    else:
        lang = f", languages: [{langue.upper()}]" if langue else ""
        q = (f"query {{ game(name: {_q(jeu)}) {{ clips(criteria: {{period: {per}, sort: VIEWS_DESC{lang}}}, "
             f"first: {n}) {{ edges {{ node {{ {CLIP_FIELDS} }} }} }} }} }}")
        node = gql(q).get("game") or {}
    edges = ((node.get("clips") or {}).get("edges")) or []
    return [_clip(e["node"]) for e in edges if e.get("node")]


@_retry
def lives(jeu: str = JEU_TWITCH, langue: str | None = None, n: int = 20) -> list[dict]:
    """les lives en cours sur le jeu, du plus regardé au moins regardé"""
    opt = f", options: {{languages: [{_q(langue.lower())}]}}" if langue else ""
    q = (f"query {{ game(name: {_q(jeu)}) {{ streams(first: {n}{opt}) {{ edges {{ node {{ title viewersCount language "
         f"broadcaster {{ login displayName }} previewImageURL(width: 640, height: 360) }} }} }} }} }}")
    edges = (((gql(q).get("game") or {}).get("streams") or {}).get("edges")) or []
    out = []
    for e in edges:
        s = e.get("node") or {}
        b = s.get("broadcaster") or {}
        out.append({"titre": s.get("title") or "", "spectateurs": s.get("viewersCount") or 0,
                    "langue": (s.get("language") or "").lower(), "streamer": b.get("displayName") or b.get("login"),
                    "login": b.get("login"), "url": f"https://www.twitch.tv/{b.get('login')}",
                    "vignette": s.get("previewImageURL")})
    return out
