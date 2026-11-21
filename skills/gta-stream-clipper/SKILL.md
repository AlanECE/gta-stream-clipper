---
name: gta-stream-clipper
description: Transforme des streams GTA (Twitch, YouTube, Kick) en clips verticaux prêts à poster - webcam du streameur en haut, gameplay en bas, titre cartoon qui rebondit au début, sous-titres 2-3 mots par 2-3 mots entre les deux. Rediffusion, live, dernières rediffusions d'une chaîne, ou recherche des plus gros streams GTA du moment. Utiliser dès que l'utilisateur dit « clippe ce stream », « fais des clips de <streamer> », « clip le live de », « trouve les streams GTA », « fais-moi des clips GTA 6 », ou donne un lien Twitch/YouTube/Kick de stream à découper en clips.
---

# GTA Stream Clipper

L'outil est un module Python : `python -m clipper …`, lancé **depuis le dossier du dépôt** (par défaut
`~/gta-stream-clipper` ; sinon cherche le dossier qui contient `clipper/__main__.py`). Les clips arrivent dans
`clips/` de ce dossier (ou `--sortie`).

Si `python -m clipper --help` échoue : `pip install -r requirements.txt` dans le dépôt, et FFmpeg
(`winget install Gyan.FFmpeg` sur Windows, `brew install ffmpeg` sur Mac).

## Rediffusion : toujours en deux temps, c'est toi qui choisis

Le score automatique se trompe parfois : une scène du jeu très bruyante ou un dialogue de mission peuvent passer
devant une vraie réaction. Ton travail, c'est de choisir.

1. **Analyse** (rien n'est monté) :
   ```bash
   python -m clipper rediff "<lien>" --analyse [--de 1:00:00 --a 3:00:00]
   ```
   La sortie liste les candidats numérotés avec ce qui est dit ; le détail est dans
   `clips/.travail/<streamer>-<id>/moments.json` (champ `cinematique` = scène du jeu repérée).

2. **Choisis** les moments où **le streameur lui-même** réagit : il crie, rit, panique, parle à son chat
   (« chat », « bro », « y'all », « no way »), jure contre le jeu. Écarte les dialogues de personnages
   (phrases de scénario, noms de personnages, « they froze our accounts », ordres de mission) et les candidats
   marqués `cinematique` sauf s'il y parle lui-même. Entre 1 et 5 clips, les meilleurs d'abord.

3. **Écris un titre par clip**, en français, court, en majuscules, qui commence par le nom du streameur et finit par
   « SUR GTA 6 » (ou le jeu) : `KAI CENAT SE FOIRE SUR GTA 6`, `KAI CENAT PANIQUE SUR GTA 6`,
   `XQC N'Y CROIT PAS SUR GTA 6`. Le titre doit coller à ce qui se passe dans le moment. 40 caractères au plus.

4. **Monte** (l'analyse est en cache, rien n'est retéléchargé) :
   ```bash
   python -m clipper rediff "<lien>" --choix 2,5 --titres "TITRE DU 2|TITRE DU 5" [mêmes --de/--a]
   ```

5. **Vérifie** : extrais une image de chaque clip (`ffmpeg -ss 1 -i clip.mp4 -frames:v 1 apercu.jpg`, puis une à
   ~8 s) et regarde-la. La webcam doit montrer le streameur entier (pas de bout de jeu ni de chat dedans), le titre
   et les sous-titres lisibles. Si le cadre de la webcam est faux, refais le clip avec le bon cadre en pixels de la
   vidéo source : `python -m clipper refaire clips/<clip>.json --cam x,y,largeur,hauteur`.

6. **Donne** à l'utilisateur la liste des clips (chemins), et pour chacun le titre et la légende du `.txt`.

## Les autres modes

- **Live** (lien ou pseudo Twitch) : `python -m clipper live <pseudo> --minutes 60`. Ça tourne longtemps : lance-le
  en arrière-plan et préviens l'utilisateur qu'un clip sort ~1 minute après chaque moment fort. Pas de choix
  manuel ici : `--seuil 1.3` pour être plus exigeant, `--seuil 0.8` pour plus de clips.
- **Dernières rediffusions d'un streameur** : `python -m clipper chaine <pseudo> --videos 1` (filtre « GTA » dans
  le titre ; `--filtre ""` pour tout). Pour garder la main, préfère : `python -m clipper chaine <pseudo> --analyse`
  puis `rediff <lien trouvé> --choix …`.
- **Trouver des streams** : `python -m clipper trouver --liste` (rediffusions des streameurs de `streamers.txt`),
  `python -m clipper trouver --live --liste` (lives GTA 6 en cours). Puis `rediff` ou `live` sur le lien choisi.
- **Vidéo locale** : `python -m clipper fichier <video.mp4> --streamer <nom>`.

## Options utiles

`--nb` (3), `--duree` (30 s), `--de`/`--a`, `--titre` (un titre pour tous ; `{streamer}` et `{jeu}` remplacés),
`--titre-langue en` (titres automatiques en anglais), `--jeu "GTA 5"`, `--langue en` (langue parlée),
`--sans-separateur`, `--titre-duree 0` (pas de titre).

## Règles

- Rappelle à l'utilisateur de ne clipper que des streameurs d'accord pour être clippés, et de regarder chaque clip
  avant de le poster.
- Ne télécharge jamais de stream réservé aux abonnés en contournant la protection.
