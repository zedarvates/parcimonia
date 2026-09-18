# Route registry

Candidates come from a versioned manifest instead of an ad-hoc caller list. A
manifest declares, per route, what it can do, what it costs, which tasks it
accepts and which verifier must judge its output.

## Manifest

```json
{
  "schema_version": 1,
  "registry_version": "routes/2026-09-18",
  "routes": [
    {
      "route_id": "rule",
      "capability_ids": ["format", "rule:format"],
      "estimated_cost": 0.01,
      "estimated_latency_ms": 30.0,
      "confidence": 0.95,
      "constraints": {
        "risk_classes": ["low"],
        "evidence_levels": ["normal"],
        "localities": ["any"]
      },
      "verifier": {"verifier_id": "format/shape", "verifier_version": "1"}
    }
  ]
}
```

## Validation

Rejected at load: an unknown schema version, an empty registry version, an empty
route list, duplicate route ids, a capability repeated inside one route, empty
constraint lists, malformed estimates, a confidence outside `[0, 1]`, and a
verifier that is not registered under exactly that identity and version. When a
list of known capabilities is supplied, a capability outside it is rejected too.
The file reader rejects malformed JSON, duplicate keys and non-finite numbers.

## Matching

`registry.candidates_for(task, required_capabilities=...)` returns the eligible
routes in manifest order. A route serves a task when the task risk class,
evidence level and locality are all accepted by its constraints, and when it
provides every required capability. No match yields an empty list, and the router
then abstains instead of guessing.

## Versioning

`registry.policy_version("shadow-routing/1")` appends the registry version, and
the router records that value in every observation, so a registry change appears
as a policy-version change. Replay still uses the candidate set stored in the
observation, which keeps older records replayable.

## Limits

The manifest declares estimates, not measurements, and a declared confidence
stays uncalibrated. Constraints are matched, not enforced by a policy engine, and
the router keeps its prototype restriction to low risk, normal evidence and any
locality. Automatic route discovery is out of scope, and protobuf stays deferred
until a second language or process consumes the manifest.
