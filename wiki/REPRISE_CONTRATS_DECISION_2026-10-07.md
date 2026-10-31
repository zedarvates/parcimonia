# Reprise : premier incrément CLEF / GEV, contrats de décision

- Réalisé le 7 octobre 2026 : les trois régressions reproduites sont corrigées.
- Calibration : `CalibrationBinding` lie question, schéma complet et ordre,
  backend/version, encodage et convention de confiance. Relevés historiques
  sans liaison et familles incompatibles restent inéligibles ; prise en charge
  des relevés par question et propagation de l’identité du backend au rejeu.
- JSON : `decision_json.py` conserve clés, types et imbrication, avec refus de
  clés non textuelles et de valeurs non finies. Entrées texte inchangées.
- Fournisseurs : `provider_answers.py` partage la tolérance d’arrondi bornée
  entre Laya/Jeff et TypeSafe ; traces brutes préservées, troncatures déclarées
  refusées, validation centrale stricte et absence de retry conservées.
- Mesure : rapports de calibration version 2 ; lot complet stable et même
  confiance pour mesure et consommation. Un rapport ne donne pas d’autorisation.
- Sources modifiées : `reflex.py`, `reflex_calibrate.py`, `laya_backend.py`,
  `agent_recipes/providers.py`, `agent_recipes/core.py`, `decision_adapter.py`,
  `pipeline.py`, `__init__.py` ; adaptation de `tests/test_reflex.py` et nouveau
  `tests/test_decision_contract_regressions.py`.
- Documentation : `docs/DECISION_CONTRACTS.md` ; analyse initiale annotée avec
  lien vers cet incrément. Copies avant modification et manifeste dans
  `runs/contracts-20261007/`, ignoré par Git.
- Vérification finale : suite complète, **917 tests passent** ; trois sondes
  corrigées ; rejeux réels conservés identiques à ceux de l’analyse : Laya 4/6,
  Jeff 5/6 types corrects acceptés, deux secours par bras. `git diff --check` passe.
- Limites : essais de contrats et rejeu, sans nouvelle inférence, réseau ou
  économie mesurée. Aucun routage automatique activé. Les labels de champs
  restent ambigus ; aucune mesure indépendante générale du français n’est établie.
- Travail local partagé préservé, dont les modules de signature et Jeff ; aucun
  commit ni démarrage de service. Les anciens relevés doivent être remesurés
  avant une utilisation avec les nouvelles liaisons.
- Prochaine étape : définir distinctement champs fournis, contexte requis et
  contexte manquant ; garder les fixtures existantes versionnées, préparer un
  lot de développement et un lot français indépendant tenu à l’écart.
