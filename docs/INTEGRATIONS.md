# Integration Targets

## Botte Secrète
Mapping:
- CapabilityAtlas -> capability discovery
- capability consequences -> risk/cost inputs
- proof/evidence contracts -> verification requirements
- protobuf IDs -> stable capability references
- memory -> KNN/proof-reuse candidates

## ShardJEPA
Use as a specialized predictive candidate for robotics simulation, next-state prediction, likely action and anomaly/consequence prediction. Safety-critical constraints remain deterministic.

## Local LLM stack
Initial adapters:
- OpenAI-compatible APIs
- Ollama
- LocalAI

Model identity and quantization are execution evidence.

## MCP / CLI
Expose MCP servers and CLI commands as typed capabilities when possible.

## Multi-machine execution
Future route costs may include GPU availability, model residency, transfer overhead, machine health, queue latency and privacy locality.

## Layering (do not collapse)

```
kanban.md / optional Kanboard Neo mirror
  -> Astral Resonance Director (intent, phase, authorization)
  -> typed reflex (choice / score / noul, advisory unless calibrated)
  -> ContinuationArbiter (quota, difficulty, time budget, freeze)
  -> schema-constrained emit (act / confirm / refuse)
  -> JEPA-style action gate (prune loop / anomaly)
  -> effectors: RULE | LOCAL_SMALL | WEBBRAIN_MCP | FRONTIER
  -> deterministic verifier
  -> counters + local kanban update
```

Parcimonia owns mechanism, cost, evidence and abstention. The Director owns
intent and approval. Reflex classifies; it does not authorize. Schema emit
constrains a tool call; it does not browse. The world-model gate is a
heuristic energy check, not a trained JEPA. Silence is not approval.

## Typed reflex (System-1 pattern)

Closed-set questions over state, evaluated in parallel, with no generated
text. The three primitives are `choice` (unordered options), `score` (ordered
rubric) and `noul` (P(true); 0.5 is unsure, not medium). Types make a
malformed answer unrepresentable. They do not make a well-typed answer true.

Original module: `src/tiberium_ai/reflex.py`. No Laya or Jev code is vendored,
no weights are downloaded, no TypeSafe/OpenRouter call is made.

Fail-closed rules we keep:

- auto-act requires a *measured* calibration snapshot on this repo's task family
- coverage-at-threshold is the gate, not headline accuracy
- confidence is `None` when the backend is uncalibrated; `None` cannot auto-act
- choice cardinality is capped at 20 (two-stage scoring is not implemented)
- a latin-only backend must refuse non-latin state; a confident-wrong English
  checkpoint on Khmer is a known failure mode that confidence gating cannot catch

Prefer a local reflex backend if one is later attached. Treat a cloud System-1
API as optional and quota-bearing. Do not load Laya checkpoints without an
explicit gate.

Independent measurements of the public System-1 models disagree on calibration.
DAIR Emotion in particular shows that a peaked distribution can assign zero
probability to the true label. That is why this repo refuses to auto-act on an
unmeasured snapshot.

TASK-058 records fixture calibration in `reflex_calibrate.py` against authored
Parcimonia labels (`reflex_corpus.py`). The hinter is a deterministic keyword
backend. `data_origin=fixture` can populate coverage, accuracy and Brier, and
still cannot set `permits_auto_act`. Only `data_origin=labelled_outcomes` with
enough labelled rows, coverage and accuracy can authorize, and that corpus does
not exist yet.

## Schema-constrained emit (tiny tool-calling pattern)

A byte-level grammar compiled from a schema makes invalid JSON unrepresentable.
Empty `function_calls` is a refusal, never a guess. Optional fields with no
source span are omitted. Required fields with no span are withheld, not filled.
Confidence, when present, is `min(head, decode_probability)`. Fine-tunes that
do not update the head report `None`.

Bands: act at/above 0.7, confirm below that or when uncalibrated, refuse when
there is nothing well-formed to do. Original module: `src/tiberium_ai/schema_emit.py`.
Needle 3 weights are not downloaded.

Tool design rules we adapt rather than copy: one tool per action, constraints
in the schema not in prose, enums for closed sets, grounding against the source
span. A valid call can still be ungrounded.

## WebBrain MCP

Adapter only (`src/tiberium_ai/webbrain.py`). The extension is GPL-3.0 and is
not vendored. ASK is the default. ACT/DEV on high or critical risk is forbidden
without prior authorization. A built request is not a round-trip.

## What this combination still does not own

- live Kanboard Neo ingest (needs `KANBOARD_URL` plus `AGENT_INGEST_TOKEN`)
- live WebBrain MCP round-trip
- VRAM / local concurrency slots
- operator attention budget (how many confirm bands before freeze)
- interruptibility and pause/resume of a delivered step
- two-stage scoring for >20 options
- labelled outcomes for reflex calibration on Parcimonia tasks
- predictor training (explicit v1 non-goal)
- reset-proximity of a quota window as a first-class signal (percent remaining
  is used; seconds-to-reset is stored but not yet a freeze rule)

A later gate may add those. None of them is implied by a green unit test.

## Project surface, usage reports, runtime plan

An agent turn is not trusted to have used the right tools. The project declares
a surface (skills, plugins, MCP, local tools, KNN / nano / micro / rule routes,
and servers). Each task has an expectation: required, allowed, forbidden.
At the end of the turn, caller-reported usage is compared to that profile:
missing required capabilities are drift; anything outside the allowlist or on
the forbidden list is a violation. Empty usage is not compliance.

The same profile yields a *shadow* runtime plan: START required stopped
processes, KEEP what is already running and needed, IDLE keep-warm unused
models, STOP unused costly servers. The plan never executes. Forbidden MCP or
tools are not started even if the agent just used them; that use is a
violation to report, not an authorization to keep the process up.

This is the control plane for “did this LLM actually use the skill / KNN /
nano path the project expected”, including studio-style local tools. It does
not replace G6 authorization and does not launch Asset Factory, WebBrain, or
any other binary.

A structured `turn_usage` report (`ingest_turn_report`) is the only ingest path:
skills, tools, MCP, plugins, routes and servers, with exact keys. No chat scrape.
`LocalCapacity` (slots + optional VRAM) withholds START and prefers STOP of unused
local/MCP processes when the machine is full. Deterministic rules and frontier
cloud routes still run. Optional local reflex weights are probed without download;
`available` stays false until a later authorized loader exists.

## Roadmaps, horizons, daily carry

Do not keep three editable backlogs. `kanban.md` is the only source of truth.
Tags `[class: security|bug|feature]`, `[severity: critical|high]`, `[horizon: near|mid|far]`
drive scheduling. Security and bugs at critical/high outrank features, including a
P0 dashboard. In-progress work still beats a same-class TODO.

`plan_day` builds a WIP-limited slice. Unfinished selected items are carried to
the next day (`close_day`); a new critical defect can displace a carried feature,
not a carried security/bug. Far-horizon items stay out of today while hot defects
wait. `export_roadmap_views` writes `roadmap-near.md`, `roadmap-mid.md`,
`roadmap-far.md` and an optional `daily-YYYY-MM-DD.md` as generated projections
with a do-not-edit header.

## Buts ultimes

Orchestration without a destination is kanban gravity. `buts.md` is human-authored.
The agent does not invent missions. Active goals have unique ranks (1 = first).
Parked or unknown ids never become rank 1. Safety-critical cards still outrank
goals. Among ordinary work, a weaker P attached to a higher goal beats a shiny
unlinked P0. Kanban tag: `[goal: GOAL-ID]`. Constraints on a goal (local-first,
no-private-publish) travel with the cards that point to it.
