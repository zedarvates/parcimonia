# Reprise : utilité des fichiers et suite des tâches

- Demande : privilégier les fichiers utiles et leur conservation pour les
  étapes suivantes, plutôt que le temps d'indexation.
- Ajouts : `src/tiberium_ai/task_followup.py`,
  `examples/continue_development_task.py`,
  `examples/fixtures/file_review_template.json`, `tests/test_task_followup.py`,
  `docs/FILE_USEFULNESS_AND_FOLLOWUP.md` et cette note. Documentation du pilote liée.
- Revue explicite par fichier : used/supporting/irrelevant/unreviewed ; manquants
  existants séparés des créations. Recherches/lectures supplémentaires nullable.
- Chaînage tâche/étape/paquet/revue par empreintes ; sources relues, notes de
  décisions et tests rapportés invalidées si les sources changent. Capacité et
  politique recalculées, aucune autorisation héritée. Limite 16 références affichées.
- CLI : création depuis `--feedback` ou rafraîchissement depuis `--review`,
  sortie exclusivement dans un nouveau dossier sous runs.
- Application rétrospective au paquet initial de la tâche --policy : 14 fichiers,
  1 soutien utile, 3 inutiles, 10 non évalués ; 4 manquants existants, 2 créations,
  1 recherche supplémentaire, nombre de lectures inconnu. Revue par l'agent ayant
  fait le travail, pas indépendante. 7 références utiles et 2 notes conservées.
- Première suite confirmée sous `runs/task-followup-20261020/next-stage` :
  7 sources inchangées. Rafraîchissement depuis la revue sauvegardée sous
  `refreshed-stage` : 6 inchangées, documentation du pilote à relire ; les deux
  notes gardent leurs sources inchangées sans redevenir des preuves certifiées.
- Inventaire v3 : 30 fiches après ajout de files.review et task.continue,
  empreintes source et dépendance au préparateur épinglées.
- Validation finale : 188 tests ciblés passent, dont 18 sur le suivi. Sources
  changées, indisponibles, notes périmées, chaîne multi-étapes, limites et CLI
  couverts. JUnit, summary.json et manifestes sous runs/task-followup-20261020.
  Deux nouvelles suggestions sont omises par le plafond de 16 fichiers, compteur
  explicite ; aucune référence utile portée n'est tronquée.
- Aucun commit, modèle chargé, route exécutée ou service modifié. Travaux locaux
  préexistants préservés. Aucun nombre de lectures évitées n'est inventé.
- Suite : utiliser la revue sur une nouvelle étape de travail, noter les lectures
  et recherches réellement nécessaires ; étendre les observations à d'autres tâches.
