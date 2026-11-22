"""Contrôle de l'application Mac avant de la publier : chaque fichier de code tourne-t-il sur le Mac des gens ?

  python packaging/check_mac.py "dist/GTA Stream Clipper.app" --min 12.0 --arch arm64

- lit l'en-tête de chaque binaire (Mach-O) : architecture (puce Apple arm64, Intel x86_64) et version de macOS
  minimale. Un seul composant construit pour un macOS plus récent que --min, et l'application plante au démarrage
  chez ceux qui ont ce macOS-là (le Mac de GitHub, lui, a toujours le plus récent : le test ne le verrait pas) ;
- vérifie que Info.plist annonce le bon minimum ;
- sur un Mac, vérifie la signature (codesign --strict) : une signature cassée donne « l'application est endommagée ».
Code de retour 1 si quelque chose ne va pas.
"""
import argparse
import plistlib
import struct
import subprocess
import sys
from pathlib import Path

CPU = {0x0100000C: "arm64", 0x01000007: "x86_64", 0x0000000C: "arm", 0x00000007: "i386"}
LC_BUILD_VERSION, LC_VERSION_MIN_MACOSX = 0x32, 0x24
PLATFORM_MACOS = 1


def ver(v: int) -> tuple:
    return (v >> 16, (v >> 8) & 0xFF)


def thin(data: bytes, off: int):
    """(architecture, macOS minimal) d'un binaire simple qui commence à off"""
    magic = struct.unpack_from("<I", data, off)[0]
    if magic not in (0xFEEDFACF, 0xFEEDFACE):
        return None
    cputype, _sub, _ft, ncmds, _size, _flags = struct.unpack_from("<iiIIII", data, off + 4)
    p = off + (32 if magic == 0xFEEDFACF else 28)
    minos = None
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_BUILD_VERSION:
            platform, m = struct.unpack_from("<II", data, p + 8)
            if platform == PLATFORM_MACOS:
                minos = ver(m)
        elif cmd == LC_VERSION_MIN_MACOSX:
            minos = ver(struct.unpack_from("<I", data, p + 8)[0])
        p += cmdsize
    return CPU.get(cputype & 0xFFFFFFFF, hex(cputype)), minos


def macho(path: Path):
    """liste de (architecture, macOS minimal), ou None si ce n'est pas du code Mac"""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            if len(head) < 8:
                return None
            magic = struct.unpack(">I", head[:4])[0]
            if magic in (0xCAFEBABE, 0xCAFEBABF):  # binaire « universel » (plusieurs architectures)
                n = struct.unpack(">I", head[4:])[0]
                if not 0 < n < 10:  # 0xCAFEBABE est aussi l'en-tête des fichiers Java
                    return None
                data = head + f.read()
                out, step = [], 20 if magic == 0xCAFEBABE else 32
                for k in range(n):
                    base = 8 + k * step
                    off = (struct.unpack_from(">I", data, base + 8)[0] if magic == 0xCAFEBABE
                           else struct.unpack_from(">Q", data, base + 8)[0])
                    r = thin(data, off)
                    if r:
                        out.append(r)
                return out or None
            if struct.unpack("<I", head[:4])[0] in (0xFEEDFACF, 0xFEEDFACE):
                r = thin(head + f.read(), 0)
                return [r] if r else None
    except OSError:
        return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("app")
    ap.add_argument("--min", default="12.0", help="macOS le plus ancien à faire tourner")
    ap.add_argument("--arch", default="arm64", help="arm64 (puce Apple) ou x86_64 (Intel)")
    a = ap.parse_args()
    app = Path(a.app)
    target = tuple(int(x) for x in a.min.split(".")[:2])
    ok = True
    files, trop_recent, sans_arch, pire = 0, [], [], (0, 0)
    for f in sorted(app.rglob("*")):
        if f.is_symlink() or not f.is_file():
            continue
        r = macho(f)
        if not r:
            continue
        files += 1
        rel = f.relative_to(app)
        mine = [m for arch, m in r if arch == a.arch]
        if not mine:
            sans_arch.append(f"{rel} ({', '.join(arch for arch, _ in r)})")
            continue
        m = mine[0] or (0, 0)
        pire = max(pire, m)
        if m > target:
            trop_recent.append((m, str(rel)))
    print(f"{files} fichiers de code · architecture {a.arch} · macOS demandé au plus : {pire[0]}.{pire[1]} "
          f"(cible {a.min})")
    if trop_recent:
        ok = False
        print(f"ÉCHEC : {len(trop_recent)} fichiers exigent un macOS plus récent que {a.min} :")
        for m, rel in sorted(trop_recent, reverse=True)[:25]:
            print(f"   macOS {m[0]}.{m[1]} : {rel}")
    if sans_arch:
        ok = False
        print(f"ÉCHEC : {len(sans_arch)} fichiers de code sans version {a.arch} :")
        for s in sans_arch[:25]:
            print("   " + s)
    plist = app / "Contents" / "Info.plist"
    if plist.exists():
        info = plistlib.loads(plist.read_bytes())
        lsmin = info.get("LSMinimumSystemVersion", "?")
        print(f"Info.plist : macOS {lsmin} minimum, version {info.get('CFBundleShortVersionString')}")
        if lsmin != a.min:
            ok = False
            print(f"ÉCHEC : Info.plist annonce macOS {lsmin}, le contrôle vise {a.min}")
    if sys.platform == "darwin":
        r = subprocess.run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)],
                           capture_output=True, text=True)
        print("signature :", "valide" if r.returncode == 0 else "CASSÉE", (r.stderr or "").strip()[-600:])
        ok &= r.returncode == 0
    print("RÉSULTAT :", "OK" if ok else "ÉCHEC")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
