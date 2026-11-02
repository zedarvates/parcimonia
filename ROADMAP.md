# Parcimonia Roadmap

## Current checkpoint

An opt-in [diagnostic prototype](docs/FEASIBILITY_DIAGNOSTICS.md) now checks
Boolean contradictions, observed blockers and missing prerequisites, alongside
three advisory Python stability patterns. Next: independently labelled project
episodes, false-impossibility and false-alarm measurements, then resource and
temporal constraints. Natural-language extraction and other code languages
remain R&D; these checks do not activate a route or establish real-world quality.

The [perception and classification axis](docs/ASSET_PERCEPTION.md) combines
deterministic format/metadata observations, proposed tags and bounded catalogue
search across text, media, 3D, code and geographic data. It includes explicit
tag review, persistent catalogue snapshots, local OCR/PDF extraction, native
stream observations, GPX, a PLY body profile and explicit expectation audits.
Next: qualify extractor quality and local semantic models, then semantic indexing
and reviewable organization. Gaussian splatting is a provisional interpretation
of the received term; compatible PLY parameters remain representation candidates.

The v1 work is sequenced in [V1 gates](docs/V1_GATES.md): real outcomes and
provenance, deterministic verifiers, escalation budgets, route registry, cost
vector and benchmarks, then opt-in active mode. A later gate does not start
while its predecessor's exit criteria are unmet.

Implemented locally: observation-only proposals, finite confidence/cost validation,
configurable confidence threshold, estimated-cost ordering, deterministic tie
breaking, and abstention on ambiguous route identities or unsupported task
requirements. Replayable JSON observations now store the proposal, policy
version, bound evidence and comparison statuses, while keeping estimated and
measured values apart. See [the current routing policy](docs/SHADOW_ROUTING.md)
and [the observation format](docs/OBSERVATIONS.md).

Phase 0 remains incomplete. The next checkpoint is baseline capture: running a
real task through its baseline, recording model and capability versions, and
aggregating observations into a report. Synthetic tests and `caller_reported`
records do not establish real savings or model quality.

## Verified mission improvements — 2026-11-02

Track the verified-mission improvements under the existing `GOAL-PARCIMONIA`
in [kanban.md](kanban.md). This section is a view of that backlog, not a second
scheduler.

The first bounded increment is [observation review](docs/VERIFIED_OBSERVATIONS.md)
(TASK-113): bind current reports to the exact task, source, input and verifier;
retain missing, stale, negative and conflicting observations; propose the next
caller-declared probe. The same increment aligns explicit local-capacity
admission when VRAM is unknown. Implementation is prepared on
`feat/verified-observations-20261102`, with offline behavior and isolated stdio
checks. Real consumer and host qualification remain pending. A candidate local-plugin surface is
prepared separately from installed plugins; it grants no action permission.

| Order / task | Increment using existing components | Observable exit criterion |
| --- | --- | --- |
| 1 / TASK-113 | Observation freshness and identity checks, explicit capacity admission, advisory plugin tool | Offline behavior and real stdio discovery/call tests reject old or incompatible evidence, preserve later failure and tied conflicts, and never return action authorization |
| 2 / TASK-114 | Bind runtime and capability observations to the existing registry and resource-admission paths | An unavailable capability, stale machine snapshot or occupied reservation is reported before starting; two consumers cannot both claim one existing heavy-operation slot |
| 3 / TASK-115 | Qualify one complete consumer-owned reconnection scenario, with versioned client/server observations | A real interrupted session resumes play, or an explicit failure/unknown is retained; interruption and duplicate execution cases have replayable receipts |
| 4 / TASK-116 | Extend the feasibility and plan-verification contracts to dependent steps, durations and alternatives | A plan violating a hard temporal/resource constraint is rejected; feasible alternatives retain separate resource dimensions and caller preferences |
| 5 / TASK-117 | Connect transitions to existing versioned memory and replay | Reuse invalidates when a bound source, input, policy or verifier changes; delayed results and contradictions remain attributable |
| 6 / TASK-118 | Extract reusable procedure candidates and connect sourced rapprochements | A candidate beats its declared baseline on reserved cases without a quality regression; citations remain reviewable and negative results are kept |
| 7 / TASK-119 | Bridge local vision transport to typed decisions and a versioned region contract | Absent targets, invalid regions and uncertain inputs are handled explicitly on labelled examples; video extraction/tracking remains a separate qualification |

TASK-114 builds on TASK-113; TASK-115 uses the runtime observations from TASK-114.
Later work keeps the existing evidence gates. TASK-116 reuses TASK-094 rather
than replacing the planner; TASK-117 extends TASK-112; TASK-118 reuses the
controlled comparisons in TASK-109 and the existing draft PR #38 for sourced
rapprochements. No draft PR is assumed merged.

The first reconnection example is authored data, not an executed Ultimate Odycer
session. Runtime adapters, machine reservations, actual model quality, a learned
predictor and deployment remain separate evidence requirements. Record accepted
task outcomes, false successes, interventions, elapsed time and measured resource
use; a successful tool call or a matching report does not establish mission
completion or savings. Use [V1 gates](docs/V1_GATES.md),
[measurement records](docs/MEASUREMENT.md),
[deterministic verification](docs/VERIFICATION.md) and
[memory execution receipts](docs/MEMORY_EXECUTION.md).

## Phase 0 — Foundation and shadow routing
Goal: prove cheaper routes can be proposed without changing real execution.

Deliverables:
- common `Task`, `CandidateRoute`, `Decision`, `Evidence` and `Result` contracts
- stable capability IDs
- cost, latency, risk and confidence fields
- observation-only router
- telemetry schema
- replayable benchmark fixtures
- deterministic verifier
- baseline comparison against normal LLM execution

Exit criteria:
- no production route is modified
- every proposed route is reproducible
- estimated and measured cost remain separate
- reports include quality and evidence, not cost alone

## Phase 1 — Deterministic + cache + KNN
Goal: capture the cheapest reliable wins first.

Deliverables:
- deterministic rule engine adapter
- structured cache / proof reuse
- KNN case retrieval
- exact / semantic confidence
- abstention thresholding
- bounded escalation to baseline

Candidate tasks:
- parsing and formatting
- schema validation
- known API/CLI argument construction
- repeated CI-state interpretation
- exact calculations
- previously validated procedural cases

## Phase 2 — Nano-NN and micro-NN
Goal: use tiny specialized models only where they measurably outperform rules/KNN.

Initial roles:
- task classification
- route selection
- anomaly detection
- likely-next-operation prediction
- structured extraction
- confidence estimation

Required:
- versioned model manifests
- calibration
- benchmark gates
- cold-start/resource measurements
- safe fallback paths

## Phase 3 — Cost/risk-aware adaptive routing
Goal: select using capability, cost and consequence.

Deliverables:
- multi-objective route scoring
- privacy/locality constraints
- hardware-aware routing
- risk-class policies
- evidence-level requirements
- CapabilityAtlas integration
- explainable decision trace

Safety-critical boundaries remain deterministic policy.

## Phase 4 — Sub-task decomposition
Goal: avoid paying largest-model cost for an entire mission.

```text
mission
  -> deterministic subtasks
  -> KNN/cache subtasks
  -> nano/micro-NN subtasks
  -> small local LLM subtasks
  -> frontier-model subtasks only where needed
  -> deterministic verification/recomposition
```

Deliverables:
- typed sub-task DAG
- per-node route decisions
- partial escalation
- evidence propagation
- failure containment
- resumable execution

## Phase 5 — Learned reuse / compile expensive reasoning
Goal: turn repeatedly successful expensive patterns into cheaper reusable procedures.

Deliverables:
- route-history analysis
- workflow candidate extraction
- offline evaluation before promotion
- rollback/versioning
- proof of non-regression

No self-promotion to production without explicit policy gates.

## Phase 6 — Ecosystem integrations
- Botte Secrète
- ShardJEPA
- ChatGPT/OpenAI-compatible clients
- Qwen/local models
- Ollama / LocalAI
- MCP
- CLI
- protobuf capability registry
- hardware pools / multi-machine inference
- agent frameworks

## Phase 7 — Open-source hardening
- stable API
- plugin SDK
- reproducible benchmark suite
- reference adapters
- security model
- contributor docs
- release process
- compatibility matrix
