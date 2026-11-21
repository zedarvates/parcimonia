# Choisir le prochain test selon ses résultats attendus

Ce prolongement de TASK-113 compare les sondes déjà déclarées à partir d'un
petit modèle d'hypothèses fourni par l'appelant. Il réutilise
`review_observations` et ne remplace ni le registre, ni l'admission de l'hôte,
ni l'investigation existante. La bibliothèque ne lance aucun test.

Le premier contrôleur classe les sondes par couverture des preuves manquantes,
puis latence. Couvrir beaucoup d'exigences ne dit pas si les résultats possibles
permettraient de distinguer les causes envisagées. Le nouveau comparateur ajoute
ce calcul limité, sans probabilité inventée.

## Entrée et liaison à la tâche

```python
from tiberium_ai.probe_planning import plan_observation_probes

report = plan_observation_probes(
    observation_request, planning_model,
    max_estimated_latency_ms=50, max_estimated_cost=0,
    now=1000,
)
```

La requête originale garde exactement le contrat des
[observations vérifiées](VERIFIED_OBSERVATIONS.md). L'adaptateur recalcule les
identités, les dates et les états ; un rapport entrant déclaré « prêt » ne les
remplace pas. Les sondes et leur latence viennent de cette requête.

Le modèle fermé `parcimonia.probe-planning-model/v1` contient :

| Champ | Signification |
| --- | --- |
| `task_id`, `task_revision` | Identité exacte de la tâche |
| `revision` | Révision déclarée du modèle |
| `observation_request_sha256` | Empreinte canonique de la requête originale |
| `cost_unit` | Une unité commune explicite pour tous les coûts et leur plafond |
| `hypothesis_ids` | De 2 à 64 scénarios déclarés distincts |
| `probes` | Au plus 32 modèles de sondes, par identifiant existant |

Chaque modèle de sonde possède `id`, `estimated_cost`,
`unmodelled_outcome_possible` et `outcomes`. Chaque résultat possède `id` et
`hypothesis_ids`. Les groupes doivent être non vides, disjoints et couvrir toutes
les hypothèses. Une sonde sans modèle reste signalée, sans score inventé.
Les identifiants sont uniques dans leur portée et les références inconnues sont
refusées. Les entrées sont bornées à 1 Mio et les nombres à `[0, 10**18]`, sans
booléens ni nombres non finis. Un budget de 65 536 visites, incluant les clés et
les occurrences partagées, borne aussi le parcours avant sérialisation.
Les empreintes contrôlent la cohérence des données,
pas leur authenticité.

## Comparer sans fabriquer de probabilités

Pour `N` hypothèses et des groupes de résultats de tailles `n₁ … nₖ`, le calcul
conserve le plus grand groupe et compte `N − max(n₁ … nₖ)` hypothèses éliminables
au minimum **parmi les résultats du modèle déclaré**. Aucune distribution uniforme
n'est supposée. Il ne s'agit ni d'une entropie mesurée, ni d'une probabilité de
réussite, ni d'un gain réel garanti.

Exemple avec quatre hypothèses :

| Test déclaré | Tailles des groupes | Élimination minimale dans ce modèle |
| --- | --- | ---: |
| Résumé identique dans tous les cas | 4 | 0 |
| Contrôle déséquilibré | 1 + 3 | 1 |
| Contrôle équilibré | 2 + 2 | 2 |
| Diagnostic qui distingue chaque cas | 1 + 1 + 1 + 1 | 3 |

Un test sans pouvoir discriminant reste exclu du choix. Si une issue
non modélisée est explicitement possible, les métriques restent inconnues et
aucune recommandation n'est tirée de cette partition. Déclarer le contraire
constitue une hypothèse de l'appelant, pas une preuve d'exhaustivité des causes.
Un timeout, une erreur ou un résultat inattendu réel demande de revoir le modèle.

## Budgets et compromis explicites

Les plafonds portent sur une seule prochaine sonde. `None` signifie sans plafond ;
le nombre `0` est une vraie contrainte. Sous un plafond actif, une estimation
inconnue ne permet pas d'admettre le test. Les comparaisons de bornes restent
exactes, y compris avec de grands entiers et flottants.

Les candidats admissibles forment un front de compromis : moins d'hypothèses
restantes dans le pire cas déclaré, moins de latence et moins de coût estimés.
Un candidat n'en domine un autre que si toutes les latences et tous les coûts
des deux sont connus, sans dégradation d'une dimension et avec une amélioration
d'au moins une. Des coûts inconnus rendent les options incomparables. Aucun
poids implicite ne transforme une inconnue en zéro.

| Résultat | Sens |
| --- | --- |
| `proposed` | Un seul candidat subsiste sur le front ; proposition consultative |
| `needs_preference` | Plusieurs compromis subsistent ; aucune sonde choisie |
| `abstained` | Aucun candidat utile ne satisfait les conditions déclarées |
| `blocked` | Un échec actuel des observations reste présent |
| `ready` | Les observations actuelles disent toutes « pass » ; aucun nouveau test proposé |

Le rapport conserve le contrôle d'observations, les motifs d'exclusion, le front
et les empreintes de la requête, du modèle et du rapport. Un échec courant
empêche toute proposition. Une seule hypothèse supposée restante ne constitue
pas une observation « pass » et n'entre pas dans ce contrat de comparaison.

## Démonstrateur et limites

```sh
python examples/observation_probe_planning.py
```

Le démonstrateur construit un cas de reconnexion : sous un budget de 50 ms et
de zéro unité de coût, le contrôle de session est proposé ; sans plafond,
le diagnostic plus discriminant et plus coûteux reste un compromis à choisir.
L'heuristique existante privilégie toujours le résumé couvrant trois exigences,
alors que son résultat déclaré ne distingue aucun scénario. Ce contraste est
une comparaison de règles sur des données construites, pas une mesure terrain.
Il conserve aussi l'abstention pour une issue non modélisée et le blocage après
un échec. Aucun client, serveur, modèle, sonde ou poste réel n'est contacté.

`auto_act_allowed`, `reservation_performed` et `execution_performed` restent faux.
Les latences et coûts sont des estimations fournies par l'appelant. Le résultat
ne prouve ni qualité du test, ni vérité des hypothèses, ni disponibilité des
outils, ni économie. L'hôte doit vérifier ces éléments et ses autorisations avant
un éventuel appel. Après un vrai résultat, reconstruire le modèle et sa liaison
à la requête actualisée avant un nouveau conseil.

Le contrôle d'observations et sa copie vendue restent identiques. Cette extension
est une API de bibliothèque ; les outils MCP et les plugins installés gardent
leur surface existante. Voir aussi [investigation](RE_INVESTIGATION.md),
[mesures](MEASUREMENT.md) et [backlog](../kanban.md).

La revue indépendante a comparé 300 cas générés de partitions, coûts et plafonds
à un oracle séparé. Elle a aussi fait corriger l'amplification du parcours par
des objets Python partagés ; une régression en sous-processus avec délai maximal
conserve ce cas. Les tailles maximales valides ont été contrôlées séparément.
Le démonstrateur passe en Python normal et optimisé (`-O`). Ces vérifications
portent sur le contrat et son calcul, sans mesure de qualité terrain.

Qualification sur Python 3.12.14 : **4 228 tests et 100 sous-tests passent**,
dont 62 tests du nouveau comparateur. Cette branche part de la PR #40 ; les
raccords runtime et RAM des PR #41 et #45 sont des propositions séparées.
