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
- choice cardinality is capped at 20 in one question; a wider closed set is cut
  into stages by `decision_adapter.py` rather than sent as one wide call
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

## Typed-decision adapter (wide option sets, replay, decision clock)

`src/tiberium_ai/decision_adapter.py` turns the reflex contract into a route
boundary. An option set wider than 20 options is cut into balanced groups, each
group becomes a question the reflex contract accepts, and the answers are
recomposed deterministically. A missing stage answer is an abstention, never a
zero score or a default option. The recomposed winner is verified by
recomputation under `decision.two_stage` version 1 instead of being trusted.

One response is stored as a record carrying the backend id and version, the
request fingerprint, the origin and the usage, and replayed offline. The library
injects the transport and performs no network I/O, so its absence is a typed
`unavailable` capture. That injection point is the only piece a real call needs,
which is what makes one authorized call convertible into a committed fixture.

`src/tiberium_ai/decision_clock.py` keeps three outcomes apart: within budget,
missed deadline, and stale state. Staleness is judged first, an unobserved age
against a declared bound fails closed, and the fallback route is declared on the
budget rather than chosen after the fact.

The scored variant scores every option with its own boolean question and then
asks one explicit choice over the top finalists, so a score stays comparable
across batches. A scored decision is two requests, and a batching transport
needs two round trips whether the option set holds 28 options or 255.

Three verifiers are registered: recomposition for each composition, and schema
conformance of a recorded response against the request it answers. Conformance
is not correctness, so a well-typed answer can still be the wrong answer.

One response can be written to and read from a self-describing JSON file, which
is the mechanical step that turns one authorized call into a committed fixture.

No model, no weights, no network and no cost claim. See
[Typed-decision adapters](DECISION_ADAPTER.md).

## WebBrain MCP

Adapter only (`src/tiberium_ai/webbrain.py`). The extension is GPL-3.0 and is
not vendored. ASK is the default. ACT/DEV on high or critical risk is forbidden
without prior authorization. A built request is not a round-trip.

## Task signatures (what an input is about)

`src/tiberium_ai/task_signature.py` predicts the descriptor a route is chosen
from: the task kind, the capabilities it needs, the fields worth reading and the
declared goal it serves. Today that descriptor is entirely caller-declared; this
is the first thing that reads the input.

The predictor is a reflex backend and nothing else, so a keyword rule, a KNN over
labelled cases and a micro-NN are interchangeable behind one protocol, and the
rule stays the baseline a learner has to beat on the same corpus. The vocabulary
is declared by the caller: a predicted goal is one of the declared ids or the
reserved none option, because a predictor that could only name a declared goal
would be forced to invent a mission.

Abstention is a value, not an exception. Nothing matching a choice question
produces a uniform distribution, which the threshold turns into an abstention;
two items matching split the mass and abstain too, because the input is
ambiguous. Risk class, evidence level and locality are deliberately not
predicted: a prompt is weak evidence for strictness and the direction of that
error is unsafe, so they stay caller-declared.

The calibration harness reports coverage and agreement separately, and a snapshot
can only be constructed as authorized when it came from labelled outcomes, so a
perfect fixture run cannot be promoted by editing a field.

An authored corpus (`signature_corpus.py`) exists, split into an aligned half
written in the hint vocabulary and a paraphrase half written in other words,
including French. The split is itself the finding: the keyword rule scores
perfectly on its own vocabulary, and on the paraphrases it is willing to answer
it names the wrong kind every time. Aggregating both halves reports a flattering
agreement and hides that, which is why the two populations are measured apart.

Provenance is carried per case: where the situations came from, and who produced
the labels. A report can only be authorized when the situations were captured and
the labels are outcomes, and it refuses when the labeller is its own predictor,
because agreement with one's own labels is not agreement with the task. A model
labelled corpus over real situations is the distillation shape and still lands as
a fixture until the labels come from outcomes.

Two candidate backends now sit behind that same contract
(`signature_backends.py`) and are measured on the same bench. A verb-frame
backend reads the head verb, the span after it and the prepositional spans, and
weights a declared hint by the span it lands in. A retrieval backend averages the
recorded answers of the nearest labelled inputs by token overlap.

Off distribution the frame triples coverage, from 0.25 to 0.75, and earns a kind
the lexical rule never earns, from 0.0 to 0.667 agreement. The span weighting also
removes the invented field the rule produced from the preposition before. It does
not buy the vocabulary: field recall stays 0.0 on the French paraphrases, because
the declared hints are still English, which is exactly what an artefact step
exists to close. The three remaining disagreements are labels of our own that are
themselves debatable, which is the second thing an authored corpus cannot settle.

The retrieval candidate is exact on the half it memorised and nearly mute on the
other: agreement 1.0 at coverage 0.583, then coverage 0.167. An exact self-match
is even diluted below the threshold by two neighbours that share only the topic
words. That is the metric's fault rather than the strategy's, and the fix is
already visible: feed the retrieval backend the frame's spans instead of raw
tokens.

A public lane (`public_corpus.py` and `examples/public_lane.py`) measures the
same three candidates on a slice of Dolly-15k, whose categories were attributed
by people who are not us, with 100 labelled instructions held out from 300
evaluated ones. It reversed the authored bench. Coverage is 0.737 for the keyword
rule, 0.223 for the verb frame and 0.277 for retrieval, because 172 of the 300
public instructions are questions and a verb-driven frame has no head verb to read
in a question. Retrieval wins on quality instead, with kind agreement 0.723 and
field precision and recall of 0.6 and 0.562, which is what a labelled
in-distribution seed buys: the field that marks an attached text is far better
reached by similarity to labelled cases than by any keyword.

That seed is exactly what does not exist on real work yet, and the public lane
authorizes nothing: every case carries the public origin, so a corpus written by
strangers can measure a mechanism and can never open the gate.

The interrogative signal was then added and measured on a slice the protocol had
never read, with the same candidate minus the signal as the control arm. The
pre-registered prediction held on its stated target: on the answer class the
frame went from 0.105 to 0.850 coverage, above the keyword rule's 0.800, at
0.953 accuracy against the rule's 0.963. Overall coverage went from 0.268 to
0.825, which puts the frame above the rule's 0.750, while overall kind agreement
stayed slightly below it (0.609 against 0.630).

The cost is measured too, and it is the next problem: the fallback fires on
questions whose category is not an answer question, so brainstorm asks phrased as
questions moved to answer 23 times instead of 3, and generation asks 15 instead
of 3. Field recall fell from 0.114 to 0.049 for the same reason. A question
marker cannot tell a question about a fact from a question asking for ideas, so
the candidate that follows is a specificity tie-break: a specific declared hint
beats a generic question marker. It must be measured on the next unread slice,
because this one is now known.

One caution the two slices make concrete: the keyword rule scored 0.737 and 0.715
on the first slice and 0.750 and 0.630 on the second, so a few points of
difference between two candidates are within slice noise and must not be read as
a ranking.

The specificity tie-break was then added as a third frame arm and measured on a
third unread slice. The pre-registered prediction failed: it earned nothing on
the classes it was written for. Brainstorm asks stayed at nought correct out of
thirty-seven answered in both arms, generation stayed at nine of seventeen, and
the answer class lost seven correct predictions, moving overall agreement from
0.638 to 0.618. The diagnosis is that the tie-break is inert rather than wrong:
it can only act on a matching hint, and almost no brainstorm instruction of the
slice contains one, so the bottleneck is the declared vocabulary of that class,
not the marker. The arm is switched off by default because it is unproven, and it
stays available so the experiment remains reproducible.

What replicates across the three slices is the part worth keeping: the signal of
the previous step held at 0.825 then 0.850 coverage, the keyword rule stayed
between 0.75 and 0.79, and the retrieval backend stayed the most accurate at
0.723, 0.750 and 0.734 kind agreement with field precision and recall near 0.69.
One class of six, brainstorm, is unreachable by any candidate so far, which is a
defect of the declared vocabulary rather than of any mechanism.

The retrieval candidate was then measured against nested memory sizes on a fourth
unread slice, with the rule and the frame on the same cases as references:

| memory | coverage | kind agreement | field precision | field recall |
| --- | --- | --- | --- | --- |
| 0 (keyword rule) | 0.730 | 0.709 | 0.385 | 0.122 |
| 0 (verb frame) | 0.833 | 0.649 | 0.250 | 0.060 |
| 25 | 0.155 | 0.694 | 0.462 | 0.545 |
| 50 | 0.237 | 0.621 | 0.500 | 0.625 |
| 100 | 0.302 | 0.686 | 0.588 | 0.645 |
| 200 | 0.355 | 0.725 | 0.629 | 0.629 |

The pre-registered prediction is half confirmed, and the half that failed is the
useful one. Coverage rises with clear diminishing increments, but agreement is
not monotone: it dips from 0.694 at 25 memories to 0.621 at 50 before climbing
again, so small memory answers a narrow, easy subset well and then takes on
harder cases before it has enough neighbours to disambiguate them. Retrieval only
clears the alternatives on the act at 200 memories, where agreement reaches 0.725
against the rule's 0.709.

Three readings matter more than the table. First, the field signal is already
five times better than the keyword rule at 25 memories, so a few dozen labelled
cases buy the field. Second, retrieval stays a precision instrument and never a
coverage one: it answers about a third of the cases and is the most accurate on
them, while the rule and the frame answer seven or eight in ten and are less
accurate. Third, nothing here has plateaued: both coverage and agreement are
still rising at 200, so this says where retrieval starts to win, not where it
stops improving.

The layered route was then measured on a fifth unread slice, with the floor set
to the 0.9 the schema already uses, so that no new knob was tuned. Half of the
pre-registered prediction held. Coverage reached 0.820 against the 0.80 announced
and above the rule's 0.750. Field precision reached 0.822, which is retrieval
grade and slightly above the pure retrieval candidate's 0.795, with field recall
at 0.327 against the rule's 0.118. Act agreement did not hold: 0.689 against the
0.70 announced, at parity with the rule's 0.690 and below the pure retrieval's
0.782.

The reason is measurable rather than mysterious. The layer decides per question,
and the primary is certain of an act less often than it is willing to answer one,
so the act comes from the fallback in most cases and the blend inherits the
fallback's accuracy there. What retrieval knows best is the field, not the act,
which points at the next candidate: the floor should not be one number for every
question, and the primary deserves to be trusted lower for fields than for acts.
That must be measured on a later unread slice, because this one is now known.

## Prompt ingestion and corpus revisions

`signature_ingest.py` reads the rollout stores already on disk, turns them into a
corpus revision, and `examples/prompt_ingest.py` drives it. A revision is
identified by its content rather than by its date: two runs over unchanged inputs
produce the same identifier, which is what lets a measurement cite exactly the
corpus it read. The store is discovered generically under the current home, the
configuration is the caller's, and nothing is written into this repository.

The first run over 824 rollout files took 41 seconds and produced 2338 distinct
prompts from 7657 user messages. It stripped assistant-injected text from 1460 of
them and redacted 6863 matches of credential and address patterns, and the second
run reported a delta of zero with the same identifier, so the update path is
idempotent.

Two numbers correct earlier work. Only 83 of the 135 prompts of the hand-extracted
corpus survive verbatim here, so 38 per cent of that corpus was not what the person
had typed; the ingest strips the surrounding harness text by construction, which
the hand extraction had not. And three entries alone, of nine, fifteen and three
characters, account for 3928 of the 7657 messages, so about half of the real
message volume carries no ask at all. The predictor concerns the other half, and
the continuation family belongs to the arbiter that already exists.

### What the real corpus says about the next three ideas

`signature_taxonomy.py` reads a revision and answers three questions by counting.
On the first real revision, of 2338 distinct prompts and 7657 messages:

* **asks are 45 per cent of the volume.** Four distinct texts, all whole-text
  continuations, already account for 3561 messages, and 143 distinct texts account
  for 4220. The other 3437 messages carry an ask.
* **several pieces of work in one input is an upper bound of 8.7 per cent of the
  volume**, counting two distinct actions or two connectives as a candidate. It is
  an over-estimate, so decomposition would bite on less than a tenth of the traffic.
  That is the precondition measured before that work is worth starting.
* **45.8 per cent of ask volume contains no action any declared vocabulary
  reaches.** But that number is an upper bound on unknown vocabulary and a lower
  bound on incomplete cleaning: the hint proposal surfaced residual harness text
  as high-weight candidates for unrelated actions, with instructions in asks
  carrying 797 messages, the not-installed notice 665, the untrusted-data notice
  478, and treat 587.

The third reading is a defect of this repository, not of the corpus. Deriving a
taxonomy from a corpus that still contains boilerplate would declare boilerplate
as vocabulary, which is precisely what the proposal showed by proposing it.

### Which layer owns a family

A continuation is not a task, and the two layers that could receive it are
distinct. `continuation.py` holds the decision: it arbitrates from quota, task
difficulty, wall clock, stalls and local capacity, and returns an action among
CONTINUE, FREEZE_QUOTA, REQUIRE_HUMAN and ESCALATE_ROUTE with a target route among
rule, local_small, webbrain_mcp and frontier. `director.py` holds the supervision
around it: it proposes one exact action, logs the proposal before any approval,
keeps proposed, delivered, confirmed and overridden in four separate counters, and
refuses to let a previous approval authorize a new intervention. `pipeline.py`
already wires the chain end to end without network access.

`responsible_layer` records the boundary in code: a continuation belongs to the
director and needs state, never a signature or a verifier, because there is no ask
in the text to verify. This is a boundary rather than a router, so that neither
layer silently takes over the other's decision.

Feeding the arbiter a real quota snapshot shows what that boundary is worth. With
the weekly window at zero per cent, a deterministic task still continues through
a local rule at zero token cost even with no wall clock left, a compact task is
downgraded to a local model at a thousand tokens, heavy reasoning is frozen, and a
non-deterministic step with no wall clock left asks for a human. The same snapshot
say the corpus: about 55 per cent of real message volume is that continuation
family, so the director is not a nicety, it is the majority path.

### What the cleaning pass changed

The hint proposal had been pointing at its own residue, so the harness rules were
extended: objective blocks, in-app browser context, recommended plugins, apps
instructions, referenced-conversation sections, replayed transcript tails, and the
notices that surround them. Two new revisions followed, one removing 539 entries
that were nothing but harness text, and the next removing 76 more.

Three numbers moved and two of them were wrong before. The redaction counter fell
from 6863 to 206, so the earlier figure was carried by harness text rather than by
the person's own words. The share of ask volume that no declared vocabulary
reaches rose from 45.8 to 72.8 per cent, because the harness had been supplying
false verbs that inflated coverage. And the proposed vocabulary changed nature
entirely: it used to be function words and notices, and it is now domain and
environment terms such as codex, session, thread, worktree, commit, zig, token,
delegation, brief and projet.

Passing the criterion is not the same as having a good vocabulary. The proposal
still mixes three populations, real domain terms, environment tokens such as a
plugin name or a year, and generic adjectives. That triage was always a human
ratification step, and it remains one.

## What this combination still does not own

- live Kanboard Neo ingest (needs `KANBOARD_URL` plus `AGENT_INGEST_TOKEN`)
- live WebBrain MCP round-trip
- VRAM / local concurrency slots
- operator attention budget (how many confirm bands before freeze)
- interruptibility and pause/resume of a delivered step
- a real typed-decision backend call. The adapter has an injection point, a
  capture format and a replay reader, and no call has been made; the documented
  local candidates (a llama.cpp decision endpoint, small open decision models)
  are third-party, unverified here, and need an explicit decision to download
- measured latency of a real decision call on this repository's tasks
- KNN retrieval itself. The descriptor contract, the keyword baseline and the
  calibration harness exist; no index does. A KNN is a reflex backend like any
  other, and it enters only as a measured candidate against the rule baseline
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
