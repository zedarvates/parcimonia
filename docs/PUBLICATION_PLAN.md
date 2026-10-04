# Research and publication plan

Parcimonia is an open-source experimental system for cost-, evidence- and
risk-aware routing. A future research publication is being considered, but no
paper result is claimed by this repository today.

## Hypothesis

Outcome-grounded decision records may let an agent workflow improve its
selection policy while deterministic gates, shadow evaluation, held-out tests
and explicit promotion prevent unconstrained self-modification.

The experimental protocol is documented in
[EXPERIMENTAL_RSI.md](EXPERIMENTAL_RSI.md).

## Evidence required before a paper

A credible submission should include:

- a frozen baseline policy and versioned implementation;
- versioned Decision/Outcome record schemas;
- enough heterogeneous tasks to avoid a single-project anecdote;
- public or publishable benchmark cases;
- development/held-out separation;
- ablations for scoring, outcome memory, VOI and policy evolution;
- measured resource vectors rather than nominal hardware assumptions;
- calibration and high-confidence-error analysis;
- negative results, abstentions and human interventions;
- adversarial/Goodhart tests;
- exact code/configuration/seed provenance where applicable.

## Candidate comparisons

At minimum:

1. baseline workflow without adaptive work selection;
2. V1 heuristic selection;
3. V1 plus outcome-memory analysis (same live policy);
4. one frozen shadow policy candidate;
5. candidate after Gauntlet only if it earns an opt-in trial.

The study should avoid changing multiple independent mechanisms between
conditions unless the ablation explicitly measures them.

## Candidate outcomes

Measure useful completion, cost/latency/compute dimensions actually observable,
selection error/regret when defensible, duplication avoided, dependencies
unblocked, abstention, regressions, high-confidence errors and human
intervention.

## Reproducibility boundary

Private project histories are not automatically publishable research data.
Public artifacts should use public/synthetic tasks or carefully anonymized
aggregate records that cannot reconstruct private prompts, secrets, paths or
holdouts.

## Publication gate

A manuscript should not make a superiority claim until a frozen candidate
outperforms the frozen baseline on held-out evidence without an unacceptable
increase in risk, high-confidence errors or human intervention.

Potential venues and archive submission should be chosen only after the
experimental result exists. An arXiv preprint is a possible dissemination path,
not a current claim of acceptance or peer review.
