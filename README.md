![Parcimonia — Adaptive compute for AI agents. A mint-green route connects selected nodes within a dark network.](docs/assets/parcimonia-header.png)

# Parcimonia

[![tests](https://github.com/zedarvates/parcimonia/actions/workflows/tests.yml/badge.svg)](https://github.com/zedarvates/parcimonia/actions/workflows/tests.yml)

> An open-source adaptive compute router for AI agents, started under the working codename Tiberium AI.

Repository: https://github.com/zedarvates/parcimonia

Where the project stands, what was decided and what was learned — including the
negative results — lives in [the wiki](wiki/WIKI.md). Mechanism documentation stays
in [docs](docs/).

Parcimonia aims to reduce token, API, latency and local-compute costs by selecting the **least expensive mechanism that can satisfy the required confidence, evidence and safety constraints** for each task or sub-task.

It is not intended to be another general-purpose LLM. It sits between an agent/LLM and its execution mechanisms:

```text
Agent / LLM
    |
    v
Parcimonia Router
    |
    +-- deterministic rules / state machines / calculators
    +-- cache / proof reuse
    +-- KNN retrieval
    +-- nano-NN classifiers / routers
    +-- micro-NN specialized predictors
    +-- ShardJEPA-style predictive modules
    +-- small local LLM
    +-- large local or cloud LLM
    |
    v
Verifier -> Accept | Escalate
```

## Core principle

**Use the minimum amount of intelligence required for each fragment of work.**

Parcimonia's planned routing criteria include:
- expected token/API cost
- local compute and VRAM
- latency
- confidence
- historical success evidence
- task risk
- required proof level
- privacy / locality constraints
- available hardware and models

## V0: shadow mode only

The current router receives a task and caller-supplied candidates and returns
an observation-only proposal. It does not execute a route or replace a baseline.
Collecting real task observations and comparing proposals with actual execution
are the next steps; production routing must remain unchanged.

## Initial integrations

Planned adapters include:
- Botte Secrète / CapabilityAtlas
- OpenAI-compatible APIs
- Ollama and local LLM runtimes
- MCP and CLI tools
- KNN memory/retrieval
- nano-NN and micro-NN registries
- ShardJEPA experiments
- protobuf/ID based capability manifests

## Success metrics

Benchmarks track tokens, API cost, compute time, VRAM/RAM, latency, quality, unsafe false positives, abstention, escalation, model calls, evidence completeness and reproducibility.

## Status

Early design / bootstrap. No automatic routing is enabled.

V1 is organised as a sequence of evidence gates rather than a list of modules;
see [V1 gates](docs/V1_GATES.md) for the order, the exit criteria and the
explicit non-goals.

The first gate is implemented: `run_baseline` executes a **caller-supplied**
callable exactly once, measures wall clock through an injected clock, and writes
a `measurement/1` record carrying the method, environment and outcome. See
[Baseline measurements](docs/MEASUREMENT.md).

The second gate is implemented: a verifier registry binds every verdict to a
named and versioned verifier and to the hash of the verified input, abstains on
an unknown identity, and marks evidence built from it as schema version 2. See
[Deterministic verification](docs/VERIFICATION.md).

Both gates run end to end on a deterministic fixture corpus:

```powershell
python examples/fixture_suite.py --out runs/fixtures
```

The suite executes 20 local tasks twice, records 40 measured runs and 20
attributed observations, and includes one deliberate route failure. Fixture
results prove provenance and replay, not representative cost.

The third gate is implemented: an escalation policy decides between `ACCEPT`,
`RETRY`, `ESCALATE`, `ABSTAIN` and `FAIL_HARD` inside cumulative budgets, with a
loop guard, a fail-closed rule for unknown cost and a reason code on every
decision. See [Escalation policy](docs/ESCALATION.md).

The fourth gate is implemented: routes come from a versioned JSON manifest that
declares capabilities, estimates, task constraints and the verifier each route
requires, and the registry version is part of the recorded policy version. See
[Route registry](docs/REGISTRY.md).

The fifth gate is implemented: a resource vector keeps tokens,
latency, VRAM and energy apart from constraints, routes are compared on a Pareto
front instead of a weighted scalar, and a seeded benchmark splits cases into
development and held-out sets before any claim is allowed. See the
[benchmark plan](docs/BENCHMARKS.md).

The sixth gate is implemented: active mode refuses to start without a policy,
budgets, a sandbox and a kill switch; it requires a single-use human
authorization for any class outside the automatic set and an idempotency key per
execution, and it returns an audit trail linking the authorization, the attempts
and a replayable observation. See [Active mode](docs/ESCALATION.md).

The first System-1 route is implemented: a deterministic static audit that
classifies a file's structural role, runs named pattern rules, scores a deficit
from four ratio dimensions, and stores the verdict in a local, content-addressed
database. It needs no model, no network and no clock, and a second pass over the
same text reuses the stored verdict instead of recomputing it. Every verdict can
be recomputed by a named verifier before it is accepted as evidence. It is shadow
only, its weights are declared defaults rather than calibrated values, and it
claims no saving. See the [static audit](docs/STATIC_AUDIT.md).

An adapter boundary for typed-decision routes is implemented: an option set
wider than one call offers is either cut into balanced stages or scored option by
option before one explicit choice, one response is recorded with the provenance
that replays it offline, and the recomposed decision is verified by recomputation
instead of being trusted. A decision clock keeps a missed deadline and a stale
snapshot apart from decision quality. No model is called, the library provides no
transport of its own and no cost is claimed. See
[Typed-decision adapters](docs/DECISION_ADAPTER.md).

A prompt-signature predictor is implemented: it reads an input and names what that
input is about, the kind of task, the capabilities it needs, the fields worth
reading and which declared goal it serves. A keyword rule, a KNN over labelled
cases and a micro-NN sit behind one protocol, so the rule stays the baseline a
learner has to beat on the same corpus. The vocabulary is caller-declared,
abstention is a value rather than an exception, and strictness stays
caller-declared because a prompt is weak evidence for it. The candidates are
measured apart on an authored corpus, on a held-out public slice whose labels were
written by strangers, and on the prompts already on disk, which the ingest lane
turns into a content-addressed corpus revision without writing anything into this
repository. A public corpus can measure a mechanism and never opens the
authorization gate, and no accuracy is claimable while the labels are not
outcomes. See [Task signatures](docs/INTEGRATIONS.md).

The current `ShadowRouter` validates confidence and cost estimates, applies a
configurable confidence threshold (default `0.9`), and proposes the lowest known
estimated cost among eligible candidates. Equal costs use higher confidence,
then lexical route ID, so input order does not change the decision.

Unknown costs are never treated as zero. If all eligible costs are unknown,
the router uses confidence and explicitly reports that no cost comparison is
possible. Unsupported task requirements and ambiguous route IDs cause abstention.

Confidence is caller-declared and uncalibrated. Independent verification,
capability matching and real baseline comparisons remain roadmap work;
the prototype does not yet demonstrate cost savings.

See the [routing policy](docs/SHADOW_ROUTING.md) for exact rules and limitations.

## One command

```powershell
python examples/flagship.py
```

Six fragments of an ordinary development day, each one proposed or refused in
shadow mode with its reason, and nothing executed. See the
[flagship walkthrough](docs/FLAGSHIP.md).

## Local development

Requires Python 3.10 or newer. From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

The Python distribution and import name remain `tiberium-ai` and `tiberium_ai`
for compatibility with the bootstrap. Parcimonia is the repository and project
name; a package rename can be handled separately.

## Shadow observations

Each proposal can be stored as a replayable JSON observation that records the
task identity, candidate estimates, policy version, decision and any evidence
bound to the baseline and proposed routes. Replay re-runs the policy and rejects
a record whose stored decision no longer matches.

```python
from pathlib import Path

from tiberium_ai import (
    CandidateRoute, Evidence, Task,
    compare_observation, read_observation, record_observation, write_observation,
)

task = Task("format-001", "format", {"text": "example"})
record = record_observation(
    task,
    [
        CandidateRoute("baseline", ["model:baseline"], 1.0, 900, 0.99),
        CandidateRoute("rule", ["rule:format"], 0.01, 5, 0.95),
    ],
    baseline_route_id="baseline",
    cost_unit="USD per 1k tasks",
    data_origin="synthetic",
    baseline_evidence=Evidence("format-001", "baseline", True, 900, 1.0),
    proposal_evidence=Evidence("format-001", "rule", True, 5, 0.01),
)
Path("observations").mkdir(exist_ok=True)
write_observation("observations/format-001.json", record)
print(compare_observation(read_observation("observations/format-001.json"))["status"])
```

Estimated and measured costs stay in separate fields, and a missing measurement
is never replaced by an estimate. See the [observation format](docs/OBSERVATIONS.md)
for the stored fields, the comparison statuses and the privacy exclusions.
`write_observation` requires the target directory to exist and never overwrites
an existing file.

## Minimal example

These are synthetic estimates in a shared arbitrary cost unit, not benchmark
measurements. No model or tool is called.

```python
from tiberium_ai.contracts import CandidateRoute, Task
from tiberium_ai.router import ShadowRouter

task = Task("format-001", "format", {"text": "example"})
candidates = [
    CandidateRoute("baseline", ["model:baseline"], estimated_cost=1.0, confidence=0.99),
    CandidateRoute("rule", ["rule:format"], estimated_cost=0.01, confidence=0.95),
]
decision = ShadowRouter(min_confidence=0.9).propose(task, candidates)
print(decision.selected_route_id)  # rule
print(decision.mode)               # shadow
```

## License

Apache-2.0 for the software bootstrap. Model weights, datasets or third-party components may require separate licensing.

## Name / affiliation

Parcimonia started under the working codename "Tiberium AI", inspired by the Command & Conquer universe. This project is not affiliated with or endorsed by Electronic Arts. The header artwork uses an original abstract routing motif; see [visual identity notes](docs/BRANDING.md).
