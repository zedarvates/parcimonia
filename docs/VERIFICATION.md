# Deterministic verification

A verdict must be attributable: a boolean with no identity behind it is a
caller assertion, not evidence. This layer accepts or rejects a route output
without asking a model.

## Registry

`VerifierRegistry.register(verifier_id, version, verifier)` takes a stable
identity and a callable that returns a boolean. Registering the same identity
and version twice is rejected, while several versions of one identity coexist,
so a verdict always names the exact implementation that produced it.

`registry.verify(verifier_id, version, value)` returns a `Verification`:

| Field | Content |
| --- | --- |
| `verifier_id`, `verifier_version` | The exact implementation that ran |
| `verdict` | `true` accepted, `false` rejected, `null` abstained |
| `input_hash` | sha256 of the canonical JSON form of the verified value |
| `detail_code` | Why an abstention happened, for example `unregistered_verifier` |

An unknown identity, or an unknown version of a known identity, abstains instead
of guessing. A verifier that raises becomes an abstention carrying the exception
type in `detail_code`; a verifier that returns a non-boolean is a programming
error and raises. `KeyboardInterrupt` is never swallowed, and a value that cannot
be serialised as finite JSON has no hash and is refused before any verdict.

## Bundled verifiers

| Verifier | Behaviour |
| --- | --- |
| `shape_verifier({"answer": "str"})` | Requires the listed fields with the listed types; booleans are not integers; extra fields are allowed |
| `exact_match_verifier(expected)` | Accepts only a value whose canonical JSON form equals `expected` |
| `runner_result_verifier()` | Accepts a test-runner summary that exited zero with no failures |

## Evidence bridge

`attributed_evidence(verification, task_id=..., route_id=..., ...)` binds a
verification run and its measurements to a route. Observations built from
attributed evidence use schema version 2 and store the verifier block instead of
the caller boolean. An abstained verification is never recorded as a success,
and a record cannot mix attributed evidence with caller assertions.

## Limits

This layer provides determinism and attribution, not truth. A shape check proves
that a field is a string, not that its content is correct, and the bundled
verifiers only decide properties a machine can decide exactly. A model-based
verifier may exist later, but it must be registered under its own identity and
version, carry its own cost and error rate, and never be treated as ground truth.
Calibration stays blocked until labelled outcomes exist.
