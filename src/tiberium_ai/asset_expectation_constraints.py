"""Certificates for independent scalar constraints in asset expectations.

No source/report is inspected. A candidate assigns declared facts, not a real
file. Relations between different facts are deliberately outside this model.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .asset_catalog_snapshot import _canonical_size
from .asset_expectations import _fact_type, _MAX_INTEGER, _validate_expectations
from .asset_tag_journal import _object, _text, _validate_report_json
from .verification import VerifierRegistry, hash_input

__all__ = [
    "MAX_CONSISTENCY_BYTES", "check_asset_expectations",
    "verify_asset_expectation_constraints", "register_asset_expectation_verifier",
]

MAX_CONSISTENCY_BYTES = 256 * 1024
_SCHEMA = "parcimonia.asset-expectation-consistency/v1"
_ANALYSER = {"id": "asset-expectation-consistency", "version": "1"}
_VERIFIER = "asset-expectation-constraints"
_CLEAR = "no_conflict_detected"
_CONFLICT = "contradictory"
_LIMITS = {
    "model": "independent_required_scalar_facts_only",
    "integer_domain": [0, _MAX_INTEGER],
    "cross_fact_relations": "not_modelled",
    "producer_profile_caps": "not_modelled",
    "candidates": "assignments_not_observed_file_values",
    "file_existence_quality_completeness": "not_established",
    "inputs": "caller_supplied_expectations_not_authenticated",
    "model_calls": 0, "file_mutations": 0,
}


def _groups(asset: dict[str, Any]) -> dict[str, list[tuple[int, dict[str, Any]]]]:
    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, check in enumerate(asset["checks"]):
        groups.setdefault(check["fact"], []).append((index, check))
    return groups


def _status(rows: list[dict[str, Any]]) -> str:
    return _CONFLICT if any(row["status"] == _CONFLICT for row in rows) else _CLEAR


def _input_hash(expectations: dict[str, Any]) -> str:
    return hash_input({"analyser": _ANALYSER, "expectations": expectations})


def _fact_result(asset_index: int, fact: str, group: list[tuple[int, dict[str, Any]]]) -> dict[str, Any]:
    pair = None
    if _fact_type(fact) == "integer":
        lower, upper = 0, _MAX_INTEGER
        lower_rule = upper_rule = None
        for index, check in group:
            value = check["value"]
            if check["op"] in {"eq", "gte"} and value >= lower:
                if value > lower or lower_rule is None:
                    lower, lower_rule = value, (index, check)
            if check["op"] in {"eq", "lte"} and value <= upper:
                if value < upper or upper_rule is None:
                    upper, upper_rule = value, (index, check)
        if lower > upper:
            pair = (lower_rule, upper_rule)
        candidate = lower
        kind = "disjoint_integer_bounds"
    else:
        first = group[0]
        candidate = first[1]["value"]
        pair = next(((first, entry) for entry in group[1:] if entry[1]["value"] != candidate), None)
        kind = "different_exact_values"
    conflict = None
    if pair is not None:
        conflict = {
            "kind": kind,
            "check_ids": [entry[1]["id"] for entry in pair],
            "check_paths": [f"/assets/{asset_index}/checks/{entry[0]}" for entry in pair],
        }
    return {
        "fact": fact, "status": _CONFLICT if conflict else _CLEAR,
        "check_ids": [check["id"] for _, check in group],
        "candidate": None if conflict else candidate, "conflict": conflict,
    }


def check_asset_expectations(expectations: dict[str, Any]) -> dict[str, Any]:
    """Find same-fact conflicts and give certificates for every declared fact.

    A conflict is a pair of individually allowed but incompatible checks.
    With no conflict, the per-fact candidates satisfy the independent model;
    they do not assert that a corresponding real file exists.
    """
    _validate_expectations(expectations)
    results = []
    for index, asset in enumerate(expectations["assets"]):
        groups = _groups(asset)
        facts = [_fact_result(index, fact, groups[fact]) for fact in sorted(groups)]
        results.append({"source": deepcopy(asset["source"]), "status": _status(facts), "facts": facts})
    report = {
        "schema": _SCHEMA, "analyser": dict(_ANALYSER), "mode": "shadow",
        "input_hash": _input_hash(expectations),
        "expectations": {"id": expectations["id"], "hash": hash_input(expectations)},
        "status": _status(results), "results": results, "limits": deepcopy(_LIMITS),
    }
    _canonical_size(report, MAX_CONSISTENCY_BYTES, "Expectation consistency report")
    return report


def _holds(value: Any, check: dict[str, Any]) -> bool:
    if check["op"] == "eq":
        return value == check["value"]
    if check["op"] == "gte":
        return value >= check["value"]
    return value <= check["value"]


def _candidate_type(value: Any, fact: str) -> None:
    kind = _fact_type(fact)
    if kind == "integer":
        if type(value) is not int or not 0 <= value <= _MAX_INTEGER:
            raise ValueError("Candidate must belong to the exact integer domain.")
    elif kind == "text":
        _text(value, "candidate", 256)
    elif kind == "boolean":
        if type(value) is not bool:
            raise ValueError("Candidate must be an exact boolean.")
    elif value is not True:
        raise ValueError("Proposal-presence candidates must be true.")


def _verify_conflict(fact: str, conflict: Any, group: list[tuple[int, dict[str, Any]]], asset_index: int) -> bool:
    _object(conflict, {"kind", "check_ids", "check_paths"}, "conflict")
    ids, paths = conflict["check_ids"], conflict["check_paths"]
    if type(ids) is not list or len(ids) != 2 or any(type(i) is not str for i in ids) or ids[0] == ids[1]:
        return False
    by_id = {check["id"]: (index, check) for index, check in group}
    if not all(ident in by_id for ident in ids):
        return False
    selected = [by_id[ident] for ident in ids]
    if paths != [f"/assets/{asset_index}/checks/{index}" for index, _ in selected]:
        return False
    pair = [check for _, check in selected]
    if _fact_type(fact) == "integer":
        if conflict["kind"] != "disjoint_integer_bounds":
            return False
        # Independent of the producer's global lower/upper scan: any nonempty
        # intersection of these two allowed intervals contains one endpoint
        # in this four-value set. No enumeration of the 63-bit domain is needed.
        probes = {0, _MAX_INTEGER, pair[0]["value"], pair[1]["value"]}
        return not any(all(_holds(value, check) for check in pair) for value in probes)
    return conflict["kind"] == "different_exact_values" and pair[0]["value"] != pair[1]["value"]


def verify_asset_expectation_constraints(expectations: Any, report: Any) -> bool:
    """Validate all assignments/conflict pairs without rerunning the producer.

    Any valid candidate or conflicting pair is accepted, even if noncanonical.
    A true verdict certifies only the input-bound independent-fact model.
    """
    try:
        _validate_expectations(expectations)
        _validate_report_json(report)
        _canonical_size(report, MAX_CONSISTENCY_BYTES, "Expectation consistency report")
        _object(report, {"schema", "analyser", "mode", "input_hash", "expectations", "status", "results", "limits"}, "consistency report")
        if (report["schema"] != _SCHEMA or report["analyser"] != _ANALYSER
                or report["mode"] != "shadow" or report["input_hash"] != _input_hash(expectations)):
            return False
        if report["expectations"] != {"id": expectations["id"], "hash": hash_input(expectations)}:
            return False
        if hash_input(report["limits"]) != hash_input(_LIMITS):
            return False
        results = report["results"]
        if type(results) is not list or len(results) != len(expectations["assets"]):
            return False
        for asset_index, (asset, result) in enumerate(zip(expectations["assets"], results)):
            _object(result, {"source", "status", "facts"}, "asset result")
            if result["source"] != asset["source"]:
                return False
            groups = _groups(asset)
            facts = result["facts"]
            if type(facts) is not list or len(facts) != len(groups):
                return False
            for fact, entry in zip(sorted(groups), facts):
                _object(entry, {"fact", "status", "check_ids", "candidate", "conflict"}, "fact result")
                group = groups[fact]
                if entry["fact"] != fact or entry["check_ids"] != [check["id"] for _, check in group]:
                    return False
                if entry["status"] == _CLEAR:
                    _candidate_type(entry["candidate"], fact)
                    if entry["conflict"] is not None or not all(_holds(entry["candidate"], check) for _, check in group):
                        return False
                elif entry["status"] == _CONFLICT:
                    if entry["candidate"] is not None or not _verify_conflict(fact, entry["conflict"], group, asset_index):
                        return False
                else:
                    return False
            if result["status"] != _status(facts):
                return False
        return report["status"] == _status(results)
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError):
        return False


def register_asset_expectation_verifier(registry: VerifierRegistry) -> None:
    """Register certificate checking for {expectations, report} JSON packets."""
    def verify(value: Any) -> bool:
        if type(value) is not dict or set(value) != {"expectations", "report"}:
            return False
        return verify_asset_expectation_constraints(value["expectations"], value["report"])

    registry.register(_VERIFIER, "1", verify)
