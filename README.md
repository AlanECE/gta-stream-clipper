# GTA Stream Clipper

**Des streams GTA aux clips verticaux prêts à poster.** Il va chercher les moments qui ont déjà fait le buzz sur
Twitch, ou il écoute une rediffusion (Twitch, Kick) ou un live, et sort des clips 1080x1920 :

```
┌──────────────────────────┐
│                          │
│   WEBCAM DU STREAMEUR    │   ← un tiers de la hauteur, recadrée sur lui
│                          │
│ ╭──────────────────────╮ │
├─│ Kai Cenat est bloqué │─┤   ← le titre façon TikTok (boîte blanche, emojis Apple),
│ │    sur GTA 6 😭      │ │     posé sur la jonction, du début à la fin
│ ╰──────────────────────╯ │
│                          │
│         GAMEPLAY         │   ← le jeu, sans la webcam ni le chat
│                          │
│        OH  MY            │   ← sous-titres deux mots par deux mots,
│                          │     le mot prononcé en jaune
└──────────────────────────┘
```

Une application (Windows), un outil en ligne de commande et un skill pour [Claude Code](https://claude.com/claude-code),
créés par [Alan (iAlan)](https://github.com/AlanECE). Gratuit, open source (MIT). **Aucune clé d'API**, ni d'IA ni de
Twitch : tout tourne sur ton PC (ou ton serveur).

## Ce qu'il sait faire

- **🔥 Clips viraux** : les clips les plus vus sur Twitch (24 h, 7 jours, 30 jours), filtrés par langue ou par
  streameur. Tu regardes le clip, tu cliques : il remonte le moment depuis la rediffusion, quelques secondes avant et
  après, au format vertical.
- **🔗 Depuis un lien** : une rediffusion Twitch ou Kick (YouTube marche aussi). Il écoute le stream, repère les moments
  où le streameur s'emballe et te les propose, avec ce qu'il dit.
- **🔴 En direct** : les lives GTA du moment (filtrés par langue). Tu en choisis un, il le regarde et sort un clip
  environ une minute après chaque moment fort. Sur un serveur, il peut rester branché sur les lives jour et nuit.
- **📚 Bibliothèque** : tous tes clips. Aperçu, titre, sous-titres et style modifiables, puis téléchargement en MP4.

## Installation

### L'application Windows (le plus simple)

1. Télécharge **[GTA-Stream-Clipper-Windows.zip](https://github.com/AlanECE/gta-stream-clipper/releases/latest/download/GTA-Stream-Clipper-Windows.zip)**
   et décompresse-le.
2. Double-clique sur **`GTA-Stream-Clipper.exe`** : l'interface s'ouvre dans ton navigateur. La fenêtre noire montre
   ce que fait l'outil ; la fermer arrête tout.
3. Tes clips sont rangés dans `Vidéos\GTA Stream Clipper`.

Au premier clip, le modèle de transcription se télécharge (0,5 Go). L'application transcrit sur le processeur ; pour
utiliser ta carte NVIDIA (bien plus rapide), installe la version Python ci-dessous.

Windows peut afficher « Windows a protégé votre ordinateur » (l'exécutable n'est pas signé) : clique sur
« Informations complémentaires », puis « Exécuter quand même ».

### Avec Claude Code

Colle ce message dans Claude Code :

```text
Installe GTA Stream Clipper depuis https://github.com/AlanECE/gta-stream-clipper :
clone le dépôt dans mon dossier personnel, installe FFmpeg s'il manque
(Windows : winget install Gyan.FFmpeg ; Mac : brew install ffmpeg),
puis lance pip install -r requirements.txt dans le dossier.
Si j'ai une carte NVIDIA, installe aussi nvidia-cublas-cu12 et nvidia-cudnn-cu12==9.*.
Copie le dossier skills/gta-stream-clipper dans ~/.claude/skills/.
Vérifie avec python -m clipper --help et dis-moi si c'est prêt.
```

Ensuite : **« ouvre l'interface de GTA Stream Clipper »**, **« trouve les clips GTA 6 français les plus vus
aujourd'hui et monte les 3 meilleurs »**, **« clippe ce stream <lien> »** ou **« surveille le live de domingo
pendant une heure »**.

### À la main

Il faut **Python 3.10 ou plus** et **FFmpeg** (`winget install Gyan.FFmpeg`, `brew install ffmpeg` ou
`sudo apt install ffmpeg`).

```bash
git clone https://github.com/AlanECE/gta-stream-clipper.git
cd gta-stream-clipper
pip install -r requirements.txt
# carte NVIDIA (transcription bien plus rapide), optionnel :
pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
python -m clipper app      # l'interface dans le navigateur
```

## En ligne de commande

Toutes les commandes se lancent depuis le dossier du dépôt. Les clips arrivent dans `./clips/` : pour chacun, un
`.mp4`, un `.txt` (titre, légende avec hashtags, lien vers le moment dans le stream, ce que dit le streameur) et un
`.json` (pour le refaire).

```bash
# l'interface graphique
python -m clipper app

# les clips viraux : liste, puis montage
python -m clipper viral --langue-clips fr --liste             # les clips GTA 6 français les plus vus (24 h)
python -m clipper viral --langue-clips fr --choix 1,4         # monter le 1er et le 4e
python -m clipper viral --chaine kaicenat --periode semaine --nb 3

# un lien de rediffusion (Twitch, Kick, YouTube)
python -m clipper lien https://www.twitch.tv/videos/2935613960 --de 3:00:00 --a 3:45:00 --analyse
python -m clipper lien https://www.twitch.tv/videos/2935613960 --de 3:00:00 --a 3:45:00 --choix 1 --titres "Kai Cenat est bloqué sur GTA 6 😭"

# il cherche tout seul les dernières rediffusions GTA 6 (streamers.txt)
python -m clipper auto --liste
python -m clipper chaine kick:jolavanille

# un live : il écoute et sort les clips au fil de l'eau (Ctrl+C pour arrêter)
python -m clipper live domingo --minutes 120

# refaire un clip : autre titre, mot par mot, autre style
python -m clipper refaire clips/<clip>.json --titre "{streamer} panique sur {jeu} 😱" --mots 1 --style boite-violette
```

### Options utiles

| Option | Rôle | Par défaut |
|---|---|---|
| `--style` | sous-titres : `jaune` (mot dit en jaune), `tout-jaune`, `blanc`, `boite-jaune`, `boite-violette`, `boite-rouge`, `boite-verte`, ou `#RRGGBB` | `jaune` |
| `--mots` | mots affichés à la fois : 1 (mot par mot), 2 ou 3 | 2 |
| `--titre` | titre imposé ; `{streamer}` et `{jeu}` sont remplacés, emojis acceptés | automatique |
| `--titre-langue` | langue des titres automatiques (`fr` ou `en`) | `fr` |
| `--sans-titre` | pas de titre sur la vidéo | |
| `--jeu` | nom du jeu dans le titre | `GTA 6` |
| `--nb`, `--duree` | nombre de clips, durée visée d'un clip (secondes) | 3, 30 |
| `--de`, `--a` | plage du stream à analyser (`1:30:00`) | tout (10 h au plus) |
| `--langue` | langue parlée par le streameur (`en`, `fr`…) | détectée |
| `--sans-chat` | ne pas regarder le chat (le son et les paroles suffisent) | |
| `--cam x,y,l,h` | cadre de la webcam à la main, si la détection se trompe | automatique |
| `--separateur` | une bande jaune entre webcam et gameplay | |

## Sur un serveur : toujours branché sur les lives

Sur un serveur Linux (VPS), l'outil tourne même PC éteint. L'interface est la même, dans ton navigateur, protégée
par un mot de passe :

```bash
sudo apt install -y ffmpeg python3-pip git tmux
git clone https://github.com/AlanECE/gta-stream-clipper.git && cd gta-stream-clipper
pip install -r requirements.txt
tmux new -s clipper
python3 -m clipper app --host 0.0.0.0 --port 8765 --mot-de-passe "un-mot-de-passe-solide" --sans-navigateur
```

Ouvre `http://<ip-du-serveur>:8765` (utilisateur `clipper`), lance la surveillance des lives depuis l'onglet
« En direct » : les clips arrivent dans la bibliothèque, tu les modifies et les télécharges depuis n'importe où.
`tmux` garde l'outil ouvert quand tu te déconnectes (`Ctrl+B` puis `D` ; `tmux attach -t clipper` pour revenir).
Sans carte graphique, la transcription tourne sur le processeur : prends au moins 4 cœurs pour suivre un live.
Pour un vrai nom de domaine en HTTPS, mets un proxy (Caddy, Nginx) devant le port 8765.

## Comment ça marche

| Étape | Ce qu'il fait |
|---|---|
| Clips viraux | l'accès public du site Twitch (le même que yt-dlp) donne les clips les plus vus, avec la seconde exacte dans la rediffusion |
| Moments d'un stream | le volume de sa voix par rapport à son niveau normal (+ la vitesse du chat Twitch ou YouTube, en bonus) |
| Paroles | Whisper (faster-whisper) transcrit chaque moment sur ton ordinateur ; les mots de réaction (« bro », « chat », « oh my god »…) font monter le score |
| Cinématiques | les bandes noires des scènes du jeu font baisser le score (les paroles sont celles des personnages) |
| Webcam | un visage qui ne bouge pas pendant que le jeu bouge, et les bordures nettes autour de lui (le même cadre pour tout le stream) |
| Clip | webcam en haut (un tiers), jeu en bas, titre en boîte blanche sur la jonction, sous-titres mot à mot, son normalisé à -14 LUFS |

Le chat est **compté, jamais lu**. S'il n'y a pas de webcam, le jeu est posé au centre sur un fond flouté ; si le
streameur est en plein écran, l'image est recadrée sur lui.

## Bon à savoir

- **Clippe seulement des streameurs d'accord pour être clippés**, et regarde chaque clip avant de le poster. Beaucoup
  de streameurs ont un programme de clippeurs ; renseigne-toi avant.
- La détection des moments d'un stream se trompe parfois (une scène du jeu très bruyante, un dialogue de mission) :
  regarde la liste avant de monter. Les clips viraux, eux, ont déjà été choisis par les viewers.
- Les streams réservés aux abonnés ne se téléchargent pas. Si une rediffusion a été supprimée, un clip viral est remonté
  à partir du clip Twitch lui-même.
- Les extraits sources restent dans le dossier `.travail` des clips pour pouvoir les modifier ; supprime-le quand tu as
  fini.

## Construire l'exécutable

```bash
pip install pyinstaller
python build_exe.py       # → dist/GTA-Stream-Clipper/ et dist/GTA-Stream-Clipper-Windows.zip
```

## Crédits et licences

GTA Stream Clipper est sous licence [MIT](LICENSE). Il repose sur [yt-dlp](https://github.com/yt-dlp/yt-dlp)
(Unlicense), [FFmpeg](https://ffmpeg.org/) (l'application Windows embarque la version « essentials » de
[gyan.dev](https://www.gyan.dev/ffmpeg/builds/), GPL), [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
(MIT) et le modèle [Whisper](https://github.com/openai/whisper) d'OpenAI (MIT), [OpenCV](https://opencv.org/)
(Apache 2.0) et son détecteur de visages [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
(MIT, fourni dans `clipper/assets/models`), [Pillow](https://python-pillow.org/) (MIT-CMU) et la police
[Montserrat](https://github.com/JulietaUla/Montserrat) (SIL OFL 1.1). Les emojis Apple sont téléchargés au besoin
depuis le paquet public [emoji-datasource-apple](https://github.com/iamcal/emoji-data) et restent la propriété
d'Apple ; ils ne sont pas fournis dans ce dépôt.

L'idée vient de [gta6-clipper](https://github.com/vossashtonai/gta6-clipper) d'Ashton Voss (MIT). Le code est écrit de
zéro. GTA Stream Clipper n'est affilié ni à Rockstar Games, ni à Twitch, ni à Kick, ni à YouTube, ni aux streameurs
cités en exemple.
