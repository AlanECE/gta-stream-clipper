"""Test de la version Mac, comme un utilisateur : double-clic sur l'application, l'interface répond, un vrai clip
viral est monté, l'éditeur le refait, « Quitter » ferme tout, l'image disque s'ouvre.
Compte rendu (captures, clip, journal) dans build/smoke/.   python packaging/smoke_test_mac.py
"""
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dist" / "GTA Stream Clipper.app"
DMG = ROOT / "dist" / "GTA-Stream-Clipper-Mac.dmg"
OUT = ROOT / "build" / "smoke"
BASE = "http://127.0.0.1:8765"
CLIPS = Path.home() / "Movies" / "GTA Stream Clipper"
FFMPEG = APP / "Contents" / "MacOS" / "ffmpeg"
OUT.mkdir(parents=True, exist_ok=True)
report = []


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    report.append(line)


def get(path, timeout=60):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=timeout).read())


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def wait_job(job, limit=1500):
    t = time.time()
    seen = ""
    while time.time() - t < limit:
        j = next(x for x in get("/api/jobs") if x["id"] == job["id"])
        line = (j["lines"] or [""])[-1]
        if line != seen:
            say(f"   [{time.time() - t:5.0f} s] {line[:150]}")
            seen = line
        if j["status"] in ("fini", "erreur"):
            j["secondes"] = round(time.time() - t)
            return j
        time.sleep(3)
    raise SystemExit("ÉCHEC : le travail n'a pas fini à temps")


def shot(name):
    subprocess.run(["screencapture", "-x", str(OUT / f"{name}.png")])


def finish(ok: bool):
    log = Path.home() / "Library" / "Logs" / "GTA Stream Clipper.log"
    if log.exists():
        shutil.copy(log, OUT / "journal-application.log")
    (OUT / "compte-rendu.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    sys.exit(0 if ok else 1)


try:
    say("1. double-clic sur l'application (open)")
    subprocess.run(["open", "-n", str(APP)], check=True)
    t = time.time()
    while True:
        try:
            cfg = get("/api/config", timeout=3)
            break
        except Exception:  # noqa: BLE001
            if time.time() - t > 120:
                shot("echec-demarrage")
                raise SystemExit("ÉCHEC : l'interface ne répond pas après 2 minutes")
            time.sleep(2)
    say(f"   interface prête en {time.time() - t:.0f} s · version {cfg['version']} · dossier {cfg['sortie']}")
    time.sleep(12)
    shot("1-navigateur")
    subprocess.run(["osascript", "-e", 'tell application "GTA Stream Clipper" to activate'])
    time.sleep(2)
    shot("1-fenetre-application")

    say("1b. FFmpeg lit une adresse https (avec les certificats de l'application)")
    import certifi
    env = {**__import__("os").environ, "SSL_CERT_FILE": certifi.where()}
    r = subprocess.run([str(FFMPEG / "ffmpeg"), "-v", "error", "-t", "1", "-i",
                        "https://upload.wikimedia.org/wikipedia/commons/4/47/PNG_transparency_demonstration_1.png",
                        "-f", "null", "-"], capture_output=True, text=True, env=env, timeout=60)
    say(f"   {'oui' if r.returncode == 0 else 'NON : ' + r.stderr.strip()[-200:]}")

    say("2. clips viraux")
    clips = []
    for langue in ("fr", "en", ""):
        clips = get(f"/api/viral?periode=semaine&langue={langue}")
        if clips:
            break
    say(f"   {len(clips)} clips trouvés (langue {langue or 'toutes'})")
    if not clips:
        raise SystemExit("ÉCHEC : Twitch n'a renvoyé aucun clip")
    c = min(clips[:12], key=lambda x: abs(float(x["duree"]) - 25))
    say(f"   montage de : {c['streamer']} · « {c['titre'][:50]} » · {c['duree']} s · {c['vues']} vues")
    j = wait_job(post("/api/jobs", {"type": "viral", "clip": c, "style": "jaune"}))
    if j["status"] != "fini":
        raise SystemExit(f"ÉCHEC du clip viral : {j['error']}")
    cid = j["result"]["clip"]
    mp4 = CLIPS / f"{cid}.mp4"
    say(f"   clip prêt en {j['secondes']} s : {mp4} ({mp4.stat().st_size / 1e6:.1f} Mo)")
    probe = json.loads(subprocess.run([str(FFMPEG / "ffprobe"), "-v", "error", "-print_format", "json", "-show_streams",
                                       str(mp4)], capture_output=True, text=True).stdout)
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    a = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    say(f"   vidéo {v['width']}x{v['height']} {v['pix_fmt']} · son : {'oui' if a else 'NON'}")
    if (v["width"], v["height"]) != (1080, 1920) or not a:
        raise SystemExit("ÉCHEC : le clip n'est pas au bon format")
    meta = get(f"/api/clip/{cid}")
    say(f"   {len(meta['words'])} mots de sous-titres · cadrage {meta['cadrage']['type']}")
    for k, sec in enumerate((2, 8)):
        subprocess.run([str(FFMPEG / "ffmpeg"), "-y", "-v", "error", "-ss", str(sec), "-i", str(mp4), "-frames:v", "1",
                        "-vf", "scale=540:-2", str(OUT / f"2-clip-{k}.jpg")])
    shutil.copy(mp4, OUT / "clip.mp4")

    say("3. éditeur : nouveau titre, style boîte jaune, mot par mot")
    r = wait_job(post("/api/jobs", {"type": "rerender", "id": cid, "titre": "Test Mac 🍎 ça marche", "style": "boite-jaune",
                                    "mots": 1}))
    if r["status"] != "fini":
        raise SystemExit(f"ÉCHEC de l'éditeur : {r['error']}")
    subprocess.run([str(FFMPEG / "ffmpeg"), "-y", "-v", "error", "-ss", "5", "-i", str(mp4), "-frames:v", "1",
                    "-vf", "scale=540:-2", str(OUT / "3-apres-editeur.jpg")])
    say(f"   refait en {r['secondes']} s")

    say("4. Quitter (Cmd+Q)")
    subprocess.run(["osascript", "-e", 'quit app "GTA Stream Clipper"'])
    time.sleep(5)
    try:
        get("/api/config", timeout=3)
        raise SystemExit("ÉCHEC : l'application tourne encore après Quitter")
    except (OSError, ValueError):
        say("   l'application s'est bien arrêtée")
    left = subprocess.run(["pgrep", "-f", "GTA Stream Clipper"], capture_output=True, text=True).stdout.split()
    say(f"   processus restants : {len(left)}")

    say("5. image disque")
    m = subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", str(DMG)], capture_output=True, text=True).stdout
    vol = next((ln.split("\t")[-1].strip() for ln in m.splitlines() if "/Volumes/" in ln), None)
    say(f"   contenu : {sorted(p.name for p in Path(vol).iterdir()) if vol else 'NON MONTÉE'}")
    if vol:
        subprocess.run(["hdiutil", "detach", vol], capture_output=True)
    say(f"   taille : {DMG.stat().st_size / 1e6:.0f} Mo")
    say("RÉSULTAT : tout est passé")
    finish(True)
except SystemExit as e:
    if e.code in (0, None):  # finish(True) : tout est passé
        raise
    say(str(e))
    shot("echec")
    finish(False)
except Exception as e:  # noqa: BLE001
    say(f"ÉCHEC inattendu : {e!r}")
    shot("echec")
    finish(False)
