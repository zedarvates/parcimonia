# Attentes explicites, manques et contradictions

Parcimonia peut comparer des attentes écrites par l'appelant avec les rapports
d'inspection déjà produits. Cela permet de demander, par exemple, une image
PNG d'au moins 512 pixels de large ou un PLY contenant au moins une face.
L'audit est un avis séparé ; il ne modifie ni fichier, ni catalogue, ni revue.

Un [contrôle préalable de cohérence](ASSET_EXPECTATION_CONSTRAINTS.md) peut
détecter deux règles incompatibles sur le même fait avant toute inspection.
Il possède son propre rapport et un vérificateur de certificats, sans changer
les quatre résultats de l'audit ci-dessous.

## Quatre résultats distincts

| Résultat d'un asset | Sens précis |
| --- | --- |
| `satisfied` | Toutes les comparaisons demandées correspondent aux déclarations du rapport fourni. |
| `contradicted` | Au moins une valeur disponible contredit une comparaison. Les autres inconnues restent visibles. |
| `unknown` | Aucune contradiction observée, mais au moins une preuve demandée n'est pas disponible. |
| `missing_report` | Aucun rapport fourni ne porte exactement l'identifiant et la révision demandés. |

**Un rapport manquant ne prouve pas qu'un fichier manque sur disque.** L'audit
n'inventorie pas les répertoires. Une absence de tag n'est pas une preuve
d'absence du contenu : elle produit `unknown`, même pour une source complète.

Un PLY dont le corps a été lu avec zéro face peut contredire l'attente
`observed_face_count >= 1`. Un PLY tronqué, pour lequel aucun compte observé
n'est disponible, produit `unknown` pour la même attente. Une image de largeur
1 contredit une exigence de largeur 512 ; cela ne la rend pas mauvaise dans
l'absolu. Ces distinctions ne constituent pas un solveur général de
l'impossibilité ou un diagnostic automatique de stabilité.

## Contrat versionné

```json
{
  "schema": "parcimonia.asset-expectations/v1",
  "id": "livraison-atelier-v1",
  "assets": [
    {
      "source": {"id": "image-001", "revision": "v1"},
      "checks": [
        {"id": "format", "fact": "format.detected", "op": "eq", "value": "png"},
        {"id": "largeur", "fact": "metadata.width", "op": "gte", "value": 512}
      ]
    },
    {
      "source": {"id": "objet-001", "revision": "v2"},
      "checks": [
        {"id": "faces", "fact": "metadata.observed_face_count", "op": "gte", "value": 1}
      ]
    }
  ]
}
```

Les champs sont fermés. Les identités attendues doivent être uniques et les
identifiants de contrôles uniques au sein d'un asset. Une révision est une
étiquette opaque : aucun remplacement par la plus récente, un nom de fichier
ou une révision approchante n'est tenté. Plusieurs révisions d'un même ID sont
admises dans un tableau de rapports si chaque paire ID/révision est unique.
Les tableaux de résultats suivent l'ordre explicite du contrat.

## Faits pris en charge

| Fait | Valeur attendue | Opérateurs |
| --- | --- | --- |
| `format.detected` | Texte exact, par exemple `png`, `ply`, `gpx` | `eq` |
| `sample.complete` | Booléen | `eq` |
| `sample.bytes` | Nombre d'octets de l'échantillon fourni, pas la taille totale supposée | `eq`, `gte`, `lte` |
| `spatial.crs` | Texte exact, par exemple `OGC:CRS84` | `eq` |
| `spatial.position_count` | Compte géographique déclaré dans le rapport | `eq`, `gte`, `lte` |
| `metadata.width`, `metadata.height` | Dimensions disponibles dans les métadonnées | `eq`, `gte`, `lte` |
| `metadata.channels`, `metadata.sample_rate`, `metadata.bits_per_sample`, `metadata.declared_frames` | Métadonnées audio disponibles, avec leur base d'origine | `eq`, `gte`, `lte` |
| `metadata.observed_vertex_count`, `metadata.observed_face_count`, `metadata.observed_field_value_count` | Comptes du corps PLY effectivement lu par son profil | `eq`, `gte`, `lte` |
| `metadata.observed_ply_encoding` | Texte de l'encodage observé | `eq` |
| `metadata.position_count` | Compte fourni par un lecteur géographique | `eq`, `gte`, `lte` |
| `tag:namespace:valeur` | `true` : présence d'une proposition exacte | `eq` |

Les comparaisons numériques utilisent des entiers de 0 à `2**63 - 1`, sans
coercition depuis booléens, flottants ou chaînes. Les seuils sont inclusifs.
Les textes sont comparés exactement, sans conversion de casse, unité ou CRS.
Les autres faits et opérateurs sont des erreurs d'entrée, pas des contrôles
silencieusement ignorés. Les valeurs absentes ou `null` restent inconnues.

Un tag présent satisfait seulement la demande de présence de cette
**proposition**. Une proposition fondée sur une extension reste un indice de
nom de fichier ; elle n'est pas promue en format constaté. Une proposition
rejetée dans un journal reste présente dans le rapport original : ce premier
audit n'applique pas les décisions du journal. Il ne crée aucune acceptation.

Les valeurs disponibles conservent leur base, leurs chemins dans le rapport et,
pour métadonnées et tags, leurs références de preuves. Une métadonnée sélectionnée
doit avoir un nom unique, une forme reconnue et une référence existante. Une
déclaration mal formée provoque une erreur d'entrée ; elle n'est pas convertie
en résultat inconnu. Les champs racines sont liés par chemin et hash du rapport.

## API et CLI

API pure : `audit_asset_expectations(reports, expectations)` dans
`tiberium_ai.asset_expectations`. Le résultat possède son propre schéma
`parcimonia.asset-expectation-audit/v1`, l'analyseur
`asset-expectation-audit/1`, le hash du contrat, les hashes des rapports exacts,
un résultat par asset et un récapitulatif des quatre états.

```bash
PYTHONPATH=src python -m tiberium_ai.asset_cli audit-expectations reports.json attentes.json
PYTHONPATH=src python -m tiberium_ai.asset_cli audit-expectations catalogue.json attentes.json --catalog
PYTHONPATH=src python -m examples.asset_expectations_demo --summary
```

Sans `--catalog`, l'entrée est un tableau JSON de rapports. Avec `--catalog`,
elle est un [snapshot existant](ASSET_CATALOG_SNAPSHOTS.md) validé puis exporté
par les fonctions du catalogue. La réponse reçoit une enveloppe distincte
`parcimonia.asset-catalog-expectation-audit/v1` : référence du catalogue,
hash lié à cette génération et résultat de l'audit. Les rapports existants
gardent leur schéma et leur contenu.

Le code de sortie **0 signifie qu'un audit exploitable a été produit**, y compris
si des attentes sont contredites ou des rapports manquent. Le code 2 signale une
erreur d'entrée, de lecture ou de budget, sans JSON partiel sur stdout. Les
fichiers d'entrée restent inchangés. Le shell peut sauvegarder stdout dans un
nouveau fichier choisi explicitement par l'utilisateur.

## Bornes, provenance et limites

| Ressource | Plafond |
| --- | --- |
| Contrat JSON canonique UTF-8 | 64 KiB |
| Assets attendus | 64 |
| Contrôles | 32 par asset, 256 au total |
| Rapports | 256, 2 MiB et 20 000 nœuds chacun, profondeur 64 |
| Tableau de rapports canonique UTF-8 | 16 MiB |
| Preuve sélectionnée d'un contrôle | 16 KiB canoniques UTF-8 ; refus au-delà, sans troncature |
| Audit canonique UTF-8 et sortie CLI ASCII | 16 MiB chacun |

La lecture CLI du tableau ou du snapshot est aussi limitée à 200 000 nœuds.
Le contrat passe par le validateur JSON partagé à 20 000 nœuds/profondeur 64.
Les hashes lient le contenu et l'ordre exacts des rapports et du contrat à la
version de l'analyseur. Changer un rapport, une attente ou la sélection d'un
snapshot exige un nouvel audit ; aucun résultat précédent n'est reporté comme
preuve sur de nouvelles entrées.

Les rapports fournis restent des déclarations non authentifiées. L'audit
vérifie leurs contrats et compare les champs sélectionnés ; il ne rejoue pas
les lecteurs sur les sources et ne valide pas récursivement toutes leurs
preuves. `satisfied` n'atteste ni contenu sémantique, ni qualité visuelle,
ni entraînement, ni stabilité du logiciel, ni exhaustivité d'une livraison.
Les caractéristiques non demandées restent hors audit. Aucun modèle, outil
natif, accès réseau ou déplacement de fichier n'est déclenché. Aucun gain de
coût ou de vitesse n'est mesuré ici.

La [démonstration conservée](../wiki/ASSET_EXPECTATIONS_DEMO_2026-10-31.json)
contient uniquement des fixtures fabriquées, leurs rapports, le contrat et
les quatre résultats. Voir le [point de vérification](../wiki/ASSET_EXPECTATIONS_2026-10-31.md).
