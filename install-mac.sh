#!/bin/bash
# Installe (ou met à jour) GTA Stream Clipper sur un Mac. Dans le Terminal, colle cette ligne puis Entrée :
#
#   curl -fsSL https://raw.githubusercontent.com/AlanECE/gta-stream-clipper/main/install-mac.sh | bash
#
# Le script prend la bonne version (puce Apple ou Intel), la range dans Applications et l'ouvre.
# Téléchargée par le Terminal, l'application n'est pas bloquée par macOS (« endommagée », « Apple n'a pas pu
# vérifier… ») : ce blocage ne vise que les fichiers téléchargés par un navigateur.
set -euo pipefail

APP="GTA Stream Clipper"
REPO="https://github.com/AlanECE/gta-stream-clipper/releases/latest/download"

say() { printf '\033[1;33m%s\033[0m\n' "$*"; }

if [ "$(uname -s)" != "Darwin" ]; then
  echo "Ce script est pour Mac. Sur Windows : $REPO/GTA-Stream-Clipper-Setup.exe"
  exit 1
fi
major="$(sw_vers -productVersion | cut -d. -f1)"
if [ "$major" -lt 12 ]; then
  echo "Il faut macOS 12 (Monterey) ou plus récent : ce Mac a macOS $(sw_vers -productVersion)."
  exit 1
fi
# « uname -m » répond x86_64 dans un Terminal lancé sous Rosetta : on demande directement au processeur
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ]; then
  DMG="GTA-Stream-Clipper-Mac.dmg"; QUOI="puce Apple"
else
  DMG="GTA-Stream-Clipper-Mac-Intel.dmg"; QUOI="Intel"
fi

TMP="$(mktemp -d)"
cleanup() { hdiutil detach "$TMP/vol" -quiet 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

say "1/3  Téléchargement de GTA Stream Clipper pour Mac $QUOI (environ 190 Mo)…"
if [ -n "${GSC_DMG:-}" ]; then  # test de ce script avec un .dmg tout juste construit (workflow « Version Mac »)
  cp "$GSC_DMG" "$TMP/$DMG"
else
  curl -fL --progress-bar -o "$TMP/$DMG" "$REPO/$DMG"
fi

say "2/3  Installation dans Applications…"
hdiutil attach -nobrowse -readonly -quiet -mountpoint "$TMP/vol" "$TMP/$DMG"
osascript -e "quit app \"$APP\"" >/dev/null 2>&1 || true
DEST="/Applications"
if [ ! -w "$DEST" ]; then  # compte sans droits d'administrateur : le dossier Applications de l'utilisateur
  DEST="$HOME/Applications"
  mkdir -p "$DEST"
fi
rm -rf "$DEST/$APP.app"
ditto "$TMP/vol/$APP.app" "$DEST/$APP.app"
xattr -dr com.apple.quarantine "$DEST/$APP.app" 2>/dev/null || true

say "3/3  Ouverture : l'interface s'ouvre dans ton navigateur."
open "$DEST/$APP.app"
echo "C'est installé dans $DEST. La prochaine fois, ouvre « $APP » depuis le Launchpad ou le dossier Applications."
