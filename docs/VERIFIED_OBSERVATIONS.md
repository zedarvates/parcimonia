# Revoir les observations d'une mission

Ce premier incrément de TASK-113 relie des rapports fournis à une tâche et à des
conditions de validité explicites. Il prépare la prochaine lecture utile avant
qu'un consommateur ne poursuive sa mission. Il réutilise les responsabilités de
[V1](V1_GATES.md) : l'hôte possède le but, les autorisations et l'exécution ;
Parcimonia examine les rapports et propose un mécanisme.

L'implémentation est préparée sur `feat/verified-observations-20261102`, avec
tests Python hors ligne et appels stdio isolés. La qualification dans le vrai
consommateur reste à réaliser. Le candidat du plugin local 0.4.3 ajoute
`parcimonia_local_observations` ; il reste distinct du plugin installé et du
candidat 0.4.2 de la PR #39. Une fonction dans la bibliothèque, une découverte
MCP et un comportement qualifié dans le vrai jeu sont trois preuves différentes.

## Contrat explicite

L'API pure `review_observations(request, *, now=None)` se trouve dans
`src/tiberium_ai/observation_review.py`. Elle ne lit pas les sources, ne lance pas
les sondes et n'appelle pas de modèle. L'horloge de production est celle de
l'hôte ; `now` permet un essai déterministe en Python. Le champ `now` ne fait pas
partie de la requête du plugin.

La requête est un objet fermé comportant cinq champs obligatoires :

| Champ | Contenu |
| --- | --- |
| `task_id`, `task_revision` | Identité exacte et révision de la mission définies par l'hôte |
| `requirements` | De 1 à 64 exigences identifiées |
| `observations` | Au plus 128 rapports fournis |
| `probes` | Au plus 32 lectures candidates déclarées par l'hôte |

Chaque exigence comporte `id`, `source_id`, `source_revision`, `input_sha256`,
`verifier_id`, `verifier_version` et `max_age_seconds`. Le digest porte sur les
entrées sélectionnées pour ce contrôle ; il ne peut pas être réutilisé pour une
entrée modifiée. Le vérificateur et sa version sont ceux exigés par le
consommateur, pas un nom accepté librement pour chaque nouveau rapport.

Chaque observation comporte `id`, `requirement_id`, `task_id`, `task_revision`,
`source_id`, `source_revision`, `input_sha256`, `verifier_id`, `verifier_version`,
`observed_at` et `outcome`. Les seules issues sont `pass`, `fail` et `unknown`.
`observed_at` est un temps Unix en secondes. Les champs d'identité doivent
correspondre exactement à la tâche et à l'exigence ; aucune similarité lexicale
ne remplace cette liaison.

Chaque sonde comporte `id`, `requirement_ids` et `estimated_latency_ms`. Elle
nomme seulement les exigences qu'elle se propose d'observer. La latence est une
estimation déclarée ou `null`, jamais une durée mesurée par cette fonction. Les
identifiants de sonde n'encodent ni commande à exécuter ni autorisation.

Les objets refusent les clés supplémentaires. Les identifiants sont des chaînes
imprimables de 1 à 128 caractères ; les SHA-256 ont 64 chiffres hexadécimaux
minuscules. Les nombres sont finis, non négatifs et au plus `10**18` ; un booléen
n'est pas accepté comme nombre. Les identifiants d'exigence, observation et
sonde sont uniques dans leur collection. Les références de sonde doivent viser
les exigences déclarées.

## Résultats et fraîcheur

Le résultat utilise `schema: parcimonia.observation-review/v1`. Chaque ligne de
`requirements` conserve l'état, les observations retenues/considérées, le dernier
temps applicable et les motifs. `rejected` conserve les identités et motifs des
observations écartées : une preuve d'une ancienne révision ou du futur ne devient
pas un silence rassurant.

| État d'exigence | Signification du rapport |
| --- | --- |
| `pass` | La dernière observation actuelle et compatible déclare une réussite |
| `fail` | La dernière observation actuelle et compatible déclare un échec |
| `unknown` | La dernière observation actuelle et compatible reste indéterminée |
| `missing` | Aucun rapport applicable ne permet de conclure |
| `stale` | Des observations compatibles existent, mais leur durée de validité est dépassée |
| `conflict` | Les observations les plus récentes, à temps égal, donnent des issues différentes |

L'intervalle de validité est inclusif :
`0 <= now - observed_at <= max_age_seconds`. Un temps futur est écarté. Une
réussite ancienne n'efface pas un échec actuel. La plus récente des observations
compatibles décide ; un conflit au même temps reste explicite.

Le statut global est `ready` si toutes les exigences ont l'état `pass`,
`blocked` si une exigence a l'état `fail`, et `needs_observation` dans les autres
cas. **`ready` signifie que les rapports fournis satisfont ce contrat**, pas que
le résultat métier a été observé indépendamment.

`auto_act_allowed` reste toujours `false` et `evidence_trust` reste
`host_reported_not_independently_attested`. Le hash et les identités contrôlent la
cohérence déclarée ; ils n'authentifient pas l'émetteur, le temps ni la vérité de
l'observation. Un statut global ne remplace pas le
[vérificateur de résultat](VERIFICATION.md).

## Proposer la prochaine observation

`next_probe` est `null` ou une sonde déclarée, accompagnée des exigences qu'elle
couvre encore, de leur nombre et de sa latence déclarée. L'heuristique ordonne
les sondes selon :

1. le plus grand nombre d'exigences `missing`, `stale`, `unknown` ou `conflict` ;
2. une latence connue avant une latence inconnue, puis la latence la plus basse ;
3. l'identifiant pour départager de manière stable.

Un échec actuel ne compte pas comme un manque d'observation à masquer par une
nouvelle lecture. L'hôte doit traiter l'échec, puis définir le contrôle adapté à
la nouvelle situation. Cette heuristique ne mesure ni gain d'information,
probabilité de succès, qualité de sonde, coût total ni économie. Elle ne réserve
aucune ressource. Le contrôle de capacité et l'admission de l'hôte restent
nécessaires avant de lancer une lecture réelle.

Un [comparateur optionnel des résultats attendus](OBSERVATION_PROBE_PLANNING.md)
prolonge cette heuristique avec un modèle fini d'hypothèses, des plafonds et un
front de compromis explicites. Il recalcule ce contrôle depuis la requête
originale, sans modifier ce contrat ni la copie vendue dans le plugin.

## Exemple authoré : préparer un contrôle de reconnexion

Cet exemple est une fixture écrite pour expliquer le contrat. Aucun client ou
serveur Ultimate Odycer n'est lancé, et les rapports ne proviennent pas du jeu.
Les labels `client-fixture-v1` et `server-fixture-v1` ne sont pas des versions
publiées d'Ultimate Odycer.

Depuis la racine du dépôt avec l'environnement de développement installé :

```python
from hashlib import sha256
from tiberium_ai.observation_review import review_observations

client_hash = sha256(b"authored client reconnection input").hexdigest()
server_hash = sha256(b"authored server reconnection input").hexdigest()

request = {
    "task_id": "reconnect-fixture-001",
    "task_revision": "scenario-v1",
    "requirements": [
        {"id": "client-ready", "source_id": "client-fixture",
         "source_revision": "client-fixture-v1", "input_sha256": client_hash,
         "verifier_id": "fixture.client-ready", "verifier_version": "1",
         "max_age_seconds": 30},
        {"id": "server-session", "source_id": "server-fixture",
         "source_revision": "server-fixture-v1", "input_sha256": server_hash,
         "verifier_id": "fixture.server-session", "verifier_version": "1",
         "max_age_seconds": 30},
    ],
    "observations": [{
        "id": "client-report-1", "requirement_id": "client-ready",
        "task_id": "reconnect-fixture-001", "task_revision": "scenario-v1",
        "source_id": "client-fixture", "source_revision": "client-fixture-v1",
        "input_sha256": client_hash, "verifier_id": "fixture.client-ready",
        "verifier_version": "1", "observed_at": 990, "outcome": "pass",
    }],
    "probes": [{"id": "read-server-session",
                "requirement_ids": ["server-session"],
                "estimated_latency_ms": 10}],
}

result = review_observations(request, now=1000)
assert result["status"] == "needs_observation"
assert result["next_probe"]["id"] == "read-server-session"
assert result["auto_act_allowed"] is False
```

L'hôte pourrait ensuite fournir un rapport du serveur lié à sa propre exigence.
Si ce rapport déclare `pass` à un temps actuel, le contrat peut devenir `ready`.
Cela n'établit toujours pas que le joueur peut reprendre : le consommateur doit
vérifier cette issue réelle et enregistrer son propre résultat indépendant.

Les cas de reprise à conserver dans les essais sont :

- à `now=1030`, le rapport client de temps 990 est périmé ;
- un rapport client `fail` de temps 999 remplace le succès de temps 990 ;
- deux rapports client de temps 999 avec `pass` et `fail` produisent un conflit ;
- changer la révision de tâche, le hash d'entrée ou la version du vérificateur
  empêche la réutilisation du rapport correspondant.

Le plugin accepte le même contrat sous `{"request": ...}` dans
`tools/call` avec `name: parcimonia_local_observations`. Le serveur utilise son
horloge réelle ; les temps 990/1000 de cette fixture Python ne sont donc pas des
temps à recopier dans un essai du plugin. Découvrir les outils par `tools/list`
avant l'appel et conserver les limites du transport existant.

## Admission de la capacité locale

Pour une `LocalCapacity` explicite, un besoin VRAM positif avec VRAM inconnue
bloque la proposition de démarrage local. Une route CPU peut exprimer
`min_vram_for_local_mb=0` ; elle reste soumise au nombre de slots. Une règle
déterministe et une route cloud conservent leurs contrôles propres.

`capacity=None` conserve la compatibilité de l'appel historique : cette absence
ne constitue ni une observation matérielle, ni une admission ou une réservation.
Le consommateur doit fournir un snapshot actuel au chemin d'admission avant de
lancer une charge. La cohérence de ce snapshot et d'un vrai bail multi-postes
appartient à TASK-114.

## Qualification et suite

Qualification exécutée le 2 novembre 2026 sur Python 3.12.14 :

- suite hors ligne complète : 4 165 tests et 100 sous-tests réussis ;
- transport MCP lancé dans un processus Python isolé : découverte des quatre
  outils, appels positifs et négatifs, poursuite après requête invalide ;
- régression de capacité : deux témoins échouaient avant la correction ;
- revue indépendante : un arrondi d’âge aux grandes dates corrigé, puis
  864 combinaisons numériques comparées à un oracle Decimal indépendant ;
- inventaire et empreintes du plugin contrôlés, copie vendue identique,
  grammaire Python 3.10 et JSON du paquet validés.

La qualification du lot doit garder séparés : tests Python hors ligne, transport
stdio du candidat, découverte dans l'hôte Codex, et essai du consommateur réel.
Les tests du contrat et les fixtures ne qualifient pas les GPU, l'index RAG,
le modèle local ou la reconnexion du jeu. Aucun apprentissage, déploiement ou
gain de coût/vitesse n'est annoncé par ce lot.

Réutiliser [les mesures](MEASUREMENT.md),
[la capture mémoire](MEMORY_CAPTURE.md) et
[les reçus d'exécution](MEMORY_EXECUTION.md) pour TASK-115 et TASK-117.
La suite ordonnée et ses critères de sortie sont dans
[ROADMAP.md](../ROADMAP.md#verified-mission-improvements--2026-11-02) ; les cartes
TASK-113 à TASK-119 restent dans [kanban.md](../kanban.md).
