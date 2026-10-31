# Faisabilité, lacunes et stabilité — premier diagnostic

Cette extension recherche ce qui empêche un objectif d'être atteint et propose
la vérification suivante. Elle réunit un moteur booléen exact dans un cadre
fini et un inspecteur de motifs Python. Les deux restent consultatifs.

Un chemin explicite supplémentaire propose une [réduction vérifiée vers
2-SAT](VERIFIED_REDUCTIONS.md). Il répond aux questions de satisfiabilité
jusqu'à 128 variables, avec témoins ou chemins contradictoires, dans un rapport
séparé ; les axes de qualité et de complétude ci-dessous restent ceux du
diagnostic exhaustif.

## Sens des conclusions

| Conclusion | Portée |
| --- | --- |
| `impossible_within_constraints` | Aucune affectation booléenne ne satisfait les contraintes déclarées. La preuve concerne ce modèle et cette révision. |
| `blocked_current_state` | Les contraintes admettent une solution, mais les observations connues ne sont compatibles avec aucune solution. |
| `consistent_within_constraints` | Un témoin satisfait les contraintes et les observations connues. La faisabilité du projet réel reste à établir. |
| `indeterminate` | Une contrainte n'est pas prise en charge ou la borne de recherche est dépassée. |

La qualité et la complétude restent séparées. Un critère déclaré en échec donne
`declared_criteria_fail`, sans rendre le modèle impossible. Aucun critère fourni
laisse la qualité indéterminée. Une observation absente ou `null` reste inconnue ;
seule une observation connue contraire à une valeur obligatoire produit
`missing_prerequisite`. Une contrainte peut imposer `false` : la condition à
restaurer est alors l'absence exigée, pas une fonctionnalité à ajouter.

Les sources sont des références fournies par l'appelant. Le moteur ne les lit
pas et n'authentifie ni leurs auteurs ni leur contenu. Une révision divergente
dans une observation est refusée. Les rapports ne prouvent pas que le modèle
décrit correctement le monde. Un échec de recherche ou un test raté ne suffit
pas à établir une impossibilité.

## Utilisation

Après `python -m pip install -e ".[dev]"`, depuis la racine du dépôt :

```powershell
python -m tiberium_ai.diagnostics feasibility examples/diagnostics/reconnect.json
python -m tiberium_ai.diagnostics stability examples/diagnostics/patterns.py --source-id fixture:patterns --revision fixture-v1
python examples/stability_sequence.py
```

Le premier exemple est un scénario fictif de reconnexion : l'objectif exige
une persistance, déclarée absente. Ce n'est pas un audit d'Ultimate Odycer.
Le second lit du texte et construit un AST, sans l'importer ni l'exécuter.
Le troisième rejoue un signal fictif autour d'un seuil, compare les bascules
avec une hystérésis et vérifie la réaction aux changements francs.

La CLI lit un seul fichier UTF-8 explicite, limité à 256 Kio, puis émet du JSON
sur stdout. Elle refuse les clés JSON dupliquées et les nombres non finis.
Code de sortie `0` : analyse produite, y compris blocage ou impossibilité ;
`2` : entrée invalide ; `3` : analyse indéterminée. Un code `0` ne signifie
jamais « projet correct ».

## Contrat de faisabilité

API : `tiberium_ai.feasibility.diagnose(request, max_variables=12)`.
Le fichier [reconnect.json](../examples/diagnostics/reconnect.json) contient une
requête complète. Champs obligatoires : `schema`, `task_id`, `scope_id`,
`revision`, `variables`, `constraints`. `observations` et `criteria` sont des
listes facultatives, vides par défaut. Les schémas sont fermés : champs inconnus,
identifiants dupliqués, références inconnues et entiers employés comme booléens
sont refusés.

| Élément | Forme |
| --- | --- |
| Requête | `schema: parcimonia.feasibility-request/v1` |
| Variable | Nom déclaré dans `variables` |
| Exigence | `{id, kind: require, variable, value: bool, source}` |
| Dépendance | `{id, kind: implies, if: {variable, value}, then: {variable, value}, source}` |
| Observation | `{variable, value: bool ou null, source, revision}` |
| Critère | `{id, status: pass ou fail ou unknown, source}` |

Une extension inconnue peut être représentée par l'enveloppe `{id, kind,
source}` ; elle provoque une abstention de faisabilité. Les champs supplémentaires
d'une contrainte non prise en charge sont refusés plutôt qu'ignorés. Les budgets
numériques, unités, durées et obligations temporelles restent à développer.

La recherche énumère au plus 4 096 affectations (12 variables, borne abaissable).
Le rapport conserve leur nombre, les contraintes utilisées, les témoins éventuels,
les valeurs obligatoires, les observations incompatibles et les contrôles suivants.
Il ne trouve pas de noyau minimal de contradiction ou de réparation optimale.
Des observations peuvent être incompatibles conjointement sans qu'une variable
soit obligatoire isolément : le blocage reste identifié, sans inventer une pièce
manquante particulière.

## Motifs de stabilité

API : `tiberium_ai.stability.inspect_python_stability(source,
source_id=..., revision=...)`.

| Règle | Risque recherché | Vérification utile |
| --- | --- | --- |
| `mutable_default_argument` | État partagé entre appels par une valeur par défaut mutable | Appels répétés et changement de leur ordre |
| `single_threshold_switch` | Oscillations possibles autour d'un seuil unique | Signal bruité, puis changements francs |
| `retry_without_visible_exit` | Relance sans sortie locale visible | Échecs persistants, borne, délai et annulation |

Chaque constat est un `risk_indicator` avec position et contrôle proposé. Une
absence de motif reconnu n'atteste pas la stabilité. Un motif reconnu ne prouve
pas une panne : l'état partagé peut être intentionnel, le signal filtré ailleurs,
ou une fonction appelée peut interrompre une boucle. L'inspection est limitée à
Python, grammaire 3.10, et à ces trois formes syntaxiques. Syntaxe invalide ou
bornes de taille/complexité dépassées donnent un résultat indéterminé. Aucun motif
n'est converti automatiquement en critère échoué ou en preuve d'impossibilité.
La borne de l'API directe limite l'analyse AST ; la construction préalable de
l'empreinte lit encore l'intégralité du texte fourni. La CLI borne aussi la lecture.

La démonstration [stability_sequence.py](../examples/stability_sequence.py)
compare un seuil 0,50 à une bande 0,45–0,55 sur dix échantillons prédéfinis.
L'hystérésis peut réduire les bascules, mais retarder une réponse pertinente
dans la bande. Le nombre de bascules ne mesure ni qualité générale ni rapidité.

## Provenance et rejeu

Les rapports portent l'empreinte de leur entrée exacte et une identité de moteur
versionnée. `register_feasibility_verifier(registry)` réutilise le
[registre existant](VERIFICATION.md) : `boolean-feasibility-report`, version `1`,
reçoit `{request, report}` et recalcule le rapport avec le budget enregistré.
Le rejeu vérifie la cohérence du calcul, pas la vérité des sources ou l'origine
authentifiée du budget. Il peut accepter la reproduction correcte d'un résultat
indéterminé ; cette acceptation n'est pas un verdict positif sur le projet.

Ces fonctions sont appelées explicitement. Elles ne découvrent pas de dépôt,
n'exécutent pas le code inspecté, ne réparent rien et ne changent pas les
politiques existantes. Les contrats des tâches et décisions restent inchangés.
Pour revenir au comportement antérieur, omettre ces appels. Aucune nouvelle
dépendance, aucun modèle ni service n'est requis.

## Suite R&D

1. Conserver de vrais épisodes autorisés avec objectif, révision, diagnostic
   attendu et résultat observé ; séparer développement et cas réservés.
2. Mesurer fausses impossibilités, faux blocages, lacunes omises, faux signalements
   de motifs et abstentions utiles.
3. Étendre les contraintes avec des vérificateurs adaptés : ressources et unités,
   puis séquences temporelles, invariants et autres langages.
4. Employer ensuite de petits modèles pour proposer des hypothèses ou formaliser
   les données manquantes ; garder leur incertitude distincte de la preuve calculée.

Les fixtures et tests vérifient le contrat logiciel. Ils n'établissent ni
couverture générale, stabilité d'une application réelle, performance matérielle,
calibration ni économie de tokens ou de coût.
