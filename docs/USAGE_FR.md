# ChipLoom

Un tracker MOD à quatre voies avec un cœur utilisable par un agent et une fenêtre de travail pour l'humain. Le projet conserve la partition JSON, les recettes des samples et l'export MOD autonome.

Le nom du programme est désormais **ChipLoom**. Le paquet Python et les anciens lanceurs gardent le nom `tracker4agents` pour préserver les commandes et les sessions. Les nouveaux lanceurs sont `Install ChipLoom.cmd` et `Launch ChipLoom.cmd`.

ChipLoom est conçu pour être utilisé par un agent tel que **Codex** ou **Hermès Agent** : l'agent compose et révise, le logiciel valide et produit un vrai MOD. La fenêtre sert à l'humain ; l'agent utilise le JSON, Python et la ligne de commande. Aucun modèle n'est embarqué, aucun entraînement n'est réalisé, et aucun serveur MCP n'est encore implémenté. Le [guide des agents](AGENT_GUIDE.md) explique la démarche.

## Écouter les exemples et composer avec Hermès

**[Écouter Pixel Rush et Voltage Odyssey V2](https://arthurreboulsalze.github.io/ChipLoom/)** : deux lecteurs MP3 avec les MOD et les projets téléchargeables. Les morceaux et leurs samples ont été créés pour ChipLoom.

Un test utilisateur avec **Hermès / glm-5.3-flash sur Debian 13** a abouti à deux compositions originales. Le [retour documenté](HERMES_FEEDBACK.md) distingue ce résultat de la CI et de la fenêtre Linux, qui reste à valider.

Depuis la version 0.5.0, tu peux planifier la durée, regrouper les erreurs et écouter un passage :

```sh
python -m tracker4agents estimate --orders 8 --speed 6 --bpm 128
python -m tracker4agents validate examples/pixel_rush.project.json --report
python -m tracker4agents render docs/listen/media/voltage_odyssey_v2.mod --from-order 6 --seconds 10 --output exports/drop.wav
```

À vitesse constante, durée = lignes × speed × 2,5 / BPM : huit ordres de 64 lignes à speed 6 et 128 BPM donnent une minute. `validate` tient compte des changements et sauts réels. Au-delà de 120 secondes, il émet un avertissement sans invalider le MOD. Le rapport rassemble les erreurs indépendantes, avec une première erreur par champ/sample/événement et les collisions ; les erreurs dépendantes peuvent demander une nouvelle validation après correction.

`--from-order` compte les ordres à partir de zéro. La prélecture conserve les instruments et effets actifs avant l'extrait ; la coupe suit le temps théorique, avec de petits écarts possibles selon le moteur. Limites : 600 secondes de prélecture et 120 secondes d'extrait.

## Générer une page HTML à la demande

Les deux possibilités restent disponibles. Pour créer un bundle d'écoute à partir d'un projet existant :

```powershell
python -m tracker4agents preview examples/pixel_rush.project.json --output exports/pixel-review --mp3 --language fr
```

Ouvre `exports/pixel-review/preview.html`. Le dossier contient également le MOD, le projet, le WAV, le MP3 facultatif, les samples et un rapport. Choisis un nouveau dossier à chaque révision ; pour partager, copie le dossier entier. Sans `--language fr`, les contrôles HTML sont en anglais. L'aperçu fonctionne sans Qt et complète la fenêtre native.

La [nouvelle sélection de quinze modules](../references/SELECTION_FR.md) est étudiée séparément de l'import éditable. L'analyse fonctionne avec `python -m tracker4agents analyze chemin/selection.zip --output exports/etude.json --probe`. Les originaux restent inchangés et hors du dépôt.

## Fenêtre de travail

Sous Windows, installe Python 3.12 ou plus récent, puis exécute **`Install ChipLoom.cmd`** et **`Launch ChipLoom.cmd`**. Les anciens lanceurs français restent disponibles pour compatibilité.

La fenêtre permet de :

- retrouver **First Light**, **Pixel Rush** et les fichiers récents ; ouvrir un MOD ou un projet JSON, y compris par glisser-déposer ;
- écouter, mettre en pause, déplacer l'écoute dans le morceau ou sur une ligne de pattern et suivre les quatre voies ; la boucle respecte le point de reprise du module ;
- couper ou réactiver une voie en cliquant sur son grand bouton **Track 1–4** au-dessus du pattern, ou l'écouter seule avec **Solo** ; les voies inaudibles sont atténuées visuellement, sans modifier la partition ;
- suivre l'intensité du son avec un **vu-mètre stéréo animé**, mesurant le niveau moyen et les crêtes du signal réellement décodé, également pendant l'écoute d'un sample ;
- choisir parmi quatre thèmes (**Midnight**, **Amber**, **Violet**, **Light**) et basculer entre **English** et **Français** avec les menus en haut à droite ; l'anglais est la langue par défaut ;
- afficher les samples et leurs boucles, les écouter séparément, régler volume et accord fin ;
- modifier les notes, numéros de samples et effets par double-clic, transposer une voie du pattern ou raccourcir une note avec `ECx` ;
- régler le titre, le tempo et la vitesse de départ, annuler/rétablir et enregistrer le projet ;
- exporter le **MOD**, un WAV ou un MP3 facultatif. L'export audio utilise les voies actuellement audibles ; le MOD conserve les quatre voies.

Les colonnes Smp et Effet ainsi que les numéros de lignes et d'ordres sont en hexadécimal. La transposition concerne toute la voie du pattern affiché, y compris ses autres occurrences dans la liste d'ordres. `ECx` remplace l'effet de la cellule sélectionnée. Le réglage du tempo refuse d'effacer d'autres effets s'il manque deux colonnes disponibles sur la première ligne.

`Ctrl+S` enregistre un projet JSON déjà ouvert ; pour un MOD, il propose un nouveau projet JSON. `Ctrl+Maj+S` enregistre sous un autre nom. `Ctrl+Z` annule, `Ctrl+Maj+Z` rétablit et Espace commande la lecture lorsque la table des patterns a le focus. **F5** recharge le fichier, notamment après une modification faite par l'agent. Une confirmation protège les retouches non enregistrées lors d'un changement de fichier ou d'une fermeture.

La fenêtre est une application **Qt Widgets / PySide6**, sans page HTML ni serveur local. L'écoute passe par le MOD réel, rendu en WAV par FFmpeg/libopenmpt en arrière-plan puis lu par Qt. Le cache évite de refaire le même rendu. Une modification demande une courte préparation avant la prochaine écoute ; ce n'est pas encore un moteur de tracker en temps réel. Les cycles audio restent limités à 120 secondes dans cette version.

La session et le cache restent dans le dossier de données local choisi par Qt (`AppData/Local/tracker4agents/tracker4agents` sous Windows). La fenêtre retrouve le dernier fichier, les fichiers récents, le volume, les options de suivi et de boucle, le thème et la langue. Ces deux derniers réglages s'appliquent immédiatement, sans interrompre l'écoute ni effacer une saisie en cours. Les titres et noms de samples conservent leur texte d'origine. `--state-dir` permet de choisir un autre dossier.

```powershell
.venv\Scripts\python.exe -m tracker4agents gui
.venv\Scripts\python.exe -m tracker4agents gui exports/pixel_rush/pixel_rush.mod
```

**La fenêtre est facultative pour l'agent.** Le cœur, le modèle de document, les recettes, l'import/export et les commandes structurées fonctionnent sans PySide6, sans écran et sans application ouverte. L'agent modifie le même projet que l'humain via le JSON ou l'API Python ; la fenêtre le recharge. Il n'a pas besoin de piloter l'interface avec une souris. L'intégration MCP reste à développer.

La base est préparée pour Linux avec `pathlib`, les dossiers de données Qt et les mêmes widgets et services. Une installation Linux se prépare avec `python3 -m venv .venv`, puis `.venv/bin/python -m pip install -e '.[desktop]'`, et se lance avec `sh launch-chiploom.sh`. FFmpeg avec libopenmpt et les dépendances système Qt doivent être présents. **Le cœur et des rendus FFmpeg sont vérifiés par la CI Ubuntu ; la fenêtre Linux et sa sortie audio physique restent à valider.** Les conditions système sont décrites dans la [documentation officielle de Qt for Python](https://doc.qt.io/qtforpython-6/gettingstarted.html).

Les prochaines options proposées et les limites de cette tranche sont dans [CONCEPTION.md](../CONCEPTION.md).

La démo **First Light** est une composition originale de seize mesures, à 125 BPM. Elle dure **30,72 secondes** et utilise **huit samples créés pour le projet**. Son fichier MOD pèse **17 206 octets** et contient tous les sons nécessaires à sa lecture.

## Écouter et examiner le prototype

Les fichiers prêts à utiliser sont dans `exports/first_light` :

- `first_light.mod` : le module principal, éditable dans un tracker compatible.
- `first_light.mp3` : la copie d’écoute optionnelle.
- `first_light.wav` : le rendu PCM du MOD avec libopenmpt via FFmpeg.
- `first_light.libxmp.wav` : le rendu du même MOD par un second moteur indépendant.
- `first_light.project.json` : la partition et les recettes des samples.
- `preview.html` : la page d’écoute et d’inspection des patterns et des samples.
- `validation.json` : les résultats des contrôles, les versions et les empreintes des fichiers.
- `samples/01.wav` à `samples/08.wav` : les aperçus individuels des sons.

Ouvre `preview.html` dans ton navigateur. Si ton navigateur limite l’audio des pages locales, lance depuis le dossier du projet :

```powershell
python tools/serve_previews.py --port 8764 --directory exports/first_light
```

Puis ouvre [l’aperçu local](http://127.0.0.1:8764/preview.html). Le serveur s’arrête avec `Ctrl+C`. La page est autonome et n’utilise aucun service distant.

## Pixel Rush

Le deuxième morceau vise une couleur plus chiptune, avec un beat à **160 BPM**, des ondes triangulaires et carrées très courtes, des changements de timbre pendant les notes et des glissés. Il dure **48 secondes**, utilise **13 samples créés pour le projet** et enchaîne huit ordres sur sept patterns. Le MOD pèse **12 924 octets**.

Les fichiers sont dans `exports/pixel_rush` : `pixel_rush.mod`, `pixel_rush.mp3`, les deux rendus WAV, le projet JSON, l’aperçu et le rapport de validation. La partition à modifier est aussi disponible dans `examples/pixel_rush.project.json`.

```powershell
python -m tracker4agents demo --song pixel-rush --with-xmp --mp3
```

Sans `--with-xmp`, la génération demande seulement le rendu principal par FFmpeg. Les deux modules que tu as fournis ont servi à examiner la construction et les procédés tracker ; les observations sont conservées dans [l’analyse des références](../references/ANALYSE.md).

Pour consulter les deux compositions avec un seul serveur local :

```powershell
python tools/serve_previews.py --port 8765
```

Ouvre alors [Pixel Rush](http://127.0.0.1:8765/pixel_rush/preview.html) ou [First Light](http://127.0.0.1:8765/first_light/preview.html).

Ce serveur prend en charge les plages d’octets HTTP, nécessaires pour déplacer immédiatement l’écoute dans un WAV sans attendre son téléchargement complet.

## Régénérer la démo

Il faut Python 3.12 ou plus récent. Le cœur du projet utilise uniquement la bibliothèque standard Python. Le rendu principal et le MP3 demandent un FFmpeg disposant respectivement de libopenmpt et de libmp3lame, accessible dans le PATH.

Toutes les commandes ci-dessous se lancent depuis la racine du projet. Aucune installation Python du paquet n’est nécessaire pour les commandes de l'agent. La fenêtre ajoute seulement la dépendance facultative `desktop`.

```powershell
python -m tracker4agents demo --mp3
```

Le MOD est toujours généré. `--mp3` ajoute une copie d’écoute encodée depuis le WAV issu du MOD. Pour produire seulement le MOD, le projet et les aperçus des samples, sans lecteur externe :

```powershell
python -m tracker4agents demo --no-audio
```

`--output` choisit un autre dossier de sortie. `--seed` change la graine des composantes de bruit ; la partition reste celle de First Light. Les mêmes recettes et la même version de l’outil reproduisent le même MOD dans l’environnement testé.

Pour activer le second moteur, le script suivant télécharge les sources officielles de libxmp 4.7.3, vérifie leur SHA256 et construit la bibliothèque dans `.tools/libxmp`. Sous Windows, il nécessite CMake et les outils C++ de Visual Studio ; les outils déjà installés sur cette machine ont servi à la validation.

```powershell
python tools/setup_reference.py
python -m tracker4agents demo --with-xmp --mp3
```

Les sources, la bibliothèque compilée et sa licence restent dans `.tools`. Le manifeste conserve l’URL, la version et les empreintes. Le script ne fait aucune installation système. FFmpeg utilise la version de libopenmpt incluse dans sa propre compilation ; sa bannière est conservée dans le rapport.

## Modifier la musique avec un agent

Le fichier de départ est `examples/first_light.project.json`. Un agent peut lire et modifier ce JSON, puis utiliser les commandes suivantes :

```powershell
python -m tracker4agents validate examples/first_light.project.json
python -m tracker4agents inspect examples/first_light.project.json --pattern 0
python -m tracker4agents export examples/first_light.project.json --output exports/custom.mod
python -m tracker4agents render exports/custom.mod --output exports/custom.wav --mp3-output exports/custom.mp3
```

Pour un rendu avec libxmp :

```powershell
python -m tracker4agents render exports/custom.mod --engine xmp --output exports/custom.libxmp.wav
```

Les commandes réussies renvoient du JSON. Les erreurs de données ou de rendu renvoient un objet d’erreur sur stderr et un code de sortie non nul. Un export valide les données avant de remplacer sa destination ; un rendu utilise un fichier temporaire avant de remplacer sa sortie.

Les lignes et les voies sont numérotées à partir de zéro. Les emplacements de samples vont de 1 à 31 ; zéro conserve le sample courant. Les notes utilisent la notation historique ProTracker `C-1` à `B-3`. Leur hauteur sonore dépend aussi du sample : ces noms ne sont pas les octaves de la notation scientifique.

Un événement est une cellule :

```json
{"row": 8, "channel": 3, "note": "E-3", "sample": 8, "effect": "C27"}
```

`effect` contient trois chiffres hexadécimaux. Ici, `C27` fixe le volume à 39 sur une échelle de 0 à 64. Un événement sans note peut modifier le volume, le vibrato ou un autre effet de la voix déjà en cours. Une cellule absente est vide.

Les samples peuvent être définis par une recette numérique (`draw`, `kick`, `snare`, `hat`, `kick_hat`, `snare_hat`, `pluck`) ou par des valeurs PCM signées 8 bits. Une recette produit son PCM et ses points de boucle ; elle ne contient pas de code exécutable. Les ondes dessinées emploient des points d’amplitude, une fréquence cible et un nombre de cycles. Les sons courts intègrent leur enveloppe directement dans le sample.

L’import est aussi disponible pour les fichiers appartenant au profil strict du prototype :

```powershell
python -m tracker4agents import exports/first_light/first_light.mod --output exports/imported.project.json
```

Un import MOD conserve le PCM, mais ne peut pas retrouver les recettes de synthèse ni les noms des patterns qui n’existent pas dans le format. Les fichiers hors profil sont refusés avec une erreur, sans conversion approximative.

## Profil MOD pris en charge

`protracker-4ch-pal-v1` cible les MOD `M.K.` non compressés : quatre voies, 64 lignes par pattern, jusqu’à 64 patterns, 128 ordres et 31 samples. Les samples sont mono, signés 8 bits, de longueur paire et limités à 65 534 octets chacun. Les textes du module sont limités à l’ASCII imprimable. Les variantes à 15 samples, `M!K!`, les extensions PC et les modules compressés restent hors périmètre.

Le prototype accepte les effets simples `0` à `7`, `9`, `A`, `B`, `C`, `D`, `F`, ainsi que les extensions `E0`, `E1`, `E2`, `E4`, `E5`, `E9`, `EA`, `EB`, `EC`, `ED`. Les paramètres de volume, de saut et de tempo sont contrôlés. `Dxx` utilise une ligne décimale codée en BCD. `F00`, `F20`, les boucles de pattern `E6x`, les délais de pattern `EEx` et l’effet destructif `EFx` sont exclus du profil initial.

Les durées reposent sur le timing CIA. Les rendus sont bornés à 120 secondes et s’exécutent dans des processus disposant d’un délai maximum. La démo réinitialise vitesse, tempo et filtre au début, puis revient au premier ordre par `B00`.

La fenêtre constitue un premier éditeur de cellules et de réglages ; le dessin interactif des samples et l'édition de l'arrangement restent à développer. Les pages d'aperçu précédentes continuent de fonctionner pour partager un morceau, mais ne sont plus nécessaires au travail quotidien. L'intégration MCP, l'analyse d'un corpus et les formats XM/IT sont des étapes suivantes du [plan](../PLAN_PROJET.md). Aucun entraînement de modèle n'est inclus.

## Vérifications

```powershell
python -m unittest discover -s tests -v
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

La suite comprend **54 tests** : les 23 contrôles initiaux du format, des rendus et du serveur, 12 tests du document et de la session, 3 tests des traductions et thèmes, 9 tests d'intégration Qt et 7 tests des bundles HTML et de l'analyse de références. Ces derniers utilisent les vrais WAV rendus par FFmpeg, le lecteur multimédia Qt, la saisie au clavier, l'annulation, les exports et la réouverture d'une fenêtre. Ils vérifient aussi la boucle après une introduction, les résultats audio devenus obsolètes, la reprise après une erreur de rendu, les clics rapides de mute, les changements de langue et thème pendant une saisie et les niveaux audio, y compris un mix entièrement muet. Le son est coupé pendant les tests : l'avancement du lecteur et ses buffers sont vérifiés, pas les enceintes physiques. Les essais Qt sont ignorés sans PySide6 ou FFmpeg ; les essais libxmp sont ignorés sans cette bibliothèque.

Les quatre thèmes ont aussi été inspectés dans des fenêtres Windows natives ; les captures et rapports sont dans `exports/desktop`. Un nouveau processus a confirmé la restauration du thème et de la langue après fermeture complète.

Le rapport de la démo contient **13 contrôles réussis** : reconstruction identique du MOD, signal présent, durée complète et absence de saturation PCM dans les deux lecteurs, puis correspondance des 256 lignes avec la trace d’exécution libxmp. Un test séparé vérifie deux boucles consécutives. Ces contrôles ne remplacent pas l’écoute musicale et ne valident pas un véritable Amiga.

La conception retenue et les limites actuelles sont décrites dans [CONCEPTION.md](../CONCEPTION.md).
