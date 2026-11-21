"""Point d'entrée de l'application (PyInstaller) : ouvre l'interface dans le navigateur.

Windows : double-clic → l'interface s'ouvre ; la fenêtre noire montre ce que fait l'outil, la fermer arrête tout.
Mac : double-clic → une petite fenêtre « GTA Stream Clipper » s'ouvre avec l'interface dans le navigateur ;
la fermer (ou Cmd+Q) arrête tout.
L'application sait aussi faire « -m yt_dlp … » : l'outil s'en sert pour télécharger les streams.
"""
import os
import sys
import threading
from pathlib import Path

PORT = 8765


def default_output() -> str:
    home = Path.home()
    folder = "Movies" if sys.platform == "darwin" else "Videos"  # le dossier Vidéos (Films sur Mac)
    return str(home / folder / "GTA Stream Clipper")


def bundled(*parts) -> str:
    """fichier fourni avec l'application (dossier de l'exécutable, ou ressources du paquet .app)"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def mac_window(out: str):
    """Mac : le serveur tourne en arrière-plan, une petite fenêtre montre l'état et permet de quitter"""
    import tkinter as tk
    import webbrowser

    from clipper import __version__
    from clipper import util
    from clipper.__main__ import main as cli

    url = f"http://localhost:{PORT}/"
    # une application Mac n'a pas de console : le journal va dans ~/Library/Logs (utile si quelque chose coince)
    try:
        logs = Path.home() / "Library" / "Logs"
        logs.mkdir(parents=True, exist_ok=True)
        f = open(logs / "GTA Stream Clipper.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = f
    except OSError:
        pass
    threading.Thread(target=cli, args=(["app", "--sortie", out, "--port", str(PORT)],), daemon=True).start()

    root = tk.Tk()
    root.title("GTA Stream Clipper")
    root.configure(bg="#0e0c14")
    root.resizable(False, False)
    try:
        logo = tk.PhotoImage(file=bundled("clipper", "app", "static", "icon.png")).subsample(2, 2)
        tk.Label(root, image=logo, bg="#0e0c14").pack(pady=(22, 8))
    except tk.TclError:
        logo = None
    tk.Label(root, text="GTA Stream Clipper", fg="#f1eef8", bg="#0e0c14", font=("Helvetica", 20, "bold")).pack()
    tk.Label(root, text=f"version {__version__}", fg="#9a93ad", bg="#0e0c14", font=("Helvetica", 11)).pack()
    tk.Label(root, text="L'application tourne : son interface s'ouvre dans ton navigateur.\n"
                        "Ferme cette fenêtre pour tout arrêter.",
             fg="#d9d4e6", bg="#0e0c14", font=("Helvetica", 13), justify="center").pack(pady=(14, 10), padx=26)
    status = tk.Label(root, text="démarrage…", fg="#ffd200", bg="#0e0c14", font=("Helvetica", 11),
                      wraplength=420, justify="center")
    status.pack(padx=20)
    row = tk.Frame(root, bg="#0e0c14")
    row.pack(pady=(16, 8))

    def open_ui():
        webbrowser.open(url)

    def open_folder():
        Path(out).mkdir(parents=True, exist_ok=True)
        os.system(f'open "{out}"')

    def quit_app(*_):
        util.kill_children()  # l'enregistrement d'un live s'arrête avec l'appli
        os._exit(0)

    tk.Button(row, text="Ouvrir l'interface", command=open_ui, font=("Helvetica", 13), width=16).pack(side="left", padx=6)
    tk.Button(row, text="Mes clips", command=open_folder, font=("Helvetica", 13), width=10).pack(side="left", padx=6)
    tk.Button(row, text="Quitter", command=quit_app, font=("Helvetica", 13), width=8).pack(side="left", padx=6)
    tk.Label(root, text=f"Tes clips : {out.replace(str(Path.home()), '~')}", fg="#9a93ad", bg="#0e0c14",
             font=("Helvetica", 11)).pack(pady=(4, 20))

    def tick():
        line = util.RECENT[-1] if util.RECENT else "démarrage…"
        status.config(text=line if len(line) < 140 else line[:137] + "…")
        root.after(800, tick)

    root.protocol("WM_DELETE_WINDOW", quit_app)
    root.createcommand("::tk::mac::Quit", quit_app)  # Cmd+Q et « Quitter » du Dock
    root.createcommand("::tk::mac::ReopenApplication", open_ui)  # clic sur l'icône du Dock : rouvre l'interface
    tick()
    root.mainloop()


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "-m" and sys.argv[2] == "yt_dlp":
        import yt_dlp
        sys.argv = ["yt-dlp", *sys.argv[3:]]
        sys.exit(yt_dlp.main())
    frozen = getattr(sys, "frozen", False)
    if frozen:
        base = os.path.dirname(sys.executable)
        for ff in (os.path.join(base, "ffmpeg"), os.path.join(base, "..", "Resources", "ffmpeg")):
            if os.path.isdir(ff):
                os.environ["PATH"] = os.path.abspath(ff) + os.pathsep + os.environ.get("PATH", "")
        os.environ.setdefault("CLIPPER_FROZEN", "1")
    args = sys.argv[1:]
    if sys.platform == "darwin" and frozen and not [a for a in args if not a.startswith("-psn")]:
        return mac_window(default_output())
    if sys.platform == "win32":
        try:
            os.system("title GTA Stream Clipper")
        except Exception:
            pass
    from clipper.__main__ import main as cli
    cli(args or ["app", "--sortie", default_output()])


if __name__ == "__main__":
    main()
