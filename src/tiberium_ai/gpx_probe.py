"""A bounded GPX 1.1 coordinate profile, not a complete XSD validator.

Only native waypoints, route points and track points at their declared paths
contribute positions. Optional fields and extension subtrees are not extracted.
No file, link, schema or external entity is opened by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from xml.parsers import expat

__all__ = ["PROFILE_ID", "probe_gpx"]

PROFILE_ID = "parcimonia.gpx-coordinate-profile/v1"
_NAMESPACE = "http://www.topografix.com/GPX/1/1"
_ROOT_NAME = _NAMESPACE + "}gpx"
_MAX_BYTES = 1024 * 1024
_MAX_ELEMENTS = 20_000
_MAX_DEPTH = 32
_MAX_POSITIONS = 2_000
_MAX_DECIMAL_CHARACTERS = 128
_MAX_CREATOR_CHARACTERS = 4_096
_XML_WHITESPACE = " \t\r\n"
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z", re.ASCII)
_PARENTS = {
    "wpt": "gpx",
    "rte": "gpx",
    "rtept": "rte",
    "trk": "gpx",
    "trkseg": "trk",
    "trkpt": "trkseg",
}
_POINTS = frozenset({"wpt", "rtept", "trkpt"})
_STRUCTURE_EVIDENCE = "gpx:structure"
_POSITIONS_EVIDENCE = "gpx:positions"


class _InvalidGPX(ValueError):
    pass


class _NotGPX(ValueError):
    pass


@dataclass
class _Frame:
    local: str | None
    path: str | None
    ignored: bool
    children: dict[str, int] = field(default_factory=dict)


def _coordinate(attributes: dict[str, str], name: str) -> float:
    if name not in attributes:
        raise _InvalidGPX("gpx_missing_coordinate_attribute")
    # XML has already normalized attributes and decoded numeric/predefined
    # references. XSD whitespace handling does not include Unicode spaces.
    token = attributes[name].strip(_XML_WHITESPACE)
    if len(token) > _MAX_DECIMAL_CHARACTERS or _DECIMAL.fullmatch(token) is None:
        raise _InvalidGPX("gpx_invalid_coordinate_decimal")
    try:
        value = Decimal(token)
    except InvalidOperation as exc:
        raise _InvalidGPX("gpx_invalid_coordinate_decimal") from exc
    if name == "lat":
        allowed = Decimal(-90) <= value <= Decimal(90)
    else:
        allowed = Decimal(-180) <= value < Decimal(180)
    if not allowed:
        raise _InvalidGPX("gpx_coordinate_out_of_range")
    converted = float(value)
    # A valid lexical longitude very close to 180 can round to the excluded
    # endpoint in binary floating point. Never clamp or silently accept it.
    if name == "lon" and converted >= 180:
        raise _InvalidGPX("gpx_longitude_rounds_to_excluded_endpoint")
    return converted


class _CoordinateParser:
    def __init__(self) -> None:
        self.seen_root = False
        self.creator = ""
        self.elements = 0
        self.frames: list[_Frame] = []
        self.counts = {name: 0 for name in _PARENTS}
        self.points: list[dict[str, Any]] = []
        self.optional_fields_present = False

    def xml_declaration(self, version: str, encoding: str | None, standalone: int) -> None:
        if version != "1.0":
            raise _InvalidGPX("gpx_unsupported_xml_version")
        if encoding is not None and encoding.lower() not in {"utf-8", "utf8"}:
            raise _InvalidGPX("gpx_unsupported_xml_encoding")

    @staticmethod
    def reject_dtd(*args: Any) -> None:
        raise _InvalidGPX("gpx_dtd_or_entity_declaration_unsupported")

    @staticmethod
    def reject_external_reference(*args: Any) -> int:
        raise _InvalidGPX("gpx_external_entity_reference_unsupported")

    def start(self, name: str, attributes: dict[str, str]) -> None:
        self.elements += 1
        if self.elements > _MAX_ELEMENTS:
            raise _InvalidGPX("gpx_element_budget_exceeded")
        if len(self.frames) + 1 > _MAX_DEPTH:
            raise _InvalidGPX("gpx_depth_budget_exceeded")
        if not self.frames:
            if self.seen_root:
                raise _InvalidGPX("gpx_multiple_roots")
            if name != _ROOT_NAME:
                raise _NotGPX()
            self.seen_root = True
            if attributes.get("version") != "1.1":
                raise _InvalidGPX("gpx_unsupported_version")
            if "creator" not in attributes:
                raise _InvalidGPX("gpx_missing_creator")
            self.creator = attributes["creator"]
            if len(self.creator) > _MAX_CREATOR_CHARACTERS:
                raise _InvalidGPX("gpx_creator_budget_exceeded")
            self.frames.append(_Frame("gpx", "/gpx[1]", False))
            return

        parent = self.frames[-1]
        namespace, separator, local = name.rpartition("}")
        native = bool(separator) and namespace == _NAMESPACE
        if parent.ignored:
            self.frames.append(_Frame(local if native else None, None, True))
            return
        if not native:
            raise _InvalidGPX("gpx_foreign_element_outside_extensions")
        if local == "extensions":
            self.optional_fields_present = True
            self.frames.append(_Frame(local, None, True))
            return
        if local == "gpx":
            raise _InvalidGPX("gpx_misplaced_structural_element")
        if local not in _PARENTS:
            # This is deliberately not an XSD validation of optional GPX
            # fields. Structural GPX descendants are still checked below.
            self.optional_fields_present = True
            self.frames.append(_Frame(local, None, False))
            return
        if parent.local != _PARENTS[local] or parent.path is None:
            raise _InvalidGPX("gpx_misplaced_structural_element")
        ordinal = parent.children.get(local, 0) + 1
        parent.children[local] = ordinal
        path = f"{parent.path}/{local}[{ordinal}]"
        self.counts[local] += 1
        if local in _POINTS:
            if len(self.points) >= _MAX_POSITIONS:
                raise _InvalidGPX("gpx_position_budget_exceeded")
            latitude = _coordinate(attributes, "lat")
            longitude = _coordinate(attributes, "lon")
            self.points.append({"path": path, "coordinates": [longitude, latitude]})
        self.frames.append(_Frame(local, path, False))

    def end(self, name: str) -> None:
        self.frames.pop()

    def text(self, text: str) -> None:
        if not self.frames or not text.strip(_XML_WHITESPACE):
            return
        frame = self.frames[-1]
        if not frame.ignored and frame.path is not None:
            raise _InvalidGPX("gpx_unexpected_structural_character_data")


def _tag(namespace: str, value: str, evidence: str = _STRUCTURE_EVIDENCE) -> dict[str, Any]:
    return {
        "namespace": namespace,
        "value": value,
        "basis": "parsed_structure",
        "evidence_refs": [evidence],
    }


def _base_report(length: int) -> dict[str, Any]:
    return {
        "format": "gpx",
        "media_type": "application/gpx+xml",
        "modalities": ["geospatial", "text"],
        "metadata": [],
        "tag_proposals": [_tag("format", "gpx"), _tag("modality", "geospatial"), _tag("modality", "text")],
        "evidence": [{
            "id": _STRUCTURE_EVIDENCE,
            "kind": "parsed_gpx_structure",
            "byte_range": [0, length],
            "profile": PROFILE_ID,
        }],
        "issues": ["gpx_schema_not_fully_validated"],
        "analysis_scope": "gpx_1_1_coordinate_profile",
        "spatial": None,
    }


def probe_gpx(data: bytes, *, complete: bool = True) -> dict[str, Any] | None:
    """Extract this coordinate profile atomically from complete UTF-8 GPX 1.1.

    Invalid API arguments raise ValueError. No recognized GPX root or a partial
    sample yields None. An error after recognizing the root yields format-only
    evidence with spatial=None; no previously parsed positions are exposed.
    """
    if type(data) is not bytes or len(data) > _MAX_BYTES:
        raise ValueError("data must be bytes containing at most 1 MiB.")
    if type(complete) is not bool:
        raise ValueError("complete must be a boolean.")
    if not complete:
        return None
    # XML 1.0 forbids a literal U+0000. ASCII/NUL UTF-16 and UTF-32 byte
    # streams can pass a UTF-8 decode and still trigger Expat autodetection,
    # even with an encoding argument. Rejecting NUL excludes those encodings
    # without rejecting any valid UTF-8 XML 1.0 or numeric character reference.
    if b"\x00" in data:
        return None
    try:
        # Reject invalid UTF-8 byte sequences; a UTF-8 BOM remains valid.
        data.decode("utf-8")
    except UnicodeError:
        return None

    state = _CoordinateParser()
    parser = expat.ParserCreate(encoding="UTF-8", namespace_separator="}")
    parser.XmlDeclHandler = state.xml_declaration
    parser.StartElementHandler = state.start
    parser.EndElementHandler = state.end
    parser.CharacterDataHandler = state.text
    parser.StartDoctypeDeclHandler = state.reject_dtd
    parser.EntityDeclHandler = state.reject_dtd
    parser.UnparsedEntityDeclHandler = state.reject_dtd
    parser.ExternalEntityRefHandler = state.reject_external_reference
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True)
    except _NotGPX:
        return None
    except (_InvalidGPX, expat.ExpatError) as exc:
        if not state.seen_root:
            return None
        report = _base_report(len(data))
        report["issues"].append(str(exc) if isinstance(exc, _InvalidGPX) else "gpx_xml_invalid")
        return report
    if not state.seen_root:
        return None

    report = _base_report(len(data))
    points = state.points
    coordinates = [point["coordinates"] for point in points]
    bbox = None
    if coordinates:
        bbox = [
            min(point[0] for point in coordinates),
            min(point[1] for point in coordinates),
            max(point[0] for point in coordinates),
            max(point[1] for point in coordinates),
        ]
    report["spatial"] = {
        "crs": "OGC:CRS84",
        "axis_order": ["longitude", "latitude"],
        "units": "degrees",
        "position_count": len(points),
        "bbox": bbox,
    }
    report["evidence"].append({
        "id": _POSITIONS_EVIDENCE,
        "kind": "parsed_gpx_positions",
        "points": points,
        "byte_range": [0, len(data)],
        "axis_order": ["longitude", "latitude"],
    })
    values: dict[str, Any] = {
        "version": "1.1",
        "creator": state.creator,
        "profile": PROFILE_ID,
        **state.counts,
        "position_count": len(points),
        "optional_fields": "not_extracted_or_validated",
    }
    report["metadata"] = [
        {"name": name, "value": value, "basis": "parsed_structure", "evidence_ref": _STRUCTURE_EVIDENCE}
        for name, value in values.items()
    ]
    if state.optional_fields_present:
        report["issues"].append("gpx_optional_fields_not_extracted")
    if points:
        report["tag_proposals"].extend([
            _tag("spatial", "has_coordinates", _POSITIONS_EVIDENCE),
            _tag("crs", "OGC:CRS84", _POSITIONS_EVIDENCE),
        ])
    for count_name, content in (("wpt", "waypoints"), ("rte", "routes"), ("trk", "tracks")):
        if state.counts[count_name]:
            report["tag_proposals"].append(_tag("gpx_content", content))
    return report
