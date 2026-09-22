# Typed-decision adapters

A decision route does not return text. It takes a state and a closed set of
typed questions and returns a choice, a score or a boolean with a confidence.
That shape is what makes a model-backed route cheap to verify: a closed answer
space can be checked by code, without a judge model.

`src/tiberium_ai/decision_adapter.py` implements the three pieces a route needs
before a real decision-model call is worth making. It performs no such call.

## 1. Option sets wider than one call

The reflex contract accepts at most 20 options in one choice question. A real
decision task often needs more: choosing among fourteen mechanisms at two
evidence levels is already 28 options.

`OptionSetQuestion` declares the wide set. `plan_two_stage` cuts it into
*balanced* groups of at most 20, so a remainder never produces a one-option
group, which is not a valid choice question. `stage_questions` turns each group
into a question the reflex contract accepts, plus a final question over the
group winners. `compose_two_stage` puts the answers back together.

Limits, stated plainly:

- an option set is capped at 255 options. Above that the decision is refused
  instead of approximated by another stage.
- groups are balanced, so 21 options become two groups of 11 and 10, not 20 and 1.
- a stage size that would need more than 20 second-stage candidates is refused
  up front, with the count and the cap in the message.
- two compositions are implemented. The grouped one chooses within each group
  and then among the winners, and a group's winner can still be wrong, so it is
  a bounded decomposition rather than an equivalent of one wide call. The scored
  one is described below and keeps a score for every option instead of
  discarding all but one per group.

An answer that is missing makes the decision `undetermined`: an unanswered
question is not a zero score and not a default option. An answer outside the
declared option set raises, because that is a malformed answer rather than an
incomplete one.

### The scored variant

`plan_scored_stages` implements the other composition: every option gets its own
boolean question, so a score is not conditioned on the other options of a batch
and the vector stays comparable across batches. The explicit choice is then asked
over the top `finalists` only, which keeps the second stage inside the choice cap.

Because the second stage's option set does not exist before the scores do, a
scored decision is two requests. The cost sits in the batches, not in the stages:
28 options are one scoring call, and 255 options are thirteen scoring calls that
share one cached context, so a batching transport needs two round trips either
way. `batched_round_trips` reports that, and `stage_calls` reports what a
transport that cannot batch would need instead.

A missing score is never zero: it makes the decision undetermined. A choice
outside the declared options, or outside the recomputed finalists, raises,
because the second-stage question only offered the finalists.

`argmax_agrees` records whether the explicit choice followed the highest score,
which is the difference between the second stage being useful and being
decorative.

## 2. Recorded responses and provenance

`DecisionRequest` carries the state, the typed questions, the state age and the
deadline, and hashes to a fingerprint. `DecisionRecord` stores one captured
response with the backend id and version, the script property that changes the
outcome, the request hash, the origin and the usage.

`capture_decision` takes an injected transport. The library performs no network
I/O: with no transport the capture is a typed `unavailable`, not an exception.
That injection point is the only piece a real call still needs, which is why one
authorized call can become a committed fixture instead of a demonstration.

The request identity covers the declared budget even though the budget is not
sent to a backend: a decision taken under another deadline is a different
commitment, and a record captured under one must not be replayed as if it
answered the other.

`replay_decision` re-evaluates a record offline and refuses a record that
answers a different request, or that claims this request while naming another
backend version. A record with an unobserved answer is `incomplete`, never
filled in.

## 3. Recomposition instead of trust

`two_stage_verifier` recomputes the winner from the option set and the raw stage
answers, and accepts a claim only when recomputation reproduces it. It is
registered as `decision.two_stage` version `1`, so the same input and version
always produce the same verdict, an undetermined decision is never accepted, and
an unknown identity abstains. This is the G2 rule applied to a model-backed
route: the answer is checked by code, not by a second model.

`scored_verifier` does the same for the scored composition: it recomputes the
finalists from the recorded scores and accepts a claim only if it is one of them.

`schema_verifier` answers a different question: does this recorded response fit
the request it answers? Every question is answered exactly once, the choice is
inside the declared option set, the probabilities sum to one, and the values are
in range. This is conformance, not correctness. A well-typed answer can still be
the wrong answer, which is a calibration failure rather than a schema one, and
that is why only a measured calibration snapshot can authorize auto-act.

A payload builder per verifier (`two_stage_payload`, `scored_payload`,
`schema_payload`) turns typed objects into the exact registry payload, so a
caller never hand-assembles the wire format.

`write_decision_record` and `read_decision_record` store one response in a
self-describing JSON file and refuse to overwrite it. That is the mechanical step
which turns one authorized call into a committed fixture.

`decision_route_entry` builds the G4 manifest entry with `estimated_cost` having
no default, so a route's cost stays a measurement or a declared estimate.
`confidence` stays `null` until the decision is calibrated on this repository's
tasks.

## The decision clock

`src/tiberium_ai/decision_clock.py` keeps two failures apart from decision
quality:

- a decision that lands after its deadline is worth zero, not less. A wall-clock
  overrun is reported with a signed remainder, so a small overrun cannot look
  like a comfortable margin.
- a decision taken from a snapshot the consumer has since replaced describes a
  state that no longer exists. Staleness is judged before the clock, because a
  fast answer about a replaced state is wrong rather than quick.
- a declared staleness bound with an unobserved age fails closed, exactly as an
  unknown cost is never treated as zero.

`fallback_route_id` is part of the budget on purpose: a fallback chosen after the
deadline has been missed would be chosen by the mechanism that failed to meet it.
The clock is never read in that module; elapsed time and state age arrive as
inputs, so every verdict is reproducible.

## What this does not claim

- no model is called, no weights are loaded, no Jev, Laya or TypeSafe code is
  vendored
- no training and no calibration. A confidence that comes from a record is a
  provider number, not a calibrated probability
- no cost or saving claim. The fixtures prove the contract, the provenance and
  the replay. They say nothing about decision quality
- no active routing. Nothing here changes what a route executes
- this is a route contract, not a new V1 gate. Promoting it to a gate is a
  separate decision with its own exit criteria

## Provenance of the pattern

The typed-decision interface, the 255-option ceiling and the two-stage fallback
above a per-call cap are published behaviour of the System One model class. The
separation of latency, stale snapshots and quality in a moving-clock environment
comes from published real-time agent evaluations.

The implementation here is original and adapted. It reuses Parcimonia's own
reflex contract as the stage question type, keeps this repository's fail-closed
rules, and documents where it differs from the source pattern instead of
implying equivalence.

## How to run

```powershell
python examples/decision_suite.py
python examples/decision_suite.py --out runs/decisions
```

The suite prints the grouped plan, the recomposed winner, the scored plan with
its batch count, the winner of both modes, the verification of a recomputed
claim, the rejection of a tampered claim, the schema verdict and the three timing
outcomes. With `--out` it writes `summary.json` and `records.jsonl` and refuses
to overwrite an existing directory.

## The local path to a real call

The gap that remains is one call. Two open routes are documented publicly and
need no waitlist:

- a llama.cpp branch exposing a decision endpoint that takes instructions, a
  schema and the state, and returns every field with a value and a confidence,
  reported at 17.3 ms per decision in bulk on a 2 GB model in 2.4 GB of VRAM,
  with every option scored from one cached context
- small open decision models: a 1B model published under Apache-2.0 and an MIT
  alternative, plus distillation recipes where a large teacher labels situations
  and a 0.6B student is fine-tuned on its percentages, with held-out agreement
  and calibration error reported

Both are third-party. This repository has not vendored them, has not verified
their licences or their numbers, and will not download weights or build a branch
without an explicit decision. What is ready here is the boundary: inject a
transport, capture one response, commit the record, replay it offline.

Two cautions carried by those sources matter for this repository's gates. A wrong
pick is not a hallucination, it is a calibration failure, which is why the schema
verifier authorizes nothing by itself. And offline agreement with a teacher is
not agreement with the task.

## Public-listing checklist

A curated list of public projects built on typed-decision models includes a
project only when all of the following hold: the source is public and citable,
it genuinely uses that model for a concrete decision, it names the model or the
typed loop, and one sentence explains scenario, method and value. Generic
routers that merely resemble the pattern are excluded, and a listing is not an
endorsement.

Applied honestly to this repository:

| Requirement | Status |
| --- | --- |
| public and citable | yes, this repository |
| a runnable check | yes, `examples/decision_suite.py` and the unit tests, covering three registered verifiers |
| typed decision loop over a closed option space | yes, `decision_adapter.py` |
| one-sentence scenario | yes: a wide closed option set is scored option by option and then chosen explicitly, and the recomposed decision is verified by recomputation instead of trusted |
| a real call to that model | **no.** The adapter has an injection point and a replay format, and no call has been made |

So the honest position is that this work makes the integration possible and
checkable without yet being an entry. Two things are missing, and both need an
owner decision rather than a code change:

1. one authorized call through the injected transport, with the response
   committed as a record and replayed by the example. That call is quota-bearing
   and belongs behind an explicit authorization, as [Integrations](INTEGRATIONS.md)
   already states for cloud System-1 APIs.
2. a public submission to the list itself. That is an external write to a
   third-party repository and needs an explicit go-ahead.
