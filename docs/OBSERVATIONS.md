# Shadow observations

An observation is the replayable trace of one shadow proposal. It answers a
narrow question: given the same task identity, candidate estimates and router
configuration, would the current policy propose the same route?

The record is a plain JSON object written by `write_observation` and read by
`read_observation`. `record_observation` builds one from a live proposal;
`replay_observation` re-runs it and rejects any record whose stored decision no
longer matches the recorded policy.

## Stored fields

| Field | Content |
| --- | --- |
| `schema_version` | Record format version (`1`) |
| `task` | Task ID, kind, risk class, evidence level and locality |
| `candidates` | Route ID, capability IDs, estimated cost and latency, confidence |
| `router` | `policy_version`, optionally suffixed with the registry version, and `min_confidence` |
| `decision` | Selected route, mode, rationale, abstention |
| `baseline_route_id` | The route the real execution used |
| `cost_unit` | The shared unit of every estimated and measured cost |
| `data_origin` | `synthetic` or `caller_reported` |
| `baseline_evidence` | Verifier outcome and measured cost/latency, or null |
| `proposal_evidence` | Verifier outcome and measured cost/latency, or null |

Task inputs, evidence metadata and `known_failure_modes` are excluded on
purpose: they are free-form text that can carry sensitive payloads, and none of
them is needed to reproduce the routing decision. Failure-mode identifiers can
be added once they become stable IDs instead of prose.

## Evidence shapes

Two record versions exist, and the version follows the evidence it carries.

| Version | Evidence block | Meaning |
| --- | --- | --- |
| 1 | `verifier_ok` boolean | A caller assertion without verifier identity |
| 2 | `verification` block with `verifier_id`, `verifier_version`, `verdict` and `input_hash` | An attributed verifier run |

A record cannot mix attributed and unattributed evidence, and a version 2 record
whose verifier block is incomplete or whose hash is malformed is rejected. An
abstained verdict (`null`) is never a success. See
[deterministic verification](VERIFICATION.md) for the registry that produces
those blocks.

A verdict cannot be reconstructed later: the verified output is deliberately
never stored, so only its hash survives inside an observation. Measure and verify
in the same pass, then write both artefacts, or the verification is lost and the
measurement stands alone.

## Validation

A record is rejected when its schema or policy version is unsupported, when a
key is missing or unexpected, when candidate route IDs are duplicated or
untrimmed, when confidence or cost values are invalid, when the baseline does
not identify a candidate, when evidence documents a different task or route, or
when the stored decision does not match a replay. Replayed active-mode decisions
are rejected; only `shadow` is supported. In version 2, evidence must also carry
a complete verifier attribution, and a `verifier_ok` that contradicts the
verdict is refused at record time.

`write_observation` refuses to overwrite an existing file and requires the
target directory to exist. It validates the record before writing, so an invalid
observation never creates a partial file.
`read_observation` rejects malformed JSON, duplicate keys and non-finite
numbers.

## Comparison statuses

`compare_observation` reports the stored contrast between the baseline and the
proposed route:

| Status | Meaning |
| --- | --- |
| `abstained` | The router proposed no route; no delta is computed |
| `baseline_selected` | The proposal equals the baseline, so the estimated delta is zero |
| `insufficient_evidence` | Baseline or proposal evidence is missing; only the estimated delta is reported |
| `verification_failed` | A verifier rejected one side; measured deltas are withheld |
| `verification_abstained` | No verdict exists for one side, for example an unregistered verifier; measured deltas are withheld |
| `unattributed_evidence` | Version 1 evidence asserts success without naming a verifier |
| `verified_evidence` | Both sides carry an attributed accepted verdict and a measured cost delta exists |
| `verified_without_measurements` | Both sides carry an attributed accepted verdict but no paired measurements exist |

Estimated and measured deltas are always separate fields. A missing measurement
is never filled from an estimate, and a negative delta is a regression, not a
saving. `data_origin` travels with the comparison so a synthetic or
caller-reported scenario cannot be mistaken for observed production data.

## Usage

```python
from pathlib import Path

from tiberium_ai import (
    CandidateRoute, Evidence, Task,
    compare_observation, read_observation, record_observation, write_observation,
)

record = record_observation(
    Task("format-001", "format", {"text": "private"}),
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
print(compare_observation(read_observation("observations/format-001.json")))
```

## Limits

An observation proves that a decision is reproducible, not that it is correct
or cheaper. It does not yet capture wall-clock time, model or capability
versions, hardware, token counts or verifier identity, and it does not run a
baseline. `caller_reported` and `synthetic` records are useful for testing and
design work; they are not benchmark evidence. Aggregation across records,
real baseline capture and versioned capability manifests remain roadmap work.
