# Attach an existing execution to a memory episode

The [explicit capture](MEMORY_CAPTURE.md) can now retain an existing
`capture_run` result through `attach_memory_run`. This adapter takes a
`CapturedRun`, never a callable or transport: it cannot launch, retry, select
or reroute an execution. It leaves authorization with the existing caller.
The active router and Botte's QA lane remain unchanged.

## Caller boundary

1. Prepare the real task, candidates, source version and observed facts at the
   existing boundary. Append them to `MemorySequenceCapture` before the caller's
   execution, so invalid facts/versions can stop preparation before a call.
2. Hash the exact canonical request payload before the existing client consumes
   it. This fingerprint is a declared request commitment, not a wire capture.
3. Keep the existing `capture_run` call and its named verifier. Do not execute a
   shadow proposal merely to collect a measurement. Keep any usage returned by
   the caller's client separately, including partial usage for a failed call.
4. Attach the completed attempt. Handle its logging result separately from the
   route's outcome; a logging failure never justifies repeating a performed call.
5. Export to a fresh private directory at the end of the episode. Supply
   independent sequence outcomes later; this adapter creates no labels.

```python
from tiberium_ai.capture import capture_run
from tiberium_ai.memory_execution import attach_memory_run
from tiberium_ai.verification import hash_input

# capture.append_turn(...) uses the observed source facts, as documented above.
request_hash = hash_input(actual_request_payload)  # before the caller's call
captured = capture_run(
    task_id=task.task_id, route_id=current_route_id,
    run=existing_run_callable,  # the caller's existing, authorized execution
    verifier_id=verifier_id, verifier_version=verifier_version, registry=registry,
    environment=environment, clock=monotonic_clock,
    cost_unit="unmeasured-provider-unit",
)
# None when the client supplied no usable receipt; never invent zeros.
receipt = observed_usage_receipt
result = attach_memory_run(
    capture, captured, execution_id=execution_id,
    request_hash=request_hash, usage_receipt=receipt,
)
# Handle captured.measurement['outcome'] using the existing loop.
# Handle result.execution_recorded / usage_recorded / detail_code as logging.
# Export via capture.write(new_private_destination) once the episode ends.
```

`observed_usage_receipt` follows `memory-usage/1`: its `receipt_id` must equal the
execution ID, its `payload_hash` the pre-call request hash and its variant
`current`. It includes explicit backend ID/version, source reference, origin
and any observed metrics. Do not relabel an observed current run as one of the
offline compact alternatives. A fixture's usage origin is retained as authored
even if its receipt was incorrectly declared provider-reported.

The caller must freeze the request hash before its client mutates/consumes a
payload. The adapter checks task/route scope, receipt/request linkage and the
output hash against its recorded verification. These checks do not authenticate
the caller, backend, request transport or source facts.

## Additional execution sidecar

`executions.jsonl` contains `memory-execution/1` rows with execution ID, task,
current route, request hash, the existing measurement and output-verification
block. The final sequence/archive and individual turn hashes bind each row;
manifest fields `executions` and `executions_revision` count and pin them.
Its origin is the episode's declared origin. The sidecar is empty when the
caller supplies only manual turns/usage and no measured runs.

Execution rows keep error type, local monotonic elapsed time and verifier
attribution; they contain no raw response or request, exception message or
answer. Capture source files still intentionally contain raw tasks/facts/history
and belong in a private location. The new sidecar shares the same byte cap,
exclusive writer and detached snapshots; no data is uploaded.

| Attachment result | Meaning | Caller response |
| --- | --- | --- |
| `recorded` | Existing execution and supplied usage stored | Continue existing outcome handling |
| `usage_not_supplied` | Execution stored; usage unknown | Keep usage unknown |
| `usage_record_rejected` | Execution stored; supplied usage rejected or too large | Repair only its logging with `record_usage`; do not repeat the call |
| `execution_record_rejected` | Measurement scope/output/linkage/budget rejected | Keep the existing `CapturedRun`; resolve logging without repeating the call |

A failed route remains failed and has no output verification; explicitly supplied
partial usage may still be attached. A successful route with an unknown verifier
keeps its null verdict. Output verification is not an independent expected
sequence outcome. Duplicate execution identities are rejected, never replayed.

Local measurement latency and provider-reported latency remain distinct. A
missing provider duration is not replaced by local elapsed time. Local cost and
resource fields retain the existing measurement's caller provenance; they are
not imported into a provider receipt. No runtime measurement is substituted
into the offline replay's token/cost fields or into its quality labels.

## First homelab pilot: local Odin caller

The homelab execution access identified for this project is the local agent on
Odin. This cloud session has no established execution link to Eurekai. Prepare
an isolated Parcimonia checkout on Odin from the current PR revision; import
the adapter in the existing caller where it already creates a typed task and
receives a `CapturedRun`. Preserve the existing backend/client configuration.
No new endpoint, credentials, model download, service or automatic hook is
provided or assumed here. The prior Eurekai micro-NN diagnostic remains read-only.

Collect one authorized episode with actual versioned facts and existing calls.
Retain a private fresh export, inspect its attachment statuses and run the
documented offline replay. Unknown results stay unlabelled. Return a payload-free
summary (revision, source/sequence hashes, counts, attachment statuses and
observed usage fields); keep raw source files private. Independent outcomes and
real paired A/B/C calls are still required before a saving claim. TASK-110 stays
open; no hardware pilot or provider measurement was run by this cloud session.
