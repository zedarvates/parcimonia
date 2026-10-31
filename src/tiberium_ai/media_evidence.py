"""Strict, bounded projection of caller-supplied ffprobe JSON.

This module does not invoke ffprobe, read files or decode media. The result
describes reported streams and durations, not a complete stream inventory or
proof that every frame/sample decodes. Stream indices are preserved and sorted.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

__all__ = ["MAX_FFPROBE_BYTES", "parse_ffprobe_json"]

MAX_FFPROBE_BYTES = 64 * 1024
_MAX_NODES = 2_000
_MAX_DEPTH = 16  # The root object is depth 1.
_MAX_STREAMS = 32
_MAX_DIMENSION = 2**31 - 1
_STREAM_TYPES = frozenset({"audio", "video", "subtitle", "data", "attachment", "unknown"})
_DEMUXER_NAMES = {
    "wav": frozenset({"wav"}),
    "flac": frozenset({"flac"}),
    "ogg": frozenset({"ogg"}),
    "mov": frozenset({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}),
}
_CODEC = re.compile(r"[a-zA-Z0-9_]{1,64}\Z", re.ASCII)
_DIGITS = re.compile(r"[0-9]{1,10}\Z", re.ASCII)
_DURATION = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z", re.ASCII)
_STREAM_REQUIRED = frozenset({"index", "codec_type"})
_STREAM_OPTIONAL = frozenset({
    "codec_name", "width", "height", "sample_rate", "channels", "duration",
    "disposition", "side_data_list",
})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ffprobe_duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("ffprobe_nonfinite_json_constant")


def _bounded_json(value: Any) -> None:
    pending = [(value, 1)]
    count = 0
    while pending:
        current, depth = pending.pop()
        count += 1
        if count > _MAX_NODES:
            raise ValueError("ffprobe_json_node_budget_exceeded")
        if depth > _MAX_DEPTH:
            raise ValueError("ffprobe_json_depth_budget_exceeded")
        if type(current) is float and not math.isfinite(current):
            raise ValueError("ffprobe_nonfinite_json_number")
        if type(current) is dict:
            pending.extend((item, depth + 1) for item in current.values())
        elif type(current) is list:
            pending.extend((item, depth + 1) for item in current)


def _object(value: Any, required: frozenset[str], optional: frozenset[str]) -> None:
    if type(value) is not dict or not required <= value.keys() or value.keys() - required - optional:
        raise ValueError("ffprobe_unexpected_object_shape")


def _optional_integer(value: dict[str, Any], key: str, maximum: int) -> int | None:
    if key not in value:
        return None
    number = value[key]
    if type(number) is not int or not 0 <= number <= maximum:
        raise ValueError("ffprobe_invalid_integer_field")
    return number or None


def _duration(value: dict[str, Any]) -> float | None:
    if "duration" not in value:
        return None
    text = value["duration"]
    if text == "N/A" and type(text) is str:
        return None
    if type(text) is not str or len(text) > 64 or _DURATION.fullmatch(text) is None:
        raise ValueError("ffprobe_invalid_duration")
    number = float(text)
    if not math.isfinite(number) or number < 0:
        raise ValueError("ffprobe_invalid_duration")
    return number


def _sample_rate(stream: dict[str, Any]) -> int | None:
    if "sample_rate" not in stream:
        return None
    text = stream["sample_rate"]
    if type(text) is not str or _DIGITS.fullmatch(text) is None:
        raise ValueError("ffprobe_invalid_sample_rate")
    number = int(text)
    if number > _MAX_DIMENSION:
        raise ValueError("ffprobe_invalid_sample_rate")
    return number or None


def _codec(stream: dict[str, Any]) -> str | None:
    if "codec_name" not in stream or stream["codec_name"] is None:
        return None
    text = stream["codec_name"]
    if type(text) is not str:
        raise ValueError("ffprobe_invalid_codec_name")
    if text == "N/A":
        return None
    if _CODEC.fullmatch(text) is None:
        raise ValueError("ffprobe_invalid_codec_name")
    return text


def _attached_picture(stream: dict[str, Any], stream_type: str) -> bool | None:
    if "disposition" not in stream:
        return None
    disposition = stream["disposition"]
    _object(disposition, frozenset(), frozenset({"attached_pic"}))
    if "attached_pic" not in disposition:
        return None
    flag = disposition["attached_pic"]
    if type(flag) is not int or flag not in (0, 1):
        raise ValueError("ffprobe_invalid_attached_picture_flag")
    if flag == 1 and stream_type != "video":
        raise ValueError("ffprobe_attached_picture_requires_video_stream")
    return bool(flag)


def _empty_auxiliary_sections(root: dict[str, Any]) -> None:
    # Real ffprobe JSON can emit these empty root sections even when only
    # stream/format entries were requested. They do not add reported facts.
    for key in ("programs", "stream_groups"):
        if key in root and (type(root[key]) is not list or root[key]):
            raise ValueError("ffprobe_nonempty_unrequested_section")


def _empty_side_data(stream: dict[str, Any]) -> None:
    # Some native JSON writers retain empty nested subsections that were not
    # selected by -show_entries. Only empty objects are tolerated, not ignored
    # side-data values whose meaning this projection does not cover.
    if "side_data_list" not in stream:
        return
    entries = stream["side_data_list"]
    if type(entries) is not list or any(type(item) is not dict or item for item in entries):
        raise ValueError("ffprobe_unrequested_side_data")


def _format_name(raw: Any, expected_demuxer: str) -> str:
    if type(raw) is not str:
        raise ValueError("ffprobe_missing_or_invalid_format_name")
    aliases = raw.split(",")
    allowed = _DEMUXER_NAMES[expected_demuxer]
    if not aliases or len(aliases) != len(set(aliases)) or any(alias not in allowed for alias in aliases):
        raise ValueError("ffprobe_format_does_not_match_demuxer")
    return raw


def parse_ffprobe_json(payload: bytes, *, expected_demuxer: str) -> dict[str, Any]:
    """Project exactly the admitted ffprobe stream and format fields.

    The expected demuxer is an explicit caller choice (wav/flac/ogg/mov), not
    inferred from a filename here. Durations accept unsigned ASCII decimals,
    including ``.5`` or ``5.``, but no signs, exponent, whitespace or coercion.
    Empty unrequested JSON sections are tolerated; their contents are not.
    All malformed, oversized or mismatched payloads raise ValueError.
    """
    if type(payload) is not bytes or len(payload) > MAX_FFPROBE_BYTES:
        raise ValueError("ffprobe_payload_must_be_bytes_at_most_64_KiB")
    if type(expected_demuxer) is not str or expected_demuxer not in _DEMUXER_NAMES:
        raise ValueError("ffprobe_unsupported_expected_demuxer")
    try:
        root = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError, MemoryError) as exc:
        raise ValueError("ffprobe_invalid_utf8_or_json") from exc
    _bounded_json(root)
    _object(root, frozenset({"streams", "format"}), frozenset({"programs", "stream_groups"}))
    _empty_auxiliary_sections(root)
    _object(root["format"], frozenset({"format_name"}), frozenset({"duration"}))
    name = _format_name(root["format"]["format_name"], expected_demuxer)
    raw_streams = root["streams"]
    if type(raw_streams) is not list or len(raw_streams) > _MAX_STREAMS:
        raise ValueError("ffprobe_invalid_stream_collection")

    streams: list[dict[str, Any]] = []
    seen_indices: set[int] = set()
    for stream in raw_streams:
        _object(stream, _STREAM_REQUIRED, _STREAM_OPTIONAL)
        index = stream["index"]
        if type(index) is not int or not 0 <= index <= 65_535 or index in seen_indices:
            raise ValueError("ffprobe_invalid_or_duplicate_stream_index")
        seen_indices.add(index)
        stream_type = stream["codec_type"]
        if type(stream_type) is not str or stream_type not in _STREAM_TYPES:
            raise ValueError("ffprobe_invalid_stream_type")
        _empty_side_data(stream)
        streams.append({
            "index": index,
            "type": stream_type,
            "codec": _codec(stream),
            "width": _optional_integer(stream, "width", _MAX_DIMENSION),
            "height": _optional_integer(stream, "height", _MAX_DIMENSION),
            "sample_rate": _sample_rate(stream),
            "channels": _optional_integer(stream, "channels", 65_535),
            "duration_seconds": _duration(stream),
            "attached_picture": _attached_picture(stream, stream_type),
        })
    return {
        "format": {"name": name, "duration_seconds": _duration(root["format"])},
        "streams": sorted(streams, key=lambda stream: stream["index"]),
        "coverage": {"streams": "reported_only", "full_decode": "not_established"},
        "limitations": [
            "reported_stream_inventory_may_be_incomplete",
            "full_decode_not_established",
            "reported_durations_not_independently_measured",
            "strict_projection_rejects_unrequested_nonempty_sections",
        ],
    }
