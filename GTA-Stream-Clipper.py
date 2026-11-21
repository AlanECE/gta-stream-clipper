"""Point d'entrée de l'exécutable Windows (PyInstaller) : ouvre l'interface dans le navigateur.

Double-clic → l'interface s'ouvre. La fenêtre noire affiche ce que fait l'outil ; la fermer arrête tout.
L'exécutable sait aussi faire « -m yt_dlp … » : l'outil s'en sert pour télécharger les streams.
"""
import os
import sys


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "-m" and sys.argv[2] == "yt_dlp":
        import yt_dlp
        sys.argv = ["yt-dlp", *sys.argv[3:]]
        sys.exit(yt_dlp.main())
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        os.environ["PATH"] = os.path.join(base, "ffmpeg") + os.pathsep + os.environ.get("PATH", "")
        os.environ.setdefault("CLIPPER_FROZEN", "1")
    try:
        os.system("title GTA Stream Clipper")
    except Exception:
        pass
    out = os.path.join(os.path.expanduser("~"), "Videos", "GTA Stream Clipper")
    args = sys.argv[1:] or ["app", "--sortie", out]
    from clipper.__main__ import main as cli
    cli(args)


if __name__ == "__main__":
    main()
