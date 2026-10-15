# Étude de la sélection de modules

15 octobre 2026 — 15 fichiers analysés en lecture seule depuis une archive fournie localement, dont l’intégrité a été vérifiée avant et après l’étude. Les références sont désignées par S01 à S15 ; leurs noms et empreintes ne sont pas publiés ici.

Les mesures et les relations entre patterns sont dans [selection-analysis.json](selection-analysis.json). Les observations ci-dessous concernent la construction inscrite dans les données ; elles ne constituent pas une écoute critique, une identification certaine des rôles musicaux ou un entraînement de modèle. Les originaux, samples et mélodies complètes ne sont pas copiés dans le dépôt.

## Vue d'ensemble

Les durées de cette table sont les estimations de **FFprobe/libopenmpt**, pas une multiplication du nombre d'ordres par 64 lignes. Les sauts et boucles peuvent modifier le parcours. Les numéros de patterns sont décimaux dans ce rapport.

| Référence | Voies | Patterns stockés / ordres | Durée | PCM total | Import strict actuel |
| --- | --- | --- | --- | --- | --- |
| S01 | 4 | 6 / 7 | 33,28 s | 1 368 o | Non |
| S02 | 4 | 4 / 4 | 25,60 s | 2 570 o | Oui |
| S03 | 2 | 9 / 12 | 46,08 s | 1 688 o | Non |
| S04 | 4 | 5 / 7 | 35,84 s | 2 212 o | Oui |
| S05 | 4 | 5 / 7 | 40,00 s | 1 326 o | Non |
| S06 | 4 | 2 / 4 | 30,72 s | 442 o | Oui |
| S07 | 4 | 2 / 2 | 10,24 s | 2 116 o | Oui |
| S08 | 4 | 4 / 4 | 46,08 s | 1 660 o | Non |
| S09 | 4 | 1 / 1 | 7,68 s | 4 264 o | Non |
| S10 | 4 | 4 / 4 | 22,40 s | 3 872 o | Oui |
| S11 | 4 | 3 / 4 | 20,48 s | 4 394 o | Non |
| S12 | 4 | 4 / 10 | 115,20 s | 728 o | Non |
| S13 | 4 | 2 / 4 | 20,48 s | 3 366 o | Oui |
| S14 | 4 | 1 / 1 | 15,36 s | 2 026 o | Non |
| S15 | 2 | 3 / 5 | 32,00 s | 1 298 o | Non |

Une commande de sample sans note peut réaffecter le même sample : ce comptage ne garantit pas à lui seul un changement de timbre.

Les fichiers utilisent **101 emplacements de samples non vides**, totalisant 33 330 octets PCM. Ce ne sont pas nécessairement 101 sons différents : certains peuvent être identiques. 70 emplacements ont une taille d'au plus 128 octets, la taille médiane est de 50 octets et 71 emplacements possèdent une boucle supérieure à deux octets.

## Construction des quinze morceaux

**S01.** La liste `5,0,2,0,1,3,4` commence par un pattern distinct avant les reprises. Les patterns 0, 1 et 2 partagent une majorité de leurs cellules occupées ; les patterns 3 et 4 forment une autre paire proche. Sept samples suffisent, dont trois ondes de 14 octets. Les arpèges et commandes de volume sont très présents. Piste : une introduction courte, une famille de variantes, puis une réponse, avec des contrastes obtenus par les patterns.

**S02.** Quatre patterns, vitesse 5 à 125 BPM dans le plan strict. Entre 0 et 1, puis entre 2 et 3, les voies **1, 2 et 4 sont identiques** ; seule la voie 3 change. La voie 4 contient seulement 12 événements avec période non nulle mais **244 événements avec sample et sans nouvelle période** sur les patterns stockés. Piste : garder un accompagnement stable et faire évoluer une ligne, tout en sculptant les timbres à l'intérieur des notes.

**S03.** Deux voies, quatre samples et douze ordres `0,7,1,4,2,3,5,6,2,3,5,8`. Les commandes F03 donnent une grille rapide ; les patterns 5 et 6 conservent exactement la deuxième voie. Piste : avec peu de voix, alterner les rôles dans le temps et varier une ligne tout en conservant l'autre. Ce fichier n'est pas un MOD à quatre voies malgré son extension.

**S04.** L'arrangement `2,3,4,3,4,1,1` ne joue pas le pattern 0. Dans les patterns 2, 3 et 4, les voies **2, 3 et 4 sont identiques** ; les variantes concernent la voie 1. La voie 2 comporte 185 commandes de sample sans note sur l'ensemble stocké. Piste : distinguer les données stockées de l'arrangement joué et construire des variantes ciblées, sans réécrire toutes les voix.

**S05.** Les ordres `2,0,2,1,3,1,4` réemploient des motifs ; les patterns 3 et 4 ont environ 86 % de cellules occupées identiques. Le fichier contient des boucles de pattern E6x et des sauts Dxx. Piste : une petite variation de fin de phrase peut suffire à relancer un motif. Son déroulement demande un lecteur qui comprend ces effets.

**S06.** Deux patterns répétés par paires `0,0,1,1`, seulement **442 octets PCM** répartis sur huit samples. La vitesse 8 ne produit pas une grille particulièrement rapide ; le mouvement vient notamment des nombreuses commandes 6xx et de l'articulation. Piste : la vitesse perçue ne se résume pas au BPM ou au nombre de notes. Un son entretenu peut rester actif grâce à ses effets.

**S07.** Deux patterns et une boucle de 10,24 s. La voie 3 compte quatre événements avec période non nulle et 124 commandes de sample sans nouvelle période. Le vibrato est fréquent. Piste : faire une proposition musicale compacte et travailler l'évolution du son à l'échelle de quelques lignes.

**S08.** Quatre patterns joués dans l'ordre `1,0,3,2`. Les voies 1 et 2 restent identiques entre toutes les paires de patterns ; certaines paires conservent aussi la troisième. Le fichier emploie E9x et EFx. Piste : le changement peut se concentrer sur la dernière voix, mais les effets modifiant le sample demandent une analyse de compatibilité spécifique.

**S09.** Un seul pattern et un seul sample non vide de 4 264 octets, avec une boucle de 978 octets. La troisième voie ne contient aucun nouvel événement de hauteur. Les autres voies réemploient le même matériau à différentes notes avec des réglages de volume et de hauteur. Piste : une palette restreinte peut servir une phrase complète ; multiplier les samples n'est pas un objectif en soi.

**S10.** Quatre patterns, forte présence du vibrato et des arpèges. La voie 3 compte 190 commandes de sample sans nouvelle note. La présence de sauts Bxx explique qu'il ne faut pas déduire la durée de quatre patterns entièrement déroulés. Piste : construire le mouvement du timbre et contrôler les sorties de phrases dans la partition.

**S11.** Trois patterns pour `0,1,1,2`, soit une forme avec reprise centrale et sortie distincte. Deux samples ne font que 20 octets ; d'autres sont beaucoup plus longs. Les commandes E0x pilotent le filtre selon les possibilités du lecteur. Piste : mélanger ondes très courtes et sons avec attaque plus développée pour donner du contraste.

**S12.** Quatre patterns alimentent dix ordres, sur 115,20 s. Les voies 1 et 3 sont identiques entre plusieurs patterns, et 1/2 conservent aussi la voie 4. Le quatrième canal possède 176 commandes de sample sans nouvelle note sur les patterns stockés. Piste : une construction longue peut être fondée sur une petite réserve de motifs ; pour nos prochains essais, garder ce procédé mais condenser la forme selon ton retour sur les variations trop longues.

**S13.** Deux patterns répétés `0,0,1,1`, vitesse 4, 20,48 s. Dix samples mêlent sons longs et boucles courtes ; les commandes Cxx sont nombreuses. Piste : deux sections contrastées, répétées chacune une fois, peuvent constituer une forme immédiatement lisible.

**S14.** Un pattern unique de 15,36 s à vitesse 12. Dix samples, dont plusieurs partagent une boucle de 28 octets avec des longueurs d'amorce différentes. Piste : travailler l'attaque et l'enveloppe pour différencier les sons, même lorsque leur boucle est courte.

**S15.** Deux voies, trois patterns et l'ordre `1,0,0,0,2`. Les patterns 0 et 2 partagent 87,5 % de leurs cellules occupées. Piste : entrée, répétition d'un motif principal et petite variante de sortie ; la répétition est une décision d'arrangement, pas forcément une absence de travail.

## Ce que j'en retiens pour composer

Ces pistes sont des choix de conception déduits de la structure, pas des règles universelles ni des mélodies à reprendre :

1. Écrire une phrase courte, puis une réponse ou une fin modifiée avant d'allonger le morceau.
2. Garder deux ou trois voies stables entre deux variantes et changer précisément la ligne utile.
3. Prévoir une famille de samples bouclés très courts ; dessiner de nouvelles formes puis écrire les changements de timbre dans les cellules.
4. Travailler les volumes et glissés à l'intérieur des notes, au lieu d'allonger toutes les variations.
5. Séparer le rythme des notes de la vitesse d'évolution du timbre. Évaluer les variations sur une ou deux mesures.
6. Tester les transitions et la reprise réelle de la boucle, pas seulement le premier pattern.

Les codes 0xy, 3xx, 4xy, 6xy, E6x, E9x et EFx ont des comportements distincts ; le comptage ne suffit pas à reconstituer leur résultat sonore. Les définitions sont détaillées dans la [référence officielle des effets OpenMPT](https://wiki.openmpt.org/Manual:_Effect_Reference).

## Conséquences pour l'outil

**Six fichiers passent le profil strict actuel.** Les neuf autres sont analysables ici, mais ne doivent pas être annoncés comme éditables. Parmi les premières causes de refus : six octets restart différents de 127, deux signatures 2CHN, et un texte hors ASCII imprimable. Corriger cette première cause ne garantit pas la compatibilité : certains fichiers contiennent aussi E6x ou EFx, exclus du profil.

L'analyse apporte une nouvelle priorité au développement : un import conscient des variantes, avec conservation des métadonnées et validation du rendu. Il ne faut pas remplacer silencieusement les octets qui gênent l'import. À court terme, l'agent peut déjà utiliser ces rapports comme références de construction tout en exportant de nouveaux morceaux conformes à notre profil.

## Reproduire l'étude

Avec ton archive locale et FFprobe/libopenmpt dans le PATH :

```sh
python -m tracker4agents analyze path/to/selection.zip --output exports/selection-study.json --probe
```

Sans `--probe`, les statistiques restent disponibles avec Python seul ; les durées du plan strict sont calculées seulement pour les fichiers compatibles. Le rapport local contient des métadonnées d’identification : retire-les avant une publication. Les mesures ne constituent pas une vérification des auteurs ou de la provenance historique.
