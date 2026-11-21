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

from .util import log, need


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
    t.add_argument("--surlignage", help="mot dit : violet (défaut), rouge, vert, bleu, orange, #code couleur, "
                                        "ou jaune (texte jaune sans boîte)")
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
    p.add_argument("--minutes", type=float, default=60, help="durée d'écoute (défaut 60 min)")
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
    p = sub.add_parser("fichier", help="clipper une vidéo déjà téléchargée")
    p.add_argument("video")
    options(p)
    p = sub.add_parser("refaire", help="refaire un clip (autre titre, autre cadrage)")
    p.add_argument("clip_json")
    options(p)
    a = ap.parse_args(argv)
    need("ffmpeg", "ffprobe")

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
    elif a.cmd == "refaire":
        made = [pipeline.redo(a.clip_json, a)]
    if made:
        print("\nClips :")
        for m in made:
            print("  ", m)


if __name__ == "__main__":
    main()
