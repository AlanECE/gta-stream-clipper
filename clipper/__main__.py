"""GTA Stream Clipper : des streams GTA aux clips verticaux prêts à poster.

  python -m clipper lien <lien>               mode 1 : une rediffusion Twitch ou Kick (YouTube aussi)
  python -m clipper auto                      mode 2 : il va chercher tout seul les rediffusions GTA et les clippe
  python -m clipper chaine <pseudo ou lien>   les dernières rediffusions GTA d'une chaîne (kick:pseudo pour Kick)
  python -m clipper live <lien ou pseudo>     un stream en direct, clip par clip
  python -m clipper fichier <video.mp4>       une vidéo déjà sur ton disque
  python -m clipper refaire <clip.json>       refaire un clip avec un autre titre ou un autre cadrage
"""
from __future__ import annotations

import argparse
import sys

from .util import die_together, log, need


def options(p: argparse.ArgumentParser):
    g = p.add_argument_group("clips")
    g.add_argument("--nb", type=int, default=3, help="nombre de clips (défaut 3)")
    g.add_argument("--duree", type=float, default=30, help="durée visée d'un clip en secondes (défaut 30)")
    g.add_argument("--seuil", type=float, default=1.0, help="score minimum d'un moment (défaut 1.0)")
    g.add_argument("--de", help="début de la plage à analyser (ex. 1:30:00)")
    g.add_argument("--a", help="fin de la plage à analyser (ex. 3:00:00)")
    g.add_argument("--sortie", default="clips", help="dossier des clips (défaut ./clips)")
    g.add_argument("--garder", action="store_true", help="garder l'audio téléchargé")
    g.add_argument("--analyse", action="store_true",
                   help="seulement lister les moments candidats avec ce qu'il dit (rien n'est monté)")
    g.add_argument("--choix", help="monter ces candidats-là (numéros de la liste --analyse), ex. 1,4")
    g.add_argument("--titres", help="un titre par clip choisi, dans l'ordre de --choix, séparés par |")
    g.add_argument("--sans-chat", action="store_true", help="ne pas regarder le chat (le son et les paroles suffisent)")
    t = p.add_argument_group("titre et sous-titres")
    t.add_argument("--titre", help="titre imposé, ex. \"{streamer} se foire sur {jeu} 💀\"")
    t.add_argument("--titre-langue", default="fr", choices=["fr", "en"], help="langue des titres automatiques")
    t.add_argument("--sans-titre", action="store_true", help="pas de titre sur la vidéo")
    t.add_argument("--jeu", default="GTA 6", help="nom du jeu dans le titre (défaut GTA 6)")
    t.add_argument("--streamer", help="nom du streameur dans le titre (sinon celui de la chaîne)")
    t.add_argument("--mots", type=int, choices=[1, 2, 3], help="sous-titres : mots affichés à la fois (défaut 2)")
    t.add_argument("--style", help="sous-titres : jaune (défaut : le mot dit en jaune), tout-jaune, blanc, boite-jaune, "
                                   "boite-violette, boite-rouge, boite-verte, ou #RRGGBB (boîte de cette couleur)")
    t.add_argument("--surlignage", help=argparse.SUPPRESS)
    t.add_argument("--sous-titres-y", type=float, help="hauteur des sous-titres, de 0 (haut) à 1 (bas), défaut 0.68")
    t.add_argument("--langue", help="langue parlée (en, fr…) ; sinon détectée")
    t.add_argument("--modele", help="modèle Whisper (défaut large-v3-turbo sur carte graphique, small sinon)")
    m = p.add_argument_group("mise en page")
    m.add_argument("--cam", type=lambda s: [float(x) for x in s.split(",")],
                   help="cadre de la webcam à la main : x,y,largeur,hauteur (pixels de la vidéo source)")
    m.add_argument("--separateur", action="store_true", help="une bande jaune entre webcam et jeu")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="python -m clipper", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lien", aliases=["rediff"], help="mode 1 : clipper une rediffusion à partir de son lien (Twitch, Kick, YouTube)")
    p.add_argument("lien")
    options(p)
    p = sub.add_parser("live", help="clipper un stream en direct")
    p.add_argument("lien", help="lien du live ou pseudo Twitch")
    p.add_argument("--minutes", type=float, default=60, help="durée d'écoute (défaut 60 min ; 0 = sans limite)")
    p.add_argument("--veille", action="store_true",
                   help="attendre que la chaîne passe en direct, et attendre le live suivant quand il se termine")
    options(p)
    p = sub.add_parser("chaine", help="clipper les dernières rediffusions d'une chaîne")
    p.add_argument("chaine", help="pseudo Twitch ou lien de chaîne")
    p.add_argument("--videos", type=int, default=1, help="nombre de rediffusions (défaut 1)")
    p.add_argument("--filtre", default="GTA", help="mot du titre de la rediffusion (défaut GTA, \"\" = toutes)")
    options(p)
    p = sub.add_parser("auto", aliases=["trouver"], help="mode 2 : il va chercher tout seul les rediffusions (ou les lives) GTA et les clippe")
    p.add_argument("--live", action="store_true", help="les lives en cours (sinon les rediffusions)")
    p.add_argument("--streams", type=int, default=2, help="nombre de streams (défaut 2)")
    p.add_argument("--jeu-twitch", default="Grand Theft Auto VI", help="catégorie Twitch (avec les clés Twitch)")
    p.add_argument("--filtre", default="GTA 6", help="mot cherché dans les titres (défaut GTA 6)")
    p.add_argument("--minutes", type=float, default=30, help="en live : durée d'écoute par stream")
    p.add_argument("--liste", action="store_true", help="juste lister, sans clipper")
    options(p)
    p = sub.add_parser("viral", help="les clips les plus vus sur Twitch (par jeu, langue ou streameur) : liste ou montage")
    p.add_argument("--periode", default="jour", choices=["jour", "semaine", "mois", "tout"], help="défaut : jour")
    p.add_argument("--langue-clips", help="seulement les clips dans cette langue (fr, en, es…)")
    p.add_argument("--chaine", help="seulement les clips de ce streameur (pseudo Twitch)")
    p.add_argument("--jeu-twitch", default="Grand Theft Auto VI", help="catégorie Twitch (défaut Grand Theft Auto VI)")
    p.add_argument("--liste", action="store_true", help="juste lister, sans monter")
    options(p)
    p = sub.add_parser("app", help="l'interface graphique (dans le navigateur)")
    p.add_argument("--host", default="127.0.0.1", help="127.0.0.1 (défaut) ; 0.0.0.0 sur un serveur")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--mot-de-passe", help="obligatoire si --host 0.0.0.0 (serveur)")
    p.add_argument("--sans-navigateur", action="store_true", help="ne pas ouvrir le navigateur")
    options(p)
    p = sub.add_parser("fichier", help="clipper une vidéo déjà téléchargée")
    p.add_argument("video")
    options(p)
    p = sub.add_parser("refaire", help="refaire un clip (autre titre, autre cadrage)")
    p.add_argument("clip_json")
    options(p)
    a = ap.parse_args(argv)
    need("ffmpeg", "ffprobe")
    die_together()

    from . import pipeline
    made = []
    if a.cmd in ("lien", "rediff", "fichier"):
        made = pipeline.clip_stream(a.video if a.cmd == "fichier" else a.lien, a)
    elif a.cmd == "live":
        from .live import clip_live
        made = clip_live(a.lien, a)
    elif a.cmd == "chaine":
        from .source import channel_vods
        vods = [v for v in channel_vods(a.chaine, 30) if a.filtre.lower() in v["title"].lower() and not v["live"]]
        if not vods:
            sys.exit(f"aucune rediffusion avec « {a.filtre} » dans le titre sur cette chaîne")
        for v in vods[:a.videos]:
            log(f"rediffusion : {v['title']} ({v['url']})")
            made += pipeline.clip_stream(v["url"], a)
    elif a.cmd in ("auto", "trouver"):
        from .trouver import find
        streams = find(a.live, a.streams, a.jeu_twitch, a.filtre)
        if not streams:
            sys.exit("aucun stream trouvé. Ajoute des pseudos dans streamers.txt ou tes clés Twitch dans .env")
        for s in streams:
            log(f"{s.get('who', '?')} · {s['title'][:70]} · {s['url']}")
        if not a.liste:
            for s in streams:
                if a.live:
                    from .live import clip_live
                    made += clip_live(s["url"], a)
                else:
                    made += pipeline.clip_stream(s["url"], a)
    elif a.cmd == "viral":
        from .viral import top_clips
        clips = top_clips(a.jeu_twitch, a.periode, a.langue_clips, a.chaine, n=max(20, a.nb))
        if not clips:
            sys.exit("aucun clip trouvé pour ces filtres")
        for i, c in enumerate(clips, 1):
            print(f"  {i:>2}. {c['vues']:>7} vues · {c['streamer']:<16} · {c['titre'][:50]:<50} · {c['url']}")
        if not a.liste:
            import copy
            idx = [int(x) - 1 for x in a.choix.split(",")] if a.choix else list(range(min(a.nb, len(clips))))
            titres = [t.strip() for t in (a.titres or "").split("|")]  # un titre par clip choisi, dans l'ordre
            for k, i in enumerate(idx):
                if not 0 <= i < len(clips):
                    continue
                o = copy.copy(a)
                if k < len(titres) and titres[k]:
                    o.titre = titres[k]
                try:
                    made.append(pipeline.clip_from_viral(clips[i], o, k))
                except RuntimeError as e:  # un clip indisponible n'arrête pas les autres
                    log(f"clip {i + 1} laissé de côté : {str(e).splitlines()[-1][:160]}")
    elif a.cmd == "app":
        from .app.server import serve
        serve(a)
    elif a.cmd == "refaire":
        made = [pipeline.redo(a.clip_json, a)]
    if made:
        print("\nClips :")
        for m in made:
            print("  ", m)


if __name__ == "__main__":
    main()
