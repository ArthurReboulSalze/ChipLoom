# Premières références de construction

15 octobre 2026. Les deux modules fournis ont été lus sans modification. Les observations détaillées et les paramètres sont conservés dans `analysis.json` sous les identifiants A01 et A02. Les noms et empreintes des originaux sont omis de cette étude publiée. Aucun sample ni séquence de notes de ces références n’a été copié dans Pixel Rush.

| Référence | Patterns stockés | Ordres | Timing CIA | Durée du cycle |
| --- | --- | --- | --- | --- |
| A01 | 8 | 12 | vitesse 5, tempo 141 | 65,248 s |
| A02 | 7 | 8 | vitesse 6, tempo 125 | 61,440 s |

La vitesse et le tempo s’interprètent ensemble : à tempo égal, une vitesse plus basse fait avancer les lignes plus vite. Pour A01, les 736 lignes jouées comprennent un saut de pattern ; la durée ne se calcule donc pas simplement avec douze patterns entiers.

**Réutilisation et variation.** A01 enchaîne les patterns `0,1,2,0,1,2,3,4,5,6,6,7`. A02 emploie `1,0,2,3,4,5,5,6`. Les reprises et les variantes donnent une forme au morceau en limitant les données à stocker.

**Samples minuscules.** Les 16 samples non vides d’A01 totalisent 4 436 octets. Plusieurs ont une boucle de 28 octets, précédée d’une amorce de longueur variable. Les 12 samples d’A02 totalisent 7 708 octets. La taille du matériau sonore ne suffit donc pas à prédire la richesse de son utilisation.

**Articulation écrite dans les patterns.** Les commandes de volume, de vibrato et de portamento occupent une place importante. Dans les patterns stockés d’A02, la deuxième voie contient 82 changements de sample sans nouvelle note : l’instrument change pendant que la hauteur reste pilotée par la note courante ou un glissé. Ce procédé mérite d’être distingué d’un simple redéclenchement de sample.

**Application à Pixel Rush.** Le nouveau morceau utilise ses propres ondes triangulaires et impulsions de 32 ou 64 octets, ainsi que des percussions synthétisées. Les largeurs d’impulsion changent pendant certaines notes, les volumes suivent des petits contours et un passage emploie de vrais portamentos. Huit ordres réutilisent sept patterns sur 32 mesures, avec entrée, thème, réponse, passage aéré, montée et retour.

Ces observations portent sur les données des fichiers. Elles ne constituent pas une vérification indépendante des auteurs ou de la provenance historique.

Pour recalculer les observations à partir d’un original conservé localement :

```powershell
python -m tracker4agents analyze path/to/reference.mod --output exports/reference-study.json
```
