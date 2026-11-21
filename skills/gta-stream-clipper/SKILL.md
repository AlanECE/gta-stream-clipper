---
name: gta-stream-clipper
description: Transforme des streams GTA (Twitch, Kick, YouTube) en clips verticaux prêts à poster - webcam du streameur en haut (un tiers), gameplay en bas, titre façon texte TikTok (boîte blanche, emojis Apple) posé sur la jonction, sous-titres deux mots par deux mots avec le mot dit en jaune. Clips viraux Twitch (les plus vus, par langue ou streameur, sans clé), lien de rediffusion, recherche automatique des rediffusions GTA 6, live, et une interface graphique (python -m clipper app). Utiliser dès que l'utilisateur dit « clippe ce stream », « fais des clips de <streamer> », « clip le live de », « trouve les streams GTA », « fais-moi des clips GTA 6 », ou donne un lien Twitch/Kick/YouTube de stream à découper en clips.
---

# GTA Stream Clipper

L'outil est un module Python : `python -m clipper …`, lancé **depuis le dossier du dépôt** (par défaut
`~/gta-stream-clipper` ; sinon cherche le dossier qui contient `clipper/__main__.py`). Les clips arrivent dans
`clips/` de ce dossier (ou `--sortie`).

Si `python -m clipper --help` échoue : `pip install -r requirements.txt` dans le dépôt, et FFmpeg
(`winget install Gyan.FFmpeg` sur Windows, `brew install ffmpeg` sur Mac).

## L'interface graphique

`python -m clipper app` ouvre l'interface dans le navigateur (clips viraux, lien, en direct, bibliothèque avec
aperçu, modification du titre, des sous-titres et du style, téléchargement). Si l'utilisateur veut cliquer plutôt
que discuter, lance-la (en arrière-plan) et donne-lui l'adresse affichée.

## Clips viraux (le plus simple et le plus fiable)

```bash
python -m clipper viral --langue-clips fr --liste [--periode jour|semaine|mois] [--chaine <pseudo>]
python -m clipper viral --langue-clips fr --choix 1,3 --titres "Titre 1 😭|Titre 2 💀"
```
Les viewers ont déjà choisi ces moments. Lis les titres des clips (souvent courts ou en argot), choisis ceux qui
parlent de GTA, écris un titre français façon TikTok par clip (`--titres` dans l'ordre de `--choix`).

## Mode 1 (un lien) : toujours en deux temps, c'est toi qui choisis

Le score automatique se trompe parfois : une scène du jeu très bruyante ou un dialogue de mission peuvent passer
devant une vraie réaction. Ton travail, c'est de choisir.

1. **Analyse** (rien n'est monté) :
   ```bash
   python -m clipper lien "<lien Twitch ou Kick>" --analyse [--de 1:00:00 --a 3:00:00] [--langue fr]
   ```
   Sur un stream de plusieurs heures, commence par une plage d'1 h environ où il joue vraiment à GTA (regarde le
   titre, ou demande à l'utilisateur). La sortie liste les candidats numérotés avec ce qui est dit ; le détail est dans
   `clips/.travail/<streamer>-<id>/moments.json` (champ `cinematique` = scène du jeu repérée).

2. **Choisis** les moments où **le streameur lui-même** réagit : il crie, rit, panique, parle à son chat
   (« chat », « les gars », « y'all », « no way »), jure contre le jeu. Écarte les dialogues de personnages
   (phrases de scénario, ordres de mission) et les candidats marqués `cinematique` sauf s'il y parle lui-même.
   Écarte aussi ce qui n'est pas du jeu (il regarde une vidéo, un combat…). Entre 1 et 5 clips, les meilleurs d'abord.

3. **Écris un titre par clip**, façon TikTok : en français, phrase normale (pas tout en majuscules), qui dit ce qui se
   passe, avec le nom du streameur, et un ou deux emojis à la fin : `Kai Cenat est bloqué sur GTA 6 😭`,
   `Les flics arrivent sur Jolavanille dans GTA 6 💀`. 55 caractères au plus.

4. **Monte** (l'analyse est en cache, rien n'est retéléchargé) :
   ```bash
   python -m clipper lien "<lien>" --choix 2,5 --titres "Titre du 2 😭|Titre du 5 💀" [mêmes --de/--a/--langue]
   ```

5. **Vérifie** : extrais une image de chaque clip (`ffmpeg -ss 3 -i clip.mp4 -frames:v 1 apercu.jpg`, puis une à
   ~10 s) et regarde-la. La webcam doit montrer le streameur (pas de bout de jeu ni de chat dedans), le titre et les
   sous-titres lisibles. Si le cadre de la webcam est faux : `python -m clipper refaire clips/<clip>.json --cam x,y,largeur,hauteur`
   (pixels de la vidéo source).

6. **Donne** à l'utilisateur la liste des clips (chemins), et pour chacun le titre et la légende du `.txt`.

## Mode 2 (auto) : il cherche tout seul

- `python -m clipper auto --liste` : les dernières rediffusions GTA 6 des streameurs de `streamers.txt`
  (Twitch, `kick:pseudo` pour Kick). Puis le mode 1 sur le lien choisi.
- `python -m clipper chaine <pseudo> --analyse` (ou `chaine kick:<pseudo>`) : la dernière rediffusion GTA d'un
  streameur, puis `lien <lien trouvé> --choix …`.
- `python -m clipper auto --live --liste` : les lives GTA 6 en cours.

## Live

`python -m clipper live <pseudo ou lien> --minutes 60` (les lives GTA du moment, par langue, sont dans l'onglet
« En direct » de l'interface). Sur un serveur : `python -m clipper app --host 0.0.0.0 --mot-de-passe <mdp> --sans-navigateur`
dans tmux, puis l'utilisateur lance les surveillances depuis son navigateur. Ça tourne longtemps : lance-le en arrière-plan et préviens
l'utilisateur qu'un clip sort ~1 minute après chaque moment fort. Pas de choix manuel ici : `--seuil 1.3` pour être
plus exigeant, `--seuil 0.8` pour plus de clips.

## Réglages du rendu

`--mots 1` (mot par mot ; défaut 2 par 2), `--style jaune|tout-jaune|blanc|boite-jaune|boite-violette|boite-rouge|boite-verte|#RRGGBB` (défaut jaune),
`--sous-titres-y 0.68`, `--separateur` (bande jaune entre webcam et jeu), `--sans-titre`, `--titre` (un titre pour
tous ; `{streamer}` et `{jeu}` remplacés), `--titre-langue en`, `--jeu "GTA 5"`, `--langue fr`, `--sans-chat`,
`--nb`, `--duree`. `refaire <clip.json>` accepte les mêmes réglages.

## Règles

- Rappelle à l'utilisateur de ne clipper que des streameurs d'accord pour être clippés, et de regarder chaque clip
  avant de le poster.
- Ne télécharge jamais de stream réservé aux abonnés en contournant la protection.
