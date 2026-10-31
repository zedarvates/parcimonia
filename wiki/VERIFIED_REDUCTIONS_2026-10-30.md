# Première réduction vérifiée — 30 octobre 2026

## Mission

Implémenter une première réduction de Karp exploitable par Parcimonia : traduire
ses exigences et implications booléennes en 2-CNF, conserver la réponse pour
chaque affectation et résoudre la satisfiabilité avec des preuves contrôlables.

Cette proposition dépend du diagnostic de la PR #20, tête inspectée
`598688f60c3cf6975dbd1f013340aa2dca0ebb9e`, arbre
`5b40c9d4e26bbfe0eb89a0c1d229bb637e70b2ba`. Cette PR était ouverte et en
brouillon lors de la préparation ; elle n'est pas traitée comme fusionnée.
La nouvelle branche cible sa branche pour isoler les changements.

## Réalisation

- Traduction exacte : exigence vers clause unitaire ; implication vers clause
  `NON antécédent OU conséquence`. L'origine de chaque clause est conservée.
- Question explicite : contraintes seules, ou contraintes et observations connues.
  Les valeurs inconnues n'ajoutent jamais de clause négative.
- Solveur 2-SAT par composantes fortement connexes, avec piles explicites.
- Vérification directe des affectations et des chemins contradictoires, distincte
  du solveur. Rejeu des rapports par le registre existant.
- CLI opt-in `reduce` et `solve`, rapports versionnés séparés, aucune route activée.

Les exigences restent limitées au langage booléen actuel. Les axes de qualité
et de complétude du diagnostic exhaustif ne sont pas repris implicitement.
Contrat, argument d'équivalence, utilisation et sources universitaires sont dans
le [guide](../docs/VERIFIED_REDUCTIONS.md).

## Vérification exécutée

Python 3.12.14 : **1 120 tests réussis**, soit les 963 tests de la base et
157 nouveaux tests. Commande : `PYTHONPATH=src python -m pytest -q`.
Un avertissement provient du plugin anyio de l'environnement.

Les tests de traduction évaluent les règles sur chaque affectation de petits
modèles, avec les polarités, auto-implications, observations et permutations.
Les tests du solveur comprennent 680 formules comparées à un oracle indépendant,
les certificats falsifiés, tautologies, unités, bornes et chaîne de 128 variables.
Les tests d'intégration contrôlent les deux questions, les inconnues, le refus
d'un faux certificat, le rejeu et les deux nouvelles commandes de la CLI.

La revue indépendante n'a identifié aucun défaut bloquant. Elle a notamment
cherché une inversion de signe, un mélange des observations et contraintes,
un ordre SCC incorrect et un certificat qui ne prouverait pas son affirmation.
Ces contrôles finis renforcent la validation du logiciel ; ils ne remplacent
pas l'argument d'équivalence des règles ou une évaluation sur projets réels.

La grammaire Python 3.10, les liens documentaires et les espaces passent. Les
exemples CLI sont exécutés et leurs sorties JSON relues. L'exemple de reconnexion
reste un blocage d'état observé. La chaîne de 128 variables produit le même type
de constat sans recourir à une table de vérité ; le diagnostic exhaustif séparé
reste indéterminé au-delà de sa borne de 12 variables.

## Limites et reprise

Les sources restent déclaratives, pas authentifiées. Une réponse SAT établit
la cohérence du modèle fourni ; une réponse UNSAT s'applique à la question
explicitement traduite. Aucune performance matérielle, économie de tokens,
vitesse relative ou qualité générale n'est mesurée.

Il s'agit d'une compilation exacte d'un fragment déjà exprimable en 2-SAT,
pas d'une découverte automatique de réductions. SAT général, contraintes
numériques ou temporelles et réparation optimale restent hors périmètre.

La proposition est destinée à une revue en brouillon, sans fusion, déploiement
du plugin cloud ou activation. Vérifier la CI du commit publié et le nouvel
état de #20 avant intégration. Pour reprendre : utiliser un épisode réel autorisé,
formaliser ses hypothèses, conserver sa révision et vérifier le diagnostic.
