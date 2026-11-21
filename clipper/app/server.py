"""L'interface graphique : un petit serveur local (bibliothèque standard seulement) + une page web.

  python -m clipper app                                   sur ton PC (s'ouvre dans le navigateur)
  python -m clipper app --host 0.0.0.0 --mot-de-passe X   sur un serveur (VPS), accessible depuis ton navigateur
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import mimetypes
import re
import subprocess
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .. import __version__
from ..util import ASSETS, _tls, log

STATIC = Path(__file__).resolve().parent / "static"
LANGS = ["fr", "en", "es", "de", "it", "pt"]


class Job:
    def __init__(self, kind: str, label: str):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.label = kind, label
        self.status = "en attente"
        self.lines: list[str] = []
        self.result = None
        self.error = None
        self.created = time.time()
        self.stop = threading.Event()

    def public(self):
        return {"id": self.id, "kind": self.kind, "label": self.label, "status": self.status,
                "lines": self.lines[-6:], "result": self.result, "error": self.error, "created": self.created}


class App:
    def __init__(self, base_opts):
        self.base = base_opts
        self.out = Path(base_opts.sortie).resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self.heavy = threading.Lock()  # un rendu à la fois (carte graphique, processeur)

    # ---------- options d'un travail
    def opts(self, **kw):
        o = copy.copy(self.base)
        for k, v in kw.items():
            setattr(o, k, v)
        o.sortie = str(self.out)
        return o

    # ---------- travaux en arrière-plan
    def start(self, kind: str, label: str, fn, heavy=True) -> Job:
        job = Job(kind, label)
        self.jobs[job.id] = job

        def run():
            _tls.job = job
            try:
                if heavy:
                    job.status = "en attente"
                    with self.heavy:
                        job.status = "en cours"
                        job.result = fn(job)
                else:
                    job.status = "en cours"
                    job.result = fn(job)
                job.status = "fini"
            except BaseException as e:  # noqa: BLE001 (on veut tout remonter à l'interface)
                job.status = "erreur"
                job.error = str(e)[-400:] or e.__class__.__name__
                traceback.print_exc()
            finally:
                _tls.job = None
        threading.Thread(target=run, daemon=True).start()
        return job

    # ---------- bibliothèque
    def library(self):
        items = []
        for jf in sorted(self.out.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            mp4 = jf.with_suffix(".mp4")
            if not mp4.exists():
                continue
            try:
                m = json.loads(jf.read_text(encoding="utf-8"))
            except Exception:
                continue
            items.append({"id": jf.stem, "titre": m.get("title", ""), "streamer": m.get("streamer", ""),
                          "duree": round(m.get("dur", 0), 1), "lien": m.get("source_link") or m.get("source"),
                          "style": (m.get("style") or {}).get("highlight", "jaune"),
                          "mp4": f"/media/{mp4.name}?v={int(mp4.stat().st_mtime)}",
                          "poster": f"/poster/{jf.stem}?v={int(mp4.stat().st_mtime)}",
                          "date": mp4.stat().st_mtime, "viral": bool(m.get("viral"))})
        return items

    def clip(self, cid: str):
        jf = self.out / f"{cid}.json"
        m = json.loads(jf.read_text(encoding="utf-8"))
        st = m.get("style") or {}
        return {"id": cid, "titre": m.get("title", ""), "streamer": m.get("streamer", ""), "words": m.get("words", []),
                "style": st.get("highlight", "jaune"), "mots": st.get("max_words", 2), "lien": m.get("source_link"),
                "mp4": f"/media/{cid}.mp4?v={int((self.out / f'{cid}.mp4').stat().st_mtime)}",
                "section_ok": Path(m.get("section", "")).exists()}

    def poster(self, cid: str) -> Path | None:
        mp4, jpg = self.out / f"{cid}.mp4", self.out / ".posters" / f"{cid}.jpg"
        if not mp4.exists():
            return None
        jpg.parent.mkdir(exist_ok=True)
        if not jpg.exists() or jpg.stat().st_mtime < mp4.stat().st_mtime:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "2.5", "-i", str(mp4), "-frames:v", "1",
                            "-vf", "scale=360:-2", "-q:v", "4", str(jpg)], capture_output=True)
        return jpg if jpg.exists() else None

    # ---------- actions
    def act(self, body: dict) -> Job:
        from .. import pipeline
        t = body.get("type")
        if t == "viral":
            c = body["clip"]

            def fn(job):
                o = self.opts(style=body.get("style") or "jaune", titre=body.get("titre") or None,
                              langue=body.get("langue") or None)
                return {"clip": pipeline.clip_from_viral(c, o).stem}
            return self.start("viral", f"Clip viral : {c.get('streamer')} · {c.get('titre', '')[:40]}", fn)
        if t == "analyse":
            url = body["url"].strip()

            def fn(job):
                o = self.opts(analyse=True, de=body.get("de") or None, a=body.get("a") or None,
                              langue=body.get("langue") or None, choix=None)
                pipeline.clip_stream(url, o)
                moments = json.loads(Path(o.moments_file).read_text(encoding="utf-8"))
                return {"url": url, "de": body.get("de"), "a": body.get("a"), "langue": body.get("langue"),
                        "info": getattr(o, "analyse_info", {}), "moments": moments}
            return self.start("analyse", f"Analyse : {url[:60]}", fn)
        if t == "moment":
            def fn(job):
                o = self.opts(analyse=False, de=body.get("de") or None, a=body.get("a") or None,
                              langue=body.get("langue") or None, choix=str(body["n"]),
                              titres=body.get("titre") or None, style=body.get("style") or "jaune")
                made = pipeline.clip_stream(body["url"], o)
                return {"clip": made[0].stem if made else None}
            return self.start("moment", f"Moment n°{body['n']} : {body['url'][:50]}", fn)
        if t == "live":
            url = body["url"]

            def fn(job):
                from ..live import clip_live
                o = self.opts(minutes=float(body.get("minutes") or 120), seuil=float(body.get("seuil") or 1.0),
                              stop_event=job.stop, style=body.get("style") or "jaune", langue=body.get("langue") or None)
                made = clip_live(url, o)
                return {"clips": [m.stem for m in made]}
            return self.start("live", f"En direct : {url.split('/')[-1]}", fn, heavy=False)
        if t == "rerender":
            cid = body["id"]

            def fn(job):
                log("nouveau rendu du clip…")
                pipeline.redo_with(self.out / f"{cid}.json", title=body.get("titre"), words=body.get("words"),
                                   style=body.get("style"), mots=body.get("mots"))
                return {"clip": cid}
            return self.start("rerender", f"Mise à jour : {cid}", fn)
        raise ValueError(f"action inconnue : {t}")


def make_handler(app: App, password: str | None):
    auth_ok = "Basic " + base64.b64encode(f"clipper:{password}".encode()).decode() if password else None

    class H(BaseHTTPRequestHandler):
        server_version = "GTAStreamClipper"

        def log_message(self, *a):
            pass

        def _auth(self) -> bool:
            if not auth_ok or self.headers.get("Authorization") == auth_ok:
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="GTA Stream Clipper (utilisateur : clipper)"')
            self.end_headers()
            return False

        def _json(self, obj, code=200):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _file(self, path: Path, download: str | None = None):
            if not path.exists() or not path.is_file():
                return self._json({"erreur": "introuvable"}, 404)
            size = path.stat().st_size
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            rng = self.headers.get("Range")
            start, end = 0, size - 1
            m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{download}"')
            self.end_headers()
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                        return
                    left -= len(chunk)

        def do_GET(self):
            if not self._auth():
                return
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            p = unquote(u.path)
            try:
                if p in ("/", "/index.html"):
                    return self._file(STATIC / "index.html")
                if p.startswith("/static/"):
                    f = (STATIC / p[len("/static/"):]).resolve()
                    return self._file(f) if STATIC in f.parents else self._json({}, 404)
                if p.startswith("/fonts/"):
                    return self._file(ASSETS / "fonts" / Path(p).name)
                if p == "/api/config":
                    from ..render import STYLES
                    return self._json({"version": __version__, "styles": STYLES, "langues": LANGS,
                                       "sortie": str(app.out)})
                if p == "/api/viral":
                    from ..viral import top_clips
                    return self._json(top_clips(q.get("jeu") or "Grand Theft Auto VI", q.get("periode") or "jour",
                                                q.get("langue") or None, q.get("chaine") or None, n=40))
                if p == "/api/lives":
                    from ..viral import lives
                    return self._json(lives(q.get("jeu") or "Grand Theft Auto VI", q.get("langue") or None, n=24))
                if p == "/api/jobs":
                    return self._json(sorted((j.public() for j in app.jobs.values()), key=lambda j: -j["created"]))
                if p == "/api/library":
                    return self._json(app.library())
                m = re.fullmatch(r"/api/clip/([\w.\-]+)", p)
                if m:
                    return self._json(app.clip(m.group(1)))
                m = re.fullmatch(r"/media/([\w.\-]+\.mp4)", p)
                if m:
                    return self._file(app.out / m.group(1))
                m = re.fullmatch(r"/poster/([\w.\-]+)", p)
                if m:
                    f = app.poster(m.group(1))
                    return self._file(f) if f else self._json({}, 404)
                m = re.fullmatch(r"/download/([\w.\-]+)", p)
                if m:
                    return self._file(app.out / f"{m.group(1)}.mp4", download=f"{m.group(1)}.mp4")
                return self._json({"erreur": "introuvable"}, 404)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                return self._json({"erreur": str(e)[-300:]}, 500)

        def do_POST(self):
            if not self._auth():
                return
            p = urlparse(self.path).path
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if p == "/api/jobs":
                    return self._json(app.act(body).public())
                m = re.fullmatch(r"/api/jobs/(\w+)/stop", p)
                if m and m.group(1) in app.jobs:
                    app.jobs[m.group(1)].stop.set()
                    return self._json({"ok": True})
                m = re.fullmatch(r"/api/clip/([\w.\-]+)/supprimer", p)
                if m:
                    for ext in (".mp4", ".json", ".txt"):
                        (app.out / f"{m.group(1)}{ext}").unlink(missing_ok=True)
                    return self._json({"ok": True})
                return self._json({"erreur": "introuvable"}, 404)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                return self._json({"erreur": str(e)[-300:]}, 400)

    return H


def serve(opts: argparse.Namespace):
    host, port = getattr(opts, "host", "127.0.0.1"), int(getattr(opts, "port", 8765))
    pwd = getattr(opts, "mot_de_passe", None)
    if host not in ("127.0.0.1", "localhost") and not pwd:
        raise SystemExit("sur un serveur, ajoute --mot-de-passe (l'interface serait sinon ouverte à tout internet)")
    if not getattr(opts, "style", None):
        opts.style = "jaune"
    app = App(opts)
    httpd = ThreadingHTTPServer((host, port), make_handler(app, pwd))
    # « localhost » plutôt que 127.0.0.1 : le lecteur de clips Twitch n'accepte que des noms de domaine
    url = f"http://{'localhost' if host in ('0.0.0.0', '', '127.0.0.1') else host}:{port}/"
    log(f"GTA Stream Clipper {__version__} : interface sur {url}" + (" (utilisateur : clipper)" if pwd else ""))
    log(f"clips enregistrés dans {app.out}")
    if not getattr(opts, "sans_navigateur", False):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("arrêt")
