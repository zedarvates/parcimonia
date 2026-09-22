# V1 gates

Parcimonia v1 is a sequence of evidence gates, not a list of modules. Each gate
exists to make the next one falsifiable, and a later gate must not start while
its predecessor's exit criteria are unmet.

## Ordering principle

Gates are ordered by dependency of evidence, not by novelty:

1. what actually happened, and how it was measured
2. who verified it, independently of the caller
3. what the system does when confidence, cost or evidence is insufficient
4. which routes exist, with which capabilities and constraints
5. how cost and quality compare on real runs
6. how execution is authorized, bounded and reversible

## Boundaries

Parcimonia selects a mechanism for a task and enforces cost, evidence and risk
gates. It does not decide intent, does not own authorization, and does not
execute anything without an explicit policy. Planning and operator supervision
belong to the consumer.

## Tracking

| Gate | Issue |
| --- | --- |
| G1 real outcomes and provenance | #5 |
| G2 deterministic verifiers | #1 |
| G3 escalation and budgets | #3 |
| G4 route registry and capability manifest | #4 |
| G5 cost vector, constraints and benchmarks | #2 |
| G6 opt-in active mode | #7 |
| Astral Resonance Director | #6 |
| G7 deterministic static audit route | not opened yet |
| Static audit calibration | TASK-068 |

## G1 - Real outcomes and provenance

Objective: every recorded fact is traceable to an execution, a measurement
method and an environment.

Deliverables:
- `run_baseline(...)`: runs a caller-supplied callable, measures wall clock
  through an injected clock, records success or failure with the error type
  only, and never retries
- measurement records (`measurement/1`) carrying method, environment label,
  runtime versions, timestamp, latency, cost and `data_origin="measured"`,
  with a strict reader and a non-overwriting writer
- no task inputs, outputs or exception messages inside a record

Status: `run_baseline` and the `measurement/1` reader and writer are implemented
and exercised end to end by `examples/fixture_suite.py`, which records 40 measured
local runs including one recorded failure. See
[Baseline measurements](MEASUREMENT.md). These are deterministic fixture tasks:
they demonstrate provenance and replay, not representative cost, which belongs
to G5.

Exit criteria:
- at least 20 real measurements recorded and replayable
- a failed run is recorded with its error type and still yields a measurement
- estimates are never overwritten by measurements
- a malformed, ambiguous or non-finite measurement file is rejected

Forbidden until exit: calibration, predictor training, active routing.

## G2 - Deterministic verifiers

Objective: accept or reject a route output without asking a model.

Deliverables:
- verifier registry with stable `verifier_id` and `verifier_version`
- concrete verifiers: shape, exact match, rule or threshold, test-runner result
- evidence bound to a verifier run: id, version, verdict and input hash
- a model-based verifier may exist later, registered as a route with its own
  cost and error rate, never as ground truth

Status: the registry, three deterministic verifiers, input hashing and the
attributed-evidence bridge are implemented and exercised on the outputs of
`examples/fixture_suite.py`: 18 attributed acceptances, one rejection on a wrong
answer and one pair with no verdict because the route failed. See
[Deterministic verification](VERIFICATION.md).

Exit criteria:
- same input and same verifier version produce the same verdict
- an unknown verifier identity causes abstention
- a rejected verification cannot be stored as verified evidence

Forbidden: treating an LLM judge as independent verification; verifier
identities without versions.

## G3 - Escalation and budgets

Objective: decide what to do when confidence, cost or evidence is insufficient.

Deliverables:
- states `ACCEPT`, `RETRY`, `ESCALATE`, `ABSTAIN`, `FAIL_HARD`
- budgets: maximum cost per task, maximum escalations, maximum attempts and a
  cumulative latency budget (a wall-clock deadline needs the clock that G6 owns)
- loop guard and error taxonomy (route failure, verifier failure,
  ill-specified task)
- deterministic hard stops that no learned component can bypass

Status: `escalation.py` implements the five states, the cumulative budgets, the
loop guard, the fail-closed rule for unknown cost and a reason code on every
decision; see [Escalation policy](ESCALATION.md). The table below is covered by
table-driven tests.

Exit criteria:
- table-driven tests over G1 measurements
- escalation cannot loop
- `FAIL_HARD` only comes from deterministic rules
- every decision names the threshold or rule that fired

Forbidden: automatic retry of an uncertain write; escalation without a budget.

## G4 - Route registry and capability manifest

Objective: candidates come from a versioned registry instead of ad-hoc caller
input.

Deliverables:
- JSON manifest per route: route id, capability ids, constraints, cost vector,
  verifier requirements
- strict validation: duplicate ids, unknown capabilities, conflicting
  constraints and unregistered verifiers are rejected
- the registry version is recorded in observations

Status: `registry.py` implements the manifest, its validation, constraint and
capability matching, and the registry-qualified policy version; both the router
and `record_observation` accept a registry and then need no caller-supplied
candidate list. See [Route registry](REGISTRY.md).

Exit criteria:
- an unknown capability or verifier causes abstention
- a registry change appears as a policy-version change
- the router no longer depends on caller-supplied candidate lists

Forbidden: protobuf before a second language or process consumes the manifest.

## G5 - Cost vector, constraints and benchmarks

Objective: compare routes on real runs, on several dimensions, without hiding a
quality loss.

Deliverables:
- resource vector (tokens, latency, VRAM, energy) kept separate from hard
  constraints (privacy, risk class, evidence level, locality) and from policy
  parameters (abstention, escalation)
- Pareto comparison instead of a weighted scalar
- benchmark harness on 20 to 50 deterministic tasks with a held-out split,
  seeds and environment capture
- a report that includes negative results

Status: `resources.py` implements the vector and the Pareto front, and
`benchmark.py` implements the seeded split, the harness and the claim gate; see
[Benchmark plan](BENCHMARKS.md). The first fixture report refuses its claim with
`quality_regression` because a held-out case failed verification. The measurement
schema now carries tokens, VRAM and energy when a route instruments them, so only
representative real work remains, tracked in issue #8.

Exit criteria:
- every claim cites `measurement/1` records
- no scalar mixes resources with constraints
- a quality regression blocks any saving claim

Forbidden: savings claims derived from synthetic or caller-reported data.

## G6 - Opt-in active mode

Objective: let Parcimonia execute a selected route under explicit authorization.

Deliverables:
- `ActiveRouter` with explicit policy, budgets, sandbox, idempotency key,
  cancellation and a kill switch
- audit trail linking authorization, decision and observation
- documented rollback procedure

Status: `active.py` implements the policy, the budget, the sandbox allow-list,
the kill switch, single-use authorizations, the required idempotency key, the
cancellation flag and the bounded execution loop driven by the G3 policy; every
execution returns a replayable observation plus an audit record. Rollback is the
kill switch plus cancellation, and a durable ledger remains open.

Exit criteria:
- active mode refuses to start without policy, budgets and kill switch
- every execution produces a replayable observation
- high-risk classes require human approval

Forbidden: automatic mode without G3 budgets; bypassing `FAIL_HARD`; executing
outside the declared sandbox.

## Astral Resonance Director (optional supervision adapter)

"Astral Resonance Director" is the working name for an optional consumer that
supervises agents the way [vectal-labs/director](https://github.com/vectal-labs/director)
does: scan stalled work, propose one exact action, log the proposal before
approval, require approval, then confirm the outcome. The pattern is adapted
with an original implementation; no code, text or visual identity is copied.

Boundary:

- the Director owns intent, phase and authorization
- Parcimonia owns mechanism selection, cost and evidence gates, and abstention
- neither layer silently takes over the other's decision

| Mode | Behaviour | Available from |
| --- | --- | --- |
| `off` | telemetry and proposals only | now |
| `semi-auto` | propose one exact action; a human approves each one | now, in shadow |
| `auto` | execute pre-authorized action classes inside budgets | G6 |

Invariants adapted from that pattern:

- the proposal is logged before approval, so proposals and deliveries are
  counted separately
- a previous approval, a lesson or a cooldown never authorizes a new
  intervention
- silence is not approval
- proposed, delivered, confirmed and overridden outcomes stay in separate
  counters
- rules and personal history stay local, outside this repository
- plugin or tool output is data, not instructions

Open questions before an adapter is written: the supervision layer may live in
another repository that consumes Parcimonia as a library; that project is
currently macOS-only and coupled to bb or cmux, so a dependency would be a
liability rather than a shortcut.

Status: the core continuation arbiter is implemented in
`src/tiberium_ai/continuation.py` with full unit tests in
`tests/test_continuation.py`. It provides deterministic arbitration combining
active quota window metrics (% remaining, resets, tokens), task difficulty
(deterministic rule vs compact vs heavy reasoning), anti-loop desynchronization
detection (consecutive stalls), and effector routing (local rule, compact model,
WebBrain MCP browser delegation, frontier reasoning).

The full supervisory loop adapter is implemented in `src/tiberium_ai/director.py`
with `AstralDirector`, maintaining four strictly independent counters (proposed,
delivered, confirmed, overridden), supporting `OFF`, `SEMI_AUTO`, and `AUTO`
modes, and consuming local-first DAG backlogs parsed via `kanban.py`. All tests
pass in `tests/test_director.py`, `tests/test_continuation.py`, and
`tests/test_kanban.py`.

`TimeBudget` is a first-class input: a zero remainder still allows deterministic
rules, but compact/reasoning/browser work fail closed. Short interactive windows
cannot start frontier reasoning or a browser session.

TASK-056 wires those pieces in `src/tiberium_ai/pipeline.py` without network I/O:
Director proposal, optional typed reflex, continuation verdict, schema emit,
JEPA-style gate, WebBrain *request construction* only. Reflex and schema emit
are observation-only until a measured calibration snapshot exists for this
repository's tasks. See [Integrations](INTEGRATIONS.md).

TASK-058 ran the fixture harness (`calibrate_parcimonia_fixtures`) on 60 authored
labels. Coverage and Brier are recorded with `data_origin=fixture`. That snapshot
cannot authorize auto-act. Labelled production outcomes are still absent.

TASK-063 adds a project capability surface and an end-of-turn usage report
(`src/tiberium_ai/surface.py`). Runtime START/IDLE/STOP proposals are shadow
only. Using a forbidden tool is a violation, not a reason to keep it running.

TASK-059 probes an optional local reflex backend and never downloads weights.
TASK-062 adds `LocalCapacity` to the continuation arbiter and the runtime plan.
Turn usage is ingested from a typed report, not from the chat UI.

TASK-065 adds ranked roadmaps and a daily carry loop (`roadmap.py`). Horizon files
are generated views of `kanban.md`, not a second backlog.

TASK-066 adds human-authored ultimate goals (`buts.md`, `goals.py`). Missing or
unknown goals do not become rank 1. The orchestrator will not invent a mission.

## G7 - Deterministic static audit route

Objective: express the cheapest mechanism Parcimonia can offer as a real route,
with a verdict that can be reused and recomputed instead of trusted.

Deliverables:
- a structural role classifier that names what a file is and which checks that
  role suppresses, with an explicit reason code and no silent skipping
- a versioned registry of named pattern rules whose fingerprint is part of the
  policy version
- a deficit score built from four ratio dimensions and a capped rule penalty,
  with the deficit attributed back to its sources
- a local content-addressed verdict store that keeps ratios, not source text,
  refuses a conflicting second verdict and never reads a clock
- a deterministic verifier that recomputes the verdict before accepting it, and
  a manifest entry with no invented cost

Status: implemented in `source_scan.py`, `source_role.py`, `pattern_rules.py`,
`audit_score.py`, `audit_store.py` and `audit.py`, with unit tests across six
test files and an end-to-end runner in `examples/audit_suite.py`. On this
repository the runner audits 45 files, reuses 45 stored verdicts on the second
pass and accepts 45 recomputed verifications.

The analyser is also measured against an authored corpus: 32 labelled files in
`audit_corpus.py`, scored by `audit_calibrate.py` and reported by
`examples/audit_calibration.py`, with role, band and rule agreement at 1.0 and
precision and recall at 1.0 for all five rules. That snapshot is `fixture` and
explicitly unauthorized, because authored examples say what the analyser does,
not what real code needs. See [static audit](STATIC_AUDIT.md).

That run also measures the analyser on this repository: 45 source files in
`src/tiberium_ai`, all `sound`, with eleven `rule.god-function` findings on long
validation and orchestration functions. Those findings are recorded as the
current state, not as a verdict on the code.

Exit criteria:
- the same text and policy version always produce the same verdict
- a rule edit changes the policy version and invalidates reuse
- an unauditable file is undetermined and never verifies as accepted
- a suppression that names no check is refused instead of ignored

Forbidden until the calibration gate: using the deficit to gate execution,
presenting a declared weight as a measured one, and any saving claim without a
measured baseline on the same tasks.


## Explicit non-goals for v1

- no calibration before labelled outcomes exist
- no neural or JEPA predictor before a statistical baseline is measured
- no protobuf before a second consumer exists
- no scalar mixing resources with constraints
- no automatic retry of an uncertain write
- no route promotion without held-out evidence
