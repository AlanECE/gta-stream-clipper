"""L'interface graphique : un petit serveur local (bibliothèque standard seulement) + une page web.

  python -m clipper app                                   sur ton PC (s'ouvre dans le navigateur)
  python -m clipper app --host 0.0.0.0 --mot-de-passe X   sur un serveur (VPS), accessible depuis ton navigateur
"""
from __future__ import annotations

import argparse
import base64
import copy
import hmac
import json
import mimetypes
import re
import shutil
import socket
import subprocess
import threading
import time
import traceback
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .. import __version__
from ..util import ASSETS, _tls, log

STATIC = Path(__file__).resolve().parent / "static"
LANGS = ["fr", "en", "es", "de", "it", "pt"]
JOBS_KEPT = 40      # travaux finis gardés en mémoire
TTL = 45            # secondes pendant lesquelles une recherche Twitch identique est resservie telle quelle


class Lines(list):
    """journal d'un travail : seulement les dernières lignes"""

    def append(self, x):
        super().append(x)
        if len(self) > 200:
            del self[:100]


class Job:
    def __init__(self, kind: str, label: str):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.label = kind, label
        self.status = "en attente"
        self.lines: list[str] = Lines()
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
        self._meta: dict[str, tuple[float, dict]] = {}  # fiches des clips déjà lues (clé : fichier, date)
        self._twitch: dict[tuple, tuple[float, list]] = {}  # recherches Twitch récentes

    def twitch(self, kind: str, *args):
        """clips viraux ou lives, avec une courte mémoire : changer d'onglet ne réinterroge pas Twitch"""
        from .. import viral
        key = (kind, *args)
        hit = self._twitch.get(key)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
        data = viral.top_clips(*args, n=40) if kind == "clips" else viral.lives(*args, n=24)
        if data:
            self._twitch[key] = (time.time(), data)
        for k in [k for k, v in self._twitch.items() if time.time() - v[0] > 10 * TTL]:
            del self._twitch[k]
        return data

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
        old = sorted((j for j in self.jobs.values() if j.status in ("fini", "erreur")), key=lambda j: j.created)
        for j in old[:-JOBS_KEPT]:  # sur un serveur qui tourne des semaines, la liste ne grossit pas
            del self.jobs[j.id]

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
    def meta(self, jf: Path) -> dict | None:
        try:
            mt = jf.stat().st_mtime
            hit = self._meta.get(jf.name)
            if hit and hit[0] == mt:
                return hit[1]
            m = json.loads(jf.read_text(encoding="utf-8"))
            self._meta[jf.name] = (mt, m)
            return m
        except Exception:  # noqa: BLE001 (fichier en cours d'écriture, ou abîmé)
            return None

    def library(self):
        items = []
        for jf in self.out.glob("*.json"):
            mp4 = jf.with_suffix(".mp4")
            m = self.meta(jf) if mp4.exists() else None
            if not m or "layout" not in m:
                continue
            mt = mp4.stat().st_mtime
            items.append({"id": jf.stem, "titre": m.get("title", ""), "streamer": m.get("streamer", ""),
                          "duree": round(m.get("dur", 0), 1), "lien": m.get("source_link") or m.get("source"),
                          "style": (m.get("style") or {}).get("highlight", "jaune"),
                          "mp4": f"/media/{mp4.name}?v={int(mt)}", "poster": f"/poster/{jf.stem}?v={int(mt)}",
                          "date": mt, "viral": bool(m.get("viral"))})
        items.sort(key=lambda c: -c["date"])
        return items

    def clip(self, cid: str):
        jf = self.out / f"{cid}.json"
        m = json.loads(jf.read_text(encoding="utf-8"))
        st = m.get("style") or {}
        L = m.get("layout") or {}
        return {"id": cid, "titre": m.get("title", ""), "streamer": m.get("streamer", ""), "words": m.get("words", []),
                "style": st.get("highlight", "jaune"), "mots": st.get("max_words", 2), "lien": m.get("source_link"),
                "mp4": f"/media/{cid}.mp4?v={int((self.out / f'{cid}.mp4').stat().st_mtime)}",
                "section_ok": Path(m.get("section", "")).exists(),
                "cadrage": {"type": L.get("kind"), "cam": L.get("box") or L.get("cam"), "l": L.get("src_w"),
                            "h": L.get("src_h")}}

    def poster(self, cid: str) -> Path | None:
        mp4, jpg = self.out / f"{cid}.mp4", self.out / ".posters" / f"{cid}.jpg"
        if not mp4.exists():
            return None
        jpg.parent.mkdir(exist_ok=True)
        if not jpg.exists() or jpg.stat().st_mtime < mp4.stat().st_mtime:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "2.5", "-i", str(mp4), "-frames:v", "1",
                            "-vf", "scale=360:-2", "-q:v", "4", str(jpg)], capture_output=True)
        return jpg if jpg.exists() else None

    def frame(self, cid: str) -> Path | None:
        """une image de la vidéo d'origine (au milieu du clip), pour tracer le cadre de la webcam à la main"""
        m = self.meta(self.out / f"{cid}.json")
        if not m or not Path(m.get("section", "")).exists():
            return None
        jpg = self.out / ".posters" / f"{cid}_source.jpg"
        jpg.parent.mkdir(exist_ok=True)
        if not jpg.exists():
            t = float(m.get("t_in", 0)) + float(m.get("dur", 0)) / 2
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", m["section"], "-frames:v", "1",
                            "-vf", "scale=960:-2", "-q:v", "4", str(jpg)], capture_output=True)
        return jpg if jpg.exists() else None

    def delete(self, cid: str):
        """supprime un clip, et son extrait source s'il ne sert à aucun autre clip (c'est lui qui prend la place)"""
        jf = self.out / f"{cid}.json"
        m = self.meta(jf) or {}
        for f in (jf, jf.with_suffix(".mp4"), jf.with_suffix(".txt"), self.out / ".posters" / f"{cid}.jpg",
                  self.out / ".posters" / f"{cid}_source.jpg"):
            f.unlink(missing_ok=True)
        self._meta.pop(jf.name, None)
        sec = Path(m["section"]) if m.get("section") else None
        work = (self.out / ".travail").resolve()
        if not sec or work not in sec.resolve().parents:  # on ne touche qu'à notre dossier de travail
            return
        used = {str(Path(x["section"]).resolve()) for x in (self.meta(j) for j in self.out.glob("*.json"))
                if x and x.get("section")}
        if str(sec.resolve()) in used:
            return
        sec.unlink(missing_ok=True)
        d = sec.parent
        if d != work and not any(d.glob("*.mp4")) and not any(d.glob("candidats_*.json")):
            shutil.rmtree(d, ignore_errors=True)

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
                o = self.opts(minutes=float(body.get("minutes") or 0), seuil=float(body.get("seuil") or 1.0),
                              stop_event=job.stop, style=body.get("style") or "jaune", langue=body.get("langue") or None,
                              veille=bool(body.get("veille")), verrou=self.heavy)
                made = clip_live(url, o)
                return {"clips": [m.stem for m in made]}
            who = url.rstrip("/").split("/")[-1].replace("kick:", "")
            return self.start("live", ("Veille : " if body.get("veille") else "En direct : ") + who, fn, heavy=False)
        if t == "rerender":
            cid = body["id"]

            def fn(job):
                log("nouveau rendu du clip…")
                pipeline.redo_with(self.out / f"{cid}.json", title=body.get("titre"), words=body.get("words"),
                                   style=body.get("style"), mots=body.get("mots"), cam=body.get("cam") or None,
                                   mise_en_page=body.get("mise_en_page") or None)
                return {"clip": cid}
            return self.start("rerender", f"Mise à jour : {cid}", fn)
        raise ValueError(f"action inconnue : {t}")


def make_handler(app: App, password: str | None):
    auth_ok = "Basic " + base64.b64encode(f"clipper:{password}".encode()).decode() if password else None

    class H(BaseHTTPRequestHandler):
        server_version = "GTAStreamClipper"
        protocol_version = "HTTP/1.1"  # la connexion reste ouverte : chaque clic ne rouvre pas une connexion

        def log_message(self, *a):
            pass

        def _auth(self) -> bool:
            if not auth_ok or hmac.compare_digest(self.headers.get("Authorization") or "", auth_ok):
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="GTA Stream Clipper (utilisateur : clipper)"')
            self.send_header("Content-Length", "0")
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
                    return self._json(app.twitch("clips", q.get("jeu") or "Grand Theft Auto VI",
                                                 q.get("periode") or "jour", q.get("langue") or None,
                                                 q.get("chaine") or None))
                if p == "/api/lives":
                    return self._json(app.twitch("lives", q.get("jeu") or "Grand Theft Auto VI",
                                                 q.get("langue") or None))
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
                m = re.fullmatch(r"/frame/([\w.\-]+)", p)
                if m:
                    f = app.frame(m.group(1))
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
                    app.delete(m.group(1))
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
    local = host in ("127.0.0.1", "localhost")
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer.allow_reuse_address = False  # sous Windows, sinon deux exemplaires se partagent le port
    if local:  # déjà ouvert (double-clic sur l'exécutable) ? on rouvre simplement la page
        try:
            cfg = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=2).read())
            if "styles" in cfg:
                log(f"GTA Stream Clipper est déjà ouvert : http://localhost:{port}/ (cette fenêtre peut être fermée)")
                if not getattr(opts, "sans_navigateur", False):
                    webbrowser.open(f"http://localhost:{port}/")
                return
        except Exception:  # noqa: BLE001 (personne sur ce port, ou autre chose que nous)
            pass
    app = App(opts)
    handler = make_handler(app, pwd)
    httpd = None
    for k in range(20 if local else 1):  # port pris par un autre programme : on essaie les suivants
        try:
            httpd = ThreadingHTTPServer((host, port + k), handler)
            port += k
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit(f"le port {port} est déjà pris : choisis-en un autre avec --port")
    if local:
        # « localhost » est d'abord essayé en IPv6 par Windows : sans écoute de ce côté, chaque requête attend
        # 0,2 à 2 secondes avant de retomber sur 127.0.0.1. On écoute donc aussi sur ::1.
        class V6(ThreadingHTTPServer):
            address_family = socket.AF_INET6
        try:
            threading.Thread(target=V6(("::1", port), handler).serve_forever, daemon=True).start()
        except OSError:
            pass  # pas d'IPv6 sur cette machine : rien à accélérer
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
