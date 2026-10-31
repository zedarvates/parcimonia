# Reprise : première tâche réelle assistée par Parcimonia

- Demande : réaliser une tâche réelle dans TiberiumAI, mesurer et relever les
  suggestions à corriger.
- Tâche achevée et validée par l'agent : `--policy` JSON pour la CLI de préparation,
  validation avant sortie, priorité de strict et traces de politique effective.
- Modifications ciblées : `src/tiberium_ai/task_preparation.py`,
  `examples/prepare_development_task.py`, inventaire de développement v2,
  documentation du pilote. Ajouts : `tests/test_task_preparation_policy.py`,
  `examples/fixtures/development_local_policy.json`, `docs/REAL_TASK_POLICY_TRIAL.md`.
- Avant : 5 candidats/14 fichiers, aucun des 3 fichiers centraux. Recherche rg
  supplémentaire nécessaire. Source CLI déjà connue avant gel : pas d'essai aveugle.
- Après ajout de 4 fiches : inventaire 28 entrées, 5 candidats/10 fichiers,
  3 références centrales retrouvées. `profiles.routes` reste superflu ; noter
  ce défaut sans surajuster davantage le classement sur ce seul cas.
- Préparation interne : 72,4 ms avant, 93,5 ms après ; 0 appel modèle du préparateur.
  Gain global non mesuré. Jalons UTC : 116 s premiers tests fonctionnels ;
  278 s validation élargie/inventaire depuis le premier paquet, raisonnement inclus.
- 170 tests ciblés passent, rapport JUnit sous
  `runs/task-policy-real-20261020/validation.xml`. `git diff --check` sans erreur.
- Preuves immuables du cas sous `runs/task-policy-real-20261020` : enregistrement,
  sources avant, paquets avant/après, essais de CLI et bilan JSON avec hashes.
- Aucun commit ni service modifié, aucun modèle chargé et aucune route proposée
  exécutée. Travaux locaux antérieurs préservés.
- Suite : nouvelle tâche indépendante avec paquet figé avant exploration des
  cibles ; maintenir le cas présent comme régression, pas comme test indépendant.
