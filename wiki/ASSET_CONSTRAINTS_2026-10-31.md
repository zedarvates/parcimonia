# Vérification — contradictions entre attentes — 2026-10-31

Base : main `034df9dfd219fe9144ba81b0ecb657252f2ec96b`.
Objectif : repérer des attentes incompatibles sur le même fait avant de
disposer d'un fichier, avec une preuve contrôlable distincte de l'analyseur.

## Réalisation et critères

- Le contrat `parcimonia.asset-expectations/v1` et son validateur fermé sont
  réutilisés. Les rapports existants d'inspection et d'audit restent inchangés.
- Les contraintes entières `eq/gte/lte` sont des intervalles fermés sur
  `[0, 2**63 - 1]`. Les textes/booléens utilisent l'égalité exacte ; les
  propositions demandées sont des présences `true`.
- Un conflit conserve deux identifiants de règles et leurs chemins exacts dans
  le contrat. Sinon, une affectation par fait satisfait toutes ses règles.
- Les sources/révisions et faits distincts sont séparés. Les relations entre
  faits et les plafonds des producteurs sont explicitement hors modèle.
- Le vérificateur contrôle indépendamment les candidates ou les paires locales,
  sans rappeler le producteur. Il réutilise `VerifierRegistry` avec l'identité
  `asset-expectation-constraints/1`. Un verdict vrai sur un conflit certifie la
  contradiction ; il ne certifie pas la réussite d'un fichier.
- CLI `check-expectations`, lecture d'un contrat explicite uniquement, sortie
  utilisable avec code 0 même en cas de contradiction ; erreurs d'entrée avec
  code 2 et sans JSON partiel sur stdout.

## Validation

**3 486 tests et 34 sous-tests passent sur Python 3.12.14**, sans test ignoré :
les 3 410 tests de la base et 76 nouveaux cas, dont 66 API/certificats et 10
CLI/démonstration. L'avertissement de dépréciation du plugin pytest `anyio`
de l'environnement reste sans échec.

Un des cas compare le résultat à une énumération exhaustive indépendante de
**815 petits modèles numériques**. Les autres exercent les extrêmes entiers,
égalités, booléens, Unicode exact, séparation des sources/faits, modifications
de certificats et limites de contrat. Ils vérifient aussi qu'une paire compatible
est refusée même quand une autre paire du groupe est contradictoire, ainsi que
le refus d'une preuve périmée malgré des hashes recalculés.

Les candidates et paires non canoniques mais valides sont acceptées. Le
producteur est remplacé par une fonction qui lève pendant un test : la
vérification continue de fonctionner. Les entrées sont préservées, les retours
sont indépendants et JSON strict, et aucun fichier/processus/socket n'est
utilisé par les API pures. La CLI réelle est testée avec identifiants français
et pipes ASCII. Les lectures de liens, contrats trop grands, JSON à clés
dupliquées, faits inconnus et sorties trop grandes sont refusées.

Une contre-revue en lecture seule a exécuté séparément **494 cas sémantiques**
et refusé **45 certificats invalides ou malformés**, sans fichier modifié.
Elle a aussi remplacé le producteur et son calcul interne par des fonctions
qui lèvent. Aucun contre-exemple restant n'a été identifié pour ce modèle.
Ces oracles sont des vérifications locales de développement, pas une mesure
de qualité sur des fichiers ou besoins réels.

## Démonstration et limites

Les [données conservées](ASSET_CONSTRAINTS_DEMO_2026-10-31.json) sont uniquement
des attentes fabriquées : largeur à la fois au moins 512 et au plus 256,
puis une révision à 512/1024. Chaque rapport conserve son reçu du registre.
Les données et les vérifications se reproduisent à l'identique après lecture
JSON. Aucun asset personnel, modèle ou rendu n'a été utilisé.

```bash
PYTHONPATH=src python -m examples.asset_constraint_demo
PYTHONPATH=src python -m tiberium_ai.asset_cli check-expectations attentes.json
PYTHONPATH=src python -m pytest -q
```

Guide : [ASSET_EXPECTATION_CONSTRAINTS.md](../docs/ASSET_EXPECTATION_CONSTRAINTS.md).
Le contrat reste borné à 64 KiB, 64 sources et 256 contrôles au total, 32 par
source. Rapport canonique et stdout ASCII sont chacun limités à 256 KiB.
La grammaire Python 3.10, les liens locaux modifiés et les espaces sont vérifiés.

`no_conflict_detected` ne prouve pas un fichier réalisable : pas de relation
format/géométrie, de plafond propre à un lecteur, de qualité, de complétude ou
de diagnostic général du monde réel. Les candidates sont des affectations,
pas des observations. Pas de correction, acceptation de tag, organisation de
fichiers, activation ou gain de coût/vitesse annoncé. Repli : omettre la
nouvelle commande et conserver l'audit d'attentes existant.
