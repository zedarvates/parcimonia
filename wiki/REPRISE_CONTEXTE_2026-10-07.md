# Reprise : sémantique des champs et préparation de revue

- Réalisé : `task_context.py`, compagnon v2 de la signature v1 ; champs fournis,
  références, contexte disponible/requis/manquant/inconnu et valeurs invalides.
  Les exigences sont déclarées par opération, pas inférées depuis des mentions.
- Références : preuve liée au contrat, au champ, à la référence et à la révision
  de contexte, avec identité de vérificateur connue. L’évaluation ne lance pas
  de vérificateur ; attribution conservée. Toute sortie reste sans autorisation.
- Compatibilité : signature, labels et captures historiques conservés. Seul
  `src/tiberium_ai/__init__.py` est modifié pour les exports de ce nouvel incrément.
  Les fichiers du premier incrément restent à leurs hashes vérifiés.
- Préparation : `context_review.py` et `examples/context_review_pilot.py`.
  Lot local dans `runs/signature-corpus/context-review-20261007.json` : 120 demandes
  candidates à signal français, zéro label, contexte source et groupes à revoir.
- Provenance : révision présente sur disque
  `22de4af5f3175be494ca84b33d456abd9f86a636bb4bcedfc822ed5f46e23b40` ; aucune
  nouvelle collecte de conversations. Source et lot contrôlés par hashes.
- Limite réelle : la révision ne conserve pas les identifiants de conversation,
  seulement `sessions` / `archived_sessions`. Aucun split développement/test
  n’est présenté comme validé ; statut `awaiting_source_and_paraphrase_group_review`.
- Vérification : **956 tests passent**, sept scénarios de contrat concordent ;
  rejeux Laya 4/6 et Jeff 5/6 inchangés. `git diff --check` passe.
- Documentation : `docs/TASK_CONTEXT.md`. Preuves agrégées et copies avant
  modification dans `runs/context-semantics-20261007/`, ignoré par Git.
- Aucun prompt réel dans le dépôt suivi ; aucune nouvelle inférence ou mesure
  d’exactitude/calibration/coût. Aucun commit, service ou routage activé.
- Prochaine action : récupérer/revoir la provenance par conversation et les
  groupes de paraphrases, confirmer langue et contexte des cas, obtenir des
  annotations indépendantes ; figer ensuite le split avec hashes des cas.
  Le compagnon est prêt pour une future porte de préparation de cascade,
  mais la cascade v1 n’a pas été remplacée par cet incrément.
