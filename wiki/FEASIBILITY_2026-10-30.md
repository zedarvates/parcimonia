# Diagnostic de faisabilité et motifs de stabilité — 30 octobre 2026

## Mission et résultat

Premier prototype consultatif pour distinguer impossibilité dans un modèle fini,
blocage actuel, prérequis absents ou inconnus et critères de qualité déclarés.
Une observation supplémentaire a élargi la mission aux motifs de code pouvant
contribuer à des problèmes de stabilité.

Base inspectée : `83f40ebd715d09add32c45a73c44dc48e88a472a` sur
`zedarvates/parcimonia/main`. Les travaux de doublons et d'organisation proposés
dans la PR #19 restent distincts. Les autres branches ouvertes ne sont pas
traitées comme fusionnées. Aucun chantier de bureau ou de personnalisation
visuelle n'est intégré.

Le résultat est accessible par la bibliothèque et une CLI explicite. Contrat,
exemples et suite R&D : [guide](../docs/FEASIBILITY_DIAGNOSTICS.md).

## Vérifications locales

Python 3.12.14, suite existante de la base : **809 tests réussis**.
Suite du candidat : **963 tests réussis**, dont **154 nouveaux**.
Commande : `PYTHONPATH=src python -m pytest -q`.
L'avertissement pytest observé provient du plugin anyio de l'environnement.

Les nouveaux contrôles couvrent les contradictions transitives, un oracle
indépendant sur de petits modèles, les observations conjointement incompatibles,
les inconnues, les critères séparés, la falsification des rapports, les bornes,
la syntaxe et les motifs AST. La CLI est exercée en sous-processus, y compris
avec des pipes ASCII et du texte français. Une source contenant une écriture
sentinelle est inspectée sans que cette écriture se produise.

Les quatre nouveaux fichiers de production et de démonstration acceptent la
grammaire Python 3.10. Les liens locaux de la documentation modifiée et les
contrôles d'espaces passent. Les trois exemples publics sont exécutés et leurs
sorties JSON relues.

## Résultats des exemples

- Reconnexion fictive : exigences cohérentes, persistance déclarée absente,
  `blocked_current_state` et `missing_prerequisites`.
- Inspection Python : les trois motifs pris en charge sont repérés comme
  indicateurs de risque, sans exécuter les fonctions inspectées.
- Signal fictif sur dix échantillons : six bascules au seuil unique, deux avec
  hystérésis ; sur le préfixe de gigue, cinq contre zéro. La réponse aux deux
  changements francs est conservée. L'hystérésis peut retarder une réponse
  pertinente à l'intérieur de sa bande.

## Revue et correction

Une revue indépendante a reproduit une incohérence : avec `c` obligatoire,
`a => b`, et les observations `a=true`, `b=false`, `c=true`, le rapport associait
un blocage à `known_requirements_present`. Les seules valeurs obligatoires
globales ne couvrent pas toutes les dépendances activées par l'état courant.

La correction exige un témoin compatible avec les observations avant d'annoncer
`known_requirements_present`. Le cas est ajouté à la suite ; sa complétude reste
indéterminée sans prérequis absent individuellement démontré. Le moteur ne
fabrique pas une réparation pour expliquer un conflit collectif.

## Limites et reprise

L'installation wheel locale n'a pas été testée : le backend de construction
existant `hatchling` n'est pas disponible dans l'environnement local. Aucun
paquet n'a été téléchargé pour ce contrôle. La CI du dépôt installe le projet
avant les tests ; son résultat doit être lu pour le commit proposé.

Ces tests et démonstrations sont des preuves du contrat logiciel sur des
fixtures, pas une qualification sur des projets réels. Les sources restent des
déclarations de l'appelant. Budgets numériques, temporalité générale, autres
langages, extraction depuis le langage naturel et calibration restent à réaliser.
Les gains de tokens, coût et performance matérielle ne sont pas mesurés.

La proposition reste isolée pour revue. Aucun outil cloud existant n'est déployé
ou remplacé par ce travail. Pour reprendre : lire le guide, collecter un épisode
réel autorisé avec révision et diagnostic attendu, puis mesurer les erreurs
avant d'élargir les motifs ou les contraintes. Un changement du moteur ou des
entrées exige un nouveau rapport et les contrôles concernés.
