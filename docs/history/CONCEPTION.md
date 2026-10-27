# Conception de ChipLoom

15 octobre 2026 — Version 0.4.0 : nom ChipLoom, documentation des agents, export HTML autonome et étude de références. La fenêtre Linux reste à valider.

Le prototype donne à un agent un chemin court entre une partition structurée et un fichier MOD autonome. L’agent travaille sur des notes, des effets et des recettes de samples ; l’exporteur construit le binaire ; des lecteurs existants rendent ensuite ce fichier. La partition et le PCM ne dépendent pas d’un fournisseur de modèle.

## Décisions retenues

**Cœur Python sans dépendance de paquet.** Python permet d'inspecter et de modifier les données, tout en s'appuyant sur des lecteurs natifs pour l'audio. L'agent utilise le modèle, le JSON et la ligne de commande sans fenêtre ni Qt. Le traitement musical ne dépend pas du toolkit graphique.

**Fenêtre pour l'humain, facultative.** Qt Widgets / PySide6 fournit la bibliothèque, les patterns, les samples, le transport et les retouches. Cette interface ne contient pas de moteur musical parallèle : ses opérations passent par le même `Document` indépendant que celles d'un agent Python. L'agent peut aussi continuer à écrire directement un projet JSON puis lancer validation et export. F5 recharge le fichier partagé, avec protection des retouches locales non enregistrées. Aucun pilotage de souris n'est nécessaire pour l'agent.

**Partition JSON indépendante du binaire.** `tracker4agents.project.v1` conserve le titre, le profil cible, les samples, les patterns, la liste d’ordres et les métadonnées. Chaque pattern contient une liste de cellules non vides identifiées par leur ligne et leur voie. La représentation conserve les commandes d’effets, y compris les commandes placées sans nouvelle note.

**Export MOD strict.** La première cible est `M.K.`, quatre voies et 31 emplacements de samples. Les limites de longueur, les périodes des notes et les boucles sont vérifiées avant l’écriture. Les textes trop longs, périodes non prévues et fonctions hors profil entraînent un refus explicite. Le lecteur interne sert à vérifier la structure et à réimporter les fichiers du même profil ; il ne prétend pas couvrir les variantes historiques.

**Sons calculés puis intégrés au MOD.** Les ondes dessinées sont générées depuis des points d’amplitude. Les percussions et le lead utilisent des oscillateurs, du bruit et des enveloppes calculées. L’outil centre et quantifie les valeurs en PCM 8 bits. Les sons sans boucle commencent par deux octets nuls et finissent par une courte atténuation. Les ondes entretenues possèdent une boucle alignée sur deux octets.

**Lecture externe et bornée.** Le moteur principal est libopenmpt, exposé par FFmpeg. Le second est libxmp 4.7.3, construit localement depuis une archive vérifiée. Libxmp utilise sa personnalité ProTracker et son mixeur A500 ; l’état actif est lu dans le moteur pour vérifier que ces réglages sont effectifs. Le worker natif est isolé dans un sous-processus. Les deux rendus utilisent le MOD exporté comme entrée.

**MP3 optionnel.** Le fichier MOD reste le résultat principal. Le MP3 est une copie d’écoute issue du WAV rendu depuis ce MOD, encodée par libmp3lame. Il ne remplace aucune des données de composition.

## Répartition du code

| Fichier | Responsabilité |
| --- | --- |
| `tracker4agents/model.py` | Objets musicaux, périodes, contraintes et déroulement temporel. |
| `tracker4agents/synth.py` | Recettes déterministes de samples et quantification. |
| `tracker4agents/project.py` | Lecture/écriture du JSON, contrôles de schéma et écriture atomique. |
| `tracker4agents/mod.py` | Encodage et décodage du profil binaire M.K. |
| `tracker4agents/demo.py` | Partition et palette sonore originales de First Light. |
| `tracker4agents/audio.py` | Rendus, copie MP3 et mesures PCM. |
| `tracker4agents/_xmp_worker.py` | Appels natifs libxmp et trace du déroulement. |
| `tracker4agents/review.py` | Génération de la page locale d’écoute et d’inspection. |
| `tracker4agents/preview.py` | Bundle HTML complet depuis un projet ou MOD existant, avec liens relatifs et publication après rendu réussi. |
| `tracker4agents/references.py` | Analyse structurelle en lecture seule de MOD et ZIP, distincte de l'import strict. |
| `tracker4agents/cli.py` | Commandes utilisables par un agent et réponses JSON. |
| `tracker4agents/document.py` | Transactions musicales validées, annulation/rétablissement, sauvegarde et export. Aucune dépendance Qt. |
| `tracker4agents/desktop_services.py` | Session locale, fichiers récents et cache des rendus. Aucune dépendance Qt. |
| `tracker4agents/desktop.py` | Fenêtre Qt pour l'humain et lecture des WAV par Qt Multimedia. |
| `tracker4agents/level_meter.py` | Mesure RMS/crêtes du PCM décodé et vu-mètre stéréo Qt. |
| `tracker4agents/themes.py` | Quatre palettes et styles communs aux contrôles, patterns et formes d'onde. |
| `tracker4agents/i18n.py` | Textes anglais/français et traduction des diagnostics courants du cœur pour la fenêtre. |
| `tools/setup_reference.py` | Préparation reproductible du second lecteur. |

## Premier essai musical

First Light utilise quatre voies : percussions, basse, arpèges et mélodie. Les huit samples comprennent des percussions seules, des combinaisons kick/charley et caisse claire/charley pour tenir sur une voie, deux ondes dessinées bouclées et un lead avec enveloppe intégrée.

La progression Am–F–C–G se répète sur quatre sections avec des variations mélodiques et rythmiques. Les arpèges utilisent les commandes tracker `037` et `047`. Les volumes et le vibrato sont également écrits dans les patterns. La dernière ligne retourne au premier ordre avec `B00`.

À vitesse 6 et 125 BPM en timing CIA, une ligne dure 0,12 seconde. Les quatre patterns de 64 lignes forment donc une boucle de 30,72 secondes. La partition sauvegardée et le binaire permettent de reproduire cet essai.

Les sources d’exemple restent séparées des sorties. Un agent peut modifier `examples/first_light.project.json`, puis exporter une nouvelle variante dans un autre fichier avec les commandes `export` et `render`.

## Vérification et portée des résultats

L’exporteur est confronté à une petite fixture binaire assemblée séparément, aux limites du format et à des entrées incorrectes. La démo passe un aller-retour binaire exact ainsi qu’une reconstruction depuis le projet JSON sauvegardé.

Les deux lecteurs rendent une boucle complète, sans échantillon PCM saturé ni silence prolongé détecté. La trace libxmp confirme l’ordre, la ligne, la vitesse, le tempo et le temps de chaque ligne. Les tests vérifient aussi deux boucles consécutives et une fixture distincte avec changement de vitesse, tempo et saut `D10`.

Les empreintes, paramètres et résultats sont enregistrés dans `exports/first_light/validation.json`. Les rendus de lecteurs différents peuvent varier à cause du mixage, du filtrage et du rééchantillonnage ; leur égalité numérique n’est pas un critère de réussite.

La compatibilité avec des modules tiers et l’écoute comparative de références restent à évaluer. La qualité artistique se juge à l’écoute. Aucun entraînement de modèle n’est inclus dans ce prototype.

## Fenêtre et lecture

L'ouverture accepte les MOD du profil strict et les projets JSON existants. Une ouverture invalide conserve le document courant. Les notes, samples et effets sont éditables ; une opération est appliquée sur une copie, validée entièrement, puis ajoutée à un historique de 50 opérations. Une erreur ne modifie aucune note. Le JSON conserve les recettes des samples ; un import MOD conserve le PCM sans inventer leur origine.

L'écoute rend le MOD dans un worker puis charge le WAV dans `QMediaPlayer`. Les calculs et les sous-processus ne bloquent pas la boucle de la fenêtre. Une empreinte du binaire, du mix et de la version sert de clé de cache. Chaque préparation possède un identifiant ; un résultat devenu obsolète après une autre ouverture ou une édition ne remplace pas l'écoute courante. Les helpers audio n'ouvrent pas de consoles sous Windows.

Le mode muet/solo utilise une copie du document, garde les effets de vitesse et de saut, puis rend le mix correspondant. Il ne modifie pas les données enregistrées. Les exports WAV/MP3 suivent ce mix ; l'export MOD garde le morceau entier. La boucle audio retourne au temps de reprise calculé dans le module pour ne pas rejouer systématiquement l'introduction. Les aperçus de samples tiennent compte du volume et de l'accord fin, sans prétendre reproduire le filtrage Paula.

Chaque voie possède un grand bouton cliquable au-dessus de ses colonnes et un bouton Solo. Une voie coupée porte la mention MUTED/MUET et ses notes sont atténuées. Des clics successifs pendant la préparation audio conservent l'intention de lecture et le temps de reprise ; seul le dernier mix demandé est chargé. Le mute conserve la courte préparation liée au rendu WAV.

Le vu-mètre reçoit le PCM stéréo 16 bits décodé par Qt avec `QAudioBufferOutput`, pour le morceau comme pour les aperçus de samples. Il mesure RMS et crêtes, applique le volume principal et affiche deux barres avec une décroissance progressive et une valeur en dBFS. L'arrêt et le déplacement de lecture effacent les anciennes mesures. Il s'agit d'un indicateur d'intensité, sans analyse fréquentielle. Cette sortie de buffers nécessite le backend multimédia FFmpeg de Qt, utilisé lors des essais Windows. [API officielle QAudioBufferOutput](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QAudioBufferOutput.html).

Les palettes Midnight, Amber, Violet et Light s'appliquent aussi aux patterns, aux contrôles de voies et à la forme d'onde. Le catalogue de textes utilise l'anglais par défaut et propose le français ; les dialogues Qt utilisent leur traduction française. Le changement de langue préserve le document, l'historique et les valeurs encore en cours de saisie. Les données musicales ne sont pas traduites, et les détails techniques d'un outil externe peuvent conserver leur langue d'origine. Thème et langue sont enregistrés dans la session locale dès leur sélection. Ces fonctionnalités restent propres à la fenêtre et n'imposent aucune dépendance graphique à l'agent.

Cette stratégie réutilise le lecteur déjà validé et garde le prototype simple. Elle entraîne une préparation après chaque modification et peut faire une petite coupure à la reprise de la boucle. Un accès direct au lecteur pour un mixage en temps réel sera nécessaire pour une édition musicale instantanée.

Les chemins du cœur utilisent `pathlib`. Qt choisit le dossier de données utilisateur, et les commandes de rendu n'utilisent pas d'API audio Windows. Les lanceurs Windows et Linux sont séparés. La dépendance PySide6 appartient à l'option `desktop`, pas au cœur. La CI Ubuntu valide l'installation du cœur, ses tests, des rendus FFmpeg et la génération d'un MOD. La fenêtre Linux, ses dépendances système Qt et la sortie audio physique restent à valider.

## Options suivantes proposées

| Priorité | Option | Intérêt |
| --- | --- | --- |
| 1 | Sélection de 1, 2 ou 4 mesures, variantes courtes et comparaison A/B | Ajuster rapidement la longueur et le rythme des variations selon ton retour sur Pixel Rush. |
| 2 | Dessin interactif des samples, édition des points de boucle et variantes de pulse | Retoucher les mêmes recettes numériques que l'agent avec un retour visuel et sonore. |
| 3 | Copier/coller des blocs, dupliquer les patterns et réordonner le morceau | Construire l'arrangement depuis la fenêtre. |
| 4 | Commandes d'édition par blocs et intégration MCP | Donner à l'agent des transactions précises, validables et annulables sans interface graphique. |
| 5 | Lecture directe et mixage en temps réel | Rendre les modifications, le solo et les boucles immédiatement audibles. |
| 6 | Paquets autonomes Windows puis Linux | Distribuer l'outil sans demander l'installation manuelle de Python. |

## Extensions du cœur

Le nom public devient **ChipLoom**, tandis que le paquet Python, le schéma JSON et l'identité du dossier de session restent `tracker4agents`. Le guide principal est désormais le README anglais, complété par `docs/USAGE_FR.md`, `docs/AGENT_GUIDE.md` et `docs/CLI.md`. L'outil convient à un agent disposant de commandes de terminal et d'accès aux fichiers, tel que Codex ou Hermès ; aucun modèle ni serveur MCP n'est intégré. La frontière du futur adaptateur MCP est détaillée dans `docs/ARCHITECTURE.md`.

La fenêtre et l'export HTML restent tous deux disponibles. La commande `preview` accepte un projet ou un MOD compatible, construit le dossier dans une zone temporaire locale puis le publie après réussite du rendu. Les fichiers du bundle utilisent des liens relatifs. L'aperçu est une vue d'écoute et d'inspection ; il n'ajoute pas un second éditeur.

La nouvelle analyse porte sur 15 références, dont deux à deux voies. Six passent l'import strict ; les neuf autres restent consultables par l'analyse séparée. Les rapports agrégés sont conservés dans `references`, sans PCM ni mélodies complètes. Les variantes de restart et les effets E6x/EFx rencontrés doivent faire l'objet d'une future extension consciente du profil, sans normalisation silencieuse.

Le document possède désormais des opérations validées avec annulation. Il reste à les exposer en commandes structurées par blocs et par MCP. L'analyse de tes références existe dans `references/ANALYSE.md` ; des profils de style et exemples consultables par l'agent pourront la prolonger.

La fenêtre réutilise ce modèle musical. Les formats XM et IT demanderont des capacités et des profils de compatibilité propres, plutôt qu'une conversion implicite du modèle MOD.

## Références techniques

- [Format et effets des modules dans OpenMPT](https://wiki.openmpt.org/Manual:_Module_formats).
- [Référence des effets](https://wiki.openmpt.org/Manual:_Effect_Reference).
- [Lecteur et exporteur MOD d’OpenMPT](https://github.com/OpenMPT/openmpt/blob/master/soundlib/Load_mod.cpp).
- [Structure et écriture d’un MOD dans ProTracker 2 clone](https://github.com/8bitbubsy/pt2-clone/blob/master/src/pt2_module_saver.c).
- [Documentation libopenmpt et limites de l’API](https://lib.openmpt.org/libopenmpt/faq/).
- [Démultiplexeur libopenmpt de FFmpeg](https://ffmpeg.org/ffmpeg-formats.html#libopenmpt).
- [API publique libxmp 4.7.3](https://github.com/libxmp/libxmp/blob/libxmp-4.7.3/include/xmp.h).
- [Installation multiplateforme de Qt for Python](https://doc.qt.io/qtforpython-6/gettingstarted.html).
- [Chargement et lecture avec QMediaPlayer](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QMediaPlayer.html).

Le code de ce prototype n’embarque pas de source ou de binaire de lecteur dans le paquet Python. Le script de préparation télécharge libxmp dans `.tools`, avec sa notice de licence d’origine et un manifeste des empreintes.
