# Benchmark Plan

Every experiment compares Tiberium against a clearly identified baseline.

Record:
- task ID
- baseline route
- Tiberium proposed route
- input/output tokens
- number of LLM calls
- API monetary cost when known
- latency
- CPU/GPU/VRAM/RAM when measurable
- task quality
- abstention
- escalation
- verifier outcome
- unsafe false positive
- evidence completeness

Initial benchmark families:
1. deterministic transforms
2. structured extraction
3. repeated known cases
4. tool selection
5. GitHub/CI state reasoning
6. agent handoff selection
7. small planning fragments
8. anomaly classification
9. local-model vs cloud escalation
10. ShardJEPA-style fast decision routing

Primary reports:
- quality vs cost
- quality vs latency
- escalation rate
- unsafe false-positive rate
- savings by task family
- savings by hardware profile
- route stability across versions

A 90% token reduction with silent quality degradation is not a success.

## Implemented harness

```powershell
python examples/benchmark_suite.py --out runs/benchmark
```

The harness splits task ids with a seeded shuffle, executes every route of every
case through the normal measured-and-verified path, writes the measurement and
observation records, and produces `report.json`. A case compares at least two
routes: one declared baseline and one or more candidates.

```json
{
  "schema_version": 2,
  "corpus": "fixture",
  "seed": 20260918,
  "split": {"development": ["..."], "heldout": ["..."]},
  "environment": {"machine_id": "fixture-runner", "runtime_versions": {"python": "3.14.0"}},
  "routes": {"rule": {"runs": 20, "accepted": 18, "rejected": 1, "no_verdict": 1,
                      "heldout_median_latency_ms": 0.05,
                      "heldout_median": {"tokens": null, "latency_ms": 0.05,
                                         "vram_mb": null, "energy_joules": null}}},
  "pareto": ["rule"],
  "cases": [{"task_id": "wrong-answer-001", "split": "heldout", "status": "verification_failed"}],
  "claim": {
    "status": "refused",
    "reason_code": "quality_regression",
    "candidate": "rule",
    "allowed": [],
    "front": [],
    "evaluated": [
      {"route_id": "rule", "status": "refused",
       "reason_code": "quality_regression", "detail": "..."}
    ]
  }
}
```

## Claim rule

A resource claim is evaluated on held-out cases only, once per candidate. It is
allowed when every held-out case was verified for the candidate and the baseline,
and the candidate dominates the baseline on the median measured vector, with at
least one strictly better shared dimension. It is refused with
`quality_regression` when a held-out case failed verification,
`insufficient_evidence` when a verdict or measurement is missing, and
`no_dominance` when the median vector is not better on every shared dimension.
A refusal is a result: the first fixture run refuses the claim because the
deliberately wrong answer sits in the held-out split.

The claim reports every candidate in `evaluated`, the qualifying ones in
`allowed`, and the non-dominated ones among them in `front`. A real trade-off
therefore produces a front rather than one winner: when two candidates each beat
the baseline on a different dimension and neither beats the other, the report
says so instead of averaging the two into a scalar. `candidate` is the headline,
which is the first front member.

## Resource dimensions

`ResourceVector` carries tokens, latency, VRAM and energy, keeps unknown
dimensions as null, and ignores them in comparisons instead of assuming equality.
Measurement records now carry a version 2 resources block, so an instrumented
route can report tokens, VRAM and energy. The fixture corpus does not instrument
them, so those dimensions stay null there, and representative real work remains
open in issue #8.

The report aggregates one median per measured dimension, over the held-out runs
only. A dimension is null only when no run in that sample measured it, and a
dimension measured on some runs only is aggregated over those runs. An integral
dimension is rounded to the nearest whole value, because half a token is not a
token count. This is what makes a token saving claimable: a route that consumes
far fewer tokens at equal latency now dominates a baseline it never dominated
while the report kept only the latency dimension.

A route declares how it reports its resources, either as a constant vector or as
a callable evaluated after the run, because a token count depends on the input.
The declaration must be genuinely observed: a guessed vector would enter the
record as if it had been measured, which is the failure mode this harness exists
to prevent.
