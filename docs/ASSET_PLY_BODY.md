# Structure réelle des fichiers PLY

Parcimonia complète désormais l'en-tête PLY par une lecture bornée des
enregistrements : positions des sommets, listes d'indices des faces et paramètres
scalaires présents. Cela permet de proposer des tags de nuage de points, de
maillage ou de structure compatible avec des splats gaussiens, avec une preuve
liée au corps effectivement lu.

Cette étape ne produit pas de rendu et ne reconnaît pas l'objet représenté.
Un corps structurellement accepté ne certifie pas la qualité d'un modèle.

## Utilisation et tags

L'inspection existante prend en charge ce profil sans nouvelle commande :

```bash
python -m tiberium_ai.asset_cli inspect objet.ply --source-id objet-001 --revision v1 > report.json
python -m tiberium_ai.asset_cli search reports.json --tag representation:mesh_structure
python -m tiberium_ai.asset_cli search reports.json --tag representation:gaussian_splat_body_candidate
```

`reports.json` est un tableau de rapports existants. Les
[snapshots sauvegardés](ASSET_CATALOG_SNAPSHOTS.md) et le
[journal de revue](ASSET_TAG_REVIEW.md) réutilisent également ces rapports.
Tous les tags restent proposés jusqu'à décision applicable au rapport exact.

| Corps accepté | Nouvelle proposition |
| --- | --- |
| Au moins un sommet avec X/Y/Z locaux | `geometry:has_local_positions` |
| Sommets sans face | `representation:point_cloud_structure` |
| Faces avec indices dans les bornes | `representation:mesh_structure` |
| Paramètres scalaires compatibles avec le profil Gaussian | `representation:gaussian_splat_body_candidate` |

Les anciens tags `point_cloud_candidate`, `mesh_candidate` et
`gaussian_splat_candidate` restent des indices d'en-tête. Ils sont conservés
séparément des nouvelles observations du corps. Un en-tête
annonçant un nuage ou des splats peut donc rester visible même quand le corps
n'est pas pris en charge ou contient une erreur ; il ne devient pas une preuve
de corps valide.

## Positions, faces et preuves

Les propriétés sont lues dans leur ordre déclaré, en repérant `x`, `y` et `z`
par leur nom. Les propriétés scalaires supplémentaires sont consommées et
contrôlées pour conserver l'alignement. Les faces peuvent précéder les sommets
dans l'ordre déclaré des éléments.

Une face du profil contient une liste `vertex_indices` ou `vertex_index`, avec
au moins trois indices entiers compris entre zéro inclus et le nombre de
sommets exclu. Les quadrilatères et autres polygones sont admis dans la limite
du profil ; aucune triangulation n'est imposée ou calculée. Les autres
propriétés scalaires d'une face sont consommées. Une section de faces vide
peut omettre la liste, puisqu'aucun enregistrement n'est à lire.

Les métadonnées distinguent les comptes déclarés dans l'en-tête des comptes
observés après lecture du corps. `geometry_bounds_xyz` contient les minima et
maxima X/Y/Z, avec unités inconnues et repère local non spécifié. Sans sommet,
l'enveloppe est `null`.

**X/Y/Z ne deviennent jamais du GPS.** Le champ géographique `spatial` reste
`null` pour ces PLY. Une recherche par rectangle GPS ne les retrouve pas sur la
seule ressemblance numérique entre X/Y et longitude/latitude.

Les preuves comprennent :

- `ply:body` : plage d'octets, profil, encodage et comptes de champs/records lus ;
- `ply:position_extrema` : pour chacun des six extrema, valeur, propriété,
  indice du sommet et plage d'octets de son enregistrement.

L'indice de sommet commence à 1 ; ce n'est pas un numéro de ligne ASCII.
Le corps ASCII peut utiliser plusieurs séparateurs entre les champs. En cas
d'ex æquo, la première occurrence est retenue. Aucun tableau complet des
positions n'est ajouté au rapport : la provenance des bornes reste compacte.

## Candidats Gaussian Splatting

Le candidat repose sur les propriétés flottantes `x/y/z`, `f_dc_0..2`,
`opacity`, `scale_0..2` et `rot_0..3`, avec des valeurs finies effectivement lues.
Si des champs `f_rest_*` existent, le profil exige des types flottants, des
suffixes canoniques contigus `0..N-1` sans zéros initiaux et un nombre de champs
divisible par trois. Leur absence est admise. Cette signature ne
prouve ni l'origine du fichier ni sa compatibilité avec tous les lecteurs de
splats.

Les paramètres sont lus et contrôlés sous leur forme brute : aucune sigmoid,
exponentielle ou normalisation n'est appliquée. Dans l'export de référence
Inria, ces transformations sont séparées de l'écriture PLY. Une opacité hors
`[0,1]`, une échelle brute négative ou un quaternion non unitaire ne constituent
donc pas, à eux seuls, un défaut. Les coefficients SH ne sont pas interprétés
comme des couleurs RGB.

Les métadonnées `gaussian_parameters` indiquent la compatibilité de schéma et
le nombre d'enregistrements examinés. Le compte de rotations exactement nulles
est une observation brute, pas une note de qualité ; il reste inconnu si les
quatre propriétés flottantes ne sont pas présentes. Aucun tag « bon/mauvais
rendu », entraînement valide ou scène reconnue n'est produit.

## Profil et refus

API pure : `tiberium_ai.ply_body_probe.probe_ply_body(data, complete=True)`.
L'inspection utilise l'identité distincte `asset-ply-inspection/1` et lie
`parcimonia.ply-body-profile/v1` à son `input_hash`. Le catalogue autorise
explicitement cette identité. Les autres formats conservent leurs rapports
précédents ; les rapports PLY changés doivent être revus à nouveau.

| Ressource ou syntaxe | Limite |
| --- | --- |
| Source complète | 1 MiB |
| En-tête ASCII | 64 KiB, 2 048 lignes |
| Formats | ASCII 1.0, binaire little-endian 1.0 et big-endian 1.0 |
| Éléments du profil | `vertex` et `face`, au plus 10 000 records chacun |
| Propriétés | Au plus 256 par élément |
| Valeurs lues | Au plus 200 000 scalaires, compteurs de listes et indices inclus |
| Liste d'une face | Au plus 256 indices |
| Nombre ASCII | Au plus 128 caractères par token |

Les types scalaires PLY usuels et leurs alias explicites `int8/uint8`,
`int16/uint16`, `int32/uint32`, `float32/float64` sont pris en charge. Les
entiers doivent respecter leurs bornes ; les flottants doivent être finis.
Les `float32` ASCII sont arrondis selon leur type, avec refus du débordement.
La notation scientifique est permise pour les flottants, pas pour les entiers.

Le corps ASCII accepte les séparateurs ASCII et l'espace final. Le corps
binaire exige une consommation exacte : aucun `strip` ne retire des octets
ressemblant à des espaces. Les listes dans les sommets, les autres éléments,
les listes non couvertes et les types hors profil sont refusés pour cette
lecture du corps, sans conclure que tout fichier PLY de ce genre est invalide.

Troncature, valeur non finie, indice hors bornes, dépassement ou octets de fin
inattendus ne laissent pas de bornes ou de comptes observés partiels. Seules
les observations d'en-tête peuvent rester, avec un motif de refus. Un préfixe
n'est jamais certifié comme corps complet.

Le statut reste `partial` : pas de validation de surface fermée, orientation,
planéité, intersections, manifold, textures, unités physiques, rendu ou qualité
perceptuelle. Aucune ressource externe, commande native, GPU ou modèle n'est
appelé. Les budgets ne sont pas une garantie absolue de durée ou de mémoire.

## Reproduction

```bash
PYTHONPATH=src python examples/ply_catalog_demo.py
PYTHONPATH=src python -m pytest -q
```

La démonstration fabrique un nuage, un maillage et un candidat de splats avec
la bibliothèque standard ; elle ne lit pas de modèle personnel. Voir le
[point de vérification](../wiki/ASSET_PLY_BODY_2026-10-31.md).

Références primaires : [document original PLY de Greg Turk, copie universitaire](https://gamma-web.iacs.umd.edu/POWERPLANT/papers/ply.pdf),
[page PLY Georgia Tech](https://www.cc.gatech.edu/projects/large_models/ply.html),
[code d'export Gaussian Splatting Inria](https://github.com/graphdeco-inria/gaussian-splatting/blob/main/scene/gaussian_model.py).
