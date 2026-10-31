# Similarité et compléments sourcés

Le catalogue peut désormais conserver des relations dirigées explicitement
déclarées entre ses rapports et les rechercher selon deux intentions distinctes :
« similaire » et « complémentaire ». Il s'agit d'un fichier annexe versionné ;
le schéma du catalogue, les tags et leur journal de revue restent inchangés.

Cette première application s'inspire du problème étudié par
[MAGE](https://arxiv.org/abs/2610.37409) : un voisin sémantique n'est pas
nécessairement un complément utile. Elle ne reproduit ni la transformation des
embeddings ni le réseau de recommandation de MAGE. Les relations sont fournies
par l'appelant, pas découvertes par le programme.

## Préparer des relations explicites

La commande `relations-build` lit un catalogue existant et un tableau JSON de
déclarations. Par exemple, si les sources `maison` et `toit` sont sélectionnées :

```json
[
  {
    "id": "maison-toit",
    "source_id": "maison",
    "target_id": "toit",
    "kind": "complements",
    "evidence": [
      {
        "reference": "recettes/maison-A.json",
        "revision": "r1",
        "locator": "/components/roof"
      }
    ]
  }
]
```

```bash
PYTHONPATH=src python -m tiberium_ai.asset_cli relations-build catalog.json declarations.json --relations-id architecture-A --expected-head CATALOG_HASH --out relations-001.json
PYTHONPATH=src python -m tiberium_ai.asset_cli relations-search catalog.json relations-001.json --source-id maison --intent complementary --limit 5
PYTHONPATH=src python -m tiberium_ai.asset_cli relations-search catalog.json relations-001.json --source-id maison --intent similar --limit 5
```

Remplacer `CATALOG_HASH` par le `snapshot_hash` exact du catalogue utilisé lors
de la rédaction des déclarations. La commande refuse une tête différente avant
de lier les rapports. Cette précondition ne surveille pas un stockage partagé et
ne prouve pas que le fichier fourni est le dernier catalogue disponible.

Chaque extrémité est liée à l'identifiant de source, sa révision et le SHA-256
canonique du rapport complet. La sortie est un fichier nouveau, créé
exclusivement : un chemin existant ou un lien ne peut pas être écrasé.
Réexécuter une préparation avec des rapports changés constitue une nouvelle
déclaration explicite, pas une revalidation automatique d'une ancienne relation.

## Sens et résolution des résultats

| Relation déclarée | Intention de recherche |
| --- | --- |
| `similar_to` | `similar` uniquement |
| `complements`, `requires`, `used_with`, `compatible_with` | `complementary` |
| `tested_by`, `fixed_by` | `complementary`, pour rapprocher une source de son test ou correctif |
| `incompatible_with` | Bloque les candidats complémentaires de la même paire dirigée |

Toutes les relations ont le statut `caller_declared`. Même `compatible_with`
reste une déclaration, sans certification de compatibilité. Les références,
révisions et localisateurs des preuves sont conservés sans être ouverts,
authentifiés ou vérifiés. Leur fraîcheur externe n'est pas évaluée.

La recherche renvoie :

- `matches` : cibles directes, avec les relations et références qui les proposent ;
- `blocked_candidates` : candidats écartés par une incompatibilité courante de
  la même paire, avec les déclarations positives et les blocages ;
- `unapplied_relations` : relations dont une extrémité est absente, a changé de
  révision ou ne possède plus le même hash de rapport ;
- les identités et hashes du catalogue, des relations et de la requête.

L'ordre est celui des identifiants de cible, sans score de qualité appris.
`limit` borne les candidats renvoyés ; `count` les compte et `truncated` indique
si d'autres candidats étaient disponibles. Les listes de blocages et de liens
inapplicables restent complètes dans la borne du document. Cette dernière liste
couvre le document entier, même les relations étrangères à la source interrogée.

Un blocage courant domine les déclarations positives quel que soit leur ordre.
Une incompatibilité isolée, sans proposition positive de la même paire, ne
figure pas dans `blocked_candidates` : cette sortie n'est pas un inventaire
général des incompatibilités connues.
Un blocage périmé est signalé comme inapplicable. Une incompatibilité ne supprime
pas un résultat `similar`, car deux variantes peuvent se ressembler tout en
étant incompatibles. Aucun lien inverse ou transitif n'est ajouté ; demander les
compléments d'un toit ne reprend pas implicitement les liens maison → toit.
Un changement d'un élément sans rapport avec les extrémités conserve les liens
encore applicables. Retirer une source n'efface pas son ancien document.

## API et limites

Les fonctions pures sont dans `tiberium_ai.asset_relations` :

| Fonction | Rôle |
| --- | --- |
| `bind_asset_relation` | Lier une déclaration aux rapports courants |
| `bind_asset_relations` | Lier un lot de déclarations et sceller son document |
| `create_asset_relations` | Sceller des relations déjà liées et encore courantes |
| `validate_asset_relations` | Contrôler le contrat et son hash, sans certifier les sources |
| `search_asset_relations` | Rechercher les candidats directs sur un catalogue fourni |

Le schéma fermé `parcimonia.asset-relations/v1` contient `schema`, `id`,
`catalog_id`, `relations`, `relations_hash`. Le hash porte sur les quatre premiers
champs. Chaque relation contient `id`, `source`, `target`, `kind`, `evidence`,
`status`. Les extrémités contiennent `id`, `revision`, `report_hash`.

Les relations sont triées par identifiant unique. Les entrées acceptent au plus
256 relations et 8 références par relation. Le document est borné à 1 Mio UTF-8
canonique, avec les contrôles JSON existants de profondeur 64 et 20 000 nœuds.
Le résultat de recherche est borné à 4 Mio ; la CLI contrôle aussi sa taille
ASCII réelle avant impression. Les recherches acceptent une limite entière
de 1 à 256, en refusant les booléens. Les commandes renvoient `0` pour un résultat
valide, y compris une recherche vide, et `2` pour une entrée ou écriture refusée.

Les fonctions retournent des copies indépendantes. Elles n'exécutent ni modèle,
ni réseau, ni accès à une preuve référencée. Les hashes assurent la cohérence
interne, sans authentifier l'appelant ou empêcher une réécriture cohérente de
l'ensemble. Les acceptations de tags ne deviennent pas des acceptations de liens.

## Premier cas Ultimate Odycer

```bash
PYTHONPATH=src python examples/asset_relations_demo.py
PYTHONPATH=src python -m pytest -q tests/test_asset_relations.py tests/test_asset_relations_cli.py
```

Le démonstrateur utilise quatre textes de fixture : maison, variante, toit et
escalier. Il retrouve la variante en recherche similaire, le toit en recherche
complémentaire, et signale l'escalier bloqué par une déclaration incompatible.
Changer la révision du toit rend son ancienne relation inapplicable. La requête
inverse ne retourne aucun résultat. Aucun modèle de maison, escalier 3D,
collision, dimension, rendu ou recette réelle d'Ultimate Odycer n'est validé par
cet exemple.

Pour utiliser ces candidats dans un éditeur, vérifier ensuite les dimensions,
unités, appuis et collisions avec ses contrôles métier. Pour le second cerveau,
ce canal peut préparer les références incident → correctif → test à faire lire
au moteur existant ; aucune connexion au wiki ou au LLM local n'est activée ici.

La prochaine épreuve métier doit comparer la recherche actuelle et ce canal sur
30 demandes réelles, dont 20 réservées sans ajustement : utilité des cinq premiers
résultats, fausses compatibilités, éléments manquants retrouvés et durée. Ces
demandes ne sont pas encore collectées. Aucun gain de qualité, coût ou vitesse
n'est revendiqué. Repli : conserver les recherches de tags et le catalogue
existants sans appeler les nouvelles commandes.
