# Inception : reprendre une discussion et échanger son journal

Inception conserve les travaux d'un projet sous forme de résultats, décisions,
enseignements, liens et points de reprise. Une nouvelle discussion peut demander
le dernier point de reprise, retrouver les tentatives concernées et distinguer
une réussite déclarée d'une cause encore hypothétique.

Ce premier pilote associe une **base SQLite locale durable**, une API Python et
une CLI. Deux copies peuvent échanger explicitement des lots JSON et leurs
accusés de réception. Le parcours est testable sans réseau. Le raccordement
automatique à un compte de conversations, à Second Brain, à un wiki ou à un
poste distant reste une intégration à réaliser sur l'hôte concerné.

« Cloud » et « local » désignent les environnements qui exécutent ces copies.
Une conversation cloud doit disposer d'un exécuteur ou d'un adaptateur capable
d'appeler l'API/CLI. La présence du dépôt n'installe pas un connecteur dans un
client de discussion. L'invocation d'un skill nommé `inception` dépend également
du client ; ce programme n'enregistre pas une commande universelle `/inception`.

## Ce qui est conservé

Chaque événement possède un identifiant stable, son projet, le nœud producteur,
un type, une clé de record, ses parents, sa portée de partage, une date déclarée,
des références de sources et une empreinte du contenu. Les événements ajoutés
ne sont pas modifiés en place. Une nouvelle version cite les têtes précédentes.

Les cinq types possèdent des payloads JSON fermés : tous les champs indiqués
sont obligatoires et les champs supplémentaires sont refusés.

| Type | Champs du payload | Usage |
| --- | --- | --- |
| `checkpoint` | `goal`, `state`, `next_action`, `acceptance`, `decision_ids`, `outcome_ids`, `open_actions` | Contexte de reprise et références aux décisions et tentatives utiles |
| `outcome` | `summary`, `result`, `verification`, `why`, `cause_status` | Résultat d'une tentative et statut de son explication |
| `decision` | `summary`, `rationale`, `alternatives` | Choix effectué, raison et alternatives considérées |
| `lesson` | `summary`, `limits` | Enseignement réutilisable avec ses conditions de validité |
| `link` | `from_id`, `to_id`, `relation`, `mode`, `status`, `reason` | Relation proposée, confirmée ou rejetée entre événements |

Les champs de texte sont des chaînes. `decision_ids` et `outcome_ids` contiennent
des identifiants d'événements ; `open_actions` et `alternatives` sont des listes
de textes. Une liste vide est possible. Les états d'un résultat sont
`success`, `failure`, `partial` et `unknown`. `verification` vaut `declared` ou
`verified` ; `cause_status` vaut `unknown`, `hypothesis` ou `verified`.

Ces deux derniers champs restent des **déclarations du producteur**. Une
déclaration `verified` exige au moins une référence de preuve déclarée disponible
avec une empreinte SHA-256. Le programme vérifie ce contrat ; il n'ouvre pas la
preuve et ne refait pas le test. `why` conserve l'explication telle qu'elle a été
fournie. Un succès n'établit donc pas, à lui seul, la cause supposée du succès.

Une source possède exactement ces champs :

```json
{
  "id": "rapport-essai-1",
  "version": "revision-1",
  "uri": "archive:rapport-essai-1",
  "sha256": null,
  "availability": "unknown"
}
```

`availability` accepte `available`, `unavailable` et `unknown`. `sha256` est
`null` ou une empreinte de 64 caractères hexadécimaux minuscules. Les URI sont
des références opaques : elles ne sont ni ouvertes ni exécutées. Les textes
mémorisés, y compris d'anciennes consignes, restent des données à réexaminer dans
le contexte de la nouvelle demande.

## Démarrer et enregistrer une session

Python 3.10 ou ultérieur et sa bibliothèque standard suffisent depuis ce
checkout. Après installation de cette branche, le point d'entrée
`parcimonia-inception` fournit la même CLI. Le lanceur ci-dessous fonctionne
depuis le dépôt, sans installation globale :

```sh
python scripts/parcimonia_inception.py --help
python scripts/parcimonia_inception.py init --db cloud.sqlite --node cloud-personnel
```

Choisir un répertoire privé existant et une identité stable différente pour
chaque copie. `init` refuse une base déjà présente. Une commande de lecture
n'en crée jamais une implicitement. La création demande des permissions `0600`
pour la base et les exports sur les systèmes qui les prennent en charge ; les
ACL Windows et les répertoires parents restent gérés par l'appelant.

Pour un nouveau record, enregistrer le fichier `empty-heads.json` contenant :

```json
[]
```

Voici un `outcome-1.json` de démonstration :

```json
{
  "summary": "Le témoin de reprise a échoué après une révision du contexte.",
  "result": "failure",
  "verification": "declared",
  "why": "Un contexte périmé est suspecté ; contrôler la révision avant le prochain essai.",
  "cause_status": "hypothesis"
}
```

La commande suivante autorise explicitement le partage de cet événement. Sans
`--scope shared`, la portée par défaut est `local`.

```sh
python scripts/parcimonia_inception.py append --db cloud.sqlite --project mon-projet --kind outcome --record essai-1 --input outcome-1.json --expected-heads empty-heads.json --event-id outcome-1 --scope shared
```

Préparer ensuite `checkpoint-1.json` :

```json
{
  "goal": "Poursuivre le même travail dans une nouvelle discussion.",
  "state": "Premier essai échoué ; le résultat et l'hypothèse de cause sont conservés.",
  "next_action": "Relire la révision du contexte et rejouer le même témoin.",
  "acceptance": "Conserver les deux résultats et vérifier leurs conditions.",
  "decision_ids": [],
  "outcome_ids": ["outcome-1"],
  "open_actions": ["Vérifier les sources avant de conclure sur la cause."]
}
```

```sh
python scripts/parcimonia_inception.py checkpoint --db cloud.sqlite --project mon-projet --input checkpoint-1.json --expected-heads empty-heads.json --event-id checkpoint-1 --scope shared
```

`checkpoint` est un alias d'ajout de type `checkpoint` dont la clé de record
vaut `main` par défaut. `--record` permet de choisir une autre reprise dans le
même projet. `--sources sources.json` accepte la liste des références déclarées
de cet événement. Utiliser un `--event-id` explicite permet de retrouver une
opération identique après une sortie perdue.

Le pilote reçoit des fiches structurées explicitement fournies. Il ne lit pas
toutes les discussions et ne déduit pas seul quels passages sont des succès,
des échecs ou des décisions.

## Reprendre le lendemain

```sh
python scripts/parcimonia_inception.py projects --db cloud.sqlite
python scripts/parcimonia_inception.py resume --db cloud.sqlite --project mon-projet
python scripts/parcimonia_inception.py status --db cloud.sqlite --project mon-projet
```

Sans `--project`, `resume` retourne la liste des projets. Avec un projet, le
rapport inclut le point de reprise, les décisions et résultats référencés, les
sources, les références manquantes ou remplacées, et les conflits observés.

| `resume.status` | Sens |
| --- | --- |
| `empty` | Aucun point de reprise unique disponible dans ce périmètre |
| `ready` | Un point de reprise unique a été trouvé sans problème structurel signalé |
| `needs_review` | Conflit, référence absente/remplacée ou source déclarée indisponible/inconnue à examiner |

`revalidation_required` reste vrai, y compris avec `ready`. L'état des fichiers,
tests, services, autorisations et sources doit être revérifié avant l'action
suivante. Le rapport n'exécute aucune action et ne certifie pas la fraîcheur des
preuves externes. Une synchronisation non observée ne devient pas une preuve
d'absence de travail sur l'autre copie.

Pour mettre à jour une reprise, lire d'abord les têtes et les conserver dans un
nouveau fichier :

```sh
python scripts/parcimonia_inception.py heads --db cloud.sqlite --project mon-projet --kind checkpoint --record main --out checkpoint-heads.json
```

Préparer le nouveau payload `checkpoint-2.json`, puis l'ajouter avec un nouvel
identifiant et ces têtes :

```sh
python scripts/parcimonia_inception.py checkpoint --db cloud.sqlite --project mon-projet --input checkpoint-2.json --expected-heads checkpoint-heads.json --event-id checkpoint-2 --scope shared
```

Pour conserver un échec initial et une réussite ultérieure comme deux tentatives,
utiliser deux records `outcome` distincts et les référencer tous les deux. Le
nouveau checkpoint indique ce qui a changé entre les essais. Remplacer la
version d'un même record indique une révision de ce record ; la reprise signale
une référence restée attachée à sa version remplacée.

La comparaison des têtes et l'ajout sont réunis dans une transaction SQLite
locale. Une tête obsolète ou incomplète est refusée. Cette transaction ne
constitue pas un verrou entre plusieurs machines. Le mécanisme est distinct de
la simple comparaison `expected_head` des snapshots du pilote de connaissances.

## Liens automatiques, proposés et explicites

```sh
python scripts/parcimonia_inception.py links --db cloud.sqlite --project mon-projet --event-id outcome-1 --limit 5
```

Le rapport distingue trois origines :

- `automatic` rapproche les événements dont une source déclarée disponible
  partage exactement l'identifiant, la version et l'empreinte. Cela établit une
  identité déclarée de référence, sans preuve de causalité.
- `proposed` réutilise les candidats lexicaux sourcés de
  [Knowledge Crosswalk](KNOWLEDGE_CROSSWALK.md). Les événements sélectionnés du
  projet fournissent des passages de prose ; les clés JSON et les statuts ne
  servent pas à fabriquer des termes communs. Les candidats restent non vérifiés.
- `explicit` conserve les événements `link` ajoutés après examen. Ils indiquent
  leur raison, leur mode `explicit` ou `semi` et leur état `proposed`, `confirmed`
  ou `rejected`.

Les relations admises sont `related_to`, `depends_on`, `supports`, `contradicts`
et `derived_from`. Une confirmation est une décision du producteur, pas une
vérification sémantique automatique. Relire les payloads et sources complets
avant de transformer un candidat en décision.

Le graphe de connaissances peut contenir des cycles. Les liens `depends_on`
sont ici des déclarations ; ce pilote n'ordonnance pas un DAG de tâches et ne
vérifie pas leur acyclicité. La recherche reste lexicale, bornée au projet
sélectionné. Aucun index vectoriel, moteur RAG distant ou wiki automatiquement
publié n'est activé. Les imports Second Brain et documents restent disponibles
dans [Knowledge Collection](KNOWLEDGE_COLLECTION.md) comme composants séparés.

## Échanger deux copies avec des accusés

Les événements `shared` forment un flux par projet. Un export est adressé à un
destinataire nommé et enregistré durablement avant sa livraison sous forme de
fichier. Il reste un seul lot en attente par paire projet/destinataire jusqu'à
son accusé accepté. Une répétition de l'export retourne ce même lot.

Sur la première copie :

```sh
python scripts/parcimonia_inception.py sync export --db cloud.sqlite --project mon-projet --peer poste-local --out cloud-to-local-1.json
```

Sur la seconde copie, créer une fois sa base puis lui fournir le lot par le
moyen de transfert déjà choisi par l'utilisateur :

```sh
python scripts/parcimonia_inception.py init --db local.sqlite --node poste-local
python scripts/parcimonia_inception.py sync receive --db local.sqlite --input cloud-to-local-1.json --out local-receipt-1.json
```

Reporter le reçu sur la première copie :

```sh
python scripts/parcimonia_inception.py sync ack --db cloud.sqlite --input local-receipt-1.json
python scripts/parcimonia_inception.py status --db cloud.sqlite --project mon-projet --peer poste-local
```

Pour partager les ajouts du poste local, refaire le même parcours dans l'autre
sens, avec `--peer cloud-personnel`. Répéter autant que nécessaire pour les lots
restants. `--limit` contrôle la taille maximale d'un lot, de 1 à 128 événements.
Un événement déjà connu avec le même contenu est dédoublonné. Un reçu accepté
rejoué n'applique pas une seconde fois ses événements.

`status.pending_event_count` décrit les événements partagés qui n'ont pas encore
été accusés pour ce pair. `pending_batches` montre les lots en attente. Les
curseurs et `confirmed_at` sont des traces d'échanges locaux ;
`connectivity=not_observed` ne renseigne pas la disponibilité actuelle du pair.

Il s'agit d'un **protocole d'échange explicite vérifié entre copies locales**.
Aucun démon, ordonnanceur, connexion distante, authentification de pair ou
transfert automatique n'est fourni. Les empreintes vérifient la cohérence des
objets reçus, pas l'identité réelle de l'expéditeur. Le transport choisi doit
respecter la confidentialité des fichiers. Ne pas réinitialiser une identité
de copie en conservant les anciens curseurs d'échange.

La portée `local` n'est jamais exportée. Un record existant ne peut pas changer
sa portée au fil de ses parents. Pour partager un travail jusque-là local,
préparer une projection distincte, relue, sous une nouvelle clé et de nouveaux
identifiants ; les références de cette projection doivent également être
destinées au partage.

### Conflits et reprises

Deux modifications concurrentes d'un même record avec des identifiants distincts
peuvent être conservées comme deux têtes. La reprise devient `needs_review` et
ne choisit pas un gagnant à partir de l'horloge. Lire les deux versions, décider
du contenu retenu, puis ajouter une version dont `--expected-heads` contient
toutes les têtes actuelles.

Si **un même identifiant d'événement possède deux contenus différents**, le
récepteur conserve le diagnostic de collision et produit un reçu `conflict`.
Le lot n'est pas partiellement ingéré et le curseur ne progresse pas. La CLI
écrit ce reçu et retourne le code `3`. Un reçu conflictuel ne peut pas être
accusé comme accepté. Le pilote ne fournit pas encore de commande de résolution
des collisions d'identité ; conserver les journaux et corriger la provenance
avant de préparer une procédure de réparation explicite.

Un lot manquant ou reçu dans le désordre est refusé ; rejouer d'abord le lot
antérieur en attente. Un rejet n'autorise pas à vider le journal ou à avancer
manuellement un curseur.

## Fichiers de sortie et erreurs

Les commandes retournent du JSON sur la sortie standard. `--out` écrit le même
rapport dans un **nouveau fichier** ; il est obligatoire pour `sync export` et
`sync receive`. Les destinations existantes, y compris les liens finaux, sont
refusées. Les fichiers JSON d'entrée utilisent les contrôles bornés de la CLI
Knowledge : lecture de fichier régulier, refus des liens finaux, des clés JSON
dupliquées, du JSON non fini et des entrées dépassant 2 Mio.

| Code | Signification |
| --- | --- |
| `0` | Rapport produit ; examiner notamment `resume.status` et les indicateurs de revalidation |
| `2` | Arguments, entrée, base, contrat ou sortie refusés/indisponibles |
| `3` | Reçu de collision d'identité produit par `sync receive` ; aucun événement du lot ingéré |

Les erreurs opérationnelles JSON sur stderr indiquent `operation_completed`.
Une erreur d'arguments du parseur utilise son message d'aide habituel.

La disponibilité de `--out` est contrôlée avant une opération, puis l'écriture
exclusive la contrôle à nouveau. Cela ne rend pas atomiques une transaction
SQLite et une écriture de fichier. Une panne de sortie peut survenir **après**
l'enregistrement durable. Dans ce cas `operation_completed=true` indique que
l'appel à l'API a déjà retourné son résultat. Pour une lecture, cela ne signifie
pas qu'une mutation a eu lieu.

Après une telle panne :

- Répéter un ajout avec le même `--event-id`, le même payload, les mêmes sources,
  parents, portée et métadonnées récupère l'événement identique. Un contenu
  différent sous cet identifiant est refusé.
- Réexporter vers le même pair récupère le lot durable en attente ; choisir un
  nouveau chemin de sortie.
- Recevoir à nouveau le même lot accepté récupère son reçu. Réappliquer le
  même reçu accepté est idempotent.

Sans identifiant d'événement explicite, lire `heads`, `resume` et `status` avant
un nouvel ajout : un nouvel identifiant ne constitue pas une répétition
idempotente. Les contrôles de chemins n'isolent pas le programme d'un
propriétaire hostile de ses répertoires.

## Bornes et validation

Le journal accepte au plus 4 096 événements. Un événement tient dans 32 Kio,
un lot dans 2 Mio et 128 événements. Un événement accepte au plus 16 sources ;
les listes de parents et de références contiennent au plus 32 identifiants,
et les listes de textes au plus 16 éléments. Les textes ordinaires sont bornés
à 2 Kio. Les dépassements sont refusés. Aucune purge, migration de journal ou
compaction automatique n'est implémentée.

Les candidats lexicaux conservent les bornes du pilote de connaissances, dont
256 fragments ; si le sous-ensemble sélectionné ne tient pas dans son contrat,
la partie `proposed` signale son indisponibilité. Cela n'efface pas le journal.
Les entrées et les sorties JSON de la CLI sont bornées à 2 Mio. La représentation
ASCII de la sortie destinée aux consoles Windows respecte également cette borne.

Les commandes suivantes utilisent uniquement des fixtures :

```sh
python examples/inception_demo.py
python -m unittest discover -s tests -p "test_inception*.py"
```

Le second appel suppose le paquet installé ou `src` présent dans `PYTHONPATH`,
comme les autres tests du dépôt. La démonstration conserve un échec, une décision
et un checkpoint, les transmet à une seconde base, reprend le lendemain, ajoute
une réussite déclarée, puis échange dans l'autre sens. Les deux tentatives et
leurs hypothèses restent présentes. Une note locale demeure sur sa copie
d'origine. Les tests CLI lancent de vrais sous-processus et vérifient aussi la
reprise après panne de sortie, les refus de destination, les collisions et la
non-création implicite d'une base.

Ces preuves couvrent les composants exécutés et l'échange de fichiers entre
bases de test. Elles n'établissent ni une synchronisation cloud/poste déployée,
ni la collecte de conversations réelles, ni une économie de tokens ou une
amélioration mesurée des décisions.
