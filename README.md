# GTA Stream Clipper

**Des streams GTA aux clips verticaux prêts à poster.** Deux modes : tu donnes le lien d'une rediffusion Twitch ou
Kick, ou il va chercher tout seul les dernières rediffusions GTA 6. Il trouve les moments où le streameur s'emballe et
sort des clips 1080x1920 :

```
┌──────────────────────────┐
│                          │
│   WEBCAM DU STREAMEUR    │   ← un tiers de la hauteur, recadrée sur lui
│                          │
│ ╭──────────────────────╮ │
├─│ Kai Cenat est bloqué │─┤   ← le titre, façon texte TikTok (boîte blanche, emojis),
│ │    sur GTA 6 😭      │ │     posé sur la jonction, du début à la fin
│ ╰──────────────────────╯ │
│                          │
│         GAMEPLAY         │   ← le jeu, sans la webcam ni le chat
│                          │
│       OH [MY]            │   ← sous-titres deux mots par deux mots,
│                          │     le mot prononcé surligné
└──────────────────────────┘
```

Un outil Python et un skill pour [Claude Code](https://claude.com/claude-code), créé par
[Alan (iAlan)](https://github.com/AlanECE). Gratuit, open source (MIT). Tout tourne sur ton PC : pas de compte,
pas de clé d'API obligatoire, pas d'abonnement.

- **Mode 1, un lien** : une rediffusion Twitch ou Kick (YouTube marche aussi) → les meilleurs moments en clips.
- **Mode 2, auto** : il va chercher les dernières rediffusions GTA 6 des streameurs de `streamers.txt` (ou les plus
  gros lives du moment) et les clippe.
- **Live** : il enregistre le stream en direct et sort un clip environ 1 minute après chaque moment fort.

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

Ensuite, dis simplement à Claude : **« clippe ce stream <lien> »**, **« fais-moi 3 clips du dernier stream GTA 6 de
kaicenat »**, **« trouve les plus gros streams GTA 6 d'aujourd'hui et clippe-les »** ou **« clippe le live de
summit1g pendant une heure »**.

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
# MODE 1 : un lien de rediffusion (Twitch, Kick, YouTube)
python -m clipper lien https://www.twitch.tv/videos/2935613960
python -m clipper lien https://kick.com/jolavanille/videos/01a1fac1-1fb8-7180-a932-3e0fc369766e --de 3:20:00 --a 4:05:00

# MODE 2 : il cherche tout seul
python -m clipper auto --liste               # juste la liste des rediffusions GTA 6 trouvées
python -m clipper auto --streams 2           # clipper les 2 premières
python -m clipper chaine kaicenat --videos 2 # les 2 dernières rediffusions GTA d'un streameur Twitch
python -m clipper chaine kick:jolavanille    # pareil sur Kick
python -m clipper auto --live --streams 1    # le plus gros live GTA 6 du moment

# un live : il écoute pendant 2 heures et sort les clips au fil de l'eau (Ctrl+C pour arrêter)
python -m clipper live kaicenat --minutes 120

# une vidéo déjà sur ton disque
python -m clipper fichier mon_stream.mp4 --streamer KaiCenat

# refaire un clip : autre titre, mot par mot, surlignage jaune
python -m clipper refaire clips/kaicenat_20261121_11459.json --titre "{streamer} panique sur {jeu} 😭" --mots 1 --surlignage jaune
```

### Choisir soi-même les moments

L'outil classe les moments tout seul, mais tu peux (ou Claude peut) regarder la liste et choisir :

```bash
python -m clipper lien <lien> --analyse
#   1. 3:10:59 · score 2.15 · « Oh my god, this is just a check. This is crazy. How am I supposed to move? … »
#   2. 3:42:26 · score 2.09 · « … »
python -m clipper lien <lien> --choix 1,4 --titres "Kai Cenat est bloqué sur GTA 6 😭|Kai Cenat n'y croit pas 💀"
```

La deuxième commande réutilise l'analyse de la première : elle ne retélécharge rien.

### Options utiles

| Option | Rôle | Par défaut |
|---|---|---|
| `--nb` | nombre de clips | 3 |
| `--duree` | durée visée d'un clip, en secondes | 30 |
| `--de`, `--a` | plage du stream à analyser (`1:30:00`) | tout (10 h au plus) |
| `--titre` | titre imposé ; `{streamer}` et `{jeu}` sont remplacés, emojis acceptés | automatique |
| `--titre-langue` | langue des titres automatiques (`fr` ou `en`) | `fr` |
| `--sans-titre` | pas de titre sur la vidéo | |
| `--jeu` | nom du jeu dans le titre | `GTA 6` |
| `--mots` | sous-titres : 1 (mot par mot), 2 ou 3 mots à la fois | 2 |
| `--surlignage` | derrière le mot dit : `violet`, `rouge`, `vert`, `bleu`, `orange`, un code `#RRGGBB`, ou `jaune` (mot en jaune, sans boîte) | `violet` |
| `--sous-titres-y` | hauteur des sous-titres, de 0 (haut) à 1 (bas) | 0.68 |
| `--langue` | langue parlée par le streameur (`en`, `fr`…) | détectée |
| `--sans-chat` | ne pas regarder le chat (le son et les paroles suffisent) | |
| `--cam x,y,l,h` | cadre de la webcam à la main, si la détection se trompe | automatique |
| `--separateur` | une bande jaune entre webcam et gameplay | |
| `--seuil` | score minimum d'un moment (le live s'en sert pour décider) | 1.0 |
| `--sortie` | dossier des clips | `clips` |

## Comment ça marche

| Étape | Rediffusion | Live |
|---|---|---|
| 1. Récupérer le stream | l'audio seul (rapide), puis seulement les minutes des clips | des morceaux de 20 s, on garde les 15 dernières minutes |
| 2. Mesurer la hype | volume de sa voix par rapport à son niveau normal (+ vitesse du chat Twitch ou YouTube, en bonus) | pareil, chat Twitch en direct |
| 3. Écouter les candidats | Whisper transcrit chaque moment ; les mots de réaction (« bro », « chat », « no way », « oh my god »…) font monter le score | pareil |
| 4. Écarter les cinématiques | les bandes noires des cinématiques de GTA font baisser le score (les paroles sont celles du jeu, pas du streameur) | |
| 5. Trouver la webcam | un visage qui ne bouge pas pendant que le jeu bouge, et les bordures nettes autour de lui (le même cadre pour tout le stream) | pareil |
| 6. Fabriquer le clip | webcam en haut (un tiers), gameplay en bas, titre en boîte blanche façon TikTok sur la jonction, sous-titres 2 par 2 avec le mot dit surligné (police Montserrat), son normalisé à -14 LUFS | pareil |

Le chat est **compté, jamais lu** : seul le nombre de messages par seconde sert. Sur les rediffusions Twitch, l'outil
passe par l'API publique du lecteur Twitch ; sur YouTube, par le chat du replay ; en live Twitch, par une connexion
anonyme au chat (sans compte).

S'il n'y a pas de webcam, le jeu est posé au centre sur un fond flouté. Si le streameur est en plein écran (pas de
jeu), l'image est recadrée sur lui.

## Trouver des streams

Le mode `auto` fonctionne sans rien configurer :

- **en live**, il cherche les lives GTA 6 en cours sur YouTube ;
- **en rediffusion**, il regarde les dernières rediffusions des streameurs listés dans [`streamers.txt`](streamers.txt)
  (Twitch, `kick:pseudo` pour Kick ; ajoute ou retire qui tu veux) et garde celles qui ont « GTA 6 » dans le titre.

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
(MIT, fourni dans `clipper/assets/models`), [Pillow](https://python-pillow.org/) (MIT-CMU), et la police
[Montserrat](https://github.com/JulietaUla/Montserrat) (SIL OFL 1.1, fournie dans `clipper/assets/fonts`).

L'idée vient de [gta6-clipper](https://github.com/vossashtonai/gta6-clipper) d'Ashton Voss (MIT). Le code est écrit de
zéro, pour Windows comme pour Mac et Linux, avec une autre mise en page. GTA Stream Clipper n'est affilié ni à
Rockstar Games, ni à Twitch, ni à YouTube, ni aux streameurs cités en exemple.
