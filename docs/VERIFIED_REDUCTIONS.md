# Une première réduction vérifiée pour Parcimonia

Une réduction traduit une question vers une autre représentation en conservant
sa réponse. Cette première version compile les exigences et implications
booléennes du [diagnostic](FEASIBILITY_DIAGNOSTICS.md) en 2-CNF, puis peut
résoudre la question obtenue avec un algorithme de graphes.

Il s'agit d'une réduction de Karp particulière, implémentée explicitement. Le
système ne découvre pas de nouvelles réductions à partir d'une demande libre.
La source est déjà un fragment exprimable en 2-SAT ; le progrès concret est une
traduction traçable, un solveur polynomial et des certificats vérifiables.

## Exemple lisible

Objectif : une connexion doit être possible et elle exige une persistance.

| Exigence source | Clause obtenue |
| --- | --- |
| La connexion est requise | `connexion` |
| La connexion exige la persistance | `NON connexion OU persistance` |
| Observation facultative : persistance absente | `NON persistance` |

Les deux exigences seules sont compatibles : connexion et persistance peuvent
être vraies. Avec l'observation, aucune affectation ne convient. Le premier
résultat est donc « exigences cohérentes » et le second « état actuel bloqué ».
Cela ne démontre pas une impossibilité générale du projet.

La traduction ne demande aucune énumération. Le solveur construit un graphe
d'implications, calcule ses composantes fortement connexes, puis produit soit
une affectation qui satisfait chaque clause, soit deux chemins contradictoires.

## Utilisation explicite

Après l'installation de développement du dépôt, depuis sa racine :

```powershell
python -m tiberium_ai.diagnostics reduce examples/diagnostics/reconnect.json
python -m tiberium_ai.diagnostics reduce examples/diagnostics/reconnect.json --with-observations
python -m tiberium_ai.diagnostics solve examples/diagnostics/reconnect.json
```

`reduce` traduit seulement les contraintes par défaut. `--with-observations`
change explicitement la question en y ajoutant les observations connues.
`solve` vérifie d'abord les contraintes seules ; si elles sont compatibles, il
vérifie ensuite les contraintes et observations connues. Une observation `null`
n'est jamais transformée en `false`.

Les commandes existantes `feasibility` et `stability` restent inchangées. Les
codes de sortie de la CLI gardent leur sens : `0` signifie qu'une analyse a été
produite, même en cas d'insatisfiabilité ; `2` désigne une entrée invalide et
`3` une abstention. Les fichiers explicites restent limités à 256 Kio.

## Pourquoi cette réduction conserve la réponse

Les noms de variables sont triés, puis associés aux entiers de 1 à n. Un entier
positif désigne la variable ; son opposé désigne sa négation. Le changement de
nom est bijectif et ne crée aucune variable auxiliaire.

Pour toute affectation des variables :

- `require(L)` est satisfaite exactement lorsque la clause unitaire `[L]` l'est.
- `implies(A, B)` est satisfaite exactement lorsque `[-A, B]` l'est, puisque
  `A implique B` équivaut à `NON A OU B`.
- Une observation booléenne connue incluse devient une clause unitaire identique
  à sa valeur ; une observation inconnue n'ajoute aucune contrainte.

La conjonction de ces équivalences donne l'équivalence pour chaque affectation,
puis l'équivalence des réponses « existe-t-il une affectation ? ». Chaque
contrainte produit une clause d'au plus deux littéraux. Le nombre de clauses
et la taille de sortie sont polynomiaux ; validation, tri et traduction restent
polynomiaux. Cela justifie le terme réduction de Karp pour ces questions précises.

La validation source est partagée avec le prototype existant. Une contrainte
de type inconnu fait abstention pour toute la traduction : elle n'est jamais
ignorée pour fabriquer une réponse positive.

## API et preuves

| API | Résultat |
| --- | --- |
| `reduce_to_2cnf(request, include_observations=False)` | Rapport `parcimonia.boolean-reduction/v1` avec question, cible, empreintes et origine de chaque clause |
| `solve_2cnf(formula)` | Résultat `parcimonia.2sat-result/v1` avec affectation ou certificat d'insatisfiabilité |
| `verify_2cnf_assignment(formula, assignment)` | Évaluation directe et stricte de toutes les clauses |
| `verify_2sat_result(formula, result)` | Contrôle d'un certificat SAT ou UNSAT sans relancer le calcul des composantes |
| `diagnose_via_2sat(request)` | Rapport séparé `parcimonia.reduced-feasibility-report/v1` distinguant contradiction et blocage actuel |

Les imports se font depuis `tiberium_ai.reductions`, `tiberium_ai.two_sat` et
`tiberium_ai.reduced_feasibility`. Les cibles sont des objets fermés :
`{schema: parcimonia.2cnf/v1, variables: [noms], clauses: [[entiers signés]]}`.
Les indices des littéraux commencent à 1 ; ceux des clauses commencent à 0.
Les booléens ne sont pas acceptés à la place des entiers.

Un résultat SAT comporte une affectation complète évaluée directement contre
les clauses. Un résultat UNSAT donne une variable et des chemins allant de son
littéral positif au négatif et réciproquement. Chaque arête référence une clause
qui implique réellement ce passage. Le vérificateur contrôle les chemins,
leurs extrémités, leurs références, le schéma et l'empreinte de la formule.
Les origines des clauses relient ensuite le certificat aux exigences sources.

`register_reduction_verifier` et `register_reduced_feasibility_verifier`
réutilisent le [registre existant](VERIFICATION.md) pour rejouer des objets
`{request, report}`. Accepter la reproduction d'une traduction, d'un résultat
indéterminé ou d'un conflit ne signifie pas que le projet réussit. Les identités
déclarées et empreintes ne constituent pas une authentification des sources.

## Bornes et portée

Le chemin explicite accepte jusqu'à 128 variables, 256 contraintes sources et
128 observations, soit au plus 384 clauses. Le calcul des composantes est
itératif. Il ne remplace pas le diagnostic exhaustif limité à 12 variables.

Ce nouveau rapport répond aux questions de satisfiabilité seulement. La qualité
et la complétude sont explicitement `not_assessed` ; les critères déclarés ne
font pas partie de la formule. Le diagnostic exhaustif garde son calcul des
prérequis obligatoires et son axe de critères. Une formule compatible ne
garantit ni que les inconnues seront favorables ni que le modèle décrit le monde.

Aucune performance matérielle ou économie de coût n'est déduite de la complexité
théorique. SAT général, contraintes numériques, temporalité, recherche de la
meilleure réparation et découverte automatique de réductions restent hors de
cette version. Il n'y a ni téléchargement, dépendance ajoutée, appel de modèle,
exécution d'un code inspecté ou activation de route. Pour revenir au comportement
antérieur, omettre ces nouveaux appels ou commandes.

## Sources primaires

- [Cours Illinois : réductions polynomiales et réduction de Karp](https://courses.grainger.illinois.edu/cs473/fa2011/lec/20_notes.pdf).
- [Cours Texas A&M : 2-SAT, graphe d'implications et composantes fortement connexes](https://people.engr.tamu.edu/andreas-klappenecker/csce411-s17/csce411-2sat.pdf), partie déterministe.

Les tests vérifient les signes, l'équivalence affectation par affectation sur de
petits cas, les certificats altérés, les inconnues, les conflits d'observations
et une chaîne de 128 variables. Ils restent des tests de contrat sur des cas
construits, pas une évaluation indépendante de projets réels.
