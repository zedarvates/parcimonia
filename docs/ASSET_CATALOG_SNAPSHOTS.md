# Enregistrer et reprendre le catalogue de fichiers

Un catalogue sauvegardé rassemble les rapports de perception et de classification
déjà produits : texte, code, images, OCR/PDF, audio ou 3D par en-têtes, et
localisation GeoJSON. Il permet de reprendre une sélection de rapports, remplacer
un rapport précis et retrouver les tags acceptés dans le journal de revue.

Chaque modification crée une nouvelle valeur et, avec la CLI, un nouveau fichier.
Les versions précédentes restent utilisables. Les fichiers analysés et le journal
de revue ne sont pas modifiés. Le catalogue conserve les rapports entiers avec
leurs preuves ; il n'ajoute pas une nouvelle capacité de reconnaissance.

## Une sélection courante par source

Le catalogue contient au plus un rapport par `source.id`. Les entrées sont triées
par cet identifiant. Une nouvelle révision ou un enrichissement OCR remplace
explicitement l'entrée de cette source ; les autres entrées restent identiques.
Les révisions sont des étiquettes opaques, sans comparaison de date ou de numéro.
L'appelant choisit le rapport à retenir et fournit son identité.

Les contrôles de modification sont :

| Précondition | Rôle |
| --- | --- |
| `expected_head` | Hash exact du snapshot fourni à l'opération |
| `expected_report_hash=None` / `none` en CLI | Insertion d'une source absente |
| `expected_report_hash` égal au rapport courant | Remplacement ou retrait de cette source |

Même un réessai avec un rapport identique vérifie d'abord ces préconditions. S'il
est exact, il retourne une copie indépendante sans changer la génération. Une
modification effective incrémente la génération et référence le hash du snapshot
précédent. Retirer un rapport enlève sa sélection du nouveau catalogue ; cela ne
supprime pas le fichier analysé ni les anciennes décisions.

Ces préconditions comparent les objets fournis. Elles ne consultent aucun pointeur
global vers « le dernier catalogue » et ne verrouillent pas un stockage partagé.
Deux utilisateurs peuvent produire deux branches à partir du même ancien snapshot.
Le hash du parent ne vérifie pas récursivement son existence ou son contenu.

## Commandes

```bash
python -m tiberium_ai.asset_cli catalog-init catalog-000.json --catalog-id mes-fichiers
python -m tiberium_ai.asset_cli catalog-put catalog-000.json report.json --expected-head SHA_C0 --expected-report-hash none --out catalog-001.json
python -m tiberium_ai.asset_cli catalog-search catalog-001.json reviews.json --tag topic:robotique
python -m tiberium_ai.asset_cli catalog-export catalog-001.json --out reports-001.json
```

Remplacer `SHA_C0` par le `snapshot_hash` réel de `catalog-000.json`, imprimé
par la première commande. `report.json` est un rapport d'inspection initial ou
d'[enrichissement OCR/PDF](ASSET_TEXT_EXTRACTION.md) existant. `reviews.json`
est un [journal de revue](ASSET_TAG_REVIEW.md) existant, éventuellement vide.

Pour remplacer une entrée, donner le hash du snapshot courant et le hash du
rapport actuellement sélectionné :

```bash
python -m tiberium_ai.asset_cli catalog-put catalog-001.json report-v2.json --expected-head SHA_C1 --expected-report-hash SHA_RAPPORT_V1 --out catalog-002.json
python -m tiberium_ai.asset_cli catalog-remove catalog-002.json --source-id fichier-001 --expected-head SHA_C2 --expected-report-hash SHA_RAPPORT_V2 --out catalog-003.json
```

Les valeurs `SHA_...` sont des valeurs à remplacer. Le hash d'un rapport entier
est celui calculé par `validated_review_report_hash(report)` ; il diffère du hash
des octets du fichier et de `report.input_hash`.

Les sorties d'écriture donnent l'identifiant de catalogue, la génération, le hash,
le nombre d'entrées et le chemin créé. `catalog-put` indique aussi
`snapshot_changed`. Un réessai identique peut créer une nouvelle copie de fichier
dont la génération et le hash restent identiques.

Les commandes de catalogue renvoient `0` si elles réussissent, `2` si la lecture,
le contrat, une précondition ou l'écriture est refusée. Elles lisent des fichiers
réguliers explicites, avec les mêmes contrôles que les commandes existantes.
Les écritures utilisent un chemin nouveau ouvert exclusivement : un chemin
existant, y compris un lien, n'est pas écrasé. Une interruption peut laisser un
nouveau fichier partiel ; la version d'entrée reste disponible. Cette création
exclusive n'est pas une publication atomique du contenu.

## Recherche et compatibilité

`catalog-search` exige un journal explicite. La politique de tags est celle de
`search-reviewed` : avec un filtre de tag, les tags acceptés sont retenus par
défaut. `--state proposed` ou `--state rejected` permettent d'examiner les autres
états. Plusieurs tags se combinent par ET. Sans filtre de tag, un listing ne
signifie pas que les fichiers sont approuvés.

`--bbox ouest sud est nord` utilise l'enveloppe CRS84 existante ; un résultat reste
un candidat d'intersection d'enveloppes. Il ne prouve ni une intersection exacte
de géométries ni l'identité d'un lieu. `--limit` conserve la borne de 256 résultats.

La sortie `parcimonia.asset-catalog-reviewed-search/v1` contient :

- `catalog` : identifiant, génération et hash du snapshot interrogé ;
- `result` : rapport `parcimonia.asset-reviewed-search/v1` existant, avec requête,
  tête du journal, résultats, états des tags et provenance de décision ;
- `input_hash` : liaison entre cette référence de catalogue et la recherche exacte.

Un rapport remplacé n'hérite pas d'une acceptation de l'ancien rapport. Les
décisions des entrées inchangées continuent à s'appliquer. Les anciennes décisions
restent dans le journal et s'appliquent toujours à un ancien snapshot compatible.
Réimporter le rapport ancien strictement identique peut donc retrouver sa décision
antérieure ; un retrait du catalogue ne constitue pas une révocation de revue.

`catalog-export --out` produit un tableau JSON compatible avec les commandes
existantes `search`, `review-view` et `search-reviewed`. Leur contrat d'entrée ne
change pas. Sans `--out`, le tableau est imprimé sur stdout en JSON ASCII, comme
les autres sorties CLI. Si les échappements Unicode font dépasser 16 MiB, la
commande refuse avant d'imprimer et demande d'utiliser `--out`. L'export vers un
fichier conserve le texte Unicode en UTF-8 compact et reste dans les limites de
lecture du catalogue.

## API et format sauvegardé

Les fonctions pures de `tiberium_ai.asset_catalog_snapshot` sont :

| Fonction | Résultat |
| --- | --- |
| `create_asset_catalog(catalog_id)` | Snapshot vide, génération zéro |
| `validate_asset_catalog(snapshot)` | Validation structurelle, limites et hash |
| `put_asset_report(snapshot, report, expected_head=..., expected_report_hash=...)` | Nouvelle sélection ou copie identique |
| `remove_asset_report(snapshot, source_id, expected_head=..., expected_report_hash=...)` | Nouvelle sélection sans cette entrée |
| `export_asset_reports(snapshot)` | Copie indépendante des rapports courants |

Le schéma fermé `parcimonia.asset-catalog-snapshot/v1` contient exactement
`schema`, `catalog_id`, `generation`, `parent_hash`, `reports` et `snapshot_hash`.
Le dernier champ est le SHA-256 canonique des cinq autres champs, calculé avec
`hash_input`. Une génération zéro doit être vide et sans parent. Les générations
suivantes ont un parent déclaré. Les générations sont des entiers stricts de zéro
à `2**63 - 1`, sans booléens.

| Limite | Portée |
| --- | --- |
| 256 rapports | Une entrée par identité de source, même si les révisions diffèrent |
| 2 MiB par rapport | JSON canonique UTF-8 du rapport entier |
| 16 MiB par snapshot | JSON canonique entier, champ `snapshot_hash` compris |
| 200 000 nœuds, profondeur 64 | Snapshot entier, aligné sur le lecteur CLI |
| 20 000 nœuds et 256 propositions par rapport | Validateur partagé des rapports de revue |

La sérialisation canonique trie les clés et utilise des séparateurs compacts,
`ensure_ascii=False`, `allow_nan=False` et UTF-8. Le stockage CLI n'ajoute pas de
nouvelle ligne, pour conserver les bornes exactes. Les clés et valeurs doivent
être de types JSON exacts : les coercitions Python, cycles et nombres non finis
sont refusés. Les objets partagés sans cycle restent possibles et comptent à
chaque occurrence sérialisée. Les limites de profondeur et de nœuds sont globales,
en plus des limites par rapport.

Les sauvegardes n'authentifient pas les sources ou les acteurs et ne détectent pas
une réécriture cohérente d'un historique entier. Les chemins et identifiants sont
déclarés par l'appelant ; aucun fichier n'est rescanné pour vérifier qu'il est
encore à sa place. Aucun dédoublonnage de fichiers ou choix automatique de dernière
révision n'est ajouté. Le moteur reste une recherche bornée sur des rapports
chargés en mémoire, sans base de données ni mesure de gain de performance.

## Démonstration

```bash
PYTHONPATH=src python examples/asset_catalog_snapshot_demo.py
PYTHONPATH=src python -m pytest -q
```

La démonstration fabrique un texte et un point GeoJSON, enregistre et relit cinq
snapshots dans un répertoire temporaire. Elle vérifie l'acceptation initiale,
l'absence de transfert à une nouvelle révision, la conservation de l'acceptation
d'une source inchangée, puis le retrait d'une entrée. Les fichiers temporaires
sont supprimés à la fin ; il ne s'agit pas d'un catalogue personnel. Voir le
[point de vérification](../wiki/ASSET_CATALOG_SNAPSHOTS_2026-10-30.md).
