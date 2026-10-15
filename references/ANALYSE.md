# Premières références de construction

15 octobre 2026. Les deux modules fournis ont été lus directement depuis Z, sans modification. Les observations détaillées, les paramètres et les SHA256 sont conservés dans `analysis.json`. Aucun sample ni séquence de notes de ces références n’a été copié dans Pixel Rush.

| Fichier fourni | Titre interne | Patterns stockés | Ordres | Timing CIA | Durée du cycle |
| --- | --- | --- | --- | --- | --- |
| 2000AD – Creatures To The Rescue +3 trn.mod | kortis | 8 | 12 | vitesse 5, tempo 141 | 65,248 s |
| ACME (Melboorn) – PC Flanc – Who Easykg.MOD | monday | 7 | 8 | vitesse 6, tempo 125 | 61,440 s |

La vitesse et le tempo s’interprètent ensemble : à tempo égal, une vitesse plus basse fait avancer les lignes plus vite. Pour kortis, les 736 lignes jouées comprennent un saut de pattern ; la durée ne se calcule donc pas simplement avec douze patterns entiers.

**Réutilisation et variation.** Kortis enchaîne les patterns `0,1,2,0,1,2,3,4,5,6,6,7`. Monday emploie `1,0,2,3,4,5,5,6`. Les reprises et les variantes donnent une forme au morceau en limitant les données à stocker.

**Samples minuscules.** Les 16 samples non vides de kortis totalisent 4 436 octets. Plusieurs ont une boucle de 28 octets, précédée d’une amorce de longueur variable. Les 12 samples de monday totalisent 7 708 octets. La taille du matériau sonore ne suffit donc pas à prédire la richesse de son utilisation.

**Articulation écrite dans les patterns.** Les commandes de volume, de vibrato et de portamento occupent une place importante. Dans les patterns stockés de monday, la deuxième voie contient 82 changements de sample sans nouvelle note : l’instrument change pendant que la hauteur reste pilotée par la note courante ou un glissé. Ce procédé mérite d’être distingué d’un simple redéclenchement de sample.

**Application à Pixel Rush.** Le nouveau morceau utilise ses propres ondes triangulaires et impulsions de 32 ou 64 octets, ainsi que des percussions synthétisées. Les largeurs d’impulsion changent pendant certaines notes, les volumes suivent des petits contours et un passage emploie de vrais portamentos. Huit ordres réutilisent sept patterns sur 32 mesures, avec entrée, thème, réponse, passage aéré, montée et retour.

Ces observations portent sur les données des fichiers. Les noms des fichiers et les textes internes ne sont pas une vérification indépendante des auteurs ou de la provenance historique.

Pour recalculer les observations à partir d’un original conservé localement :

```powershell
python -m tracker4agents analyze path/to/reference.mod --output exports/reference-study.json
```
