# Experimental RSI protocol

> Status: research protocol / shadow-only. This document defines measurements and
> hypotheses. It does **not** claim that recursive improvement, cost savings, or
> quality gains have been demonstrated.

## Research question

Can an evidence-gated agent workflow improve how it selects work over time by
comparing predicted utility with observed consequences, while keeping policy
changes offline and reversible?

Parcimonia already separates deterministic gates, estimates, measured outcomes,
resource vectors, held-out evaluation and shadow routing. This experiment extends
those principles from *route selection* to *work-selection policy evaluation*.

## Roles

A reference deployment separates responsibilities:

1. **Sensors** detect external or internal changes.
2. **Consolidators** turn signals into evidence-backed candidates.
3. **Planner** orders candidates but does not authorize unsafe work.
4. **Orchestrator** selects one bounded task.
5. **Specialized executors** act only inside explicit authority.
6. **Outcome recorder** captures consequences.
7. **Governance/Gauntlet** challenges policy changes before promotion.

Deterministic safety, authorization and privacy gates run before any learned or
heuristic score. A high score is never an authorization.

## Active baseline policy (V1)

For eligible candidates, six ordinal fields are recorded on a 1–5 scale:

- impact
- unblock value
- confidence in the evidence
- urgency
- expected cost
- risk

The current experimental ranking heuristic is:

```text
score_v1 = (impact * unblock * confidence * urgency) / (cost * risk)
```

The scale is deliberately coarse. Unknown values use the neutral value 3 and
must be marked unknown. The scalar is a baseline to challenge, not a target to
optimize.

Value of information (VOI) and estimated probability of success are collected
in **shadow** fields first; they do not alter V1 selection until evaluated.

## Decision record

Before execution, record at minimum:

- stable decision ID and timestamp
- task/candidate identity and provenance
- policy/version and applicable deterministic gates
- selected candidate and 1–2 strongest non-selected alternatives
- V1 components, score, shadow VOI and probability-of-success estimate
- predicted result and expected evidence
- expected resource vector (only dimensions actually estimated)
- expected dependencies unblocked
- unknowns and assumptions

Never store secrets or private payloads merely to make a record self-contained.

## Outcome record

After a material execution, record:

- decision ID and exact execution/version provenance
- success / partial / failure / abstention
- measured resource vector where available
- evidence produced
- dependencies actually unblocked
- regressions, incidents and human interventions
- prediction error: predicted versus observed, without inventing missing values
- whether the result changes confidence in future similar decisions

Estimated and measured values remain distinct.

## Controls

### Anti-Goodhart

The score is not the objective. External evidence and observed consequences are
the arbiter. A policy that raises its own scores without improving held-out
outcomes fails.

### Confidence decay

Evidence can lose relevance after time, dependency changes, model changes or
environment changes. Confidence must not remain high by inertia.

### Stop / rethink

After three material iterations on the same line with neither measurable
improvement nor meaningful new information, automatic continuation stops and
the line is marked for reassessment.

### Controlled exploration

A safe, reversible, low-cost candidate with high information value may be
labelled an exploration candidate. Exploration is bounded and must not bypass
policy gates.

### Meta-budget

Improving the selector consumes resources too. Meta-work competes with project
work and must justify its own expected information value.

## Policy candidates

The active policy never edits or promotes itself. A proposed policy change is a
`POLICY_CANDIDATE` and remains shadow-only. It records:

- observed failure or opportunity
- supporting decision/outcome records
- proposed change
- expected benefit
- new failure modes
- evaluation metric
- rollback path

Examples include calibrated success probabilities, dependency-graph-aware
unblock value, explicit VOI, or better treatment of multi-dimensional cost.

## Gauntlet evaluation

When enough comparable records exist:

1. freeze an evaluation snapshot;
2. separate policy-development data from a held-out slice where feasible;
3. replay V1 and the policy candidate offline on the same candidate sets;
4. compare selection quality, measured cost vector, task success, high-confidence
   errors, abstention, regressions and human intervention;
5. run adversarial cases for score gaming, stale evidence and missing costs;
6. reject on material safety/evidence regression;
7. require explicit promotion outside the evaluated policy.

No result from a development set alone supports a superiority claim.

## Proposed research metrics

Primary:
- useful-task completion rate
- selection regret where a defensible counterfactual becomes observable
- predicted-to-observed calibration
- duplicate/redundant work avoided
- measured resource vector per useful outcome
- human intervention rate
- high-confidence selection errors

Secondary:
- dependencies unblocked
- abstention rate
- evidence completeness
- stop/rethink frequency
- exploration yield
- policy stability across task families

## Experimental phases

**E0 — Instrumentation.** Collect decision/outcome records without changing V1.

**E1 — Calibration.** Measure prediction errors, missing-data rate and stability.

**E2 — Shadow policies.** Replay candidate policies offline; no live influence.

**E3 — Held-out Gauntlet.** Compare frozen policies on unseen or held-out cases.

**E4 — Opt-in trial.** Only after E3, allow a bounded reversible trial with
explicit rollback and unchanged deterministic gates.

## Publication perspective

A future paper may study evidence-gated recursive improvement of autonomous
agent workflows. Candidate contribution: a reproducible method for improving
*work-selection policy* from outcome memory without allowing unconstrained
self-modification.

A publication is contingent on sufficient experimental evidence. Until then:

- do not claim recursive self-improvement has been demonstrated;
- do not claim cost or quality improvements from the protocol itself;
- publish negative results and abstentions;
- disclose task-selection and evaluation procedures;
- keep private project data out of public datasets;
- prefer synthetic/public benchmark cases plus anonymized aggregate statistics.

Possible working title:

> **Evidence-Gated Recursive Improvement for Autonomous Agent Workflows:
> Outcome Memory, Cost-Aware Selection and Shadow Policy Evolution**

This is a research direction, not a publication announcement.
