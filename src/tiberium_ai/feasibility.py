"""Bounded, declarative feasibility checks; no route or model is executed.

An impossibility verdict concerns the supplied finite Boolean model only.
Sources and observations are caller assertions, not authenticated world facts.
"""

from __future__ import annotations

import itertools
from typing import Any

from .verification import VerifierRegistry, hash_input

REQUEST_SCHEMA = "parcimonia.feasibility-request/v1"
REPORT_SCHEMA = "parcimonia.feasibility-report/v1"
VERIFIER_ID = "boolean-feasibility-report"
VERIFIER_VERSION = "1"
MAX_VARIABLES = 12

__all__ = [
    "REQUEST_SCHEMA", "REPORT_SCHEMA", "VERIFIER_ID", "VERIFIER_VERSION",
    "MAX_VARIABLES", "diagnose", "register_feasibility_verifier",
]


def _object(value: Any, required: set[str], optional: set[str], label: str) -> None:
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object.")
    if not required <= value.keys() or value.keys() - required - optional:
        raise ValueError(f"{label} has missing or unsupported fields.")


def _text(value: Any, label: str) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{label} must be a nonempty, trimmed string.")
    if len(value) > 4096:
        raise ValueError(f"{label} exceeds the 4096-character limit.")


def _array(value: Any, label: str, maximum: int) -> None:
    if type(value) is not list or len(value) > maximum:
        raise ValueError(f"{label} must be an array of at most {maximum} entries.")


def _literal(value: Any, variables: set[str], label: str) -> None:
    _object(value, {"variable", "value"}, set(), label)
    _text(value["variable"], f"{label}.variable")
    if value["variable"] not in variables:
        raise ValueError(f"{label} references an unknown variable.")
    if type(value["value"]) is not bool:
        raise ValueError(f"{label}.value must be a boolean.")


def _validate(request: Any, max_variables: Any) -> list[dict[str, Any]]:
    if type(max_variables) is not int or not 0 <= max_variables <= MAX_VARIABLES:
        raise ValueError(f"max_variables must be an integer from 0 to {MAX_VARIABLES}.")
    _object(
        request,
        {"schema", "task_id", "scope_id", "revision", "variables", "constraints"},
        {"observations", "criteria"},
        "request",
    )
    if request["schema"] != REQUEST_SCHEMA:
        raise ValueError("Unsupported request schema.")
    for field in ("task_id", "scope_id", "revision"):
        _text(request[field], field)
    _array(request["variables"], "variables", 128)
    for variable in request["variables"]:
        _text(variable, "variable")
    variables = set(request["variables"])
    if len(variables) != len(request["variables"]):
        raise ValueError("Duplicate variables are not allowed.")
    _array(request["constraints"], "constraints", 256)
    identifiers: set[str] = set()
    unsupported: list[dict[str, Any]] = []
    for constraint in request["constraints"]:
        if type(constraint) is not dict:
            raise ValueError("constraint must be a JSON object.")
        for field in ("id", "kind", "source"):
            _text(constraint.get(field), f"constraint.{field}")
        if constraint["id"] in identifiers:
            raise ValueError("Duplicate constraint IDs are not allowed.")
        identifiers.add(constraint["id"])
        kind = constraint["kind"]
        if kind == "require":
            _object(constraint, {"id", "kind", "source", "variable", "value"}, set(), "require")
            _literal({key: constraint[key] for key in ("variable", "value")}, variables, "require")
        elif kind == "implies":
            _object(constraint, {"id", "kind", "source", "if", "then"}, set(), "implies")
            _literal(constraint["if"], variables, "implies.if")
            _literal(constraint["then"], variables, "implies.then")
        else:
            # An opaque extension marker can request abstention; it cannot
            # smuggle unsupported fields into a known constraint's meaning.
            _object(constraint, {"id", "kind", "source"}, set(), "unsupported constraint")
            unsupported.append(constraint)
    observations = request.get("observations", [])
    _array(observations, "observations", 128)
    observed: set[str] = set()
    for observation in observations:
        _object(observation, {"variable", "value", "source", "revision"}, set(), "observation")
        _text(observation["variable"], "observation.variable")
        if observation["variable"] not in variables:
            raise ValueError("Observation references an unknown variable.")
        if observation["variable"] in observed:
            raise ValueError("Duplicate observations are not allowed.")
        observed.add(observation["variable"])
        if observation["value"] is not None and type(observation["value"]) is not bool:
            raise ValueError("observation.value must be a boolean or null.")
        for field in ("source", "revision"):
            _text(observation[field], f"observation.{field}")
        if observation["revision"] != request["revision"]:
            raise ValueError("Observation revision must match the request revision.")
    criteria = request.get("criteria", [])
    _array(criteria, "criteria", 128)
    criterion_ids: set[str] = set()
    for criterion in criteria:
        _object(criterion, {"id", "status", "source"}, set(), "criterion")
        for field in ("id", "status", "source"):
            _text(criterion[field], f"criterion.{field}")
        if criterion["id"] in criterion_ids:
            raise ValueError("Duplicate criterion IDs are not allowed.")
        criterion_ids.add(criterion["id"])
        if criterion["status"] not in {"pass", "fail", "unknown"}:
            raise ValueError("criterion.status must be pass, fail or unknown.")
    # Keep the binding to the *original* request, including optional-field
    # omission. Validation above rejects coercible, non-JSON container types.
    hash_input(request)
    return unsupported


def _matches(assignment: dict[str, bool], literal: dict[str, Any]) -> bool:
    return assignment[literal["variable"]] is literal["value"]


def _satisfies(assignment: dict[str, bool], constraint: dict[str, Any]) -> bool:
    if constraint["kind"] == "require":
        return _matches(assignment, constraint)
    return not _matches(assignment, constraint["if"]) or _matches(assignment, constraint["then"])


def diagnose(request: dict[str, Any], *, max_variables: int = MAX_VARIABLES) -> dict[str, Any]:
    """Return a deterministic report about a caller-supplied Boolean model.

    Malformed input raises ValueError. A valid request outside the supported
    search budget or carrying an opaque constraint kind returns indeterminate.
    The maximum search space is 4096 assignments, without recursive solving.
    """
    unsupported = _validate(request, max_variables)
    variables = sorted(request["variables"])
    constraints = sorted(request["constraints"], key=lambda item: item["id"])
    observations = {item["variable"]: item for item in request.get("observations", [])}
    criteria = sorted(request.get("criteria", []), key=lambda item: item["id"])
    quality = "indeterminate"
    if any(item["status"] == "fail" for item in criteria):
        quality = "declared_criteria_fail"
    elif criteria and all(item["status"] == "pass" for item in criteria):
        quality = "declared_criteria_pass"
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "task_id": request["task_id"],
        "scope_id": request["scope_id"],
        "revision": request["revision"],
        "input_hash": hash_input(request),
        "engine": {"id": "boolean-feasibility", "version": "1"},
        "mode": "shadow",
        "feasibility": "indeterminate",
        "quality": quality,
        "completeness": "indeterminate",
        "findings": [],
        "conditions": [],
        "next_checks": [],
        "proof": None,
        "limits": {
            "max_variables": max_variables,
            "actual_variables": len(variables),
            "world_feasibility": "not_established",
            "sources": "caller_supplied_unverified",
            "savings": "not_measured",
        },
    }
    for criterion in criteria:
        if criterion["status"] != "pass":
            report["findings"].append({
                "code": "declared_criterion_" + criterion["status"],
                "criterion_id": criterion["id"],
                "constraint_ids": [],
                "sources": [criterion["source"]],
            })
    if unsupported or len(variables) > max_variables:
        if unsupported:
            report["findings"].append({
                "code": "unsupported_constraint_kind",
                "constraint_ids": [
                    item["id"]
                    for item in sorted(unsupported, key=lambda item: item["id"])
                ],
                "sources": sorted({item["source"] for item in unsupported}),
            })
            report["next_checks"].append({"code": "use_a_verifier_for_unsupported_constraints"})
        if len(variables) > max_variables:
            report["findings"].append({
                "code": "variable_budget_exceeded", "constraint_ids": [], "sources": [],
            })
            report["next_checks"].append({"code": "reduce_or_partition_the_declared_model"})
        return report

    models: list[dict[str, bool]] = []
    for values in itertools.product((False, True), repeat=len(variables)):
        assignment = dict(zip(variables, values))
        if all(_satisfies(assignment, item) for item in constraints):
            models.append(assignment)
    known_observations = {
        name: item for name, item in observations.items() if item["value"] is not None
    }
    compatible = [
        assignment for assignment in models
        if all(assignment[name] is item["value"] for name, item in known_observations.items())
    ]
    constraint_ids = [item["id"] for item in constraints]
    sources = sorted({item["source"] for item in constraints})
    report["proof"] = {
        "kind": "exhaustive_boolean_search",
        "assignments_checked": 2 ** len(variables),
        "satisfying_assignments": len(models),
        "observed_compatible_assignments": len(compatible),
        "constraint_ids": constraint_ids,
        "witness": models[0] if models else None,
        "current_state_witness": compatible[0] if compatible else None,
    }
    if not models:
        report["feasibility"] = "impossible_within_constraints"
        report["findings"].append({
            "code": "constraint_conflict", "constraint_ids": constraint_ids, "sources": sources,
        })
        report["next_checks"].append({"code": "review_the_declared_constraints"})
        return report

    report["feasibility"] = (
        "consistent_within_constraints" if compatible else "blocked_current_state"
    )
    if not compatible:
        report["findings"].append({
            "code": "observations_conflict_with_constraints",
            "constraint_ids": constraint_ids,
            "sources": sorted(
                set(sources) | {item["source"] for item in known_observations.values()}
            ),
        })
        report["next_checks"].append({"code": "review_observations_and_constraints"})
    for variable in variables:
        required = models[0][variable]
        if any(assignment[variable] is not required for assignment in models[1:]):
            continue
        observation = observations.get(variable)
        observed_value = observation["value"] if observation else None
        if observation is None:
            status = "unobserved"
        elif observed_value is None:
            status = "unknown"
        else:
            status = "matched" if observed_value is required else "mismatch"
        report["conditions"].append({
            "variable": variable, "value": required,
            "observed": observed_value, "status": status,
        })
        if status == "matched":
            continue
        report["findings"].append({
            "code": "missing_prerequisite" if status == "mismatch" else "unobserved_prerequisite",
            "variable": variable,
            "expected": required,
            "observed": observed_value,
            "constraint_ids": constraint_ids,
            "sources": sorted(set(sources) | ({observation["source"]} if observation else set())),
        })
        report["next_checks"].append({
            "code": "restore_required_value" if status == "mismatch" else "observe_required_value",
            "variable": variable, "value": required,
        })
    statuses = [item["status"] for item in report["conditions"]]
    if "mismatch" in statuses:
        report["completeness"] = "missing_prerequisites"
    elif compatible and statuses and all(status == "matched" for status in statuses):
        report["completeness"] = "known_requirements_present"
    return report


def register_feasibility_verifier(registry: VerifierRegistry) -> None:
    """Register replay verification for {request, report}, not source truth.

    Exact canonical JSON comparison rejects Boolean/integer substitutions and
    additional fields, which ordinary Python container equality would accept.
    """
    def verify(value: Any) -> bool:
        try:
            _object(value, {"request", "report"}, set(), "verification input")
            report = value["report"]
            if type(report) is not dict or type(report.get("limits")) is not dict:
                return False
            budget = report["limits"].get("max_variables")
            recomputed = diagnose(value["request"], max_variables=budget)
            return hash_input(report) == hash_input(recomputed)
        except (TypeError, ValueError, KeyError):
            return False

    registry.register(VERIFIER_ID, VERIFIER_VERSION, verify)
