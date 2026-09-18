"""Replayable, privacy-bounded shadow-routing observations.

An observation stores only what is required to reproduce a routing decision:
the task identity, candidate estimates, router configuration, decision and the
measurements explicitly bound to the baseline and proposed routes. Free-form
task inputs, evidence metadata and failure-mode text are deliberately excluded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    CandidateRoute,
    Decision,
    Evidence,
    Task,
    Verification,
    validate_verification_record,
)
from .router import ShadowRouter, is_nonnegative_number

SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = (1, 2)
POLICY_VERSION = "shadow-routing/1"
SUPPORTED_DATA_ORIGINS = ("caller_reported", "synthetic")

_TASK_FIELDS = frozenset(
    {"task_id", "kind", "risk_class", "evidence_level", "locality"}
)
_CANDIDATE_FIELDS = frozenset(
    {
        "route_id",
        "capability_ids",
        "estimated_cost",
        "estimated_latency_ms",
        "confidence",
    }
)
_ROUTER_FIELDS = frozenset({"policy_version", "min_confidence"})
_DECISION_FIELDS = frozenset(
    {"task_id", "selected_route_id", "mode", "rationale", "abstained"}
)
_EVIDENCE_FIELDS_V1 = frozenset(
    {"task_id", "route_id", "verifier_ok", "measured_latency_ms", "measured_cost"}
)
_EVIDENCE_FIELDS_V2 = frozenset(
    {"task_id", "route_id", "verification", "measured_latency_ms", "measured_cost"}
)
_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "task",
        "candidates",
        "router",
        "decision",
        "baseline_route_id",
        "cost_unit",
        "data_origin",
        "baseline_evidence",
        "proposal_evidence",
    }
)


def record_observation(
    task: Task,
    candidates: list[CandidateRoute],
    *,
    baseline_route_id: str,
    cost_unit: str,
    data_origin: str,
    min_confidence: float = 0.9,
    baseline_evidence: Evidence | None = None,
    proposal_evidence: Evidence | None = None,
) -> dict[str, Any]:
    """Build a replayable observation from one shadow proposal.

    `data_origin` records whether the estimates describe a synthetic scenario
    or values reported by the caller. It never turns a report into a measurement.
    """
    if not isinstance(cost_unit, str) or not cost_unit.strip():
        raise ValueError("cost_unit must be a nonempty string.")
    if data_origin not in SUPPORTED_DATA_ORIGINS:
        raise ValueError(f"data_origin must be one of {list(SUPPORTED_DATA_ORIGINS)}.")

    decision = ShadowRouter(min_confidence=min_confidence).propose(task, candidates)

    route_ids = [candidate.route_id for candidate in candidates]
    if not isinstance(baseline_route_id, str) or baseline_route_id not in route_ids:
        raise ValueError("baseline_route_id must identify one of the candidates.")

    if baseline_evidence is not None:
        _check_evidence(
            baseline_evidence, task.task_id, baseline_route_id, "baseline_evidence"
        )
    if proposal_evidence is not None:
        if decision.abstained or decision.selected_route_id is None:
            raise ValueError(
                "proposal_evidence cannot be recorded when the router abstained."
            )
        _check_evidence(
            proposal_evidence,
            task.task_id,
            decision.selected_route_id,
            "proposal_evidence",
        )

    present = [
        evidence
        for evidence in (baseline_evidence, proposal_evidence)
        if evidence is not None
    ]
    attributed = [e for e in present if e.verification is not None]
    unattributed = [e for e in present if e.verification is None]
    if attributed and unattributed:
        raise ValueError(
            "Evidence must be either fully attributed or fully unattributed; a "
            "record cannot mix verifier-bound evidence with caller assertions."
        )
    schema_version = SCHEMA_VERSION if attributed else 1

    record = {
        "schema_version": schema_version,
        "task": {
            "task_id": task.task_id,
            "kind": task.kind,
            "risk_class": task.risk_class,
            "evidence_level": task.evidence_level,
            "locality": task.locality,
        },
        "candidates": [_candidate_to_record(c) for c in candidates],
        "router": {
            "policy_version": POLICY_VERSION,
            "min_confidence": min_confidence,
        },
        "decision": _decision_to_record(decision),
        "baseline_route_id": baseline_route_id,
        "cost_unit": cost_unit,
        "data_origin": data_origin,
        "baseline_evidence": (
            None
            if baseline_evidence is None
            else _evidence_to_record(baseline_evidence, schema_version)
        ),
        "proposal_evidence": (
            None
            if proposal_evidence is None
            else _evidence_to_record(proposal_evidence, schema_version)
        ),
    }
    replay_observation(record)
    return record


def replay_observation(record: Mapping[str, Any]) -> Decision:
    """Rebuild and re-run the recorded proposal under the recorded policy."""
    _validate_record(record)
    task = Task(
        task_id=record["task"]["task_id"],
        kind=record["task"]["kind"],
        inputs={},
        risk_class=record["task"]["risk_class"],
        evidence_level=record["task"]["evidence_level"],
        locality=record["task"]["locality"],
    )
    candidates = [_candidate_from_record(c) for c in record["candidates"]]
    decision = ShadowRouter(
        min_confidence=record["router"]["min_confidence"]
    ).propose(task, candidates)
    if _decision_to_record(decision) != dict(record["decision"]):
        raise ValueError(
            "Stored decision does not match a replay under policy "
            f"{POLICY_VERSION}; the record is stale or forged."
        )
    return decision


def compare_observation(record: Mapping[str, Any]) -> dict[str, Any]:
    """Compare one replayed proposal against its recorded baseline.

    Estimated and measured values stay separate. Measured deltas are only
    reported when both sides carry bound, verified measurements.
    """
    decision = replay_observation(record)
    candidates = {candidate["route_id"]: candidate for candidate in record["candidates"]}
    baseline = candidates[record["baseline_route_id"]]
    result: dict[str, Any] = {
        "task_id": record["task"]["task_id"],
        "baseline_route_id": record["baseline_route_id"],
        "proposed_route_id": decision.selected_route_id,
        "cost_unit": record["cost_unit"],
        "data_origin": record["data_origin"],
        "estimated_cost_delta": None,
        "measured_cost_delta": None,
        "measured_latency_delta_ms": None,
        "status": "abstained",
    }
    if decision.abstained:
        return result

    if decision.selected_route_id == record["baseline_route_id"]:
        result["estimated_cost_delta"] = _delta(
            baseline["estimated_cost"], baseline["estimated_cost"]
        )
        result["status"] = "baseline_selected"
        return result

    proposed = candidates[decision.selected_route_id]
    result["estimated_cost_delta"] = _delta(
        baseline["estimated_cost"], proposed["estimated_cost"]
    )

    baseline_evidence = record["baseline_evidence"]
    proposal_evidence = record["proposal_evidence"]
    if baseline_evidence is None or proposal_evidence is None:
        result["status"] = "insufficient_evidence"
        return result

    schema_version = record["schema_version"]
    baseline_verdict = _verdict_of(baseline_evidence, schema_version)
    proposal_verdict = _verdict_of(proposal_evidence, schema_version)
    if baseline_verdict is False or proposal_verdict is False:
        result["status"] = "verification_failed"
        return result
    if baseline_verdict is None or proposal_verdict is None:
        result["status"] = "verification_abstained"
        return result

    result["measured_cost_delta"] = _delta(
        baseline_evidence["measured_cost"], proposal_evidence["measured_cost"]
    )
    result["measured_latency_delta_ms"] = _delta(
        baseline_evidence["measured_latency_ms"],
        proposal_evidence["measured_latency_ms"],
    )
    if schema_version == 1:
        # Version 1 evidence is a caller assertion without verifier identity.
        result["status"] = "unattributed_evidence"
    else:
        result["status"] = (
            "verified_evidence"
            if result["measured_cost_delta"] is not None
            else "verified_without_measurements"
        )
    return result


def _verdict_of(evidence: Mapping[str, Any], schema_version: int) -> bool | None:
    if schema_version == 2:
        return evidence["verification"]["verdict"]
    return True if evidence["verifier_ok"] else False


def write_observation(path: str | Path, record: Mapping[str, Any]) -> None:
    """Write a validated observation without overwriting an existing file."""
    replay_observation(record)
    payload = json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)


def read_observation(path: str | Path) -> dict[str, Any]:
    """Read one observation, rejecting malformed or ambiguous JSON."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        record = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ValueError as exc:
        raise ValueError(f"Observation file is not valid JSON: {exc}") from exc
    _validate_record(record)
    return record


def _delta(baseline: float | None, proposal: float | None) -> float | None:
    if baseline is None or proposal is None:
        return None
    return baseline - proposal


def _candidate_to_record(candidate: CandidateRoute) -> dict[str, Any]:
    # known_failure_modes is free-form text and can carry sensitive payloads,
    # so it stays out of the replay record until it becomes stable IDs.
    return {
        "route_id": candidate.route_id,
        "capability_ids": list(candidate.capability_ids),
        "estimated_cost": candidate.estimated_cost,
        "estimated_latency_ms": candidate.estimated_latency_ms,
        "confidence": candidate.confidence,
    }


def _candidate_from_record(candidate: Mapping[str, Any]) -> CandidateRoute:
    return CandidateRoute(
        candidate["route_id"],
        list(candidate["capability_ids"]),
        candidate["estimated_cost"],
        candidate["estimated_latency_ms"],
        candidate["confidence"],
    )


def _evidence_to_record(evidence: Evidence, schema_version: int) -> dict[str, Any]:
    # metadata is caller-defined and therefore excluded from the record.
    record = {
        "task_id": evidence.task_id,
        "route_id": evidence.route_id,
        "verifier_ok": evidence.verifier_ok,
        "measured_latency_ms": evidence.measured_latency_ms,
        "measured_cost": evidence.measured_cost,
    }
    if schema_version == 2:
        if evidence.verification is None:
            raise ValueError("Version 2 evidence requires a verifier attribution.")
        del record["verifier_ok"]
        record["verification"] = evidence.verification.to_record()
    return record


def _decision_to_record(decision: Any) -> dict[str, Any]:
    return {
        "task_id": decision.task_id,
        "selected_route_id": decision.selected_route_id,
        "mode": decision.mode,
        "rationale": decision.rationale,
        "abstained": decision.abstained,
    }


def _check_optional_number(value: object, label: str) -> None:
    if value is None:
        return
    if not is_nonnegative_number(value):
        raise ValueError(f"{label} must be null or a finite nonnegative number.")


def _check_evidence(
    evidence: object, task_id: str, route_id: str, label: str
) -> None:
    if not isinstance(evidence, Evidence):
        raise ValueError(f"{label} must be an Evidence instance.")
    if evidence.task_id != task_id:
        raise ValueError(f"{label}.task_id must match the task it documents.")
    if evidence.route_id != route_id:
        raise ValueError(f"{label}.route_id must match the route it documents.")
    if not isinstance(evidence.verifier_ok, bool):
        raise ValueError(f"{label}.verifier_ok must be a boolean.")
    _check_optional_number(evidence.measured_latency_ms, f"{label}.measured_latency_ms")
    _check_optional_number(evidence.measured_cost, f"{label}.measured_cost")
    if evidence.verification is not None:
        if not isinstance(evidence.verification, Verification):
            raise ValueError(f"{label}.verification must be a Verification instance.")
        if evidence.verifier_ok is not (evidence.verification.verdict is True):
            raise ValueError(
                f"{label}.verifier_ok must match {label}.verification.verdict."
            )


def _require_exact_keys(
    value: object, expected: frozenset[str], label: str
) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    if set(value) != expected:
        raise ValueError(f"{label} must contain exactly {sorted(expected)}.")


def _validate_record(record: object) -> None:
    _require_exact_keys(record, _RECORD_FIELDS, "observation")
    schema_version = record["schema_version"]
    if type(schema_version) is not int or schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"Unsupported schema_version; expected one of {list(SUPPORTED_SCHEMA_VERSIONS)}."
        )

    task = record["task"]
    _require_exact_keys(task, _TASK_FIELDS, "task")
    for field in ("task_id", "kind", "risk_class", "evidence_level", "locality"):
        if not isinstance(task[field], str) or not task[field]:
            raise ValueError(f"task.{field} must be a nonempty string.")

    candidates = record["candidates"]
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a JSON array.")
    route_ids = set()
    for index, candidate in enumerate(candidates):
        label = f"candidates[{index}]"
        _require_exact_keys(candidate, _CANDIDATE_FIELDS, label)
        route_id = candidate["route_id"]
        if (
            not isinstance(route_id, str)
            or not route_id
            or route_id != route_id.strip()
            or route_id in route_ids
        ):
            raise ValueError(
                f"{label}.route_id must be a unique, trimmed, nonempty string."
            )
        route_ids.add(route_id)
        capability_ids = candidate["capability_ids"]
        if not isinstance(capability_ids, list) or not all(
            isinstance(value, str) and value for value in capability_ids
        ):
            raise ValueError(f"{label}.capability_ids must be a list of nonempty strings.")
        _check_optional_number(candidate["estimated_cost"], f"{label}.estimated_cost")
        _check_optional_number(
            candidate["estimated_latency_ms"], f"{label}.estimated_latency_ms"
        )
        confidence = candidate["confidence"]
        if confidence is not None and (
            not is_nonnegative_number(confidence) or confidence > 1
        ):
            raise ValueError(f"{label}.confidence must be null or in [0, 1].")

    router = record["router"]
    _require_exact_keys(router, _ROUTER_FIELDS, "router")
    if router["policy_version"] != POLICY_VERSION:
        raise ValueError(
            f"Unsupported policy_version; expected {POLICY_VERSION}."
        )
    try:
        ShadowRouter(min_confidence=router["min_confidence"])
    except ValueError as exc:
        raise ValueError(f"router.min_confidence is invalid: {exc}") from exc

    decision = record["decision"]
    _require_exact_keys(decision, _DECISION_FIELDS, "decision")
    if decision["task_id"] != task["task_id"]:
        raise ValueError("decision.task_id must match the task.")
    selected = decision["selected_route_id"]
    if selected is not None and not isinstance(selected, str):
        raise ValueError("decision.selected_route_id must be null or a string.")
    if selected is not None and selected not in route_ids:
        raise ValueError("decision.selected_route_id must identify a candidate.")
    if decision["mode"] != "shadow":
        raise ValueError("decision.mode must be 'shadow'; active routing is unsupported.")
    if not isinstance(decision["rationale"], str):
        raise ValueError("decision.rationale must be a string.")
    if not isinstance(decision["abstained"], bool):
        raise ValueError("decision.abstained must be a boolean.")
    if decision["abstained"] != (selected is None):
        raise ValueError("decision.abstained and selected_route_id disagree.")

    baseline_route_id = record["baseline_route_id"]
    if not isinstance(baseline_route_id, str) or baseline_route_id not in route_ids:
        raise ValueError("baseline_route_id must identify one of the candidates.")
    if not isinstance(record["cost_unit"], str) or not record["cost_unit"].strip():
        raise ValueError("cost_unit must be a nonempty string.")
    if record["data_origin"] not in SUPPORTED_DATA_ORIGINS:
        raise ValueError(
            f"data_origin must be one of {list(SUPPORTED_DATA_ORIGINS)}."
        )

    baseline_evidence = record["baseline_evidence"]
    if baseline_evidence is not None:
        _validate_evidence_record(
            baseline_evidence,
            task["task_id"],
            baseline_route_id,
            "baseline_evidence",
            schema_version,
        )
    proposal_evidence = record["proposal_evidence"]
    if proposal_evidence is not None:
        if selected is None:
            raise ValueError("proposal_evidence is present but the decision abstained.")
        _validate_evidence_record(
            proposal_evidence,
            task["task_id"],
            selected,
            "proposal_evidence",
            schema_version,
        )


def _validate_evidence_record(
    evidence: object, task_id: str, route_id: str, label: str, schema_version: int
) -> None:
    if schema_version == 2:
        _require_exact_keys(evidence, _EVIDENCE_FIELDS_V2, label)
        try:
            validate_verification_record(evidence["verification"])
        except ValueError as exc:
            raise ValueError(f"{label}.verification is invalid: {exc}") from exc
    else:
        _require_exact_keys(evidence, _EVIDENCE_FIELDS_V1, label)
        if not isinstance(evidence["verifier_ok"], bool):
            raise ValueError(f"{label}.verifier_ok must be a boolean.")
    if evidence["task_id"] != task_id:
        raise ValueError(f"{label}.task_id must match the observation task.")
    if evidence["route_id"] != route_id:
        raise ValueError(f"{label}.route_id must match the route it documents.")
    _check_optional_number(evidence["measured_latency_ms"], f"{label}.measured_latency_ms")
    _check_optional_number(evidence["measured_cost"], f"{label}.measured_cost")


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite number {value!r} is not supported")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r} is not allowed")
        result[key] = value
    return result
