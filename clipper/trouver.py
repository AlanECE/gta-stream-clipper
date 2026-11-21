"""Trouver des streams GTA à clipper : les lives du moment, ou les dernières rediffusions."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from .source import channel_vods
from .util import log, ytdlp

STREAMERS_FILE = Path(__file__).resolve().parent.parent / "streamers.txt"


def load_env():
    for f in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))


def _helix(path: str, params: dict, cid: str, token: str) -> dict:
    url = f"https://api.twitch.tv/helix/{path}?{urllib.parse.urlencode(params, doseq=True)}"
    req = urllib.request.Request(url, headers={"Client-Id": cid, "Authorization": f"Bearer {token}"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def twitch_creds():
    load_env()
    cid, sec = os.environ.get("TWITCH_CLIENT_ID"), os.environ.get("TWITCH_CLIENT_SECRET")
    if not (cid and sec):
        return None
    data = urllib.parse.urlencode({"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"}).encode()
    tok = json.loads(urllib.request.urlopen("https://id.twitch.tv/oauth2/token", data=data, timeout=20).read())
    return cid, tok["access_token"]


def twitch_top(game: str, n: int, creds) -> list[dict]:
    cid, tok = creds
    g = _helix("games", {"name": game}, cid, tok)["data"]
    if not g:
        raise SystemExit(f"jeu « {game} » inconnu sur Twitch (essaie --jeu-twitch \"Grand Theft Auto V\")")
    streams = _helix("streams", {"game_id": g[0]["id"], "first": n, "type": "live"}, cid, tok)["data"]
    return [{"url": f"https://www.twitch.tv/{s['user_login']}", "title": s["title"], "who": s["user_name"],
             "viewers": s["viewer_count"], "user_id": s["user_id"]} for s in streams]


def twitch_last_vod(user_id: str, creds) -> dict | None:
    cid, tok = creds
    v = _helix("videos", {"user_id": user_id, "type": "archive", "first": 1}, cid, tok)["data"]
    return {"url": v[0]["url"], "title": v[0]["title"], "who": v[0]["user_name"]} if v else None


def youtube_lives(query: str, n: int) -> list[dict]:
    q = urllib.parse.quote_plus(query)
    r = ytdlp("--flat-playlist", "--playlist-end", str(n), "-J",
              f"https://www.youtube.com/results?search_query={q}&sp=EgJAAQ%253D%253D", check=False)
    try:
        entries = json.loads(r.stdout).get("entries") or []
    except Exception:
        return []
    return [{"url": e.get("url") or f"https://www.youtube.com/watch?v={e['id']}", "title": e.get("title", ""),
             "who": e.get("channel") or e.get("uploader") or "?", "viewers": e.get("concurrent_view_count")}
            for e in entries if e.get("id")]


def streamers_list() -> list[str]:
    if not STREAMERS_FILE.exists():
        return []
    return [l.split("#")[0].strip() for l in STREAMERS_FILE.read_text(encoding="utf-8").splitlines()
            if l.split("#")[0].strip()]


def find(live: bool, n: int, game: str, filtre: str) -> list[dict]:
    creds = None
    try:
        creds = twitch_creds()
    except Exception as e:
        log(f"clés Twitch refusées ({e}) : on continue sans")
    found: list[dict] = []
    if creds:
        top = twitch_top(game, n * 2, creds)
        if live:
            found = top[:n]
        else:
            for s in top:
                v = twitch_last_vod(s["user_id"], creds)
                if v:
                    found.append(v)
                if len(found) >= n:
                    break
    if live and len(found) < n:
        found += youtube_lives(f"{filtre} live", n - len(found))
    if not live and len(found) < n:
        for name in streamers_list():
            try:
                vods = [v for v in channel_vods(name, 8) if filtre.lower() in v["title"].lower() and not v["live"]]
            except Exception:
                continue
            if vods:
                found.append({**vods[0], "who": name})
            if len(found) >= n:
                break
    return found[:n]
