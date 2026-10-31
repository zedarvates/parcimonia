"""Compare explicit asset expectations with exact supplied report declarations.

Missing reports, unknown facts and contradicted expectations are distinct.
No source is read, no negative fact is inferred from a missing proposal, and
no comparison authenticates the source or certifies its semantic quality.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .asset_catalog import MAX_REPORTS
from .asset_catalog_snapshot import MAX_SNAPSHOT_BYTES, _canonical_size, _report_hash
from .asset_tag_journal import _object, _text, _validate_report_json
from .verification import hash_input

__all__ = ["EXPECTATIONS_SCHEMA", "MAX_EXPECTATIONS_BYTES", "MAX_AUDIT_BYTES", "audit_asset_expectations"]

EXPECTATIONS_SCHEMA = "parcimonia.asset-expectations/v1"
AUDIT_SCHEMA = "parcimonia.asset-expectation-audit/v1"
MAX_EXPECTATIONS_BYTES = 64 * 1024
MAX_AUDIT_BYTES = 16 * 1024 * 1024
_MAX_OBSERVATION_BYTES = 16 * 1024
_MAX_ASSETS = 64
_MAX_CHECKS = 256
_MAX_CHECKS_PER_ASSET = 32
_MAX_INTEGER = 2**63 - 1
_ANALYSER = {"id": "asset-expectation-audit", "version": "1"}
_NUMERIC_FACTS = {
    "sample.bytes", "spatial.position_count",
    *(f"metadata.{name}" for name in (
        "width", "height", "channels", "sample_rate", "bits_per_sample",
        "declared_frames", "observed_vertex_count", "observed_face_count",
        "observed_field_value_count", "position_count",
    )),
}
_TEXT_FACTS = {"format.detected", "spatial.crs", "metadata.observed_ply_encoding"}
_STATES = ("satisfied", "contradicted", "unknown", "missing_report")


def _integer(value: Any, label: str) -> None:
    if type(value) is not int or not 0 <= value <= _MAX_INTEGER:
        raise ValueError(f"{label} must be a nonnegative 63-bit integer, not a boolean.")


def _fact_type(fact: Any) -> str:
    _text(fact, "check.fact", 512)
    if fact in _NUMERIC_FACTS:
        return "integer"
    if fact in _TEXT_FACTS:
        return "text"
    if fact == "sample.complete":
        return "boolean"
    if fact.startswith("tag:"):
        namespace, separator, value = fact[4:].partition(":")
        if not separator:
            raise ValueError("Tag facts must use tag:namespace:value syntax.")
        _text(namespace, "tag namespace", 128)
        _text(value, "tag value", 256)
        return "proposal"
    raise ValueError("Unsupported expectation fact; arbitrary paths are not evaluated.")


def _validate_expectations(expectations: Any) -> None:
    _validate_report_json(expectations)
    _canonical_size(expectations, MAX_EXPECTATIONS_BYTES, "Expectations")
    _object(expectations, {"schema", "id", "assets"}, "expectations")
    if expectations["schema"] != EXPECTATIONS_SCHEMA:
        raise ValueError("Unsupported expectations schema.")
    _text(expectations["id"], "expectations.id", 128)
    assets = expectations["assets"]
    if type(assets) is not list or not 1 <= len(assets) <= _MAX_ASSETS:
        raise ValueError("Expectations must contain 1..64 assets.")
    seen_sources: set[tuple[str, str]] = set()
    count = 0
    for asset in assets:
        _object(asset, {"source", "checks"}, "expected asset")
        _object(asset["source"], {"id", "revision"}, "expected source")
        for key in ("id", "revision"):
            _text(asset["source"][key], "expected source." + key)
        identity = (asset["source"]["id"], asset["source"]["revision"])
        if identity in seen_sources:
            raise ValueError("Expected source identities must be unique.")
        seen_sources.add(identity)
        checks = asset["checks"]
        if type(checks) is not list or not 1 <= len(checks) <= _MAX_CHECKS_PER_ASSET:
            raise ValueError("Each expected asset needs 1..32 checks.")
        count += len(checks)
        if count > _MAX_CHECKS:
            raise ValueError("Expectations are limited to 256 checks in total.")
        seen_checks: set[str] = set()
        for check in checks:
            _object(check, {"id", "fact", "op", "value"}, "expectation check")
            _text(check["id"], "check.id", 128)
            if check["id"] in seen_checks:
                raise ValueError("Check IDs must be unique within an asset.")
            seen_checks.add(check["id"])
            kind = _fact_type(check["fact"])
            if type(check["op"]) is not str or check["op"] not in {"eq", "gte", "lte"}:
                raise ValueError("check.op must be eq, gte or lte.")
            if kind == "integer":
                _integer(check["value"], "check.value")
            else:
                if check["op"] != "eq":
                    raise ValueError("Only integer facts support ordering comparisons.")
                if kind == "text":
                    _text(check["value"], "check.value", 256)
                elif kind == "boolean" and type(check["value"]) is not bool:
                    raise ValueError("sample.complete expects a boolean.")
                elif kind == "proposal" and check["value"] is not True:
                    raise ValueError("Tag checks only ask for proposal presence with value true.")


def _observation(value: Any, basis: str, paths: list[str], refs: list[str]) -> dict[str, Any]:
    return {"value": value, "basis": basis, "paths": paths, "evidence_refs": sorted(set(refs))}


def _observe(report: dict[str, Any], fact: str) -> dict[str, Any] | None:
    if fact.startswith("tag:"):
        namespace, _, value = fact[4:].partition(":")
        matches = [(index, tag) for index, tag in enumerate(report["tag_proposals"])
                   if tag["namespace"] == namespace and tag["value"] == value]
        if not matches:
            return None  # Missing proposals are not evidence of absent content.
        result = _observation(True, "proposal_presence", [f"/tag_proposals/{i}" for i, _ in matches],
                              [ref for _, tag in matches for ref in tag["evidence_refs"]])
        result["proposal_bases"] = sorted({tag["basis"] for _, tag in matches})
        return result
    section, name = fact.split(".")
    if section == "metadata":
        matches = [(i, item) for i, item in enumerate(report["metadata"])
                   if type(item) is dict and item.get("name") == name]
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError("A selected metadata fact is ambiguous.")
        index, item = matches[0]
        _object(item, {"name", "value", "basis", "evidence_ref"}, "selected metadata")
        _text(item["basis"], "metadata.basis")
        _text(item["evidence_ref"], "metadata.evidence_ref")
        if item["evidence_ref"] not in {evidence["id"] for evidence in report["evidence"]}:
            raise ValueError("Selected metadata must reference existing report evidence.")
        value = item["value"]
        observation = _observation(value, item["basis"], [f"/metadata/{index}/value"], [item["evidence_ref"]])
    else:
        container = report[section]
        if container is None or name not in container or container[name] is None:
            return None
        value = container[name]
        basis = "sample_declaration" if section == "sample" else "spatial_declaration"
        if section == "format":
            basis = container.get("basis")
            _text(basis, "format.basis")
        observation = _observation(value, basis, [f"/{section}/{name}"], [])
    if value is None:
        return None
    if fact in _NUMERIC_FACTS:
        _integer(value, "observed " + fact)
    elif fact in _TEXT_FACTS:
        _text(value, "observed " + fact)
    elif type(value) is not bool:
        raise ValueError("Observed sample.complete must be boolean.")
    return observation


def audit_asset_expectations(
    reports: list[dict[str, Any]], expectations: dict[str, Any],
) -> dict[str, Any]:
    """Return an advisory comparison, binding every exact report and contract.

    Target identity is (source ID, revision), without filename or revision
    fallback. Satisfied means the supplied declaration meets the explicit
    comparison; it is not automatic tag acceptance or source validation.
    """
    _validate_expectations(expectations)
    if type(reports) is not list or len(reports) > MAX_REPORTS:
        raise ValueError(f"reports must be an array of at most {MAX_REPORTS} entries.")
    for report in reports:
        _validate_report_json(report)
    _canonical_size(reports, MAX_SNAPSHOT_BYTES, "Report array")
    indexed: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
    references = []
    for report in reports:
        digest = _report_hash(report)
        source = report["source"]
        identity = (source["id"], source["revision"])
        if identity in indexed:
            raise ValueError("Duplicate report identity and revision are ambiguous.")
        indexed[identity] = (report, digest)
        references.append({"source": deepcopy(source), "report_hash": digest})
    results = []
    for asset in expectations["assets"]:
        source = asset["source"]
        found = indexed.get((source["id"], source["revision"]))
        report, digest = found if found else (None, None)
        checks = []
        for check in asset["checks"]:
            observation = _observe(report, check["fact"]) if report is not None else None
            if observation is not None:
                _canonical_size(observation, _MAX_OBSERVATION_BYTES, "Selected fact proof")
            status = "unknown"
            reason = "report_not_supplied" if report is None else "fact_not_available"
            if observation is not None:
                actual, expected = observation["value"], check["value"]
                matches = (actual == expected if check["op"] == "eq" else
                           actual >= expected if check["op"] == "gte" else actual <= expected)
                status = "satisfied" if matches else "contradicted"
                reason = "declared_fact_matches" if matches else "declared_fact_conflicts"
            checks.append({**deepcopy(check), "status": status, "reason": reason, "observation": observation})
        statuses = {check["status"] for check in checks}
        status = ("missing_report" if report is None else "contradicted" if "contradicted" in statuses
                  else "unknown" if "unknown" in statuses else "satisfied")
        results.append({
            "source": deepcopy(source), "report_hash": digest,
            "status": status, "checks": checks,
        })
    summary = {status: sum(result["status"] == status for result in results) for status in _STATES}
    audit = {
        "schema": AUDIT_SCHEMA, "analyser": dict(_ANALYSER), "mode": "shadow",
        "input_hash": hash_input({"analyser": _ANALYSER, "reports": reports, "expectations": expectations}),
        "expectations": {"id": expectations["id"], "hash": hash_input(expectations)},
        "reports": references, "results": results, "summary": summary,
        "limits": {
            "inputs": "caller_supplied_declarations_not_authenticated_or_replayed",
            "missing_report": "absent_from_supplied_array_not_proof_of_missing_file",
            "unknown": "no_negative_inference_from_missing_fact_or_tag",
            "satisfied": "explicit_comparison_only_not_quality_or_tag_acceptance",
            "scope": "listed_facts_only_not_general_impossibility_or_stability_analysis",
            "review_decisions": "not_applied", "file_mutations": 0, "model_calls": 0,
        },
    }
    _canonical_size(audit, MAX_AUDIT_BYTES, "Expectation audit")
    return audit
