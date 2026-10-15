# Faisabilité et plan de ChipLoom

15 octobre 2026 — Plan de progression, mis à jour après le premier prototype MOD.

La première version vise l’Amiga et les cracktros, avec des modules MOD à quatre voies, conformément à ton choix. XM puis IT restent dans la trajectoire du projet.

**L’idée est techniquement faisable.** Un agent peut manipuler les notes, les patterns, les effets et les samples sous forme de données, puis produire un véritable module éditable. La qualité musicale, la proximité avec tes références et la fidélité de lecture devront être démontrées sur des morceaux concrets.

L’objectif proposé est un tracker utilisable directement par un agent, avec une interface pour que tu puisses écouter, comprendre et retoucher son travail. La première preuve à obtenir est une courte composition complète, créée par l’agent avec ses propres samples et relue correctement dans un tracker existant.

## Ce qui est faisable et ce qui reste à démontrer

| Besoin | Appréciation | Point déterminant |
| --- | --- | --- |
| Créer de vrais fichiers MOD | Faisable avec un périmètre bien défini | Écrire les données et respecter les comportements du lecteur ciblé. |
| Dessiner et synthétiser les samples | Faisable dès le premier prototype | Accorder les sons, préparer leurs boucles et maîtriser les clics. |
| Analyser les modules fournis | Faisable pour les formats pris en charge | Conserver les effets et le déroulement réel du morceau. |
| Composer dans une esthétique donnée | Hypothèse crédible à évaluer | Construire des phrases, des variations et un arrangement convaincants. |
| Améliorer automatiquement un morceau | Faisable sur certains critères | Les mesures audio détectent des défauts, mais ne suffisent pas à juger l’intérêt musical. |
| Entraîner un modèle spécialisé | Chantier distinct et optionnel | Préparer un corpus et démontrer un gain par rapport à l’agent utilisant des références. |

Les briques de lecture existent : libopenmpt transforme les modules en audio PCM, et openmpt123 fournit un lecteur en ligne de commande. Leur existence rend raisonnable la réutilisation d’un moteur de lecture pour le prototype. [Présentation officielle](https://lib.openmpt.org/libopenmpt/).

**Attention à la différence entre lecture et écriture :** la FAQ de libopenmpt indique que l’export de modules et l’édition des patterns ne font pas partie de son rôle actuel. Il faudra donc une couche d’édition et d’export séparée. [FAQ de libopenmpt](https://lib.openmpt.org/libopenmpt/faq/).

## Périmètre musical proposé

| Étape | Format | Intérêt pour le projet |
| --- | --- | --- |
| Première version | MOD de type ProTracker, quatre voies | Cible Amiga, samples 8 bits, patterns de 64 lignes et contraintes adaptées aux premiers essais. |
| Extension suivante | XM | Instruments avec enveloppes et affectation de plusieurs samples à un instrument. |
| Extension ultérieure | IT | Gestion plus riche des voix, notamment les New Note Actions, et filtres d’instrument. |

Ces différences sont décrites dans le [manuel des formats OpenMPT](https://wiki.openmpt.org/Manual:_Module_formats). Chaque format devra avoir son propre profil de compatibilité. Une conversion vers MOD ne pourra pas préserver automatiquement toutes les possibilités d’un morceau XM ou IT.

Pour la première version, je propose un profil volontairement limité : quatre voies, 31 emplacements de samples, des sons courts et des effets choisis pour la cible ProTracker. Le code de référence OpenMPT confirme la structure à 31 samples et distingue plusieurs variantes MOD ; l’extension du fichier ne suffit donc pas à identifier son comportement exact. [Lecteur et exporteur MOD d’OpenMPT](https://github.com/OpenMPT/openmpt/blob/master/soundlib/Load_mod.cpp).

La version précise de ProTracker, le mode de tempo et les limites de taille seront fixés pendant le cadrage. L’esthétique recherchée et la compatibilité avec un véritable Amiga seront deux critères distincts.

## Fonctionnement proposé pour un agent

L’agent recevrait une intention musicale et des références. Il pourrait créer une palette de sons, écrire un motif, développer des variations, organiser les patterns, exporter le module, produire un rendu audio puis corriger une partie du morceau.

Pour cela, le logiciel devrait proposer des commandes structurées accessibles en ligne de commande, puis éventuellement par MCP. Les mêmes opérations serviraient à l’interface humaine. Les actions porteraient sur des objets musicaux : lire un pattern, remplacer une phrase, transposer une basse, modifier un sample ou rendre un passage.

Les points à prévoir lors de la conception sont les suivants :

- Un projet de travail conservant notes, commandes d’effets, samples, ordre des patterns et paramètres de compatibilité.
- Des modifications par blocs, avec validation, historique et possibilité d’annuler.
- Des réponses compactes pour l’agent, afin de consulter uniquement les passages utiles.
- Un export vérifié après réouverture du fichier réellement écrit.
- Des rendus audio bornés en durée, y compris lorsque le morceau boucle.
- La conservation des paramètres de synthèse et des graines aléatoires pour reproduire les samples.

Les effets font partie de la composition : leur mémoire, leur exécution à l’intérieur des lignes et leurs variantes de lecture doivent être conservées. Une représentation réduite aux notes et à leurs durées perdrait une partie essentielle du morceau. [Référence des effets OpenMPT](https://wiki.openmpt.org/Manual:_Effect_Reference).

Pour la lecture, libopenmpt est le candidat principal. Pour l’écriture MOD, un exporteur limité au profil retenu paraît raisonnable. Avant d’élargir à XM et IT, il faudra comparer cette approche à la réutilisation de code existant. OpenMPT contient des fonctions d’écriture, mais leur intégration demanderait une adaptation de son code interne. Son dépôt est distribué sous BSD 3-Clause, avec des dépendances pouvant avoir d’autres licences. [Dépôt officiel](https://github.com/OpenMPT/openmpt).

libxmp est une autre piste pour l’analyse : son API expose des structures de patterns, d’instruments et de samples, y compris leurs données. Cette représentation devra être évaluée avant de lui confier un import destiné à être réexporté sans perte. [API publique libxmp](https://github.com/libxmp/libxmp/blob/master/include/xmp.h).

Le cœur retenu est Python sans dépendance de paquet ; la fenêtre humaine utilise Qt Widgets / PySide6 en option. La première cible est Windows, avec une structure prévue pour Linux. Le moteur de composition reste utilisable sans interface, par différents agents et indépendamment de leur fournisseur.

## Création des samples

Oui, l’agent pourra dessiner les samples au sens littéral : écrire les amplitudes successives d’une onde. Le dessin de formes d’onde pour créer des sons chip existe déjà dans les trackers. [Édition des samples dans OpenMPT](https://wiki.openmpt.org/Manual:_Samples).

Trois méthodes sont à prévoir :

1. **Dessin numérique** : forme carrée, triangulaire, dent de scie ou forme définie par des points, avec une boucle et un accordage.
2. **Synthèse calculée** : oscillateurs, bruit, enveloppes et filtrage pour produire basses, leads, kicks, caisses claires et charleys.
3. **Transformation de samples fournis** : découpage, réaccordage, réduction en 8 bits, bouclage et variantes.

En MOD, le résultat de cette synthèse sera enregistré dans les samples du module. La lecture du morceau ne dépendra pas du synthétiseur ayant servi à les créer. Les variations pendant la lecture utiliseront les possibilités du format.

L’outil devra vérifier le niveau, le décalage continu, l’accordage et les raccords de boucle. Le caractère rugueux d’un son pourra être intentionnel ; une correction automatique devra rester explicable et réversible. Chaque sample conservera son origine et sa recette dans le projet de travail.

## Utilisation de tes modules de référence

Je recommande de distinguer trois niveaux.

**Analyse musicale.** Lire les fichiers et extraire les motifs, intervalles, rythmes, changements de tempo, effets, structures et propriétés des samples. Les fonctions musicales des voies et la tonalité seront des estimations, car une même voie peut accueillir plusieurs rôles.

**Composition guidée par des exemples.** Conserver des profils de style et des passages représentatifs dans le projet. L’agent pourra les consulter pour composer de nouveaux motifs et ajuster ses propositions à tes retours. Cela ne modifie pas les poids du modèle. C’est la première approche à essayer.

**Entraînement spécialisé.** Si les résultats précédents sont insuffisants, étudier un modèle entraînable sur une représentation des événements tracker. Il faudrait préparer et dédupliquer les données, séparer les morceaux d’apprentissage et d’évaluation, mesurer le coût, puis vérifier un bénéfice musical réel. Quelques fichiers de référence peuvent orienter des essais ; ils ne prouvent pas qu’un entraînement produira un modèle généraliste de qualité.

Pour commencer, un petit lot proposé de cinq à dix modules représentatifs serait utile, avec une phrase par morceau indiquant ce qui te plaît : mélodie, basse, groove, timbre ou construction. Ce nombre sert à cadrer les essais, sans constituer une estimation de corpus d’entraînement.

Les originaux resteraient conservés tels quels. L’analyse de style et la reprise de samples seraient deux opérations séparées. Les nouvelles compositions pourraient ainsi utiliser uniquement des sons créés pour le projet.

## Plan de réalisation proposé

| Phase | Travail | Critère pour passer à la suite |
| --- | --- | --- |
| 0 — Faisabilité | Étude des possibilités, des limites et des briques disponibles ; priorité MOD décidée avec toi. | Présente étude terminée. |
| 1 — Cadrage et conception | Examiner tes références, choisir le profil ProTracker et définir les opérations de l’agent. | Périmètre clair et critères d’écoute convenus. |
| 2 — Preuve technique complète | Générer quelques samples, écrire une courte composition à quatre voies, exporter un MOD et son rendu audio. | Fichier rouvert et joué dans des lecteurs de référence ; morceau éditable. |
| 3 — Première version pilotable | Ajouter import MOD du périmètre retenu, édition des patterns et samples, commandes structurées, contrôles et annulation. | Un agent crée puis révise un morceau de bout en bout. |
| 4 — Composition avec références | Extraire des profils, générer plusieurs variantes et intégrer tes retours. | Amélioration perceptible par rapport aux compositions sans références. |
| 5 — Interface de tracker | Afficher patterns, ordre du morceau, samples, formes d’onde, transport et modifications de l’agent ; permettre les retouches. | Tu peux inspecter, écouter et modifier le même projet que l’agent. |
| 6 — Formats supplémentaires | Ajouter XM avec ses propres validations, puis IT. | Chaque format passe ses essais d’import, d’export et de lecture. |
| 7 — Entraînement éventuel | Évaluer un modèle spécialisé si le besoin est démontré. | Gain mesuré justifiant la complexité supplémentaire. |

La phase 2 est le premier point de décision important. Elle évite d’investir dans une interface complète avant d’avoir entendu ce que l’agent sait produire. Pour cette preuve, OpenMPT et le clone de ProTracker 2 peuvent servir à la vérification manuelle. Le second fournit une implémentation distincte utile pour confronter les résultats. [ProTracker 2 clone](https://16-bits.org/pt2.php).

## Validation de la première preuve

La cible proposée est une boucle de 30 à 60 secondes avec un motif identifiable, une variation et une transition. Tous les samples seraient créés pour cet essai. Les livrables seraient le projet éditable, le fichier MOD, le rendu WAV et un court relevé des contrôles.

- **Structure** : samples, notes, effets et références de patterns valides dans le profil choisi.
- **Export** : réouverture du MOD et comparaison des données musicales attendues, sans perte silencieuse.
- **Lecture** : vérification dans au moins deux implémentations distinctes. OpenMPT et libopenmpt partagent une base de lecture et ne suffisent pas à eux seuls pour cette comparaison.
- **Audio** : contrôle des silences imprévus, dépassements de niveau et raccords suspects, avec écoute des passages concernés.
- **Musique** : ton appréciation du motif, du rythme, des timbres, des variations et de la proximité avec les références.
- **Reproductibilité** : conservation des fichiers et paramètres ayant produit la version retenue.

Une comparaison audio entre lecteurs devra tenir compte du filtrage et du rééchantillonnage ; une différence numérique ne prouve pas à elle seule un défaut musical. Une validation sur lecteur logiciel ne constituera pas une validation sur un véritable Amiga.

Pour évaluer l’apport des références, on pourra comparer un même brief avec une composition simple à règles, une composition par l’agent seul et une composition par l’agent disposant des profils de style. Tes préférences d’écoute resteront le critère musical principal. Les mesures automatiques et un éventuel modèle d’analyse audio seront des aides, sans équivalence avec une écoute humaine.

**État actuel, version 0.4.0 :** First Light et Pixel Rush sont disponibles en MOD autonome, projets éditables, WAV et MP3 facultatif. Les deux modules fournis ont été analysés en lecture seule. Le cœur reste pilotable en ligne de commande sans Qt ; le modèle de document ajoute des opérations validées et annulables.

La première fenêtre humaine ouvre les modules et projets, affiche patterns et samples, assure l'écoute et les modes muet/solo, permet les retouches de cellules, tempo, titre, volume et accord fin, puis sauvegarde et exporte MOD/WAV/MP3. Le travail courant ne demande plus de générer une page HTML. Les phases 3 et 5 sont donc commencées ; l'édition de blocs, le dessin graphique des samples et l'arrangement restent à faire.

La fenêtre propose maintenant le mute par clic sur chaque voie, un vu-mètre stéréo alimenté par l'audio réellement décodé, quatre thèmes et les langues anglais/français, avec l'anglais par défaut. Le thème et la langue changent sans recharger le morceau et sont conservés après fermeture. Les 47 tests passent sous Windows ; la réouverture et les quatre thèmes ont aussi été vérifiés dans des fenêtres natives.

La conception et les options proposées sont dans `CONCEPTION.md`, les lanceurs et commandes dans `README.md`. Linux est préparé mais non exécuté ; l'intégration MCP, les formats XM/IT et l'entraînement restent à développer. La validation sur matériel Amiga n'a pas été effectuée.

La tranche 0.4.0 ajoute le nom ChipLoom, un guide pour Codex et Hermès, une commande `preview` indépendante des démos et une commande `analyze` pour les MOD/ZIP de référence. La sélection de 15 modules est documentée dans `references/SELECTION_FR.md`. Six passent le profil éditable actuel. Le dépôt privé est sous licence MIT pour le code original ; les originaux tiers restent hors du dépôt. MCP reste un adaptateur à développer, distinct du cœur déjà utilisable par les agents.
