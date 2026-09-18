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

The harness splits task ids with a seeded shuffle, executes both routes of every
case through the normal measured-and-verified path, writes the measurement and
observation records, and produces `report.json`.

```json
{
  "schema_version": 1,
  "corpus": "fixture",
  "seed": 20260918,
  "split": {"development": ["..."], "heldout": ["..."]},
  "environment": {"machine_id": "fixture-runner", "runtime_versions": {"python": "3.14.0"}},
  "routes": {"rule": {"runs": 20, "accepted": 18, "rejected": 1, "no_verdict": 1}},
  "pareto": ["rule"],
  "cases": [{"task_id": "wrong-answer-001", "split": "heldout", "status": "verification_failed"}],
  "claim": {"status": "refused", "reason_code": "quality_regression"}
}
```

## Claim rule

A resource claim is evaluated on held-out cases only. It is allowed when every
held-out case was verified for both routes and the candidate dominates the
baseline on the median measured vector, with at least one strictly better shared
dimension. It is refused with `quality_regression` when a held-out case failed
verification, `insufficient_evidence` when a verdict or measurement is missing,
and `no_dominance` when the median vector is not better on every shared
dimension. A refusal is a result: the first fixture run refuses the claim because
the deliberately wrong answer sits in the held-out split.

## Resource dimensions

`ResourceVector` carries tokens, latency, VRAM and energy, keeps unknown
dimensions as null, and ignores them in comparisons instead of assuming equality.
Measurement records currently carry latency only, so tokens, VRAM and energy stay
null until the measurement schema carries them; a fixture corpus further means
the numbers are not representative of real work.
