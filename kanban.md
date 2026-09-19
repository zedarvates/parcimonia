# Parcimonia Kanban Backlog

Dernière mise à jour : 2026-09-19T15:00:00Z
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
  - Reçu : kanban_to_jobs_payload, export_kanban_mirror (tests/test_kanban.py)
  - Notes : Synchronisation asynchrone non-bloquante du kanban.md local vers l'API /api/jobs

- [x] TASK-053 [P0] [difficulté: compact]
  - Intitulé : Implémentation complète de l'Astral Resonance Director
  - Reçu : AstralDirector, DirectorCounters, DirectorMode, DirectorProposal
  - Preuve : tests/test_director.py (10/10 passés)

- [x] TASK-054 [P1] [difficulte: compact] [outil: webbrain]
  - Intitule : Integration adaptateur WebBrain MCP pour actions navigateur
  - Recu : WebBrainClient, WebBrainCommand, WebBrainAction, offline fallback
  - Preuve : tests/test_webbrain.py (3/3 passes)

## En cours

- [ ] TASK-055 [P2] [difficulte: raisonnement]
  - Intitule : World Model d'interface predictif (JEPA-like action gate)
  - Dependances : TASK-054
  - Notes : Evaluation latente de faisabilite d'action avant consommation de tokens


## À faire (Backlog)

