# Parcimonia Roadmap

## Current checkpoint

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
