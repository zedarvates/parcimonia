# Parcimonia Kanban Backlog

Dernière mise à jour : 2026-09-21T00:00:00Z
Mode : Local-First / Résilient (compatible Kanboard Neo et autonome)

## Terminé

- [x] TASK-G1 [P0] [difficulté: déterministe]
  - Intitulé : Baseline measurements & provenance (G1)
  - Reçu : 40 runs enregistrés dans examples/fixture_suite.py

- [x] TASK-G2 [P0] [difficulté: déterministe]
  - Intitulé : Deterministic verifiers (G2)
  - Reçu : shape, exact match, runner result verifiers

- [x] TASK-G3 [P0] [difficulté: déterministe]
  - Intitulé : Escalation budgets and hard stops (G3)
  - Reçu : Budget, EscalationPolicy, EscalationState

- [x] TASK-G4 [P0] [difficulté: déterministe]
  - Intitulé : Route registry and capability manifests (G4)
  - Reçu : RouteManifest, RouteRegistry, candidate filtering

- [x] TASK-G5 [P0] [difficulté: déterministe]
  - Intitulé : Resource vectors and Pareto front (G5)
  - Reçu : ResourceVector (tokens, latency, vram, energy), pareto_front

- [x] TASK-G6 [P0] [difficulté: compact]
  - Intitulé : Active mode with sandbox and kill switch (G6)
  - Reçu : ActiveRouter, ActivePolicy, Sandbox, KillSwitch

- [x] TASK-050 [P0] [difficulté: compact]
  - Intitulé : ContinuationArbiter pour Astral Resonance Director
  - Reçu : Arbitrage sur quotas, difficulté, arrêts consécutifs et WebBrain MCP
  - Preuve : tests/test_continuation.py

- [x] TASK-051 [P1] [difficulté: compact]
  - Intitulé : Parser et ordonnanceur local-first kanban.md
  - Reçu : KanbanBoard, KanbanTask, dépendances DAG sans dépendance externe
  - Preuve : tests/test_kanban.py

- [x] TASK-052 [P1] [difficulté: compact]
  - Intitulé : Pont d'ingestion miroir vers Kanboard Neo
  - Reçu : kanban_to_jobs_payload, export_kanban_mirror, sync_kanban_mirror
  - Preuve : tests/test_kanban.py

- [x] TASK-053 [P0] [difficulté: compact]
  - Intitulé : Implémentation complète de l'Astral Resonance Director
  - Reçu : AstralDirector, DirectorCounters, DirectorMode, DirectorProposal
  - Preuve : tests/test_director.py

- [x] TASK-054 [P1] [difficulté: compact] [outil: webbrain]
  - Intitulé : Intégration adaptateur WebBrain MCP pour actions navigateur
  - Reçu : WebBrainClient, WebBrainCommand, WebBrainResult, build/parse MCP
  - Preuve : tests/test_webbrain.py

- [x] TASK-055 [P2] [difficulté: raisonnement]
  - Intitulé : World Model d'interface prédictif (JEPA-like action gate)
  - Reçu : StateVector, ActionDescriptor, JEPAActionGate, loop & anomaly pruning
  - Preuve : tests/test_world_model.py

- [x] TASK-056 [P2] [difficulté: compact]
  - Intitulé : Scénario d'intégration bout-en-bout (Director + Router + WebBrain + WorldModel)
  - Dépendances : TASK-055
  - Reçu : ContinuityPipeline, TimeBudget, reflex advisory, schema emit, no network
  - Preuve : tests/test_pipeline.py

- [x] TASK-057 [P3] [difficulté: compact]
  - Intitulé : Documentation synthétique dans docs/INTEGRATIONS.md
  - Dépendances : TASK-056
  - Reçu : couches Director / reflex / schema emit / WebBrain, ce qui reste hors scope

- [x] TASK-058 [P2] [difficulté: compact]
  - Intitulé : Calibration mesurée du reflex sur des tâches Parcimonia labellisées
  - Dépendances : TASK-056
  - Reçu : corpus fixture, HintReflexBackend, coverage/Brier, data_origin=fixture fail-closed
  - Preuve : tests/test_reflex_calibrate.py

- [x] TASK-063 [P1] [difficulté: compact]
  - Intitulé : Surface projet, rapport d'usage fin de tour, plan runtime ombre
  - Dépendances : TASK-056
  - Reçu : ProjectSurface, compare_usage, plan_runtime START/IDLE/STOP shadow
  - Preuve : tests/test_surface.py

- [x] TASK-059 [P3] [difficulté: compact]
  - Intitulé : Backend reflex local optionnel (sans téléchargement tant que non autorisé)
  - Dépendances : TASK-058
  - Reçu : probe_optional_local_backend, never download, available stays false
  - Preuve : tests/test_reflex_local.py

- [x] TASK-062 [P3] [difficulté: compact]
  - Intitulé : Capacité locale (VRAM / slots concurrents) dans ContinuationArbiter
  - Dépendances : TASK-056
  - Reçu : LocalCapacity, compact/MCP blocked, frontier still allowed, plan START withheld
  - Preuve : tests/test_continuation.py, tests/test_surface.py

- [x] TASK-064 [P2] [difficulté: compact]
  - Intitulé : Ingest rapport d'usage fin de tour (skills/tools/MCP) vers UsageEvent
  - Dépendances : TASK-063
  - Reçu : ingest_turn_report schema turn_usage, no UI scrape
  - Preuve : tests/test_surface.py

- [x] TASK-065 [P1] [difficulté: compact] [class: feature] [horizon: near]
  - Intitulé : Roadmaps classées sécu/bug d'abord, vues court/moyen/long, plan du jour avec report
  - Dépendances : TASK-051
  - Reçu : WorkClass/Severity/Horizon, plan_day, close_day, export_roadmap_views
  - Preuve : tests/test_roadmap.py

- [x] TASK-066 [P1] [difficulty: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitule : Buts ultimes humains pour l orchestration (buts.md)
  - Dependances : TASK-065
  - Recu : GoalSet, rank fail-closed, tag [goal:], plan_day goal_ranks
  - Preuve : tests/test_goals.py

- [x] TASK-067 [P1] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Route System-1 d'audit statique (rôles de fichier, règles nommées, score, store local)
  - Dépendances : TASK-065
  - Reçu : source_scan / source_role / pattern_rules / audit_score / audit_store / audit, vérificateur audit.recompute, entrée de manifeste sans coût inventé
  - Preuve : tests/test_source_scan.py, tests/test_source_role.py, tests/test_pattern_rules.py, tests/test_audit_score.py, tests/test_audit_store.py, tests/test_audit.py, examples/audit_suite.py
  - Notes : shadow only, aucun modèle appelé ; poids et seuils non calibrés, aucun routage gaté par ce score

- [x] TASK-070 [P2] [difficulté: compact] [class: feature] [horizon: near] [goal: GOAL-PARCIMONIA]
  - Intitulé : Corpus labellisé et harnais de calibration de l'audit statique
  - Dépendances : TASK-067
  - Reçu : audit_corpus.py (31 cas, rôles/bandes/règles attendus), audit_calibrate.py (défauts par règle, precision/recall, accord rôle/bande/règle), examples/audit_calibration.py
  - Preuve : tests/test_audit_calibrate.py ; 31 cas, accords 1.0, precision/recall 1.0 pour les 5 règles
  - Notes : provenance fixture ; threshold_authorized=false et impossible à forcer hors données mesurées ; les 3 faux positifs de développement ont des contrôles négatifs dédiés

## En cours

- [ ] TASK-060 [P3] [difficulté: compact] [class: feature] [horizon: near]
  - Intitulé : Round-trip WebBrain MCP réel en ASK only
  - Dépendances : TASK-054
  - Notes : observation-only, loopback, pas d'ACT

## À faire (Backlog)

- [ ] TASK-068 [P1] [difficulté: raisonnement] [class: feature] [horizon: near]
  - Intitulé : Calibration mesurée de l'audit statique sur fichiers réels (labels humains)
  - Dépendances : TASK-070
  - Notes : la partie corpus fixture est faite (TASK-070) ; il reste des labels humains sur du code réel ; snapshot data_origin mesuré seulement ; aucun seuil ne gate l'exécution avant ce snapshot

- [ ] TASK-069 [P2] [difficulté: raisonnement] [class: feature] [horizon: medium] [goal: GOAL-PARCIMONIA]
  - Intitulé : Route baseline modèle sur la même question (comparaison de coût honnête)
  - Dépendances : TASK-067, TASK-068
  - Notes : sans baseline mesurée, aucune économie n'est déclarable ; la comparaison se fait sur le vecteur de ressources, pas sur un score scalaire

- [ ] TASK-061 [P3] [difficulté: compact]
  - Intitulé : Sync live Kanboard Neo si KANBOARD_URL et AGENT_INGEST_TOKEN existent
  - Dépendances : TASK-052

- [ ] TASK-062 [P3] [difficulté: compact]
  - Intitulé : Capacité locale (VRAM / slots concurrents) dans ContinuationArbiter
  - Dépendances : TASK-056
