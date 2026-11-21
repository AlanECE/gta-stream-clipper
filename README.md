# GTA Stream Clipper

**Des streams GTA aux clips verticaux prêts à poster.** Tu donnes le lien d'une rediffusion (ou d'un live, ou juste
le pseudo d'un streameur) : l'outil trouve les moments où le streameur s'emballe et où le chat explose, et sort des
clips 1080x1920 :

```
┌──────────────────────────┐
│                          │
│     WEBCAM DU STREAMEUR  │   ← sa caméra, recadrée sur son visage
│                          │
│ ═══  KAI CENAT  ═══════  │   ← au début : un titre cartoon qui pop et rebondit
│   SE FOIRE SUR GTA 6     │     ensuite : les sous-titres, 2-3 mots par 2-3 mots,
│                          │     le mot prononcé en jaune
│                          │
│        GAMEPLAY          │   ← le jeu, sans la webcam ni le chat
│                          │
└──────────────────────────┘
```

Un outil Python et un skill pour [Claude Code](https://claude.com/claude-code), créé par
[Alan (iAlan)](https://github.com/AlanECE). Gratuit, open source (MIT). Tout tourne sur ton PC : pas de compte,
pas de clé d'API obligatoire, pas d'abonnement.

- **Rediffusion** : un lien Twitch, YouTube ou Kick → les meilleurs moments en clips.
- **Live** : il enregistre le stream en direct et sort un clip environ 1 minute après chaque moment fort.
- **Chaîne** : il va chercher tout seul les dernières rediffusions GTA d'un streameur.
- **Trouver** : il cherche les plus gros streams GTA du moment (en live ou en rediffusion).

## Installation

### Dans Claude Code (le plus simple)

Colle ce message dans Claude Code :

```text
Installe GTA Stream Clipper depuis https://github.com/AlanECE/gta-stream-clipper :
clone le dépôt dans ~/gta-stream-clipper, installe FFmpeg s'il manque
(Windows : winget install Gyan.FFmpeg ; Mac : brew install ffmpeg),
puis lance pip install -r requirements.txt dans le dossier.
Si j'ai une carte NVIDIA, installe aussi nvidia-cublas-cu12 et nvidia-cudnn-cu12==9.*.
Copie le dossier skills/gta-stream-clipper dans ~/.claude/skills/.
Vérifie avec python -m clipper --help et dis-moi si c'est prêt.
```

Ensuite, dis simplement à Claude : **« clippe ce stream <lien> »**, **« fais-moi 3 clips du dernier stream GTA de
kaicenat »** ou **« clippe le live de summit1g pendant une heure »**.

### À la main

Il faut **Python 3.10 ou plus** et **FFmpeg**.

```bash
git clone https://github.com/AlanECE/gta-stream-clipper.git
cd gta-stream-clipper
pip install -r requirements.txt
# carte NVIDIA (transcription bien plus rapide), optionnel :
pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
```

FFmpeg : `winget install Gyan.FFmpeg` sur Windows, `brew install ffmpeg` sur Mac, `sudo apt install ffmpeg` sur
Linux. Rouvre ton terminal après l'installation.

Au premier clip, le modèle de transcription Whisper se télécharge tout seul (`large-v3-turbo`, 1,6 Go, avec une
carte NVIDIA ; sinon `small`, 0,5 Go, sur le processeur).

## Utilisation

Toutes les commandes se lancent depuis le dossier du dépôt. Les clips arrivent dans `./clips/` : pour chacun, un
`.mp4`, un `.txt` (titre, légende avec hashtags, lien vers le moment dans le stream, ce que dit le streameur) et un
`.json` (pour le refaire).

```bash
# une rediffusion (Twitch, YouTube, Kick…)
python -m clipper rediff https://www.twitch.tv/videos/2935613960

# seulement une partie d'un long stream, 5 clips de 40 s
python -m clipper rediff https://www.twitch.tv/videos/2935613960 --de 2:00:00 --a 4:00:00 --nb 5 --duree 40

# un live : il écoute pendant 2 heures et sort les clips au fil de l'eau (Ctrl+C pour arrêter)
python -m clipper live kaicenat --minutes 120

# les 2 dernières rediffusions GTA d'un streameur
python -m clipper chaine kaicenat --videos 2

# les plus gros streams GTA du moment
python -m clipper trouver --liste            # juste la liste des rediffusions trouvées
python -m clipper trouver --live --streams 2 # clipper les 2 plus gros lives

# une vidéo déjà sur ton disque
python -m clipper fichier mon_stream.mp4 --streamer KaiCenat

# refaire un clip avec un autre titre
python -m clipper refaire clips/kaicenat_20261121_10860.json --titre "{streamer} PANIQUE SUR {jeu}"
```

### Choisir soi-même les moments

L'outil classe les moments tout seul, mais tu peux (ou Claude peut) regarder la liste et choisir :

```bash
python -m clipper rediff <lien> --analyse
#   1. 3:10:59 · score 2.15 · « Oh my god, this is just a check. This is crazy. How am I supposed to move? … »
#   2. 3:42:26 · score 2.09 · « … »
python -m clipper rediff <lien> --choix 1,4 --titres "KAI CENAT EST BLOQUÉ SUR GTA 6|KAI CENAT N'Y CROIT PAS"
```

La deuxième commande réutilise l'analyse de la première : elle ne retélécharge rien.

### Options utiles

| Option | Rôle | Par défaut |
|---|---|---|
| `--nb` | nombre de clips | 3 |
| `--duree` | durée visée d'un clip, en secondes | 30 |
| `--de`, `--a` | plage du stream à analyser (`1:30:00`) | tout (10 h au plus) |
| `--titre` | titre imposé ; `{streamer}` et `{jeu}` sont remplacés | automatique |
| `--titre-langue` | langue des titres automatiques (`fr` ou `en`) | `fr` |
| `--jeu` | nom du jeu dans le titre | `GTA 6` |
| `--titre-duree` | secondes d'affichage du titre (0 = pas de titre) | 2.4 |
| `--langue` | langue parlée par le streameur (`en`, `fr`…) | détectée |
| `--cam x,y,l,h` | cadre de la webcam à la main, si la détection se trompe | automatique |
| `--sans-separateur` | pas de bande jaune entre webcam et gameplay | |
| `--seuil` | score minimum d'un moment (le live s'en sert pour décider) | 1.0 |
| `--sortie` | dossier des clips | `clips` |

## Comment ça marche

| Étape | Rediffusion | Live |
|---|---|---|
| 1. Récupérer le stream | l'audio seul (rapide), puis seulement les minutes des clips | des morceaux de 20 s, on garde les 15 dernières minutes |
| 2. Mesurer la hype | volume de sa voix par rapport à son niveau normal + vitesse du chat | pareil, chat Twitch en direct |
| 3. Écouter les candidats | Whisper transcrit chaque moment ; les mots de réaction (« bro », « chat », « no way », « oh my god »…) font monter le score | pareil |
| 4. Écarter les cinématiques | les bandes noires des cinématiques de GTA font baisser le score (les paroles sont celles du jeu, pas du streameur) | |
| 5. Trouver la webcam | un visage qui ne bouge pas pendant que le jeu bouge, et les bordures nettes autour de lui (le même cadre pour tout le stream) | pareil |
| 6. Fabriquer le clip | webcam en haut, gameplay en bas, titre cartoon (police Luckiest Guy) qui pop, sous-titres 2-3 mots qui rebondissent, son normalisé à -14 LUFS | pareil |

Le chat est **compté, jamais lu** : seul le nombre de messages par seconde sert. Sur les rediffusions Twitch, l'outil
passe par l'API publique du lecteur Twitch ; sur YouTube, par le chat du replay ; en live Twitch, par une connexion
anonyme au chat (sans compte).

S'il n'y a pas de webcam, le jeu est posé au centre sur un fond flouté. Si le streameur est en plein écran (pas de
jeu), l'image est recadrée sur lui.

## Trouver des streams

`trouver` fonctionne sans rien configurer :

- **en live**, il cherche les lives GTA 6 en cours sur YouTube ;
- **en rediffusion**, il regarde les dernières rediffusions des streameurs listés dans [`streamers.txt`](streamers.txt)
  (ajoute ou retire qui tu veux) et garde celles qui ont « GTA 6 » dans le titre.

Pour chercher aussi sur Twitch (les plus gros lives de la catégorie Grand Theft Auto VI), crée une application
gratuite sur [dev.twitch.tv/console](https://dev.twitch.tv/console), puis copie `.env.example` en `.env` et
remplis `TWITCH_CLIENT_ID` et `TWITCH_CLIENT_SECRET`.

## Bon à savoir

- **Clippe seulement des streameurs d'accord pour être clippés**, et regarde chaque clip avant de le poster.
  Beaucoup de streameurs ont un programme de clippeurs ; renseigne-toi avant.
- La détection des moments se trompe parfois (une scène du jeu très bruyante, un dialogue de mission). Le plus
  fiable : `--analyse`, puis `--choix`, ou laisser Claude choisir avec le skill.
- Les streams réservés aux abonnés ou supprimés ne peuvent pas être téléchargés.
- Les extraits sources restent dans `clips/.travail/` pour pouvoir refaire un clip ; supprime ce dossier quand tu
  as fini.
- Pour la monétisation sur YouTube, le contenu repris tel quel est souvent refusé : ajoute quelque chose à toi.

## Crédits et licences

GTA Stream Clipper est sous licence [MIT](LICENSE). Il repose sur [yt-dlp](https://github.com/yt-dlp/yt-dlp)
(Unlicense), [FFmpeg](https://ffmpeg.org/) (LGPL/GPL), [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
(MIT) et le modèle [Whisper](https://github.com/openai/whisper) d'OpenAI (MIT), [OpenCV](https://opencv.org/)
(Apache 2.0) et son détecteur de visages [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
(MIT, fourni dans `clipper/assets/models`), et la police
[Luckiest Guy](https://fonts.google.com/specimen/Luckiest+Guy) (Apache 2.0, fournie dans `clipper/assets/fonts`).

L'idée vient de [gta6-clipper](https://github.com/vossashtonai/gta6-clipper) d'Ashton Voss (MIT). Le code est écrit de
zéro, pour Windows comme pour Mac et Linux, avec une autre mise en page. GTA Stream Clipper n'est affilié ni à
Rockstar Games, ni à Twitch, ni à YouTube, ni aux streameurs cités en exemple.
