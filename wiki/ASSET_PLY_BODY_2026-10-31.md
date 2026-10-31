# Vérification — corps PLY, géométrie locale et candidats de splats — 2026-10-31

Objectif : passer des indices d'en-tête à des tags appuyés sur les enregistrements
réellement lus dans un fichier PLY. Proposition empilée sur la PR #28, tête
`b0592c3b69ddf10d42d2281cce9f22f69c8de991`, sans fusion ni activation.

## Réalisation

- Lecteur pur et borné du corps PLY 1.0 ASCII, binaire little-endian et
  big-endian : scalaires typés, valeurs finies, propriétés dans l'ordre déclaré,
  indices des faces contrôlés. Les faces polygonales sont admises ; elles ne
  sont pas triangulées. Les propriétés scalaires supplémentaires sont consommées.
- Lecture atomique : une erreur, une troncature, des octets finaux inattendus ou
  un dépassement de budget retirent toutes les observations du corps. Les seuls
  indices d'en-tête peuvent subsister avec le motif de refus.
- Comptes observés, enveloppe X/Y/Z locale et six extrema avec indice du sommet
  et plage d'octets de son enregistrement. Aucun tableau complet des positions
  n'est conservé. Le champ `spatial` reste `null`, même pour des X/Y ressemblant
  à des coordonnées GPS ou un commentaire mentionnant un système géographique.
- Tags proposés de positions locales, nuage de points, maillage et candidat de
  splats. Le profil distingue la signature flottante compatible des paramètres
  bruts : une opacité ou une échelle négative ne produit pas de jugement de
  qualité. Les coefficients SH ne deviennent pas des couleurs RGB.
- Identité `asset-ply-inspection/1` acceptée explicitement par le catalogue,
  profil `parcimonia.ply-body-profile/v1` lié au hash d'entrée, recherche,
  snapshots et revue existants réutilisés. Un corps modifié invalide les
  décisions du rapport précédent ; l'ancien snapshot reste consultable.

## Validation locale

**2 378 tests passent sur Python 3.12.14**, sans test ignoré : les 2 194 tests
de la base et **184 nouveaux cas**, dont 154 pour le lecteur et 30 pour
l'intégration et la démonstration. Un avertissement de dépréciation provient
du plugin pytest `anyio` de l'environnement, sans échec.

Les cas couvrent les trois encodages, l'ordre des propriétés et éléments,
les types et alias, les bornes d'entiers, l'arrondi float32, les preuves
d'extrema et leurs plages exactes, les polygones, les échecs tardifs atomiques,
les plafonds exacts et dépassés, les paramètres de splats, l'absence d'I/O et
la conservation des rapports non PLY. Les tests d'intégration vérifient aussi
la sérialisation JSON stricte, les snapshots, le journal de revue, la CLI et
l'absence de correspondance dans une recherche géographique.

La démonstration utilise exclusivement des fixtures fabriquées avec la
bibliothèque standard. Ses [résultats conservés](ASSET_PLY_BODY_DEMO_2026-10-31.json)
ont été reproduits à l'identique après la dernière correction :

| Fixture | Encodage | Sommets / faces observés | Minimum X/Y/Z | Maximum X/Y/Z |
| --- | --- | --- | --- | --- |
| Nuage | ASCII | 3 / 0 | -1, 2, -2 | 1, 3, 4 |
| Maillage avec un quadrilatère | Binaire big-endian | 4 / 1 | 1, 2, 0 | 2, 3, 3 |
| Candidat de splats | Binaire little-endian | 2 / 0 | -1, 2, 0 | 1, 4, 3 |

Pour chaque fixture : un résultat de recherche parmi les propositions,
zéro accepté avant revue, un accepté après revue, zéro acceptation héritée
après modification du corps, un résultat toujours accepté dans l'ancien
snapshot, et zéro correspondance dans la recherche GPS. Aucun modèle personnel
n'a été lu et aucun rendu ou appel de modèle n'a été effectué.

## Revue indépendante et correction

La relecture a trouvé un désaccord concret entre le découpage de l'en-tête
existant en octets et sa seconde lecture en texte. `str.splitlines()` pouvait
interpréter VT, FF, FS, GS ou RS à l'intérieur d'un commentaire comme une nouvelle
ligne. Une propriété fictive pouvait alors décaler X/Y/Z, inventer une signature
de splats ou provoquer une exception avant le premier élément.

Le lecteur utilise désormais les mêmes frontières de lignes en octets que
l'analyseur d'en-tête. Vingt cas de régression couvrent ces cinq caractères et
quatre positions/effets. La contre-revue a reproduit les erreurs de l'ancienne
fonction en mémoire puis vérifié le refus ou les observations corrigées.
Un commentaire contenant une fausse propriété ne peut plus faire lire quatre
valeurs comme trois coordonnées ; les valeurs supplémentaires sont refusées.

Des oracles indépendants ont aussi vérifié six combinaisons d'encodage et
d'ordre des éléments, les extrema exacts, la conservation d'octets binaires
ressemblant à des espaces, les indices invalides, la troncature, les valeurs
non finies, les paramètres bruts de splats et le seuil de 200 000 valeurs.
Aucun autre défaut reproductible n'a été identifié dans le périmètre relu.

## Reproduction et limites

```bash
PYTHONPATH=src python examples/ply_catalog_demo.py
PYTHONPATH=src python -m pytest -q
```

Guide et références primaires : [ASSET_PLY_BODY.md](../docs/ASSET_PLY_BODY.md).
La grammaire Python 3.10 et les espaces du patch ont été vérifiés.

Le profil accepte au plus 1 MiB de source complète, 64 KiB / 2 048 lignes
d'en-tête, 10 000 sommets et 10 000 faces, 256 propriétés par élément,
200 000 valeurs scalaires et 256 indices par face. Ces restrictions sont celles
du profil ; un refus ne rend pas nécessairement invalide un autre fichier PLY.
Un préfixe ne devient jamais une preuve de corps complet.

Le statut reste `partial` : pas de validation complète de topologie ou de
surface, d'unités physiques, de géoréférencement, de rendu, de qualité
perceptuelle ou d'entraînement. La signature de splats ne garantit pas la
compatibilité avec tous les lecteurs. Aucun reclassement des fichiers ni gain
de coût, de mémoire ou de vitesse n'a été mesuré. Les budgets ne constituent
pas une garantie absolue de temps ou de mémoire.

Repli : conserver les rapports antérieurs et les indices d'en-tête ; les
nouvelles propositions ne sont pas des acceptations automatiques.
