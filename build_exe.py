"""Fabrique l'exécutable Windows : dist/GTA-Stream-Clipper/ (dossier) et dist/GTA-Stream-Clipper-Windows.zip.

  pip install pyinstaller
  python build_exe.py

FFmpeg (version « essentials » de gyan.dev, GPL) est téléchargé et rangé à côté de l'exécutable.
Le modèle Whisper n'est pas dans le zip : il se télécharge au premier clip.
"""
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "GTA-Stream-Clipper"
DIST, BUILD = ROOT / "dist", ROOT / "build"
FF_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def ffmpeg(dst: Path):
    z = BUILD / "ffmpeg-essentials.zip"
    BUILD.mkdir(exist_ok=True)
    if not z.exists():
        print("téléchargement de FFmpeg…", flush=True)
        urllib.request.urlretrieve(FF_URL, z)
    dst.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z) as zf:
        for n in zf.namelist():
            base = n.rsplit("/", 1)[-1]
            if base in ("ffmpeg.exe", "ffprobe.exe", "LICENSE", "README.txt"):
                with zf.open(n) as src, open(dst / (base if base.endswith(".exe") else f"FFMPEG-{base}"), "wb") as out:
                    shutil.copyfileobj(src, out)


def prune(internal: Path):
    """ce qui ne sert pas dans l'application (la détection de voix tourne sur le processeur)"""
    import cv2
    gone = 0
    for pat in ("onnxruntime/capi/onnxruntime_providers_cuda.dll", "onnxruntime/capi/onnxruntime_providers_tensorrt.dll"):
        for f in internal.glob(pat):
            gone += f.stat().st_size
            f.unlink()
    keep = f"opencv_videoio_ffmpeg{cv2.__version__.replace('.', '')}_64.dll"
    for f in internal.glob("cv2/opencv_videoio_ffmpeg*_64.dll"):  # restes d'anciennes versions d'OpenCV
        if f.name != keep:
            gone += f.stat().st_size
            f.unlink()
    print(f"allégé de {gone / 1e6:.0f} Mo", flush=True)


def main():
    sep = os.pathsep
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", NAME, "--console",
           "--distpath", str(DIST), "--workpath", str(BUILD / "pyi"), "--specpath", str(BUILD),
           "--add-data", f"{ROOT / 'clipper' / 'assets'}{sep}clipper/assets",
           "--add-data", f"{ROOT / 'clipper' / 'app' / 'static'}{sep}clipper/app/static",
           "--add-data", f"{ROOT / 'streamers.txt'}{sep}.",
           "--collect-submodules", "clipper", "--collect-all", "faster_whisper", "--collect-all", "ctranslate2",
           "--collect-binaries", "onnxruntime", "--collect-submodules", "yt_dlp",
           *[a for m in ("torch", "tensorflow", "matplotlib", "numba", "llvmlite", "pyarrow", "scipy", "pandas",
                         "sympy", "sklearn", "IPython", "jedi", "notebook", "lxml", "pytest")
             for a in ("--exclude-module", m)],
           str(ROOT / f"{NAME}.py")]
    subprocess.run(cmd, check=True, cwd=ROOT)
    app = DIST / NAME
    prune(app / "_internal")
    ffmpeg(app / "ffmpeg")
    for f in ("README.md", "LICENSE"):
        shutil.copy(ROOT / f, app / f)
    (app / "LISEZ-MOI.txt").write_text(
        "GTA Stream Clipper\r\n\r\nDouble-clique sur GTA-Stream-Clipper.exe : l'interface s'ouvre dans ton navigateur.\r\n"
        "La fenêtre noire montre ce que fait l'outil ; la fermer arrête tout.\r\n"
        "Tes clips sont rangés dans Vidéos\\GTA Stream Clipper.\r\n"
        "Au premier clip, le modèle de transcription se télécharge (environ 0,5 Go).\r\n\r\n"
        "Code source et aide : https://github.com/AlanECE/gta-stream-clipper\r\n", encoding="utf-8")
    zpath = DIST / f"{NAME}-Windows.zip"
    if zpath.exists():
        zpath.unlink()
    shutil.make_archive(str(zpath.with_suffix("")), "zip", DIST, NAME)
    print("prêt :", app, "et", zpath, f"({zpath.stat().st_size / 1e6:.0f} Mo)")


if __name__ == "__main__":
    main()
