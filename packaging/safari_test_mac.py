"""Test de l'interface dans le vrai Safari (le navigateur de la plupart des MacBook), à lancer après
smoke_test_mac.py (qui laisse un clip dans la bibliothèque) :
ouvre l'application, la Bibliothèque, l'éditeur ; la timeline se charge et se lit ; la poignée de gauche se tire à la
souris, les flèches du clavier la déplacent ; « Mettre à jour l'aperçu » refait le clip. Aucune erreur JavaScript.
Il faut avoir lancé une fois « sudo safaridriver --enable ».   python packaging/safari_test_mac.py
Captures dans build/smoke/safari/.
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dist" / "GTA Stream Clipper.app"
OUT = ROOT / "build" / "smoke" / "safari"
BASE = "http://127.0.0.1:8765"
URL = "http://localhost:8765/"
OUT.mkdir(parents=True, exist_ok=True)
report = []


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    report.append(line)


def get(path, timeout=30):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=timeout).read())


def until(fn, limit, what):
    t = time.time()
    while time.time() - t < limit:
        try:
            v = fn()
            if v:
                return v
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    raise SystemExit(f"ÉCHEC : {what} (après {limit} s)")


d = None
ok = False
try:
    say("1. l'application")
    t = time.time()
    subprocess.run(["open", "-n", str(APP)], check=True)
    until(lambda: get("/api/config", 3), 120, "l'interface ne répond pas")
    say(f"   deuxième lancement : l'interface répond en {time.time() - t:.0f} s")
    lib = get("/api/library")
    if not lib:
        raise SystemExit("ÉCHEC : la bibliothèque est vide (lancer smoke_test_mac.py avant)")
    cid = lib[0]["id"]
    say(f"   {len(lib)} clip(s) · on édite {cid}")

    say("2. Safari")
    d = webdriver.Safari()
    d.set_window_size(1440, 1000)
    d.get(URL)
    js = d.execute_script
    until(lambda: js("return document.querySelector('#vRes .card, #vRes .empty') !== null"), 60,
          "la liste des clips viraux ne s'affiche pas dans Safari")
    js("window.__err = []; addEventListener('error', e => __err.push(e.message + ' @' + (e.filename || '') + ':' + e.lineno));"
       "addEventListener('unhandledrejection', e => __err.push('promesse : ' + ((e.reason && e.reason.message) || e.reason)));")
    n = js("return document.querySelectorAll('#vRes .card').length")
    say(f"   accueil : {n} clips viraux affichés · Safari {d.capabilities.get('browserVersion')}")
    d.save_screenshot(str(OUT / "1-accueil.png"))

    say("3. Bibliothèque → clic sur le clip")
    d.find_element(By.CSS_SELECTOR, 'button[data-tab="biblio"]').click()
    until(lambda: js("return document.querySelectorAll('#bRes .card').length"), 30, "la bibliothèque reste vide")
    next(c for c in d.find_elements(By.CSS_SELECTOR, "#bRes .card") if c.get_attribute("data-id") == cid).click()
    until(lambda: js("return !!document.querySelector('#eVid')"), 30, "l'éditeur ne s'ouvre pas")
    has_trim = js("return !!document.querySelector('#tVid')")
    if not has_trim:
        raise SystemExit("ÉCHEC : pas de timeline dans l'éditeur")
    t = time.time()
    until(lambda: js("return document.querySelector('#tLoad').classList.contains('hidden')"), 240,
          "la timeline ne se prépare pas")
    until(lambda: js("return getComputedStyle(document.querySelector('#tStrip')).backgroundImage.includes('filmstrip')"),
          60, "la bande d'images ne s'affiche pas")
    st = js("const a = document.querySelector('#eVid'), b = document.querySelector('#tVid');"
            "return {clip: a.readyState, src: b.readyState, dur: b.duration, err: a.error && a.error.code, err2: b.error && b.error.code}")
    say(f"   timeline prête en {time.time() - t:.0f} s · aperçu du clip readyState {st['clip']} · "
        f"stream d'origine readyState {st['src']}, {st['dur']:.1f} s")
    if st["err"] or st["err2"]:
        raise SystemExit(f"ÉCHEC : Safari ne lit pas une vidéo (erreurs {st['err']}, {st['err2']})")
    time.sleep(1.5)
    d.save_screenshot(str(OUT / "2-editeur.png"))

    say("4. « Lire la sélection »")
    t0 = js("return document.querySelector('#tVid').currentTime")
    d.find_element(By.ID, "tPlay").click()
    time.sleep(2.5)
    t1 = js("return document.querySelector('#tVid').currentTime")
    d.find_element(By.ID, "tPlay").click()
    say(f"   lecture : {t0:.2f} s → {t1:.2f} s")
    if t1 - t0 < 0.8:
        raise SystemExit("ÉCHEC : la vidéo du stream ne se lit pas dans Safari")

    say("5. poignée de gauche tirée à la souris, puis flèches du clavier")
    tc0 = d.find_element(By.ID, "tTc").text
    hl = d.find_element(By.ID, "tHL")
    ActionChains(d).click_and_hold(hl).pause(0.2).move_by_offset(-30, 0).pause(0.2).move_by_offset(-50, 0) \
        .pause(0.2).release().perform()
    time.sleep(0.6)
    tc1 = d.find_element(By.ID, "tTc").text
    say(f"   avant : {tc0!r}")
    say(f"   après la souris : {tc1!r}")
    if tc1 == tc0:
        raise SystemExit("ÉCHEC : la poignée ne bouge pas dans Safari")
    ActionChains(d).send_keys(Keys.ARROW_RIGHT).pause(0.1).send_keys(Keys.ARROW_RIGHT).perform()
    time.sleep(0.4)
    tc2 = d.find_element(By.ID, "tTc").text
    say(f"   après 2 flèches → : {tc2!r}")
    if tc2 == tc1:
        raise SystemExit("ÉCHEC : les flèches du clavier ne déplacent pas la poignée")
    d.save_screenshot(str(OUT / "3-poignee.png"))

    say("6. « Mettre à jour l'aperçu »")
    before = {j["id"] for j in get("/api/jobs")}
    d.find_element(By.ID, "eSave").click()
    job = until(lambda: next((j for j in get("/api/jobs") if j["id"] not in before), None), 30,
                "aucun travail lancé par le bouton")
    t = time.time()
    while time.time() - t < 900:
        j = next(x for x in get("/api/jobs") if x["id"] == job["id"])
        if j["status"] in ("fini", "erreur"):
            break
        time.sleep(3)
    say(f"   {j['status']} en {time.time() - t:.0f} s {j.get('error') or ''}")
    if j["status"] != "fini":
        raise SystemExit("ÉCHEC : le clip n'a pas été refait")
    time.sleep(3)
    d.save_screenshot(str(OUT / "4-apres.png"))

    errs = js("return window.__err || []")
    say(f"7. erreurs JavaScript : {len(errs)}")
    for e in errs[:10]:
        say("   " + str(e)[:200])
    ok = not errs
    say("RÉSULTAT :", "tout est passé dans Safari" if ok else "ÉCHEC : erreurs JavaScript")
except SystemExit as e:
    say(str(e))
except Exception as e:  # noqa: BLE001
    say(f"ÉCHEC inattendu : {e!r}")
finally:
    if d is not None:
        try:
            if not ok:
                d.save_screenshot(str(OUT / "echec.png"))
            d.quit()
        except Exception:  # noqa: BLE001
            pass
    subprocess.run(["osascript", "-e", 'quit app "GTA Stream Clipper"'])
    (OUT / "compte-rendu.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
sys.exit(0 if ok else 1)
