# Shadow routing policy

`ShadowRouter.propose(task, candidates)` returns a `Decision`. It has no route
executor, model client, network calls or telemetry writer. The caller keeps
control of baseline execution. Inputs and candidate order are not modified.

## Eligibility

The current prototype supports only tasks with `risk_class="low"`,
`evidence_level="normal"` and `locality="any"`. Any other combination causes
abstention: candidate contracts cannot yet substantiate stronger requirements.
This is a conservative scope restriction, not a complete policy engine.

Route IDs must be unique, nonempty strings without surrounding whitespace.
An invalid or duplicate ID causes abstention for the entire proposal, because
the selected identity would otherwise be ambiguous.

Confidence must be a finite Python `int` or `float` in `[0, 1]`, at or above
the configured `min_confidence`. The default is `0.9`; this is an initial
configurable heuristic, not a calibrated probability of success. Missing,
non-numeric, boolean, non-finite or insufficient confidence excludes a candidate.
An invalid threshold raises `ValueError` when constructing the router.

Cost may be `None` (unknown) or a finite, nonnegative Python `int` or `float`.
Booleans are rejected. An invalid cost excludes a candidate even if its
confidence is high. All supplied costs must use one common unit and estimation
basis; the current contract cannot detect mixed currencies or incomparable units.

## Selection

| Eligible candidates | Proposal |
| --- | --- |
| None | Abstain, with no selected route |
| At least one known cost | Lowest known estimated cost |
| All costs unknown | Highest declared confidence; no cost comparison claimed |
| Equal known costs | Higher declared confidence |
| Remaining tie | Lexically smallest route ID (Python string ordering) |

An unknown-cost candidate is excluded from the cost comparison when eligible
priced candidates exist. This does not mean that it is more expensive; it means
that its cost is unavailable. Zero is an explicit estimate, never a substitute
for missing information.

Every returned decision retains `mode="shadow"`. Rationale explains the selection
rule or why the router abstained. Reordering identical candidate sets does not
change the decision.

## Limits

The caller is responsible for proposing capabilities appropriate to the task.
Capability matching, latency budgets, hardware limits, capability versions,
known failure modes, calibrated confidence and independent verification are not
implemented. `estimated_latency_ms` is currently descriptive, not a selection
criterion. A proposal is not authorization to execute a route.

Replayable observations linking a proposal to a baseline and verification
result now exist: see [Shadow observations](OBSERVATIONS.md). Estimated costs remain separate
from measured costs. Until those measurements exist, no real token, cost or
latency savings are established.

## Local validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests cover malformed confidence/cost values, threshold boundaries, zero and
unknown costs, reordered candidates, ambiguous IDs, unsupported requirements,
abstention and preservation of inputs. They run without model or API access.
