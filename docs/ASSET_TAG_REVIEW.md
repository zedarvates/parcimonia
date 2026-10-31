# Conserver les tags acceptés, rejetés et à revoir

Les inspections proposent des tags. Cette extension conserve les décisions de
revue dans un journal séparé, puis les projette sur un catalogue précis.
Les fichiers analysés et les propositions d'origine restent intacts.

Les rapports de l'[extraction locale du texte](ASSET_TEXT_EXTRACTION.md)
utilisent le même parcours de revue, avec une identité d'analyseur distincte et
un lien au rapport d'extraction exact. Une acceptation de l'inspection initiale
ne devient pas automatiquement une acceptation du rapport enrichi.

Le [catalogue sauvegardé](ASSET_CATALOG_SNAPSHOTS.md) peut conserver une sélection
courante de rapports. Les entrées inchangées gardent leurs décisions applicables ;
une entrée remplacée est évaluée contre son nouveau rapport exact.

Un tag accepté signifie qu'un acteur déclaré a enregistré ce jugement. Cela
ne prouve pas son identité, le contenu réel du fichier ou l'autorisation de
lancer une action. Aucune décision n'est enregistrée automatiquement par un modèle.

## Trois états et un historique

| Action enregistrée | État effectif | Historique |
| --- | --- | --- |
| Aucune décision | `proposed` | Proposition de l'inspection |
| `accept` | `accepted` | Décision conservée avec acteur et motif |
| `reject` | `rejected` | Faux positif ou tag jugé inadapté, avec motif |
| `reset` | `proposed` | Retour à la revue, sans effacer les décisions antérieures |

Chaque décision vise un tag déjà proposé, identifié par son espace de noms et
sa valeur. Une proposition absente ne peut pas être inventée par cette API.
Plusieurs bases d'observation du même tag sont regroupées dans la vue de revue,
en conservant leurs références de preuve.

## Liaison au bon fichier et à la bonne analyse

Une décision se lie à l'identité de source, à la révision et au SHA-256 du
**rapport d'inspection entier**. Le hash d'un préfixe, le nom du fichier ou son
seul hash de contenu ne suffisent pas pour transférer un choix.

Une nouvelle révision commence avec ses propres propositions. Un rapport changé
par un nouveau vocabulaire, de nouvelles preuves ou une analyse différente ne
reprend pas les décisions de l'ancien. Les anciens choix restent dans le journal
et sont signalés comme non appliqués : source absente, révision différente ou
rapport différent. Plusieurs révisions explicitement présentes dans le catalogue
restent distinctes ; le système ne devine pas laquelle est « la plus récente ».

La frontière de revue exige du JSON pur : objets à clés chaînes, listes,
chaînes UTF-8 valides, nombres finis, booléens et null. Tuples, clés non textuelles,
objets particuliers et cycles sont refusés avant le hachage. Cela empêche qu'une
conversion implicite de Python vers JSON masque un changement de représentation.

## API

| Fonction | Comportement |
| --- | --- |
| `create_tag_journal()` | Retourne un journal vide, sans fichier ni horloge |
| `validate_tag_journal(journal)` | Contrôle schéma, séquence, identifiants, liens et tête |
| `append_tag_decision(journal, report, ...)` | Produit une nouvelle copie avec une décision explicite |
| `project_tag_reviews(reports, journal)` | Calcule les états effectifs et les événements non appliqués |
| `search_reviewed_assets(reports, journal, ...)` | Recherche les tags avec une politique d'états explicite |

Les trois premières fonctions viennent de `tiberium_ai.asset_tag_journal`, les
deux suivantes de `tiberium_ai.asset_tag_review`. Les objets d'entrée ne sont
pas mutés et les retours n'exposent pas d'alias mutable de l'historique.

Schémas versionnés : `parcimonia.asset-tag-journal/v1`,
`parcimonia.asset-tag-decision/v1`, `parcimonia.asset-tag-review/v1` et
`parcimonia.asset-reviewed-search/v1`. Le schéma d'inspection proposé par la
[première étape](ASSET_PERCEPTION.md) reste inchangé.

## Tête attendue, reprises et limites de la chaîne

Chaque événement contient un identifiant unique, un numéro de séquence, le
hash précédent, l'identité de source, le hash du rapport, le tag, l'action,
l'acteur déclaré et son motif. Son hash couvre ces champs. Le journal conserve
le hash de son dernier événement.

Une nouvelle décision exige `expected_head`, la tête que l'appelant pense
modifier. Une tête périmée est refusée : il faut relire l'historique avant
d'ajouter un nouveau choix. Il s'agit d'une vérification de l'instantané fourni,
pas d'un verrou sur plusieurs processus ou machines.

Une reprise avec le même identifiant et exactement la même déclaration, y
compris la tête précédente d'origine, ne duplique pas l'événement. Elle retourne
l'historique courant. Un ancien `accept` rejoué après un `reject` plus récent
ne réapplique donc pas l'ancien choix. Réutiliser un identifiant avec une autre
déclaration est refusé.

La chaîne détecte les incohérences internes. Elle ne signe pas l'identité d'un
acteur et ne détecte pas une réécriture cohérente de tout l'historique ou une
troncature suivie d'une nouvelle tête cohérente. Il faut une tête indépendante
conservée ailleurs pour comparer à un état attendu. Cette version n'ajoute pas
d'infrastructure de signature ou de stockage protégé.

## CLI et persistance explicites

Depuis la racine du dépôt après installation de développement :

```powershell
python -m tiberium_ai.asset_cli review-init reviews-000.json
python -m tiberium_ai.asset_cli review-tag report.json reviews-000.json --tag topic:robotique --decision accept --actor local-reviewer --reason "Tag pertinent dans cet exemple" --event-id review-001 --expected-head none --out reviews-001.json
python -m tiberium_ai.asset_cli review-view catalogue.json reviews-001.json
python -m tiberium_ai.asset_cli search-reviewed catalogue.json reviews-001.json --tag topic:robotique
python -m tiberium_ai.asset_cli search-reviewed catalogue.json reviews-001.json --tag topic:robotique --state rejected
```

`report.json` est un rapport d'inspection, `catalogue.json` un tableau de ces
rapports. `none` désigne la tête du journal vide. Pour la décision suivante,
utiliser le `head_hash` retourné par la précédente commande et un nouvel
identifiant d'événement.

`review-init` et `review-tag` écrivent seulement un **nouveau** fichier de
journal, sur le chemin explicite fourni. Un chemin existant est refusé, y
compris le rapport ou le journal d'entrée. Le répertoire parent doit exister.
La sortie stdout est un petit compte rendu d'écriture, pas le journal complet.
`event_created=false` signale une reprise sans ajout d'événement ; le nouvel
instantané peut néanmoins avoir été créé.

L'écriture suit le motif exclusif déjà utilisé par les mesures et observations
du dépôt. Elle ne fournit pas une transaction partagée ou une publication
atomique du contenu : une interruption peut laisser un nouveau fichier incomplet,
que la lecture refuse. Le journal d'entrée reste disponible.

La CLI refuse de créer un instantané UTF-8 dépassant sa borne de relecture de
8 Mio. La limite est vérifiée sur les octets sérialisés avant de créer le fichier,
car une longueur en caractères ne suffit pas avec Unicode. Les codes de sortie
existants restent applicables : `0` rapport produit, `2` entrée/lecture/écriture
refusée ; les commandes d'inspection conservent aussi le code `3` indéterminé.

## Recherche selon les choix

Avec un filtre de tag, `search-reviewed` utilise `accepted` par défaut.
`--state proposed` ou `--state rejected` doit être explicite ; plusieurs états
peuvent être demandés. Les filtres de tags restent exacts et combinés par ET.
Le résultat précise les états qui ont servi au match et les événements associés.

Sans filtre de tag, la commande liste le catalogue ou applique son filtre de
zone ; cela ne signifie pas que tous les fichiers sont approuvés. La géographie
garde le comportement d'enveloppe du catalogue existant, sans nouvelle preuve
géométrique, reprojection ou géocodage. La commande `search` d'origine reste
disponible pour découvrir les propositions sans politique de revue.

## Bornes et suite

La revue est bornée à 256 rapports, 256 propositions par rapport et 1 024
événements de journal. Le nombre de caractères des champs et la profondeur/taille
de l'arbre JSON sont aussi limités. La borne de fichier de 8 Mio peut être
atteinte avant 1 024 événements avec de longs champs Unicode.

La démonstration `python examples/asset_tag_review_demo.py` construit deux
propositions lexicales, en accepte une, rejette l'autre, réinitialise un choix et
montre l'invalidation d'une révision modifiée. Les acteurs et décisions y sont
des fixtures, pas des évaluations de fichiers personnels ou un corpus de vérité.

Ce travail prépare les corrections de classification et leur traçabilité. Il
n'entraîne pas de modèle et ne transforme pas un choix en label étalon sans
qualification. Les prochains extracteurs de contenu pourront proposer des tags
avec leurs propres preuves ; leur revue utilisera les mêmes liaisons de rapport.
Le classement physique, les sidecars des fichiers, la reconnaissance sémantique
et l'activation du plugin cloud restent des étapes distinctes.
