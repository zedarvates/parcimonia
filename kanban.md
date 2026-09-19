# Parcimonia Kanban Backlog

Dernière mise à jour : 2026-09-19T15:30:00Z
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
  - Preuve : tests/test_continuation.py (10/10 passés)

- [x] TASK-051 [P1] [difficulté: compact]
  - Intitulé : Parser et ordonnanceur local-first kanban.md
  - Reçu : KanbanBoard, KanbanTask, dépendances DAG sans dépendance externe
  - Preuve : tests/test_kanban.py (4/4 passés)

- [x] TASK-052 [P1] [difficulté: compact]
  - Intitulé : Pont d'ingestion miroir vers Kanboard Neo
  - Reçu : kanban_to_jobs_payload, export_kanban_mirror, sync_kanban_mirror
  - Preuve : tests/test_kanban.py (8/8 passés)

- [x] TASK-053 [P0] [difficulté: compact]
  - Intitulé : Implémentation complète de l'Astral Resonance Director
  - Reçu : AstralDirector, DirectorCounters, DirectorMode, DirectorProposal
  - Preuve : tests/test_director.py (10/10 passés)

- [x] TASK-054 [P1] [difficulté: compact] [outil: webbrain]
  - Intitulé : Intégration adaptateur WebBrain MCP pour actions navigateur
  - Reçu : WebBrainClient, WebBrainCommand, WebBrainResult, build/parse MCP
  - Preuve : tests/test_webbrain.py (6/6 passés)

- [x] TASK-055 [P2] [difficulté: raisonnement]
  - Intitulé : World Model d'interface prédictif (JEPA-like action gate)
  - Reçu : StateVector, ActionDescriptor, JEPAActionGate, loop & anomaly pruning
  - Preuve : tests/test_world_model.py (6/6 passés)

## En cours

- [ ] TASK-056 [P2] [difficulté: compact]
  - Intitulé : Scénario d'intégration bout-en-bout (Director + Router + WebBrain + WorldModel)
  - Dépendances : TASK-055
  - Notes : Valide la décision de reprise complète avec tous les composants

## À faire (Backlog)

- [ ] TASK-057 [P3] [difficulté: compact]
  - Intitulé : Documentation synthétique dans docs/INTEGRATIONS.md
