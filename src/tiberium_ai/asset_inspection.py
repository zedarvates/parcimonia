"""Bounded asset observations and proposed tags, without semantic fabrication.

This API inspects caller-supplied bytes. It does not read, import, render, move
or execute a file. A prefix hash is never represented as a full-content hash.
"""

from __future__ import annotations

import ast
import codecs
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
from typing import Any

from .geo_probe import probe_geojson
from .media_probe import probe_media
from .pattern_rules import builtin_rule_registry
from .source_role import classify_source_role
from .source_scan import scan_source
from .verification import hash_input

MAX_SAMPLE_BYTES = 1024 * 1024
_MAX_AST_NODES = 10_000
_MAX_AST_DEPTH = 128
_EXTENSIONS = {
    ".png": ("png", "image"), ".jpg": ("jpeg", "image"),
    ".jpeg": ("jpeg", "image"), ".gif": ("gif", "image"),
    ".webp": ("webp", "image"), ".tif": ("tiff", "image"),
    ".tiff": ("tiff", "image"), ".bmp": ("bmp", "image"),
    ".wav": ("wav", "audio"), ".flac": ("flac", "audio"),
    ".ogg": ("ogg", "container"), ".mp3": ("mp3", "audio"),
    ".aac": ("aac", "audio"), ".m4a": ("iso_bmff", "audio"),
    ".mp4": ("iso_bmff", "video"), ".mov": ("iso_bmff", "video"),
    ".webm": ("webm", "video"), ".mkv": ("matroska", "video"),
    ".avi": ("avi", "video"), ".glb": ("glb", "3d"),
    ".gltf": ("gltf", "3d"), ".ply": ("ply", "3d"),
    ".obj": ("obj", "3d"), ".stl": ("stl", "3d"),
    ".fbx": ("fbx", "3d"), ".usd": ("usd", "3d"),
    ".usdz": ("zip", "3d"), ".splat": ("splat", "3d"),
    ".ksplat": ("ksplat", "3d"), ".spz": ("spz", "3d"),
    ".txt": ("text", "text"), ".md": ("text", "text"),
    ".csv": ("csv", "text"), ".tsv": ("tsv", "text"),
    ".json": ("json", "text"), ".geojson": ("geojson", "geospatial"),
    ".gpx": ("gpx", "geospatial"), ".kml": ("kml", "geospatial"),
    ".shp": ("shapefile", "geospatial"), ".py": ("python", "code"),
    ".js": ("javascript", "code"), ".ts": ("typescript", "code"),
    ".zig": ("zig", "code"), ".gd": ("gdscript", "code"),
    ".pdf": ("pdf", "document"), ".docx": ("zip", "document"),
    ".zip": ("zip", "container"),
}


def _text(value: Any, name: str, maximum: int = 1024) -> None:
    if type(value) is not str or not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be a nonempty trimmed string of at most {maximum} characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{name} must be valid UTF-8 text.") from exc


def _validate_topics(topics: Any) -> None:
    if topics is None:
        return
    if type(topics) is not dict or len(topics) > 32:
        raise ValueError("topic_terms must be null or a mapping of at most 32 labels.")
    for label, terms in topics.items():
        _text(label, "topic label", 128)
        if type(terms) is not list or not 1 <= len(terms) <= 8:
            raise ValueError("Each topic needs one to eight literal terms.")
        for term in terms:
            _text(term, "topic term", 64)


def _tag(namespace: str, value: str, basis: str, refs: list[str]) -> dict[str, Any]:
    return {"namespace": namespace, "value": value, "status": "proposed", "basis": basis, "evidence_refs": refs}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are unsupported.")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON value: {value}")


def _json_value(text: str, *, max_nodes: int = 20_000) -> Any:
    result = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_constant)
    pending = [(result, 0)]
    count = 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if depth > 64 or count > max_nodes:
            raise ValueError("JSON structural budget exceeded.")
        if type(value) is dict:
            pending.extend((item, depth + 1) for item in value.values())
        elif type(value) is list:
            pending.extend((item, depth + 1) for item in value)
        elif type(value) is float and not math.isfinite(value):
            raise ValueError("Non-finite JSON number.")
    return result


def _decode_text(data: bytes, complete: bool) -> str | None:
    try:
        text = codecs.getincrementaldecoder("utf-8")().decode(data, final=complete)
    except UnicodeError:
        return None
    controls = sum(ord(char) < 32 and char not in "\t\n\r\f" for char in text)
    if "\x00" in text or controls > max(1, len(text) // 100):
        return None
    return text


def _python_tags(report: dict[str, Any], text: str, filename: str) -> None:
    try:
        tree = ast.parse(text, feature_version=(3, 10))
        pending = [(tree, 0)]
        count = 0
        while pending:
            node, depth = pending.pop()
            count += 1
            if count > _MAX_AST_NODES or depth > _MAX_AST_DEPTH:
                raise ValueError("Python AST budget exceeded.")
            pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
        scan = scan_source(filename, text)
        role = classify_source_role(scan)
        registry = builtin_rule_registry()
        findings = registry.run(scan, role.role)
    except (ValueError, SyntaxError, RecursionError, MemoryError):
        report["reason_codes"].append("python_structure_unavailable")
        return
    report["format"].update(detected="python", media_type="text/x-python", basis="syntax_parse")
    report["modalities"] = ["code", "text"]
    report["evidence"].append({"id": "code:structure", "kind": "bounded_python_ast", "byte_range": [0, report["sample"]["bytes"]]})
    report["tag_proposals"].append(_tag("code_role", role.role.value, "code_structure_heuristic", ["code:structure"]))
    report["metadata"].extend([
        {"name": "python_role_reason", "value": role.reason_code, "basis": "code_structure_heuristic", "evidence_ref": "code:structure"},
        {"name": "code_rule_registry", "value": registry.fingerprint(), "basis": "named_rules", "evidence_ref": "code:structure"},
    ])
    for index, finding in enumerate(findings):
        evidence_id = f"code:pattern:{index}"
        report["evidence"].append({"id": evidence_id, "kind": "named_code_pattern", "line_range": [finding.line, finding.line + 1], "rule_id": finding.rule_id})
        report["tag_proposals"].append(_tag("code_pattern", finding.rule_id, "named_rule_indicator", [evidence_id]))


def inspect_asset(
    data: bytes, *, filename: str, source_id: str, revision: str,
    complete: bool = True, total_bytes: int | None = None,
    topic_terms: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Inspect a bounded full file or prefix and return proposed tags only."""
    if type(data) is not bytes or len(data) > MAX_SAMPLE_BYTES:
        raise ValueError("data must be bytes of at most 1 MiB.")
    for name, value in (("filename", filename), ("source_id", source_id), ("revision", revision)):
        _text(value, name)
    if type(complete) is not bool:
        raise ValueError("complete must be a boolean.")
    if total_bytes is not None and (type(total_bytes) is not int or not 0 <= total_bytes < 2 ** 63):
        raise ValueError("total_bytes must be null or a nonnegative 63-bit integer.")
    if complete:
        if total_bytes is not None and total_bytes != len(data):
            raise ValueError("A complete sample must equal total_bytes.")
        total_bytes = len(data)
    elif total_bytes is not None and total_bytes <= len(data):
        raise ValueError("A known prefix total must exceed sample bytes.")
    _validate_topics(topic_terms)
    digest = hashlib.sha256(data).hexdigest()
    sample = {"sha256": digest, "bytes": len(data), "complete": complete, "total_bytes": total_bytes, "content_sha256": digest if complete else None}
    source = {"id": source_id, "revision": revision, "filename": filename}
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    hint = _EXTENSIONS.get(suffix)
    report: dict[str, Any] = {
        "schema": "parcimonia.asset-inspection/v1",
        "source": source,
        "input_hash": hash_input({"source": source, "sample": sample, "topic_terms": topic_terms}),
        "sample": sample,
        "analyser": {"id": "asset-inspection", "version": "1"},
        "mode": "shadow",
        "status": "indeterminate",
        "format": {"detected": None, "media_type": None, "basis": None, "extension_hint": hint[0] if hint else None, "extension_conflict": None},
        "modalities": [], "metadata": [], "tag_proposals": [], "evidence": [],
        "spatial": None, "reason_codes": [],
        "limits": {"semantic_content": "not_assessed", "sources": "caller_supplied_unverified", "tag_state": "proposals_only", "max_sample_bytes": MAX_SAMPLE_BYTES, "model_calls": 0, "file_mutations": 0},
    }
    if hint:
        report["evidence"].append({"id": "name:extension", "kind": "filename_hint", "suffix": suffix})
        report["tag_proposals"].extend([
            _tag("format_hint", hint[0], "extension_hint", ["name:extension"]),
            _tag("modality_hint", hint[1], "extension_hint", ["name:extension"]),
        ])
    if not data:
        report["reason_codes"] = ["empty_sample"]
        return report
    probe = probe_geojson(data, complete=complete) or probe_media(data, complete=complete)
    decoded = None
    if probe is not None:
        report["format"].update(detected=probe["format"], media_type=probe["media_type"], basis=probe["analysis_scope"])
        for field in ("modalities", "metadata", "evidence"):
            report[field] = probe[field]
        # Keep filename evidence independently of byte observations.
        if hint:
            report["evidence"].append({"id": "name:extension", "kind": "filename_hint", "suffix": suffix})
        report["tag_proposals"].extend(dict(tag, status="proposed") for tag in probe["tag_proposals"])
        report["spatial"] = probe.get("spatial")
        report["reason_codes"].extend(probe["issues"])
    elif data.startswith(b"%PDF-") or data.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        pdf = data.startswith(b"%PDF-")
        report["format"].update(detected="pdf" if pdf else "zip", media_type="application/pdf" if pdf else "application/zip", basis="signature_only")
        report["modalities"] = ["document" if pdf else "container"]
        report["evidence"].append({"id": "bytes:signature", "kind": "signature", "byte_range": [0, 5 if pdf else 4]})
        report["reason_codes"].append("container_contents_not_inspected")
    else:
        decoded = _decode_text(data, complete)
        if decoded is not None:
            report["format"].update(detected="text", media_type="text/plain", basis="utf8_text")
            report["modalities"] = ["text"]
            report["evidence"].append({"id": "text:utf8", "kind": "utf8_text_sample", "byte_range": [0, len(data)]})
            report["metadata"].append({"name": "sample_text_characters", "value": len(decoded), "basis": "decoded_sample", "evidence_ref": "text:utf8"})
            if complete and decoded.lstrip().startswith(("{", "[")):
                try:
                    document = _json_value(decoded)
                    gltf = type(document) is dict and type(document.get("asset")) is dict and document["asset"].get("version") == "2.0"
                    report["format"].update(detected="gltf" if gltf else "json", media_type="model/gltf+json" if gltf else "application/json", basis="parsed_structure")
                    if gltf:
                        report["modalities"] = ["3d", "text"]
                        report["reason_codes"].append("gltf_resources_and_schema_not_validated")
                    report["evidence"].append({"id": "text:json", "kind": "bounded_json_parse", "byte_range": [0, len(data)]})
                except (ValueError, RecursionError):
                    report["reason_codes"].append("structured_json_unavailable")
            if suffix == ".py":
                if complete:
                    _python_tags(report, decoded, filename)
                else:
                    report["reason_codes"].append("python_prefix_not_parsed")
        else:
            report["reason_codes"].append("unsupported_binary_sample")
    if topic_terms:
        if report["format"]["detected"] in {"text", "json", "python", "geojson", "gltf"}:
            decoded = decoded if decoded is not None else _decode_text(data, complete)
            if decoded is not None:
                for index, (label, terms) in enumerate(sorted(topic_terms.items())):
                    matches = []
                    for term in sorted(set(terms)):
                        for match in re.finditer(r"(?<!\w)" + re.escape(term) + r"(?!\w)", decoded, re.IGNORECASE):
                            # The end of a prefix is not an observed word boundary.
                            if complete or match.end() < len(decoded):
                                matches.append(match)
                                break
                    if matches:
                        match = min(matches, key=lambda item: (item.start(), item.end()))
                        evidence_id = f"text:topic:{index}"
                        report["evidence"].append({"id": evidence_id, "kind": "lexical_match", "char_range": [match.start(), match.end()], "indexing": "unicode_codepoints"})
                        report["tag_proposals"].append(_tag("topic", label, "lexical_hint", [evidence_id]))
        report["limits"]["semantic_content"] = "not_assessed_lexical_hints_only"
    detected = report["format"]["detected"]
    if detected is not None:
        if detected == "python":
            ref = "code:structure"
        elif detected in {"json", "gltf"}:
            ref = "text:json"
        else:
            ref = next((item["id"] for item in report["evidence"] if item["kind"] != "filename_hint"), None)
        if ref:
            if not any(tag["namespace"] == "format" and tag["value"] == detected for tag in report["tag_proposals"]):
                report["tag_proposals"].append(_tag("format", detected, report["format"]["basis"], [ref]))
            for value in report["modalities"]:
                if not any(tag["namespace"] == "modality" and tag["value"] == value for tag in report["tag_proposals"]):
                    report["tag_proposals"].append(_tag("modality", value, report["format"]["basis"], [ref]))
        if hint:
            compatible = {hint[0]}
            if hint[0] in {"text", "csv", "tsv", "javascript", "typescript", "zig", "gdscript", "gpx", "kml", "obj"}:
                compatible.add("text")
            if hint[0] == "json":
                compatible.update({"geojson", "gltf"})
            report["format"]["extension_conflict"] = detected not in compatible
            if report["format"]["extension_conflict"]:
                report["reason_codes"].append("format_extension_conflict")
        report["status"] = "partial" if not complete or report["reason_codes"] else "inspected"
    report["reason_codes"] = sorted(set(report["reason_codes"]))
    # Preserve one proposal per namespace/value/basis, merging supporting refs.
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for tag in report["tag_proposals"]:
        key = (tag["namespace"], tag["value"], tag["basis"])
        if key not in grouped:
            grouped[key] = tag
        else:
            grouped[key]["evidence_refs"] = sorted(set(grouped[key]["evidence_refs"]) | set(tag["evidence_refs"]))
    report["tag_proposals"] = [grouped[key] for key in sorted(grouped)]
    return report
