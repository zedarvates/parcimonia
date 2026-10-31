# Reprise : préparation locale des tâches avec Parcimonia

- Demande : commencer le pilote de préparation des travaux sur TiberiumAI.
- Ajouts : `src/tiberium_ai/task_preparation.py`,
  `examples/prepare_development_task.py`, inventaire épinglé de 24 entrées dans
  `examples/fixtures/development_capabilities.json`,
  `tests/test_task_preparation.py`, `docs/TASK_PREPARATION_PILOT.md` et cette note.
- Fonctions : index borné, relecture des hashes, réutilisation de termes/AST,
  filtrage par profils avant classement lexical, fichiers/tests suggérés,
  contraintes conservées, propositions sans exécution ni appel de modèle.
- Inventaire : 20 mécanismes locaux + 4 sources de skills engineering fournies
  par racine optionnelle ; tags déclarés, inconnus non convertis en permission.
  19 mécanismes compatibles en mode déclaratif sur la démonstration.
- Résultats cold/warm confirmés sous `runs/task-preparation-20261020-*` :
  mêmes cinq candidats, un skill à revoir, six fichiers, 30 dérivations réutilisées
  au second passage. Sources relues dans les deux cas : 219138 octets.
- Mesures internes uniques : index 166,5/31,7 ms ; préparation 38,1/37,9 ms.
  Contexte compact 6347 caractères vs index complet hypothétique 98519.
  Aucune économie réelle de tokens, qualité ou temps de tâche démontrée.
- Validation : 157 tests ciblés passés ; les 16 tests de préparation repassent
  après amélioration du rendu des contraintes et contrôles. `git diff --check`
  sans erreur. Le paquet final est sous `runs/task-preparation-20261020-final`,
  avec manifeste complet et réutilisation des 30 dérivations de l'index.
- Aucun commit, modèle chargé, hook activé, service modifié ou tâche proposée
  exécutée. Travaux locaux antérieurs conservés.
- Suite : utiliser les paquets sur des tâches réelles et consigner sélection
  effective, omissions/corrections et temps jusqu'au résultat accepté ; comparer
  à des tâches indépendantes avant un branchement automatique ou un SFT.
