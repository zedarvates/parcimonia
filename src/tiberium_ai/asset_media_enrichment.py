"""Propose stream tags from one exact saved native observation.

No tool is run here. Structural and hash checks establish consistency of
caller-supplied declarations, not authenticated execution or media truth.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

from .asset_media_probe import BMFF_MEDIA_BRANDS, PROFILE_ID, SUPPORTED_DEMUXERS
from .asset_tag_journal import _validate_report_json, validated_review_report_hash
from .asset_text_enrichment import _elapsed, _hash, _object
from .media_evidence import parse_ffprobe_json
from .verification import hash_input

__all__ = ["enrich_asset_with_media"]

_FIELDS = {
    "schema", "source", "input_hash", "sample_sha256", "source_complete",
    "backend", "profile", "status", "raw_json", "projection", "reason_codes",
    "native_calls", "elapsed_ms", "limits",
}
_CALL_FIELDS = {
    "phase", "status", "returncode", "stdout_sha256", "stderr_sha256",
    "stdout_complete", "stderr_complete", "elapsed_ms", "started", "error",
}


def _validate_observation(observation: Any, inspection: dict[str, Any]) -> dict[str, Any]:
    _validate_report_json(observation)
    _object(observation, _FIELDS, "media observation")
    if observation["schema"] != "parcimonia.asset-media-observation/v1":
        raise ValueError("Unsupported media observation schema.")
    _object(observation["source"], {"id", "revision", "filename"}, "observation source")
    if observation["source"] != inspection["source"]:
        raise ValueError("Media observation and inspection must name the exact same source.")
    for field in ("input_hash", "sample_sha256"):
        _hash(observation[field], "observation." + field)
    if (
        observation["status"] != "completed" or observation["source_complete"] is not True
        or inspection["sample"]["complete"] is not True
        or observation["sample_sha256"] != inspection["sample"]["sha256"]
    ):
        raise ValueError("A completed observation and complete matching source are required.")
    backend = observation["backend"]
    _object(backend, {"id", "version", "executable", "executable_sha256"}, "media backend")
    if type(backend["id"]) is not str or backend["id"] != "ffprobe":
        raise ValueError("Unsupported media backend.")
    for field in ("version", "executable"):
        if type(backend[field]) is not str or not backend[field] or backend[field] != backend[field].strip():
            raise ValueError("Completed observation must identify its declared native backend.")
    if not backend["version"].startswith("ffprobe version "):
        raise ValueError("An ffprobe version declaration is required.")
    _hash(backend["executable_sha256"], "backend.executable_sha256")
    profile = observation["profile"]
    _object(profile, {"id", "source_format", "demuxer"}, "media profile")
    source_format = profile["source_format"]
    if (
        profile["id"] != PROFILE_ID or type(source_format) is not str
        or source_format not in SUPPORTED_DEMUXERS
        or profile["demuxer"] != SUPPORTED_DEMUXERS[source_format]
        or source_format != inspection["format"].get("detected")
    ):
        raise ValueError("The media profile must match the supported source format.")
    if source_format == "iso_bmff":
        brands = [item.get("value") for item in inspection["metadata"] if type(item) is dict and item.get("name") == "major_brand"]
        if len(brands) != 1 or type(brands[0]) is not str or brands[0] not in BMFF_MEDIA_BRANDS:
            raise ValueError("The BMFF major brand is outside this audio/video profile.")
    _elapsed(observation["elapsed_ms"])
    if type(observation["reason_codes"]) is not list or any(type(reason) is not str for reason in observation["reason_codes"]):
        raise ValueError("Observation reasons must be strings.")
    if type(observation["limits"]) is not dict:
        raise ValueError("Media observation limits must be recorded.")
    calls = observation["native_calls"]
    if type(calls) is not list or len(calls) != 2:
        raise ValueError("Expected the version and probe native calls.")
    for phase, call in zip(("version", "probe"), calls):
        _object(call, _CALL_FIELDS, "native media call")
        if (
            call["phase"] != phase or call["status"] != "completed"
            or type(call["returncode"]) is not int or call["returncode"] != 0
            or call["stdout_complete"] is not True or call["stderr_complete"] is not True
            or call["started"] is not True or call["error"] is not None
        ):
            raise ValueError("Native provenance must describe complete successful calls.")
        _hash(call["stdout_sha256"], "stdout_sha256")
        _hash(call["stderr_sha256"], "stderr_sha256")
        _elapsed(call["elapsed_ms"])
    raw_json = observation["raw_json"]
    if type(raw_json) is not str:
        raise ValueError("A completed observation must retain its native JSON response.")
    payload = raw_json.encode("utf-8")
    if hashlib.sha256(payload).hexdigest() != calls[1]["stdout_sha256"]:
        raise ValueError("The saved media response must match its native stdout hash.")
    projection = parse_ffprobe_json(payload, expected_demuxer=profile["demuxer"])
    if hash_input(projection) != hash_input(observation["projection"]):
        raise ValueError("The media projection must reproduce the exact saved native response.")
    return projection


def enrich_asset_with_media(inspection: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    """Return proposed tags with exact reported-stream evidence, without I/O."""
    base_hash = validated_review_report_hash(inspection)
    if inspection["analyser"] != {"id": "asset-inspection", "version": "1"}:
        raise ValueError("Start media enrichment from the original deterministic inspection.")
    projection = _validate_observation(observation, inspection)
    observation_hash = hash_input(observation)
    result = deepcopy(inspection)
    result["analyser"] = {"id": "asset-media-enrichment", "version": "1"}
    result["input_hash"] = hash_input({"base_report_hash": base_hash, "media_observation_hash": observation_hash})
    summary_id = f"media:{observation_hash}:summary"
    result["evidence"].append({
        "id": summary_id, "kind": "native_media_observation", "observation_hash": observation_hash,
        "backend": deepcopy(observation["backend"]), "profile": deepcopy(observation["profile"]),
        "coverage": deepcopy(projection["coverage"]), "source_sha256": observation["sample_sha256"],
        "raw_stdout_sha256": observation["native_calls"][1]["stdout_sha256"],
    })
    result["metadata"].extend([
        {"name": "media_observation", "value": {"report_hash": observation_hash, "stream_count": len(projection["streams"]), "native_calls": 2, "elapsed_ms": observation["elapsed_ms"]}, "basis": "native_tool_observation", "evidence_ref": summary_id},
        {"name": "media_format", "value": deepcopy(projection["format"]), "basis": "native_reported_or_estimated", "evidence_ref": summary_id},
    ])
    proposals: dict[tuple[str, str], dict[str, Any]] = {}
    observed_modalities: set[str] = set()

    def propose(namespace: str, value: str, stream_ref: str) -> None:
        key = (namespace, value)
        if key not in proposals:
            proposals[key] = {"namespace": namespace, "value": value, "status": "proposed", "basis": "native_stream_observation", "evidence_refs": [summary_id]}
        proposals[key]["evidence_refs"].append(stream_ref)
        if namespace == "modality":
            observed_modalities.add(value)

    for stream in projection["streams"]:
        stream_ref = f"media:{observation_hash}:stream:{stream['index']}"
        result["evidence"].append({"id": stream_ref, "kind": "native_media_stream", "observation_hash": observation_hash, "stream": deepcopy(stream)})
        result["metadata"].append({"name": "media_stream", "value": deepcopy(stream), "basis": "native_reported_or_estimated", "evidence_ref": stream_ref})
        propose("stream_type", stream["type"], stream_ref)
        if stream["codec"] is not None:
            propose("codec", stream["codec"], stream_ref)
        if stream["type"] == "audio":
            propose("modality", "audio", stream_ref)
        elif stream["type"] == "video":
            if stream["attached_picture"] is True:
                propose("modality", "image", stream_ref)
                propose("media_feature", "attached_picture", stream_ref)
            elif stream["attached_picture"] is False:
                propose("modality", "video", stream_ref)
    result["modalities"].extend(sorted(observed_modalities - set(result["modalities"])))
    result["tag_proposals"].extend(proposals[key] for key in sorted(proposals))
    result["status"] = "partial"
    result["reason_codes"] = sorted(set(result["reason_codes"]) | set(observation["reason_codes"]) | {"reported_stream_metadata_only"})
    result["limits"].update({
        "semantic_content": "not_assessed_stream_metadata_only", "native_media_tool_calls": 2,
        "model_calls": 0, "native_media_quality": "not_qualified",
        "stream_inventory": "reported_under_probe_limits_not_exhaustive",
        "full_decode": "not_established", "duration": "reported_or_estimated",
        "observation_sources": "caller_supplied_unverified",
    })
    validated_review_report_hash(result)
    return result
