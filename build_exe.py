"""Fabrique l'application à télécharger.

  pip install pyinstaller
  python build_exe.py

Windows → dist/GTA-Stream-Clipper/ (dossier), dist/GTA-Stream-Clipper-Windows.zip (version portable) et, si
          Inno Setup 6 est installé, dist/GTA-Stream-Clipper-Setup.exe (installeur avec icône sur le Bureau et tuto).
Mac     → dist/GTA Stream Clipper.app et dist/GTA-Stream-Clipper-Mac.dmg (puce Apple) ou
          dist/GTA-Stream-Clipper-Mac-Intel.dmg (Mac Intel) : chacune se construit sur un Mac de son type.
          Elles doivent tourner dès macOS 12 (MAC_MIN) : les dépendances s'installent depuis des paquets compatibles
          (voir .github/workflows/mac.yml) et packaging/check_mac.py refuse une application qui exigerait plus.

FFmpeg (GPL) est téléchargé et rangé dans l'application : version « essentials » de gyan.dev sous Windows,
version statique de Martin Riedl (ffmpeg.martin-riedl.de) sur Mac.
Le modèle de transcription n'est pas dans le paquet : il se télécharge au premier clip.
"""
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "GTA-Stream-Clipper"
APP = "GTA Stream Clipper"
DIST, BUILD = ROOT / "dist", ROOT / "build"
PACK = ROOT / "packaging"
MAC = sys.platform == "darwin"
FF_WIN = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FF_MAC = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/{}/release/{}.zip"
MAC_MIN = "12.0"  # macOS Monterey : le plus ancien qu'on fait tourner (puce Apple et Intel)
ARCH = platform.machine() if MAC else ""  # arm64 (puce Apple) ou x86_64 (Intel)
DMG = f"{NAME}-Mac.dmg" if ARCH != "x86_64" else f"{NAME}-Mac-Intel.dmg"


def version() -> str:
    for line in (ROOT / "clipper" / "__init__.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=")[1].strip().strip("\"'")
    return "0.0.0"


def download(url: str, dst: Path, tries: int = 4) -> Path:
    """téléchargement avec délai maximal et nouveaux essais (un serveur qui se fige ne bloque pas la construction)"""
    if dst.exists():
        return dst
    part = dst.with_suffix(".part")  # un téléchargement coupé ne laisse pas un fichier incomplet derrière lui
    for k in range(1, tries + 1):
        print(f"téléchargement ({k}/{tries}) :", url, flush=True)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gta-stream-clipper-build"})
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as out:
                size = int(r.headers.get("Content-Length") or 0)
                shutil.copyfileobj(r, out, 1 << 20)
            if size and part.stat().st_size != size:
                raise OSError(f"fichier incomplet ({part.stat().st_size} sur {size} octets)")
            part.replace(dst)
            return dst
        except OSError as e:
            print("   échec :", e, flush=True)
    sys.exit(f"impossible de télécharger {url}")


def ffmpeg_windows(dst: Path):
    z = download(FF_WIN, BUILD / "ffmpeg-essentials.zip")
    dst.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z) as zf:
        for n in zf.namelist():
            base = n.rsplit("/", 1)[-1]
            if base in ("ffmpeg.exe", "ffprobe.exe", "LICENSE", "README.txt"):
                with zf.open(n) as src, open(dst / (base if base.endswith(".exe") else f"FFMPEG-{base}"), "wb") as out:
                    shutil.copyfileobj(src, out)


def ffmpeg_mac(dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    ff_arch = "amd64" if ARCH == "x86_64" else "arm64"
    for tool in ("ffmpeg", "ffprobe"):
        z = download(FF_MAC.format(ff_arch, tool), BUILD / f"{tool}-mac-{ff_arch}.zip")
        with zipfile.ZipFile(z) as zf:
            member = next(n for n in zf.namelist() if n.rsplit("/", 1)[-1] == tool)
            with zf.open(member) as src, open(dst / tool, "wb") as out:
                shutil.copyfileobj(src, out)
        os.chmod(dst / tool, 0o755)
    filters = subprocess.run([str(dst / "ffmpeg"), "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    if " subtitles " not in filters:
        sys.exit("ce FFmpeg pour Mac n'a pas libass (filtre subtitles) : les sous-titres ne marcheraient pas")
    (dst / "FFMPEG-LICENSE.txt").write_text("FFmpeg est distribué sous licence GPL : https://ffmpeg.org/legal.html\n"
                                            "Version statique : https://ffmpeg.martin-riedl.de\n", encoding="utf-8")


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


def version_file(v: str) -> Path:
    """les propriétés de l'exe Windows (nom, version, éditeur) : Windows les affiche dans ses avertissements"""
    t = tuple(int(x) for x in (v.split(".") + ["0", "0", "0"])[:4])
    f = BUILD / "version.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040C04B0', [
    StringStruct('CompanyName', 'iAlan'),
    StringStruct('FileDescription', '{APP}'),
    StringStruct('FileVersion', '{v}'),
    StringStruct('InternalName', '{NAME}'),
    StringStruct('LegalCopyright', 'MIT - github.com/AlanECE/gta-stream-clipper'),
    StringStruct('OriginalFilename', '{NAME}.exe'),
    StringStruct('ProductName', '{APP}'),
    StringStruct('ProductVersion', '{v}')])]),
  VarFileInfo([VarStruct('Translation', [1036, 1200])])])
""", encoding="utf-8")
    return f


def pyinstaller(v: str):
    sep = os.pathsep
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--distpath", str(DIST), "--workpath", str(BUILD / "pyi"), "--specpath", str(BUILD),
           "--add-data", f"{ROOT / 'clipper' / 'assets'}{sep}clipper/assets",
           "--add-data", f"{ROOT / 'clipper' / 'app' / 'static'}{sep}clipper/app/static",
           "--add-data", f"{ROOT / 'streamers.txt'}{sep}.",
           "--collect-submodules", "clipper", "--collect-all", "faster_whisper", "--collect-all", "ctranslate2",
           "--collect-binaries", "onnxruntime", "--collect-submodules", "yt_dlp",
           *[a for m in ("torch", "tensorflow", "matplotlib", "numba", "llvmlite", "pyarrow", "scipy", "pandas",
                         "sympy", "sklearn", "IPython", "jedi", "notebook", "lxml", "pytest")
             for a in ("--exclude-module", m)]]
    if MAC:
        cmd += ["--name", APP, "--windowed", "--icon", str(PACK / "icon-mac.png"),
                "--osx-bundle-identifier", "com.alanece.gta-stream-clipper"]
    else:
        cmd += ["--name", NAME, "--console", "--icon", str(PACK / "icon.ico"), "--version-file", str(version_file(v)),
                "--exclude-module", "tkinter"]
    subprocess.run(cmd + [str(ROOT / f"{NAME}.py")], check=True, cwd=ROOT)


def build_windows(v: str):
    pyinstaller(v)
    app = DIST / NAME
    prune(app / "_internal")
    ffmpeg_windows(app / "ffmpeg")
    for f in ("README.md", "LICENSE"):
        shutil.copy(ROOT / f, app / f)
    (app / "LISEZ-MOI.txt").write_text(
        "GTA Stream Clipper\r\n\r\nDouble-clique sur GTA-Stream-Clipper.exe : l'interface s'ouvre dans ton navigateur.\r\n"
        "La fenêtre noire montre ce que fait l'outil ; la fermer arrête tout.\r\n"
        "Tes clips sont rangés dans Vidéos\\GTA Stream Clipper.\r\n"
        "Au premier clip, le modèle de transcription se télécharge (environ 0,5 Go).\r\n\r\n"
        "Code source et aide : https://github.com/AlanECE/gta-stream-clipper\r\n", encoding="utf-8")
    zpath = DIST / f"{NAME}-Windows.zip"
    zpath.unlink(missing_ok=True)
    shutil.make_archive(str(zpath.with_suffix("")), "zip", DIST, NAME)
    print("version portable :", zpath, f"({zpath.stat().st_size / 1e6:.0f} Mo)", flush=True)
    iscc = os.environ.get("ISCC") or shutil.which("iscc") or next(
        (str(p) for p in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
                          Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe")
         if p.exists()), None)
    if not iscc:
        print("Inno Setup 6 introuvable (variable ISCC) : pas d'installeur, seulement la version portable")
        return
    subprocess.run([iscc, "/Qp", f"/DAppVersion={v}", str(PACK / "installer.iss")], check=True, cwd=PACK)
    setup = DIST / f"{NAME}-Setup.exe"
    print("installeur :", setup, f"({setup.stat().st_size / 1e6:.0f} Mo)", flush=True)


def build_mac(v: str):
    pyinstaller(v)
    app = DIST / f"{APP}.app"
    ffmpeg_mac(app / "Contents" / "MacOS" / "ffmpeg")
    plist = app / "Contents" / "Info.plist"
    info = plistlib.loads(plist.read_bytes())
    info.update({"CFBundleDisplayName": APP, "CFBundleShortVersionString": v, "CFBundleVersion": v,
                 "NSHighResolutionCapable": True, "LSMinimumSystemVersion": MAC_MIN,
                 "LSApplicationCategoryType": "public.app-category.video",
                 "NSHumanReadableCopyright": "MIT - github.com/AlanECE/gta-stream-clipper"})
    plist.write_bytes(plistlib.dumps(info))
    # signature « ad hoc » : sans elle, une application pour puce Apple ne se lance pas du tout
    for tool in ("ffmpeg", "ffprobe"):
        subprocess.run(["codesign", "--force", "-s", "-", str(app / "Contents" / "MacOS" / "ffmpeg" / tool)], check=True)
    subprocess.run(["codesign", "--force", "--deep", "-s", "-", str(app)], check=True)
    # chaque binaire doit tourner sur le macOS annoncé et sur ce type de Mac, et la signature doit être intacte
    subprocess.run([sys.executable, str(PACK / "check_mac.py"), str(app), "--min", MAC_MIN, "--arch", ARCH], check=True)
    stage = BUILD / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    subprocess.run(["ditto", str(app), str(stage / app.name)], check=True)
    os.symlink("/Applications", stage / "Applications")
    dmg = DIST / DMG
    dmg.unlink(missing_ok=True)
    subprocess.run(["hdiutil", "create", "-volname", APP, "-srcfolder", str(stage), "-ov", "-format", "UDZO",
                    str(dmg)], check=True)
    print("prêt :", app, "et", dmg, f"({dmg.stat().st_size / 1e6:.0f} Mo)", flush=True)


def main():
    v = version()
    BUILD.mkdir(exist_ok=True)
    build_mac(v) if MAC else build_windows(v)


if __name__ == "__main__":
    main()
