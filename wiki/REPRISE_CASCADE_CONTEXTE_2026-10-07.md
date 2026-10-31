# Reprise : cascade de signature avec contexte préalable

- Ajout explicite `SignatureCascadeBackend.propose_signature` : contexte validé
  avant tout prédicteur ; collecte si manquant/inconnu, réparation si invalide.
  Type conforme au contrat et seuil effectif requis pour sélectionner une signature.
- Une baseline incertaine ou d’un autre type peut consulter une fois le secours
  déclaré. Le lot est validé entier ; pas d’assemblage de réponses de deux backends.
  Secours faible/incompatible = abstention, erreur de protocole = refus explicite.
- Identités (id/version) contrôlées, scripts non compatibles sautés avant appel,
  compteurs/plafonds partagés avec la v1. Hash liant contexte, questions, politique
  et compteurs de budget avant l’appel. Aucun résultat ne donne d’autorisation.
- `ContextCascadeProposal` conserve contexte, signature éventuelle, traces et nombre
  d’appels `backend.evaluate` ; coûts/latences non mesurés à `None`. Pas de preuve
  d’économie ou de calibration déduite du nombre d’appels.
- Source modifiée : `src/tiberium_ai/signature_cascade.py`. Méthodes v1 `evaluate`
  et `_stage` inchangées par comparaison AST. Copie avant modification conservée
  dans `runs/context-cascade-20261007/before/`.
- Nouveaux tests/pilote : `tests/test_context_signature_cascade.py`,
  `tests/test_context_signature_cascade_pilot.py`,
  `examples/context_signature_cascade_pilot.py`.
- Validation finale : **1007 tests passent**. Huit scénarios authored, dont trois
  sans appel au prédicteur. Callbacks injectés seulement, aucune inférence neuronale.
  Rejeux historiques Laya 4/6 et Jeff 5/6 inchangés ; `git diff --check` passe.
- Documentation : `docs/CONTEXT_SIGNATURE_CASCADE.md` et lien depuis `TASK_CONTEXT.md`.
  Rapports, hashes et comparaisons dans `runs/context-cascade-20261007/`, ignoré par Git.
- Limites : plafonds d’appels, pas budgets monétaires/latences mesurés ; hôte doit
  contrôler ressources, frais et fraîcheur avant action. Le contexte n’est pas ajouté
  implicitement au prompt modèle. Les probabilités demeurent non calibrées.
- Lot humain : toujours distinct, 114 candidats et six cas isolés. Aucune annotation
  indépendante ou capture nouvelle sur ces cas n’est créée par ce pilote.
- Prochaine action : connecter les propositions aux mesures/captures et aux politiques
  de ressources existantes ; obtenir la revue humaine puis la comparaison appariée.
  Le nouveau mode reste opt-in et n’active pas le routage de production.
- Aucun commit, téléchargement de poids, nouveau modèle, helper supplémentaire,
  service partagé redémarré ou effector exécuté.
