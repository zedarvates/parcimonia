"""Pure, proposal-only search over caller-supplied asset inspection reports.

The catalogue validates fields needed by its filters, not parser reproduction,
source truth or authenticated origin. A bounding-box match is an envelope candidate, not a geometric or
place-identity assertion. No files are read, moved, renamed or reclassified.
"""

from __future__ import annotations

import math
from typing import Any

from .verification import hash_input

__all__ = ["search_asset_reports"]

REPORT_SCHEMA = "parcimonia.asset-inspection/v1"
SEARCH_SCHEMA = "parcimonia.asset-search/v1"
MAX_REPORTS = 256
_MAX_SAMPLE_BYTES = 1024 * 1024

_REPORT_FIELDS = {
    "schema", "source", "input_hash", "sample", "analyser", "mode", "status",
    "format", "modalities", "metadata", "tag_proposals", "evidence", "spatial",
    "reason_codes", "limits",
}


def _object(value: Any, fields: set[str], label: str) -> None:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"{label} must contain exactly {sorted(fields)}.")


def _text(value: Any, label: str, maximum: int = 4096) -> None:
    if (
        type(value) is not str or not value or value != value.strip()
        or len(value) > maximum
    ):
        raise ValueError(f"{label} must be a trimmed string of 1..{maximum} characters.")


def _hash(value: Any, label: str) -> None:
    if (
        type(value) is not str or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 hexadecimal string.")


def _strings(value: Any, label: str) -> None:
    if type(value) is not list:
        raise ValueError(f"{label} must be an array of strings.")
    for item in value:
        _text(item, label)


def _number(value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _bbox(value: Any, *, degrees: bool, label: str) -> list[float]:
    if type(value) is not list or len(value) != 4 or not all(_number(item) for item in value):
        raise ValueError(f"{label} must contain four finite numbers, not booleans.")
    west, south, east, north = value
    if degrees:
        if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
            raise ValueError(f"{label} must be an ordered CRS84 envelope; wrapping is unsupported.")
    # Unknown CRS envelopes are opaque. In particular, do not apply degree
    # bounds, normalize coordinates, or infer their axis meaning.
    return [float(item) for item in value] if degrees else list(value)


def _sample(value: Any) -> None:
    _object(value, {"sha256", "bytes", "complete", "total_bytes", "content_sha256"}, "sample")
    _hash(value["sha256"], "sample.sha256")
    size, total = value["bytes"], value["total_bytes"]
    if type(size) is not int or not 0 <= size <= _MAX_SAMPLE_BYTES:
        raise ValueError("sample.bytes must be an integer within the analyser's 1 MiB bound.")
    if type(value["complete"]) is not bool:
        raise ValueError("sample.complete must be a boolean.")
    if total is not None and (type(total) is not int or not size <= total < 2**63):
        raise ValueError("sample.total_bytes must be null or a 63-bit integer at least sample.bytes.")
    content_hash = value["content_sha256"]
    if content_hash is not None:
        _hash(content_hash, "sample.content_sha256")
    if value["complete"]:
        if total != size or content_hash != value["sha256"]:
            raise ValueError("A complete sample must bind its exact size and full-content hash.")
    elif content_hash is not None or (total is not None and total <= size):
        raise ValueError("A prefix has no full-content hash and a known total must exceed its size.")


def _tag_key(tag: Any, evidence_ids: set[str]) -> str:
    _object(tag, {"namespace", "value", "status", "basis", "evidence_refs"}, "tag proposal")
    for field in ("namespace", "value", "basis"):
        _text(tag[field], f"tag.{field}")
    if ":" in tag["namespace"]:
        raise ValueError("tag.namespace must not contain ':'.")
    if type(tag["status"]) is not str or tag["status"] != "proposed":
        raise ValueError("Only proposed inspection tags are supported.")
    _strings(tag["evidence_refs"], "tag.evidence_refs")
    if not tag["evidence_refs"] or not set(tag["evidence_refs"]) <= evidence_ids:
        raise ValueError("Tag proposals must reference known report evidence IDs.")
    return f"{tag['namespace']}:{tag['value']}"


def _spatial(value: Any) -> list[float] | None:
    if value is None:
        return None
    _object(value, {"crs", "axis_order", "units", "position_count", "bbox"}, "spatial")
    _text(value["crs"], "spatial.crs")
    _text(value["units"], "spatial.units")
    _strings(value["axis_order"], "spatial.axis_order")
    if len(value["axis_order"]) != 2:
        raise ValueError("spatial.axis_order must identify two axes.")
    if type(value["position_count"]) is not int or value["position_count"] < 0:
        raise ValueError("spatial.position_count must be a nonnegative integer.")
    known = value["crs"] == "OGC:CRS84"
    if known and (value["axis_order"] != ["longitude", "latitude"] or value["units"] != "degrees"):
        raise ValueError("CRS84 spatial data must declare longitude/latitude axes and degree units.")
    bounds = None
    if value["bbox"] is not None:
        bounds = _bbox(value["bbox"], degrees=known, label="spatial.bbox")
    if known and ((value["position_count"] == 0) != (bounds is None)):
        raise ValueError("CRS84 position_count and bbox must consistently describe empty or located data.")
    return bounds if known else None


def _report(value: Any) -> tuple[set[str], list[float] | None]:
    _object(value, _REPORT_FIELDS, "inspection report")
    if type(value["schema"]) is not str or value["schema"] != REPORT_SCHEMA:
        raise ValueError("Unsupported inspection report schema.")
    _object(value["source"], {"id", "revision", "filename"}, "source")
    for field in ("id", "revision", "filename"):
        _text(value["source"][field], f"source.{field}")
    _hash(value["input_hash"], "input_hash")
    _sample(value["sample"])
    _object(value["analyser"], {"id", "version"}, "analyser")
    analyser = value["analyser"]
    if (
        type(analyser["id"]) is not str or type(analyser["version"]) is not str
        or (analyser["id"], analyser["version"]) not in {
            ("asset-inspection", "1"), ("asset-text-enrichment", "1")
        }
    ):
        raise ValueError("Unsupported analyser identity or version.")
    if type(value["mode"]) is not str or value["mode"] != "shadow":
        raise ValueError("Inspection mode must be shadow.")
    if type(value["status"]) is not str or value["status"] not in {"inspected", "partial", "indeterminate"}:
        raise ValueError("Unsupported inspection status.")
    for field in ("format", "limits"):
        if type(value[field]) is not dict:
            raise ValueError(f"{field} must be an object.")
    for field in ("metadata", "evidence", "tag_proposals"):
        if type(value[field]) is not list:
            raise ValueError(f"{field} must be an array.")
    _strings(value["modalities"], "modalities")
    _strings(value["reason_codes"], "reason_codes")
    evidence_ids: set[str] = set()
    for evidence in value["evidence"]:
        if type(evidence) is not dict or "id" not in evidence:
            raise ValueError("Each evidence entry must be an object with an ID.")
        _text(evidence["id"], "evidence.id")
        if evidence["id"] in evidence_ids:
            raise ValueError("Evidence IDs must be unique within a report.")
        evidence_ids.add(evidence["id"])
    tags = {_tag_key(tag, evidence_ids) for tag in value["tag_proposals"]}
    bounds = _spatial(value["spatial"])
    return tags, bounds


def _query_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if type(tags) is not list or len(tags) > 256:
        raise ValueError("tags must be null or an array of at most 256 namespace:value filters.")
    for tag in tags:
        _text(tag, "query tag", 8193)
        namespace, separator, value = tag.partition(":")
        if not separator:
            raise ValueError("query tags must use namespace:value syntax.")
        _text(namespace, "query tag namespace")
        _text(value, "query tag value")
    return sorted(set(tags))


def search_asset_reports(
    reports: list[dict[str, Any]], *, tags: list[str] | None = None,
    bbox: list[float] | None = None, limit: int = 50,
) -> dict[str, Any]:
    """Search validated report references by exact AND tags and envelope overlap.

    ``count`` counts returned matches; ``truncated`` indicates additional matches.
    The input hash binds the supplied report order and the normalized query.
    No query means a sorted bounded listing. Reports claiming an unknown CRS
    remain listable by tags but cannot match a spatial query.
    """
    if type(reports) is not list or len(reports) > MAX_REPORTS:
        raise ValueError(f"reports must be an array of at most {MAX_REPORTS} entries.")
    if type(limit) is not int or not 1 <= limit <= MAX_REPORTS:
        raise ValueError(f"limit must be an integer from 1 to {MAX_REPORTS}.")
    requested_tags = _query_tags(tags)
    query_bbox = None if bbox is None else _bbox(bbox, degrees=True, label="query bbox")
    query = {"tags": requested_tags, "bbox": query_bbox, "limit": limit}
    validated = []
    identities: set[tuple[str, str]] = set()
    for report in reports:
        actual_tags, actual_bbox = _report(report)
        source = report["source"]
        identity = (source["id"], source["revision"])
        if identity in identities:
            raise ValueError("Duplicate source identity and revision are ambiguous.")
        identities.add(identity)
        validated.append((report, actual_tags, actual_bbox))
    try:
        input_hash = hash_input({"reports": reports, "query": query})
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("Reports and query must be finite UTF-8 JSON.") from exc

    matches = []
    for report, actual_tags, actual_bbox in sorted(
        validated, key=lambda entry: (entry[0]["source"]["id"], entry[0]["source"]["revision"])
    ):
        if not set(requested_tags) <= actual_tags:
            continue
        if query_bbox is not None:
            if actual_bbox is None:
                continue
            west, south, east, north = actual_bbox
            qwest, qsouth, qeast, qnorth = query_bbox
            if east < qwest or qeast < west or north < qsouth or qnorth < south:
                continue
        matches.append({
            "source": dict(report["source"]),
            "input_hash": report["input_hash"],
            "sample_sha256": report["sample"]["sha256"],
            "matched_tags": list(requested_tags),
            "spatial_match": "envelope_overlap_candidate" if query_bbox is not None else None,
        })
    returned = matches[:limit]
    return {
        "schema": SEARCH_SCHEMA,
        "input_hash": input_hash,
        "query": query,
        "matches": returned,
        "count": len(returned),
        "truncated": len(matches) > limit,
        "limits": {
            "tags": "proposals_only",
            "inputs": "caller_supplied_unverified",
            "spatial": "envelope_only_no_geometry_verification",
            "reprojection": "not_performed",
            "geocoding": "not_performed",
        },
    }
