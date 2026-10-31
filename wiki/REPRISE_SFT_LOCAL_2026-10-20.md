# Reprise : pilote SFT local issu de JevAgentHarness

- Demande : continuer l'analyse de la vidéo `yfepTKKhgKg` pour Parcimonia.
- Ajout : `docs/spikes/architecture-local-decision-sft-spike.md` et cette reprise.
- État : protocole écrit ; expérimentation et entraînement non réalisés.
- Base relue : contrats de décision, cascade, contexte et pilote local Jeff/Laya.
- Choix : apprendre une difficulté de routage résiduelle ; conserver les contrôles
  déterministes de contexte. Ne pas entraîner un modèle à recopier ces contrôles.
- Banc proposé : au plus 300 épisodes synthétiques, groupes séparés 150/75/75,
  états après erreur, vérité terrain indépendante, coûts inconnus explicites.
- Vérifications : liens locaux du document et contrôle du diff ; pas de test
  applicatif nécessaire pour ces seuls ajouts documentaires.
- Sources : transcription consultée le 19 ; papier v1 relu en ligne le 20.
- Travaux locaux nombreux préexistants conservés ; aucun commit ou service lancé.
- Suite : générateur et rejeu hors réseau avec tests des labels, transitions,
  groupes et coûts. Comparer les baselines avant de décider d'un SFT.

## Incrément suivant : banc hors réseau

- Ajouts : `src/tiberium_ai/decision_gym.py`, `examples/decision_gym_pilot.py`,
  `tests/test_decision_gym.py`, `docs/DECISION_GYM_PILOT.md`.
- 300 épisodes, six scénarios par famille, groupes intacts ; découpage ajusté
  à 150/78/72. Modèles linguistiques partagés : test du protocole uniquement.
- Rejeu de règles et cache exact ; vérificateur distinct, erreurs rejetées,
  reprises visibles et budgets consommés. Jev/SFT/cascade historique `not_run`.
- 68 tests ciblés passés après ajout de `src` au PYTHONPATH du processus.
  Première collecte sans ce chemin : import impossible, aucun test exécuté.
- Suite : reformulations indépendantes, mesure des erreurs résiduelles et
  admissibilité multi-route avant export de données SFT. Aucun entraînement.
- Exécution confirmée : `runs/decision-gym-20261020-v1/{episodes,report}.json`.
  Chaque bras : 200 résultats vérifiés, 50 escalades, 50 budgets épuisés ;
  50 sorties mal formées rejetées puis corrigées. 68 tests passent après ajout
  des compteurs et percentiles ; `git diff --check` sans erreur.
