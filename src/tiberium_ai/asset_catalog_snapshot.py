"""Pure immutable snapshots selecting one current inspection per source ID.

Canonical sizes and hashes use compact JSON with sorted keys, ensure_ascii=False
and allow_nan=False, encoded as UTF-8 without a trailing newline. Snapshot size
includes snapshot_hash; that hash covers the other five fields only.

Hashes establish internal consistency, not authenticated provenance, a storage
lock or recursively verified history. Revisions are opaque labels. Mutations
return independent values and never change assets or review journals.
"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from .asset_catalog import MAX_REPORTS
from .asset_tag_journal import _validate_report_json, validated_review_report_hash
from .verification import hash_input

__all__ = [
    "SNAPSHOT_SCHEMA", "MAX_REPORTS", "MAX_REPORT_BYTES", "MAX_SNAPSHOT_BYTES",
    "MAX_SNAPSHOT_NODES", "MAX_SNAPSHOT_DEPTH", "create_asset_catalog",
    "validate_asset_catalog", "put_asset_report", "remove_asset_report",
    "export_asset_reports",
]

SNAPSHOT_SCHEMA = "parcimonia.asset-catalog-snapshot/v1"
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_NODES = 200_000
MAX_SNAPSHOT_DEPTH = 64
_MAX_GENERATION = 2**63 - 1
_FIELDS = {
    "schema", "catalog_id", "generation", "parent_hash", "reports", "snapshot_hash",
}
_ENCODER = json.JSONEncoder(
    sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
)


def _text(value: Any, label: str) -> None:
    if type(value) is not str or not value or value != value.strip() or len(value) > 4096:
        raise ValueError(f"{label} must be a trimmed string of 1..4096 characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8 text.") from exc


def _hash(value: Any, label: str) -> None:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hexadecimal string.")


def _canonical_size(value: Any, maximum: int, label: str) -> None:
    """Count encoded chunks only after strict JSON-type/cycle validation."""
    size = 0
    try:
        for chunk in _ENCODER.iterencode(value):
            size += len(chunk.encode("utf-8"))
            if size > maximum:
                raise ValueError(f"{label} canonical UTF-8 JSON exceeds {maximum} bytes.")
    except (TypeError, UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError(f"{label} must be finite UTF-8 JSON.") from exc


def _report_hash(report: Any) -> str:
    # This first shared validation refuses foreign Python values and cycles
    # before the serializer or deepcopy can traverse them. Check the byte cap
    # before asking the shared report boundary to hash its canonical form.
    _validate_report_json(report)
    _canonical_size(report, MAX_REPORT_BYTES, "Inspection report")
    return validated_review_report_hash(report)


def _snapshot_budget(snapshot: dict[str, Any]) -> None:
    # The envelope and each report have already been strictly validated. Count
    # repeated acyclic subobjects on every occurrence, as JSON serialization
    # and the file reader do. Reservations also bound the pending queue.
    pending = [(snapshot, 0)]
    reserved = 1
    while pending:
        value, depth = pending.pop()
        if depth > MAX_SNAPSHOT_DEPTH:
            raise ValueError(f"Snapshot JSON exceeds depth {MAX_SNAPSHOT_DEPTH}.")
        kind = type(value)
        if kind is dict or kind is list:
            if reserved + len(value) > MAX_SNAPSHOT_NODES:
                raise ValueError(f"Snapshot JSON exceeds {MAX_SNAPSHOT_NODES} nodes.")
            reserved += len(value)
            children = value.values() if kind is dict else value
            pending.extend((child, depth + 1) for child in children)
    _canonical_size(snapshot, MAX_SNAPSHOT_BYTES, "Snapshot")


def _payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in snapshot.items() if key != "snapshot_hash"}


def _validated_snapshot(snapshot: Any) -> list[str]:
    if (
        type(snapshot) is not dict
        or any(type(key) is not str for key in snapshot)
        or set(snapshot) != _FIELDS
    ):
        raise ValueError(f"Catalogue snapshot must contain exactly {sorted(_FIELDS)}.")
    if type(snapshot["schema"]) is not str or snapshot["schema"] != SNAPSHOT_SCHEMA:
        raise ValueError("Unsupported catalogue snapshot schema.")
    _text(snapshot["catalog_id"], "catalog_id")
    generation = snapshot["generation"]
    if type(generation) is not int or not 0 <= generation <= _MAX_GENERATION:
        raise ValueError("generation must be a nonnegative 63-bit integer, not a boolean.")
    if generation == 0:
        if snapshot["parent_hash"] is not None:
            raise ValueError("Generation zero must have no parent_hash.")
    else:
        _hash(snapshot["parent_hash"], "parent_hash")
    _hash(snapshot["snapshot_hash"], "snapshot_hash")
    reports = snapshot["reports"]
    if type(reports) is not list or len(reports) > MAX_REPORTS:
        raise ValueError(f"reports must be an array of at most {MAX_REPORTS} entries.")
    if generation == 0 and reports:
        raise ValueError("Generation zero must contain no reports.")
    hashes = []
    previous_id = None
    for report in reports:
        hashes.append(_report_hash(report))
        source_id = report["source"]["id"]
        if previous_id is not None and source_id <= previous_id:
            raise ValueError("Reports must be sorted by unique source.id values.")
        previous_id = source_id
    _snapshot_budget(snapshot)
    if snapshot["snapshot_hash"] != hash_input(_payload(snapshot)):
        raise ValueError("snapshot_hash does not match the catalogue payload.")
    return hashes


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    # A placeholder has the exact size of the eventual digest, so reject the
    # full snapshot's structural/byte limits before computing its final hash.
    result = {**payload, "snapshot_hash": "0" * 64}
    _snapshot_budget(result)
    result["snapshot_hash"] = hash_input(payload)
    return result


def create_asset_catalog(catalog_id: str) -> dict[str, Any]:
    """Return a fresh generation-zero catalogue without clocks or I/O."""
    _text(catalog_id, "catalog_id")
    return _seal({
        "schema": SNAPSHOT_SCHEMA, "catalog_id": catalog_id, "generation": 0,
        "parent_hash": None, "reports": [],
    })


def validate_asset_catalog(snapshot: Any) -> None:
    """Validate this snapshot, not the existence or contents of its parent."""
    _validated_snapshot(snapshot)


def _expected_head(snapshot: dict[str, Any], expected_head: Any) -> None:
    _hash(expected_head, "expected_head")
    if expected_head != snapshot["snapshot_hash"]:
        raise ValueError("expected_head is stale; re-read the catalogue before changing it.")


def _next_snapshot(snapshot: dict[str, Any], reports: list[dict[str, Any]]) -> dict[str, Any]:
    if snapshot["generation"] == _MAX_GENERATION:
        raise ValueError("Catalogue generation cannot exceed the 63-bit integer bound.")
    return _seal({
        "schema": SNAPSHOT_SCHEMA, "catalog_id": snapshot["catalog_id"],
        "generation": snapshot["generation"] + 1,
        "parent_hash": snapshot["snapshot_hash"],
        "reports": deepcopy(reports),
    })


def put_asset_report(
    snapshot: dict[str, Any], report: dict[str, Any], *,
    expected_head: str, expected_report_hash: str | None,
) -> dict[str, Any]:
    """Select a report with exact head and prior-report preconditions.

    New source IDs require expected_report_hash=None. Replacements and exact
    retries require the current report's hash. An exact retry returns an
    independent snapshot without advancing its generation. Preconditions are
    optimistic comparisons on values, not a lock on external storage.
    """
    current_hashes = _validated_snapshot(snapshot)
    _expected_head(snapshot, expected_head)
    if expected_report_hash is not None:
        _hash(expected_report_hash, "expected_report_hash")
    report_hash = _report_hash(report)
    source_id = report["source"]["id"]
    reports = list(snapshot["reports"])
    for index, current in enumerate(reports):
        if current["source"]["id"] == source_id:
            if expected_report_hash != current_hashes[index]:
                raise ValueError("expected_report_hash does not match the current source report.")
            if report_hash == current_hashes[index]:
                return deepcopy(snapshot)
            reports[index] = report
            return _next_snapshot(snapshot, reports)
    if expected_report_hash is not None:
        raise ValueError("A new source requires expected_report_hash=None.")
    if len(reports) == MAX_REPORTS:
        raise ValueError(f"The catalogue is limited to {MAX_REPORTS} reports.")
    reports.append(report)
    reports.sort(key=lambda item: item["source"]["id"])
    return _next_snapshot(snapshot, reports)


def remove_asset_report(
    snapshot: dict[str, Any], source_id: str, *,
    expected_head: str, expected_report_hash: str,
) -> dict[str, Any]:
    """Return a successor omitting an exactly identified current report."""
    current_hashes = _validated_snapshot(snapshot)
    _expected_head(snapshot, expected_head)
    _text(source_id, "source_id")
    _hash(expected_report_hash, "expected_report_hash")
    for index, report in enumerate(snapshot["reports"]):
        if report["source"]["id"] == source_id:
            if expected_report_hash != current_hashes[index]:
                raise ValueError("expected_report_hash does not match the current source report.")
            reports = snapshot["reports"][:index] + snapshot["reports"][index + 1:]
            return _next_snapshot(snapshot, reports)
    raise ValueError("source_id is not selected in the catalogue.")


def export_asset_reports(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return independent current reports, in stable source-ID order."""
    _validated_snapshot(snapshot)
    return deepcopy(snapshot["reports"])
