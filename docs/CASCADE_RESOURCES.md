# Mesures et budgets du mode contexte de la cascade

Incrément du 7 octobre 2026. `CascadeResourceControl` est un contrôle optionnel
pour `SignatureCascadeBackend.propose_signature`. Il réutilise la mesure
`measurement/2`, la politique d’escalade et l’horloge de décision existantes.
Les chemins historiques et le mode contexte sans ce contrôle restent compatibles.

## Avant un appel

Le contexte est vérifié avant tout prédicteur. Pour une entrée prête :

- coût et latence estimés de l’étape doivent être connus et compatibles avec
  les limites restantes ; une estimation absente ne devient pas zéro ;
- les tentatives et escalades déjà consommées restent dans le calcul ;
- le temps déjà passé est pris en compte ;
- si une borne d’âge du contexte est déclarée, son âge doit être observé.

Le secours passe par `EscalationPolicy.decide` avec un verdict nul : une signature
n’est pas un résultat de tâche vérifié. Aucun retry n’est demandé. Le refus de
la politique est conservé avec son état, sa raison et son détail.

## Pendant et après un appel

`run_baseline` mesure une fois le callback complet : prédiction, validation du
lot et construction de la signature. L’environnement et la politique sont
photographiés au début du contrôle ; leurs mappings partagés ne peuvent pas
réattribuer ensuite une mesure à un autre runtime.

Un observateur fourni par l’hôte retourne `CostReceipt(amount, unit, method)`.
Le coût observé reste distinct des estimations. La même unité est requise pour
les budgets, estimations et reçus ; aucune conversion automatique n’est tentée.
Un coût inconnu, une mauvaise unité ou un observateur en erreur empêche de
sélectionner la signature ou de lancer le secours. L’observateur est une source
déclarée par l’hôte : sa présence ne certifie pas une facture indépendante.

Le contrôle vérifie ensuite le temps total et la fraîcheur. Une réponse correcte
en forme mais arrivée après l’échéance n’est pas sélectionnée. L’âge du snapshot
avance avec le temps écoulé pendant la décision. Un contexte trop ancien appelle
une nouvelle collecte ; un modèle plus fort ne le rend pas plus frais.

L’horloge doit produire des nombres finis non décroissants. Son origine peut
être négative ; seules les différences de temps comptent. Les erreurs de mesure
ne laissent pas de signature sélectionnée ou de coût supposé gratuit. Les
exceptions des fournisseurs et observateurs ne sont conservées que par type.

## Configuration

```python
from time import perf_counter
from tiberium_ai.cascade_resources import (
    CascadeResourceControl, CostReceipt, StageEstimate,
)
from tiberium_ai.decision_clock import DecisionBudget
from tiberium_ai.escalation import Budget
from tiberium_ai.measurement import Environment

resources = CascadeResourceControl(
    budget=Budget(max_cost=3, max_escalations=1, max_attempts=2, max_latency_ms=100),
    deadline=DecisionBudget(budget_ms=100, max_state_age_ms=50),
    baseline=StageEstimate(cost=1, latency_ms=5),
    fallback=StageEstimate(cost=1, latency_ms=20),
    cost_unit="caller-declared-unit",
    environment=Environment("caller-labelled-machine", {"clock": "perf_counter"}),
    clock=perf_counter,
    observe_cost=observer,  # Reçu après l’étape, avec montant/unité/méthode.
    state_age_ms=0,         # Seulement si l’hôte vient de mesurer cet âge.
)
proposal = cascade.propose_signature(
    prompt, schema=signature_schema, contract=context_contract,
    baseline_identity=baseline_identity, fallback_identity=fallback_identity,
    context_revision=context_revision, values=known_values,
    resource_control=resources,
)
```

Les nombres ci-dessus illustrent le protocole ; ils ne sont pas des prix ou
latences de modèles. Les dépenses antérieures peuvent être transmises par
`spent_cost_before`, `spent_latency_ms_before`, `attempts_before` et
`escalations_before`. Les valeurs par défaut correspondent à une nouvelle
décision ; réutiliser la configuration ne remplace pas un ledger de tâche.
Une dépense antérieure inconnue empêche un nouvel appel coûteux.

Les limites de nombre d’appels de la cascade demeurent partagées entre ses modes.
Le hash de demande inclut la politique de ressources et son état antérieur.

## Résultat et portée des preuves

`resource_trace` conserve les mesures canoniques, reçus de coût, décisions
d’escalade, verdict temporel et totaux. Les champs `measured_cost` et
`measured_latency_ms` du résultat restent nuls au sens de non renseignés lorsque
la valeur n’est pas établie. Les estimations ne remplissent jamais ces champs.

Les mesures réussies ou échouées restent exportables par `write_measurement`
et contrôlables par `read_measurement`. Une erreur de mesure totale ne fabrique
pas un enregistrement valide. Une exception de prédicteur peut en revanche
laisser une mesure d’échec et un reçu de frais déjà engagés.

La deadline est vérifiée avant appel et au retour ; elle ne préempte pas un
callback synchrone. Les timeouts de transport et la capacité de cancellation
restent à configurer par l’hôte. Un coût réel supérieur à l’estimation peut déjà
avoir été engagé : le contrôle refuse alors la réponse et les appels suivants,
mais ne rembourse pas l’opération.

`selected` reste une proposition de signature. `auto_act_allowed=false` ; aucune
autorisation d’exécution ou revendication de gain de qualité ne découle d’un
budget respecté. Les versions, unités et frais observés ne remplacent pas
l’autorisation du fournisseur ou la vérification du résultat de tâche.

## Pilote

```powershell
rtk proxy .venv/Scripts/python.exe examples/resource_context_cascade_pilot.py --output-dir runs/resource-pilot-new
```

Le pilote comprend huit scénarios avec horloge synthétique injectée, puis un
callback local mesuré avec `perf_counter`. Il exporte dix mesures `measurement/2`.
Les délais synthétiques sont des valeurs de test ; le callback réel n’est pas
un modèle neuronal. Coûts de fixture et absence d’appel payant restent explicités
par leur unité et leur méthode d’observation.

Ces résultats valident des garde-fous et le chemin de mesure. Ils ne mesurent
ni économie de production, qualité générale, latence Laya/Jeff/CLEF/GEV, VRAM,
énergie ou comportement sous une vraie charge concurrente. Le lot humain reste
à annoter et à capturer de manière appariée.
