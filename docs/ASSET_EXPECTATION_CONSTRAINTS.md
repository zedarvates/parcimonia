# Contradictions dans les attentes d'un asset

Avant de comparer un fichier à des attentes, Parcimonia peut contrôler si
celles-ci se contredisent sur un même fait. Une largeur demandée à la fois
supérieure ou égale à 512 et inférieure ou égale à 256 fournit une contradiction
sans avoir besoin d'inspecter une image.

Ce contrôle utilise le [contrat d'attentes existant](ASSET_EXPECTATIONS.md),
avec un rapport distinct `parcimonia.asset-expectation-consistency/v1`.
Les rapports d'inspection et d'audit précédents ne changent pas.

## Résultats et portée

| Statut | Ce qui est établi |
| --- | --- |
| `contradictory` | Au moins deux contrôles d'un même fait et d'une même source sont incompatibles dans le modèle déclaré. |
| `no_conflict_detected` | Une affectation par fait satisfait les contrôles de ce modèle indépendant. L'existence d'un fichier correspondant reste à vérifier. |

Chaque entier est modélisé dans `[0, 2**63 - 1]`, avec `eq`, `gte` et `lte`
inclusifs. Les textes et booléens n'admettent que l'égalité exacte. Les demandes
de présence de propositions sont toujours `true`, conformément au contrat
existant. Pas de conversion de type, unité, casse ou normalisation Unicode.

**Le modèle n'établit ni les relations entre faits ni les limites des lecteurs.**
Par exemple, il peut affecter un compte de faces et un format indépendamment,
sans prouver leur compatibilité physique. Une demande `sample.bytes >= 2 MiB`
ne contredit pas son domaine abstrait entier, alors que l'inspection actuelle
limite son échantillon à 1 MiB. Le rapport conserve explicitement
`cross_fact_relations` et `producer_profile_caps` à `not_modelled`.

Les identités de source ID/révision sont exactes. Deux révisions ou deux faits
différents ne sont pas comparés entre eux. Les caractéristiques non demandées,
la qualité, la complétude et la faisabilité réelle restent hors contrôle.

## Certificats

Pour chaque fait, le rapport garde tous les identifiants de contrôles :

- sans conflit, une valeur `candidate` satisfaisant ces contrôles ; elle n'est
  pas une observation d'un fichier ;
- avec conflit, deux identifiants et leurs chemins dans le contrat, par exemple
  `/assets/0/checks/0` et `/assets/0/checks/1`.

Les deux règles d'une paire sont chacune autorisées par le contrat, mais ne
peuvent être satisfaites ensemble. Ce certificat local ne prétend pas identifier
une cause générale ou toutes les paires incompatibles. Pour les entiers,
l'analyseur conserve la borne inférieure la plus forte et la borne supérieure
la plus forte ; les égalités fixent les deux bornes. Les ex æquo gardent la
première règle. Les faits sont triés par nom et les sources gardent l'ordre
du contrat.

Le hash d'entrée lie le contrat complet à l'analyseur
`asset-expectation-consistency/1`. Le rapport conserve aussi le hash du contrat.
Changer des attentes exige un nouveau contrôle ; les déclarations restent
fournies par l'appelant et non authentifiées.

## Vérification distincte

`verify_asset_expectation_constraints(expectations, report)` contrôle les formes,
les identités, la couverture exacte de tous les faits, leurs règles et les
certificats, sans rappeler l'analyseur. Il teste toutes les règles d'un fait
contre sa candidate. Pour une paire entière, il examine un ensemble complet
d'extrémités possibles pour ces deux intervalles, séparément du calcul global
des bornes effectué par le producteur.

Une candidate différente mais valide, ou une autre paire réellement
incompatible, reste un certificat acceptable. Une paire compatible est refusée,
même si le groupe entier est contradictoire à cause d'une autre règle.

Le raccord utilise le registre existant :

```python
from tiberium_ai.asset_expectation_constraints import (
    check_asset_expectations, register_asset_expectation_verifier,
)
from tiberium_ai.verification import VerifierRegistry

report = check_asset_expectations(expectations)
registry = VerifierRegistry()
register_asset_expectation_verifier(registry)
proof = registry.verify("asset-expectation-constraints", "1", {
    "expectations": expectations, "report": report,
})
```

`proof.verdict == True` signifie que le certificat est valide, y compris quand
il démontre une contradiction. Cela ne signifie pas que les attentes sont
satisfaites ou qu'un fichier est bon. Une version inconnue s'abstient.
L'API de vérification refuse aussi les objets Python étrangers, cycles et
valeurs non finies ; le registre attend un paquet JSON sérialisable, comme
ses autres vérificateurs.

## Utilisation

```bash
PYTHONPATH=src python -m tiberium_ai.asset_cli check-expectations attentes.json
PYTHONPATH=src python -m examples.asset_constraint_demo
```

Seul le contrat est lu. Aucun asset, catalogue, modèle ou programme natif n'est
appelé. Une contradiction produit un rapport exploitable et le code 0 ; une
erreur de contrat, lecture ou budget produit le code 2, sans JSON partiel sur
stdout. Les faits ou opérateurs non pris en charge sont des erreurs explicites.

Les budgets d'entrée restent ceux du contrat : 64 KiB canoniques UTF-8, 64
sources, 32 contrôles par source et 256 au total. Le rapport est limité à
256 KiB canoniques UTF-8 ; la sortie CLI ASCII possède le même plafond. Le
validateur JSON partagé borne profondeur et nœuds à 64 et 20 000. Les plafonds
ne garantissent pas une durée ou une mémoire système absolue.

Le contrôle est un premier filtre. Après examen d'une contradiction éventuelle,
l'[audit d'attentes](ASSET_EXPECTATIONS.md) compare les rapports aux exigences
retenues. Un contrat sans conflit peut être contredit par une valeur observée ;
un rapport absent reste manquant dans l'audit. Aucun reclassement, acceptation
de tag, correction automatique ou routage actif n'est déclenché.

La [démonstration conservée](../wiki/ASSET_CONSTRAINTS_DEMO_2026-10-31.json)
contient des attentes fabriquées, un conflit 512/256, une révision à 512/1024 et
les reçus de vérification. Aucun fichier utilisateur n'a été inspecté.
Voir le [point de vérification](../wiki/ASSET_CONSTRAINTS_2026-10-31.md).
