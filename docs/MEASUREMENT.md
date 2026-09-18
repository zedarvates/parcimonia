# Baseline measurements

A measurement record answers a narrow question: what happened when a specific
baseline callable ran, how was it measured, and where. It is the raw material
that observations, verifiers and benchmarks will consume.

`run_baseline` executes the caller's callable exactly once, measures wall clock
through an injected clock, and captures success or failure. It never retries,
never calls a network, and never executes a route on its own initiative.

## Stored fields

| Field | Content |
| --- | --- |
| `schema_version` | Record format version (`1`) |
| `kind` | Always `measurement` |
| `task_id`, `route_id` | Identity of the executed task and route |
| `method` | How the number was obtained, `wall_clock/monotonic` today |
| `environment` | Caller-chosen `machine_id` label and runtime versions |
| `measured_at` | ISO 8601 timestamp with a timezone offset |
| `outcome` | `ok` plus the exception type name when it failed |
| `latency_ms` | Measured wall-clock duration |
| `cost` | Measured or billed cost, or null |
| `cost_unit` | Unit shared by every cost in the record |
| `data_origin` | Always `measured` |
| `resources` | Version 2: tokens, VRAM and energy, or null when not instrumented |

Task inputs, outputs, exception messages and free-form metadata are never
stored: a failure keeps the exception type name only. `machine_id` is a label
chosen by the caller, not a hostname or hardware fingerprint.

## Why `data_origin` is fixed

This record type is reserved for runs that actually happened. Synthetic or
caller-reported figures belong to observations and can never masquerade as a
measurement, because the reader rejects any other value.

## Validation

Records are rejected when the schema version, kind or data origin is
unexpected, when a key is missing or extra, when an identifier or cost unit is
empty or untrimmed, when latency or cost is non-finite or negative, when the
timestamp carries no timezone, or when `outcome.ok` and `outcome.error_type`
disagree. Reading rejects malformed JSON, duplicate keys and non-finite
numbers. Writing validates first, refuses to overwrite an existing file, and
requires the target directory to exist.
A version 2 resources block must contain exactly `tokens`, `vram_mb` and
`energy_joules`, each null or a finite nonnegative value, with `tokens` an
integer. Version 1 records remain readable and their resources stay unknown.

## Usage

```python
from time import monotonic

from tiberium_ai import Environment, run_baseline, write_measurement

result = run_baseline(
    task_id="format-001",
    route_id="baseline",
    run=lambda: format_document(document),
    cost_unit="USD per 1k tasks",
    environment=Environment("odin-pc", {"python": "3.14.0", "ollama": "0.5.0"}),
    clock=monotonic,
    cost=0.42,
)
write_measurement("measurements/format-001.json", result.to_record())
print(result.latency_ms, result.ok, result.error_type)
```

## Limits

A measurement proves that a run happened and how long it took. It does not
prove that the output was correct, which is the verifier gate, and it does not
compare routes, which is the benchmark gate. `cost` is caller-supplied: a billed
figure, an API response or an estimate labelled as measured must stay traceable
to its source before any savings claim is published.
