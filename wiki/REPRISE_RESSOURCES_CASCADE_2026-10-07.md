# Reprise : mesure et budgets de la cascade en mode contexte

- Ajout `cascade_resources.py` et option `resource_control` dans `propose_signature`.
  Contrôle de coût/latence estimés avant appel ; coût observé et durée au retour ;
  politique native d’escalade pour le secours, horloge native pour deadline/âge.
- Estimations et reçus observés séparés, unités identiques requises. Coût inconnu
  jamais remplacé par une estimation ou zéro. Dépenses/tentatives antérieures
  explicitement transmises ; environnement et politique figés par copies.
- Réponse tardive ou contexte trop ancien non sélectionnés. Erreurs d’horloge,
  unité ou observateur = refus, sans retry ou message privé. Mesures d’échec
  conservées lorsqu’elles sont valides ; mesure invalide non inventée.
- Réutilisation `run_baseline`, mesures `measurement/2`, `EscalationPolicy`,
  `DecisionBudget` / `assess_decision_timing`. Pas de nouveau transport ni runtime.
- Pilote `examples/resource_context_cascade_pilot.py` : neuf cas, dix mesures
  canoniques ; huit horloges synthétiques et un callback local `perf_counter`.
  Aucun modèle neuronal appelé ; coûts de fixture nommés, économies/qualité à null.
- Validation finale : **1038 tests passent**, `git diff --check` passe. Mesures
  exportées relues par le lecteur canonique. Chemins v1 inchangés par AST, mode
  contexte sans contrôle de ressources préservé ; Laya 4/6 et Jeff 5/6 inchangés.
- Source modifiée : `signature_cascade.py` ; nouveau module, tests et pilote.
  Copie avant modification et preuves dans `runs/cascade-resources-20261007/`.
  Documentation : `docs/CASCADE_RESOURCES.md`, lien depuis la doc de cascade.
- Limite : le contrôle ne préempte pas un callback synchrone ni ne rembourse un
  coût réel sous-estimé. L’hôte doit configurer transport/timeout/cancellation,
  provenance des reçus, autorisations et vérification du résultat de tâche.
- Statut sélectionné = descripteur satisfaisant les contrôles, pas résultat vérifié
  ou permission. `auto_act_allowed=false`. Aucun gain de production mesuré.
- Lot humain encore distinct : 114 candidats et six cas isolés, sans nouveau
  label humain ou nouvelle capture de modèle dans cet incrément.
- Prochaine action : produire/rejouer des captures exactes avec ces mesures,
  puis comparaison appariée sur revue humaine finalisée. Le contrôle est opt-in.
- Aucun commit, poids chargé, inférence nouvelle, helper supplémentaire ou service
  partagé redémarré ; aucun routage de production activé.
