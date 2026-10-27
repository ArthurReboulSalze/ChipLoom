# ChipLoom

Un tracker MOD à quatre voies avec un cœur utilisable par un agent et une fenêtre de travail pour l'humain. Le projet conserve la partition JSON, les recettes des samples et l'export MOD autonome.

Le nom du programme est **ChipLoom**. Le paquet Python garde le nom `tracker4agents` pour préserver les commandes, les projets et les sessions. Les lanceurs sont `Install ChipLoom.cmd` et `Launch ChipLoom.cmd` sous Windows, `launch-chiploom.sh` sous Linux. Les anciens lanceurs en français (`Lancer tracker4agents.cmd`, `Installer interface Windows.cmd`, `lancer-tracker4agents.sh`) ont été retirés en 0.7.0.

ChipLoom est conçu pour être utilisé par un agent tel que **Codex** ou **Hermès Agent** : l'agent compose et révise, le logiciel valide et produit un vrai MOD. La fenêtre sert à l'humain ; l'agent utilise le JSON, Python et la ligne de commande. Aucun modèle n'est embarqué et aucun entraînement n'est réalisé. Un adaptateur MCP facultatif (`chiploom mcp`) enveloppe la ligne de commande ; il est testé automatiquement, mais pas avec des clients MCP précis, et un agent doté d'un terminal peut s'en passer. Le [guide des agents](AGENT_GUIDE.md) explique la démarche.

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

Sous Windows, installe Python 3.12 ou plus récent, puis exécute **`Install ChipLoom.cmd`** et **`Launch ChipLoom.cmd`**.

Un dossier Windows autonome peut aussi être construit avec `python tools/build_windows.py` (option `--zip` pour une archive), après l'installation de `.[desktop]` et de PyInstaller. Le résultat, `build/windows/ChipLoom/`, contient `ChipLoom.exe` (la fenêtre) et `chiploom-cli.exe` (la ligne de commande, nommée autrement parce que Windows ignore la casse des noms de fichiers). FFmpeg n'est pas inclus ; libxmp l'est si la bibliothèque a été construite avant. Le paquet est préparé pour PyPI mais pas encore publié.

La fenêtre permet de :

- retrouver **First Light**, **Pixel Rush** et les fichiers récents ; ouvrir un MOD ou un projet JSON, y compris par glisser-déposer ;
- écouter, mettre en pause, déplacer l'écoute dans le morceau ou sur une ligne de pattern et suivre les quatre voies ; la boucle respecte le point de reprise du module ;
- couper ou réactiver une voie en cliquant sur son grand bouton **Track 1–4** au-dessus du pattern, ou l'écouter seule avec **Solo** ; les voies inaudibles sont atténuées visuellement, sans modifier la partition ;
- suivre l'intensité du son avec un **vu-mètre stéréo animé**, mesurant le niveau moyen et les crêtes du signal réellement décodé, également pendant l'écoute d'un sample ;
- choisir parmi quatre thèmes (**Midnight**, **Amber**, **Violet**, **Light**) et basculer entre **English** et **Français** avec les menus en haut à droite ; l'anglais est la langue par défaut ;
- afficher les samples et leurs boucles, les écouter séparément, régler volume et accord fin ;
- modifier les notes, numéros de samples et effets par double-clic, au clavier (voir ci-dessous) ou par blocs, et transposer une voie du pattern ;
- éditer la liste d'ordres et suivre les modifications faites par l'agent, en direct ou à travers le fichier ;
- régler le titre, le tempo et la vitesse de départ, annuler/rétablir et enregistrer le projet ;
- exporter le **MOD**, un WAV ou un MP3 facultatif. L'export audio utilise les voies actuellement audibles ; le MOD conserve les quatre voies.

Les colonnes Smp et Effet ainsi que les numéros de lignes et d'ordres sont en hexadécimal. La transposition concerne toute la voie du pattern affiché, y compris ses autres occurrences dans la liste d'ordres. Les effets s'éditent directement dans le tableau. Les réglages du morceau, les exports WAV/MP3 et le vu-mètre se trouvent en haut de la fenêtre : le tracker occupe toute la largeur à droite de la bibliothèque. Le réglage du tempo refuse d'effacer d'autres effets s'il manque deux colonnes disponibles sur la première ligne.

### Saisie au clavier, blocs et ordres

- **Saisie des notes** : active le **mode saisie** (`Ctrl+E`), puis joue les touches du piano. La rangée du bas commence à l'octave de base, celle du haut une octave plus haut. **Octave** se règle avec `F1` à `F3` ou `+`/`−` du pavé numérique ; **Pas** fixe le nombre de lignes dont le curseur avance après chaque saisie. Le réglage **Clavier** propose Auto, QWERTY et AZERTY ; Auto choisit AZERTY lorsque la langue de saisie est le français.
- Touches QWERTY : rangée du bas `Z S X D C V G B H N J M , L . ; /`, rangée du haut `Q 2 W 3 E R 5 T 6 Y 7 U I 9 O 0 P`. Touches AZERTY : rangée du bas `W S X D C V G B H N J , ; L : M !`, rangée du haut `A é Z " E R ( T - Y è U I ç O à P`.
- Dans les colonnes Smp et Effet, les chiffres hexadécimaux se tapent directement (en AZERTY, la rangée des chiffres sans Maj est acceptée). `Suppr` efface la cellule ; `Retour arrière` l'efface et remonte d'une ligne.
- **Blocs** : `Ctrl+C`, `Ctrl+X` et `Ctrl+V` copient, coupent et collent. Le presse-papiers contient le même texte en grille que celui affiché par l'agent (`inspect --grid`) : on peut donc coller ce que l'agent a écrit. `Alt` + flèches déplace le bloc ; `Ctrl+↑`/`Ctrl+↓` le transpose d'un demi-ton et `Ctrl+Maj+↑`/`Ctrl+Maj+↓` d'une octave.
- **Éditeur d'ordres** : **Insérer**, **Nouveau**, **Dupliquer**, **Retirer**, ↑/↓ pour déplacer et **Renommer…** le pattern courant.

### Rechargement automatique

Lorsque le fichier ouvert change sur le disque (par exemple après une commande `patch` de l'agent), la fenêtre le recharge d'elle-même. Sans modification locale non enregistrée, le rechargement forme une seule étape annulable, « Agent changes ». S'il existe des modifications locales, la fenêtre fait une fusion à trois voies : les cellules en conflit sont listées dans la barre d'état et la version du fichier est conservée. Les cellules modifiées clignotent. **F5** recharge toujours à la demande.

### Collaboration en direct avec l'agent

Le menu **Agent** contient **Collaboration en direct**, activée par défaut ; un indicateur de la barre d'état affiche *Direct : désactivé*, *à l'écoute* ou *agent connecté*. L'agent trouve la fenêtre avec `chiploom live`.

- Les modifications de l'agent apparaissent aussitôt, surlignées, et s'annulent avec `Ctrl+Z` comme les tiennes.
- L'agent voit tes modifications. S'il devait en écraser une, la sienne est refusée (`LIVE_CONFLICT`) : il relit puis s'adapte. Tes modifications l'emportent.
- Pour une réécriture plus large (« refais la basse »), l'agent peut envoyer une **proposition**. L'onglet **Agent** du bas la montre en superposition violette. **Écouter la proposition**, puis **Accepter** (`Ctrl+Entrée`) ou **Refuser** ; **Effacer l'aperçu** retire la superposition. Si le morceau a changé entre-temps, une boîte de conflit liste les cellules et demande s'il faut accepter quand même et les écraser.
- Les versions annoncées par l'agent (`take`) apparaissent dans le même onglet ; **Ouvrir la version** la charge.
- L'agent peut demander à la fenêtre de lire, d'arrêter, de se placer, de sélectionner un passage ou d'ouvrir un fichier. L'ouverture te demande d'abord ce qu'il faut faire des modifications non enregistrées.

Sans fenêtre, `chiploom live serve MORCEAU.json` héberge la même session sans interface. Le serveur n'écoute que sur la machine locale (loopback) et exige un jeton que la ligne de commande lit seule. Voir la [référence CLI](CLI.md#live-sessions) et le [guide des agents](AGENT_GUIDE.md#composing-with-the-owner-in-the-window-live).

`Ctrl+S` enregistre un projet JSON déjà ouvert ; pour un MOD, il propose un nouveau projet JSON. `Ctrl+Maj+S` enregistre sous un autre nom. `Ctrl+Z` annule, `Ctrl+Maj+Z` rétablit et Espace commande la lecture lorsque la table des patterns a le focus. **F5** recharge le fichier, notamment après une modification faite par l'agent. Une confirmation protège les retouches non enregistrées lors d'un changement de fichier ou d'une fermeture.

La fenêtre est une application **Qt Widgets / PySide6**, sans page HTML. Lorsque libxmp est disponible, elle joue le morceau **en temps réel** : les modifications, les coupures de voies et les solos s'entendent aussitôt, sans nouveau rendu. Les exports et les copies d'écoute restent rendus par FFmpeg/libopenmpt ; de petites différences entre les deux moteurs sont possibles. Sans libxmp, la fenêtre revient à l'écoute rendue : le MOD réel est rendu en WAV en arrière-plan puis lu par Qt, avec un cache, et une modification demande une courte préparation avant la prochaine écoute. Sous Windows, `python tools/setup_reference.py` construit la libxmp épinglée ; sous Linux, le paquet `libxmp4` convient. Les cycles audio rendus restent limités à 120 secondes.

Le temps réel tourne dans son propre fil d'exécution : déplacer la fenêtre ou ouvrir une boîte de dialogue ne coupe plus le son. **Lecture → Tampon audio** règle la latence (80, 150, 300 ou 600 ms, 150 par défaut) ; un tampon plus court fait entendre une modification plus vite, un tampon plus long laisse plus de marge à une machine chargée. Le réglage s'applique sans arrêter la lecture et reste mémorisé.

La session et le cache restent dans le dossier de données local choisi par Qt (`AppData/Local/tracker4agents/tracker4agents` sous Windows). La fenêtre retrouve le dernier fichier, les fichiers récents, le volume, les options de suivi et de boucle, le thème, la langue et le dossier de bibliothèque de samples. Thème et langue s'appliquent immédiatement, sans interrompre l'écoute ni effacer une saisie en cours. Les titres et noms de samples conservent leur texte d'origine. `--state-dir` permet de choisir un autre dossier.

### Bibliothèque de samples dans la fenêtre

La zone du bas propose **Samples du morceau** et **Bibliothèque**. Le tracker garde
toute sa largeur ; le séparateur horizontal permet d'ajuster la hauteur des deux zones.

1. Dans **Bibliothèque**, clique sur **Dossier…** pour choisir une banque contenant
   `library.json`. Depuis ce dépôt, `exports/sample_library` est détecté par défaut.
   **Actualiser** recharge les ajouts et les étiquettes modifiés par l'agent.
2. Recherche un nom, un identifiant ou une étiquette et filtre par type ou rôle.
   **Compatibles MOD** affiche les entrées immédiatement utilisables. Les rôles restent
   des suggestions, à confirmer par écoute.
3. Sélectionne un sample pour voir sa forme d'onde et ses réglages. **Écouter** ou un
   double-clic lance l'audition à la note choisie ; **Stop** l'arrête. Le vu-mètre du haut
   suit aussi cette audition. La lecture du morceau se met en pause pendant l'écoute.
4. Garde **Emplacement libre**, puis clique sur **Ajouter au morceau**. Le PCM et ses
   réglages sont incorporés au projet ; les notes de la partition ne sont pas modifiées.
   Pour un emplacement occupé, choisis-le et coche explicitement **Remplacer**. Si les
   31 emplacements sont remplis, ce choix devient nécessaire.
5. **Ctrl+Z** annule l'ajout ou le remplacement ; le rétablissement est disponible.
   Enregistre le projet ou exporte le MOD pour conserver la modification.

Pour les quelques entrées nécessitant une adaptation, décoche le filtre de compatibilité
et sélectionne le sample. **Adapter la copie** autorise la préparation limitée décrite
dans le [contrat CLI](CLI.md#local-sample-library) ; l'original de la banque est conservé.
Les autres incompatibilités bloquent l'ajout. Une bibliothèque absente laisse le morceau
ouvert et éditable ; le bouton **Dossier…** permet de la retrouver.

Le projet JSON et le MOD sont autonomes après insertion. La bibliothèque et les caches
audio restent locaux. Par défaut, la composition utilise uniquement les samples de la banque. Sur demande,
un morceau peut être fait uniquement de samples créés (voir plus bas).

```powershell
.venv\Scripts\python.exe -m tracker4agents gui
.venv\Scripts\python.exe -m tracker4agents gui exports/pixel_rush/pixel_rush.mod
```

**La fenêtre est facultative pour l'agent.** Le cœur, le modèle de document, les recettes, l'import/export et les commandes structurées fonctionnent sans PySide6, sans écran et sans application ouverte. L'agent modifie le même projet que l'humain via le JSON, `patch`, l'API Python ou une session en direct ; la fenêtre le recharge ou l'affiche aussitôt. Il n'a pas besoin de piloter l'interface avec une souris. L'adaptateur MCP (`chiploom mcp`) est facultatif.

La base est préparée pour Linux avec `pathlib`, les dossiers de données Qt et les mêmes widgets et services. Une installation Linux se prépare avec `python3 -m venv .venv`, puis `.venv/bin/python -m pip install -e '.[desktop]'`, et se lance avec `sh launch-chiploom.sh`. FFmpeg avec libopenmpt et les dépendances système Qt doivent être présents. **Le cœur et des rendus FFmpeg sont vérifiés par la CI Ubuntu ; la fenêtre Linux et sa sortie audio physique restent à valider.** Les conditions système sont décrites dans la [documentation officielle de Qt for Python](https://doc.qt.io/qtforpython-6/gettingstarted.html).

Les prochaines options sont dans la [feuille de route](ROADMAP.md) ; les anciennes notes de conception sont dans [history/CONCEPTION.md](history/CONCEPTION.md).

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

Les commandes réussies renvoient du JSON. Les erreurs de données ou de rendu renvoient sur stderr un objet `{"ok": false, "error", "code", "message"}` (avec `message_fr` pour le texte français d'origine) et le code de sortie 2. Les scripts doivent se fonder sur `code`, jamais sur la formulation ; la liste des codes est dans la [référence CLI](CLI.md#error-contract-and-codes). Un export valide les données avant de remplacer sa destination ; un rendu utilise un fichier temporaire avant de remplacer sa sortie.

Les lignes et les voies sont numérotées à partir de zéro. Les emplacements de samples vont de 1 à 31 ; zéro conserve le sample courant. Les notes utilisent la notation historique ProTracker `C-1` à `B-3`. Leur hauteur sonore dépend aussi du sample : ces noms ne sont pas les octaves de la notation scientifique.

Depuis la version 0.7.0, les nouveaux projets utilisent le schéma `tracker4agents.project.v2`. Chaque pattern est une grille de lignes (`rows`) : la clé est un numéro de ligne hexadécimal à deux chiffres, `00` à `3F`, et la valeur contient les quatre cellules séparées par `|`. Une cellule s'écrit `NOTE SS EEE` ; `---`, `--` et `...` désignent une note, un sample et un effet vides. Les lignes entièrement vides sont omises.

```json
{"name": "Boot", "rows": {
  "00": "C-2 04 F06 | E-1 06 FA0 | E-2 08 037 | E-2 0A E01",
  "01": "--- -- ... | --- -- A03 | --- -- 037 | --- 0B 412"
}}
```

Les samples stockent `pcm_base64` avec une empreinte `pcm_sha256` vérifiée au chargement (et les champs de boucle), ou une recette. Les fichiers sont écrits de façon compacte, une ligne par sample et par ligne de pattern. Le schéma v2 lit aussi l'ancienne disposition en événements, qui est celle des projets v1 :

```json
{"row": 8, "channel": 3, "note": "E-3", "sample": 8, "effect": "C27"}
```

`effect` contient trois chiffres hexadécimaux. Ici, `C27` fixe le volume à 39 sur une échelle de 0 à 64. Un événement sans note peut modifier le volume, le vibrato ou un autre effet de la voix déjà en cours. Une cellule absente est vide. Un pattern emploie soit `rows`, soit `events`, jamais les deux.

`chiploom migrate ancien.json --output nouveau.json` réécrit un projet v1 (ou un MOD) en v2 sans changer le MOD exporté : `voltage_odyssey_v2` passe de 690 Ko à 117 Ko et `pixel_rush` de 192 Ko à 34 Ko. `inspect --pattern N --grid` affiche un pattern dans ce même texte.

### Morceaux faits uniquement de samples créés

La banque reste le mode par défaut. Sur demande, l'agent peut composer un morceau uniquement avec des samples qu'il crée. `synth palette` écrit un projet de départ avec 13 instruments équilibrés (batterie, basses, leads pulse, accords, bruit) ; `synth preview` fait écouter une recette ; `synth add` ou l'opération de patch `recipe_sample` en ajoute une. Les recettes `wave` produisent des ondes bouclées propres et accordées (pulse, triangle, dent de scie, sinus, bruit).

Le volume des samples créés est calé sur ta banque, rôle par rôle : la grosse caisse sur le quartile haut des percussions, la caisse claire sur la médiane, le charleston sur le quartile bas, et les basses, leads et textures sur la médiane de leur famille. `synth levels` affiche ces références, et `report` signale un sample à plus de 6 dB de la sienne. Un projet marqué `"sample_source": "synthesized"` refuse les samples de la banque, et inversement ; `validate --sample-source synthesized` le vérifie.

```powershell
python -m tracker4agents synth palette --output exports/morceau-synth/project.json --title "Morceau synth"
python -m tracker4agents validate exports/morceau-synth/project.json --sample-source synthesized
```

### Modifier par lots avec `patch`

```powershell
python -m tracker4agents inspect exports/morceau/v1.project.json --pattern 1 --grid --rows 8
python -m tracker4agents patch exports/morceau/v1.project.json --output exports/morceau/v2.project.json --label "Lead plus haut" --op '{"op": "transpose", "pattern": 1, "channel": 0, "semitones": 12}'
```

`patch` applique une liste d'opérations à une copie du projet, valide le résultat et écrit un nouveau projet, ou n'écrit rien : une erreur cite l'opération fautive (`ops[1] (set): …`). Les opérations sont `set`, `write`, `clear`, `copy`, `move`, `transpose`, `add_pattern`, `remove_pattern`, `rename_pattern`, `set_orders`, `insert_order`, `remove_order`, `move_order`, `title`, `timing`, `sample` et `library_sample`. La liste des champs est dans la [référence CLI](CLI.md#operations).

### Mesurer, comparer, noter

- `report` mesure la partition jouée : densité, ambitus, silences, répétitions, tonalité estimée (une estimation, pas un fait). Ce sont des mesures, pas un jugement musical.
- `compare A B --output dossier` crée une page d'écoute A/B à l'aveugle (X et Y dans un ordre aléatoire). C'est un test informel : la réponse figure dans `comparison.json` et, encodée, dans la page, et le volume n'est pas égalisé.
- `feedback --text … --rating 1-5 --version … --output nouveau.json` enregistre ton avis dans les métadonnées d'une copie du projet.

### Adaptateur MCP

`python -m tracker4agents mcp` lance un serveur MCP sur l'entrée et la sortie standard. Il expose 29 outils qui exécutent les commandes ci-dessus, avec les mêmes résultats JSON. Il est couvert par les tests automatiques ; il n'a pas été essayé avec des clients MCP précis. La [référence CLI](CLI.md#mcp-adapter) donne un exemple de configuration.

Les samples peuvent être définis par une recette numérique (`draw`, `kick`, `snare`, `hat`, `kick_hat`, `snare_hat`, `pluck`) ou par des valeurs PCM signées 8 bits. Une recette produit son PCM et ses points de boucle ; elle ne contient pas de code exécutable. Les ondes dessinées emploient des points d’amplitude, une fréquence cible et un nombre de cycles. Les sons courts intègrent leur enveloppe directement dans le sample.

L’import (écrit en schéma v2) est aussi disponible pour les fichiers appartenant au profil strict du prototype :

```powershell
python -m tracker4agents import exports/first_light/first_light.mod --output exports/imported.project.json
```

Un import MOD conserve le PCM, mais ne peut pas retrouver les recettes de synthèse ni les noms des patterns qui n’existent pas dans le format. Les fichiers hors profil sont refusés avec une erreur, sans conversion approximative.

## Profil MOD pris en charge

`protracker-4ch-pal-v1` cible les MOD `M.K.` non compressés : quatre voies, 64 lignes par pattern, jusqu’à 64 patterns, 128 ordres et 31 samples. Les samples sont mono, signés 8 bits, de longueur paire et limités à 65 534 octets chacun. Les textes du module sont limités à l’ASCII imprimable. Les variantes à 15 samples, `M!K!`, les extensions PC et les modules compressés restent hors périmètre.

Le prototype accepte les effets simples `0` à `7`, `9`, `A`, `B`, `C`, `D`, `F`, ainsi que les extensions `E0`, `E1`, `E2`, `E4`, `E5`, `E9`, `EA`, `EB`, `EC`, `ED`. Les paramètres de volume, de saut et de tempo sont contrôlés. `Dxx` utilise une ligne décimale codée en BCD. `F00`, `F20`, les boucles de pattern `E6x`, les délais de pattern `EEx` et l’effet destructif `EFx` sont exclus du profil initial.

Les durées reposent sur le timing CIA. Les rendus sont bornés à 120 secondes et s’exécutent dans des processus disposant d’un délai maximum. La démo réinitialise vitesse, tempo et filtre au début, puis revient au premier ordre par `B00`.

La fenêtre offre la saisie au clavier, l'édition par blocs et des ordres, mais le dessin interactif des samples reste à développer (il est suspendu par la politique actuelle, qui n'emploie que la banque locale). Les pages d'aperçu et de comparaison servent à écouter et à partager ; l'édition dans le navigateur figure sur la [feuille de route](ROADMAP.md), tout comme un import MOD plus large et les formats XM/IT. Les anciens plans, en français, sont dans [history/PLAN_PROJET.md](history/PLAN_PROJET.md). Aucun entraînement de modèle n'est inclus.

## Vérifications

```powershell
python -m unittest discover -s tests -v
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

La suite couvre le format, les rendus, le serveur, le document et la session, les traductions et thèmes, les bundles HTML, l'analyse de références et la bibliothèque de samples, ainsi que, depuis la version 0.7.0, `patch`, le contrat d'erreurs, le schéma v2, `report`, `compare`, les sessions en direct, l'adaptateur MCP, la saisie au clavier et l'intégration en direct de la fenêtre. L'intégration continue exécute Ruff, les tests du cœur et la construction du paquet, ainsi que les tests de la fenêtre sous Windows et sous Linux (cette dernière tâche ne bloque pas encore). Elle vérifie notamment la conservation exacte du PCM, les doublons et variantes, le réimport, les noms neutres et les limites d'emplacements. Les tests Qt utilisent les vrais WAV rendus par FFmpeg, le lecteur multimédia, la saisie au clavier, l'annulation, les exports et la réouverture d'une fenêtre. Ils couvrent la recherche, les filtres, l'audition, l'ajout et le remplacement de samples, une banque absente, la boucle après une introduction, les résultats audio devenus obsolètes, les clics rapides de mute, les changements de langue et thème pendant une saisie et les niveaux audio. Le son est coupé pendant les tests : l'avancement du lecteur et ses buffers sont vérifiés, pas les enceintes physiques. Les essais Qt sont ignorés sans PySide6 ou FFmpeg ; les essais libxmp sont ignorés sans cette bibliothèque.

Les quatre thèmes ont aussi été inspectés dans des fenêtres Windows natives ; les captures et rapports sont dans `exports/desktop`. Un nouveau processus a confirmé la restauration du thème et de la langue après fermeture complète.

Le rapport de la démo contient **13 contrôles réussis** : reconstruction identique du MOD, signal présent, durée complète et absence de saturation PCM dans les deux lecteurs, puis correspondance des 256 lignes avec la trace d’exécution libxmp. Un test séparé vérifie deux boucles consécutives. Ces contrôles ne remplacent pas l’écoute musicale.

La conception retenue et les limites actuelles sont décrites dans [history/CONCEPTION.md](history/CONCEPTION.md) et la [feuille de route](ROADMAP.md).

## Skill agent et banque personnelle

Le [skill ChipLoom](../skills/chiploom/SKILL.md) permet de reproduire le travail avec
tes propres modules. Demande à ton agent de le lire depuis le dépôt, ou copie le
dossier complet `skills/chiploom` dans son dossier de skills. Aucun skill n'est
installé automatiquement et aucun sample de référence n'est fourni.

Tu peux lui donner une liste de MOD, une archive ZIP, ou un dossier dans lequel
choisir une sélection. La [procédure de banque](../skills/chiploom/references/sample-bank.md)
contient une liste JSON et une boucle Python reproductible : import dans une même
banque, déduplication, noms neutres, classement à affiner après écoute, audit puis
petit MOD original de test. Les identifiants sont découverts dans ta banque.
Sources, banque, provenance et morceaux utilisant ces samples restent locaux.
