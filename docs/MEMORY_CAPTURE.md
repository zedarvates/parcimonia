# Explicit capture for offline memory replay

`MemorySequenceCapture` records the caller's observed episode into the existing
[replay contract](MEMORY_REPLAY.md). It is opt-in: no agent interception, trace
discovery, model call, route execution or outcome creation. It does not change
the active router. Recording an episode is not running an A/B/C comparison.

## Collect at the existing task boundary

After the caller has prepared a typed task, candidate estimates and exact
versioned source facts, append the observed turn. Preserve the actual history
events needed by the baseline. Do not reconstruct candidate estimates or source
versions from a successful answer after the fact.

```python
from dataclasses import asdict
from tiberium_ai.memory_capture import MemorySequenceCapture
from tiberium_ai.verification import hash_input

capture = MemorySequenceCapture(
    sequence_id=episode_id, origin="captured",
    source_ref=export_revision, producer_id=producer_id,
    initial_history=actual_prior_events,
)
capture.append_turn(
    {"task": asdict(task), "candidates": [asdict(c) for c in candidates],
     "required_keys": requested_keys, "routing_epoch": estimation_and_tool_revision,
     "critical_change": critical_change, "history_events": actual_prior_turn_events},
    facts=resolved_source_facts, missing=unresolved_keys,
)
# After the caller's existing request completes, record only observed usage.
capture.record_usage(task.task_id, {
    "receipt_id": receipt_id, "origin": "provider_reported",
    "source_ref": response_reference, "variant": "current",
    "backend_id": backend_id, "backend_version": backend_version,
    "payload_hash": hash_input(actual_request_payload),
    "input_tokens": observed_input_tokens, "output_tokens": observed_output_tokens,
    "latency_ms": observed_latency_ms, "n_retries": observed_retries,
    "cost": observed_cost, "cost_unit": observed_cost_unit,
})
# The destination's parent must exist; the destination itself must be new.
manifest = capture.write(private_destination)
```

The variables above come from the caller's existing loop; the library does not
obtain or invent them. Missing usage fields stay null. Facts and missing keys
must partition requested keys. An actual JSON null fact is distinct from an
absent fact. Values **and absences** are pinned within each entity/key/version:
changed values, missing-to-present and present-to-missing all require a new
source version. This prevents a later archive snapshot from filling an earlier
missing fact during replay. Repeated identical facts are deduplicated.

The snapshot detaches nested values. Appends and usage recording are validated
before committing state; a rejected operation preserves the earlier snapshot.
An episode is bounded to 256 turns and 32 MiB of serialized capture by default.
Custom positive limits are explicit, with at most 32 MiB to keep the export
replayable; overflow raises, never truncates history.

## Files and usage attribution

| File | Content | Treatment |
| --- | --- | --- |
| `sequences.jsonl` | Ordered tasks, candidates, scope and actual history | Private raw replay input |
| `facts.jsonl` | Exact versioned fact snapshot; may be empty when all facts are missing | Private raw replay input |
| `usage.jsonl` | Optional `memory-usage/1` receipts bound to final sequence/archive hashes and each turn hash | Usage sidecar, not offline benchmark measurements |
| `manifest.json` | Revisions, origin, counts, raw-input flag and refused saving claim | Capture receipt; no quality labels |

Usage requires a unique `receipt_id`, declared `origin`, `source_ref`, variant,
backend ID/version and nullable canonical request `payload_hash`. Variants are
`current`, `full_history`, `compact`, `compact_persistent`; origin is `authored`,
`provider_reported`, `local_measured` or `caller_reported`. The capture preserves
these declarations; it cannot authenticate them or prove experimental pairing.

Optional metrics are `input_tokens`, `output_tokens`, `tokens_total`, `n_retries`,
`latency_ms`, `cost`, `cost_unit`. Counts must be exact nonnegative integers;
timings and costs must be finite and nonnegative. Known cost needs an explicit
unit. A total is derived only when both token counts are known; a contradictory
explicit total is rejected. A total-only receipt keeps both components unknown.
Receipt IDs must identify disjoint observations: duplicate identities are
rejected, but different IDs do not prove that two records are distinct calls.
Do not record a consolidated retry total and also its constituent attempts.
Fields such as `tokens_saved` and a caller's quality verdict are rejected.

Final hashes are computed when taking a snapshot or exporting, so later turns
cannot leave earlier receipts pinned to an unfinished sequence revision.
The writer creates a fresh directory and exclusive files, using owner-only
POSIX permissions. It refuses any existing destination; a failed new write
removes only its own created files. Source files remain unchanged.

## Convert an explicit turn export

Each input JSONL row has exactly `schema: "memory-capture-turn/1"`, `turn`,
`facts`, `missing`, and optionally a list of `usage` receipt objects. `turn` uses
the replay turn contract. Supply origin and attribution explicitly:

```bash
PYTHONPATH=src python examples/memory_capture.py \
  --turns /private/observed-turns.jsonl --sequence-id episode-001 \
  --origin captured --source-ref export-v1 --producer-id producer-001 \
  --out runs/private-episode-001
PYTHONPATH=src python examples/memory_replay.py \
  --sequences runs/private-episode-001/sequences.jsonl \
  --archive runs/private-episode-001/facts.jsonl --out runs/replay-episode-001
```

The collector prints counts only and rejects malformed/ambiguous inputs without
echoing raw content. Unlike the payload-free replay report, these capture files
deliberately contain tasks, facts and history. Keep them in a caller-chosen
private location such as the ignored `runs/` directory; no upload occurs.

## Existing integrations and the remaining gate

Botte's `skills/trajectory/agent_run.py` and `outcome.py` already emit private QA
envelopes with caller-reported duration, cost and total tokens. Those envelopes
do not contain replayable versioned source facts, and their quality verdicts
are not the sequence labels. Its `skills/auto_memory/hook.py` exposes a step
hook, but does not provide immutable fact versions. Inspection of main revision
`f5b95459624e5e3d74ca14cd2fe065c290a8f2bc` informed the boundary above; no Botte
hook or private journal was modified or read. Preserve its QA lane separately.

For Parcimonia's `DecisionRecord.usage`, input/output totals, retry count and
latency already exist. Map recorded usage explicitly at the caller boundary;
a fixture record must keep an authored origin. Do not interpret a cost estimate
or UTF-8 byte count as usage. `surface.ingest_turn_report` remains the capability
compliance lane, not a token/cost receipt or an answer-quality oracle.

Separately attributed outcomes still need to bind the final sequence and
archive hashes. No outcomes file is generated here. A current-route receipt
alone does not measure the compact alternatives; offline replay keeps its own
provider cost and token fields unknown even when a usage sidecar is present.
Real paired calls, independent quality evaluation, repeated latency and complete
cost accounting remain TASK-110. Every capture explicitly refuses a production
saving claim; no deployment or promotion is performed.
