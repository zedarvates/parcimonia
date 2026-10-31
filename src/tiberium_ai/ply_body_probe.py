"""Bounded, atomic PLY record validation with local-coordinate evidence.

This profile validates typed records and face references, not topology,
renderability or Gaussian-splat quality. Coordinates retain file-local axes
and unknown units. No geographic interpretation, I/O or rendering is performed.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
import re
import struct
from typing import Any

from .media_probe import _PLY_FLOATS, _PLY_TYPES, _SPLAT_PROPERTIES, probe_media

__all__ = ["PROFILE_ID", "probe_ply_body"]

PROFILE_ID = "parcimonia.ply-body-profile/v1"
_MAX_VERTICES = 10_000
_MAX_FACES = 10_000
_MAX_PROPERTIES = 256
_MAX_FIELD_VALUES = 200_000
_MAX_FACE_ITEMS = 256
_MAX_TOKEN_BYTES = 128
_TOKEN = re.compile(rb"[^ \t\r\n\v\f]+")
_INTEGER = re.compile(rb"[+-]?[0-9]+\Z", re.ASCII)
_FLOAT = re.compile(rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z", re.ASCII)
_BODY_EVIDENCE = "ply:body"
_EXTREMA_EVIDENCE = "ply:position_extrema"
_INDEX_PROPERTIES = frozenset({"vertex_indices", "vertex_index"})
_ROTATIONS = tuple(f"rot_{index}" for index in range(4))

# Format character and integer bounds; aliases have precisely the same type.
_TYPE_SPECS: dict[str, tuple[str, int | None, int | None]] = {
    "char": ("b", -128, 127), "int8": ("b", -128, 127),
    "uchar": ("B", 0, 255), "uint8": ("B", 0, 255),
    "short": ("h", -(2**15), 2**15 - 1), "int16": ("h", -(2**15), 2**15 - 1),
    "ushort": ("H", 0, 2**16 - 1), "uint16": ("H", 0, 2**16 - 1),
    "int": ("i", -(2**31), 2**31 - 1), "int32": ("i", -(2**31), 2**31 - 1),
    "uint": ("I", 0, 2**32 - 1), "uint32": ("I", 0, 2**32 - 1),
    "float": ("f", None, None), "float32": ("f", None, None),
    "double": ("d", None, None), "float64": ("d", None, None),
}


class _InvalidPLY(ValueError):
    pass


@dataclass
class _Property:
    name: str
    scalar: str | None = None
    count_type: str | None = None
    item_type: str | None = None


@dataclass
class _Element:
    name: str
    count: int
    properties: list[_Property]


def _parse_header(data: bytes, end: int) -> tuple[str, list[_Element]]:
    # The existing header probe has already established its own byte/line
    # budgets, grammar and unique names. Re-read only to retain property order.
    encoding = ""
    elements: list[_Element] = []
    # Match the header probe's byte line boundaries exactly. str.splitlines()
    # additionally splits VT/FF/FS/GS/RS inside an accepted comment, which could
    # otherwise turn comment text into fictitious properties or elements.
    for raw in data[:end].splitlines()[1:-1]:
        parts = raw.decode("ascii").strip().split()
        if parts[0] in {"comment", "obj_info"}:
            continue
        if parts[0] == "format":
            encoding = parts[1]
        elif parts[0] == "element":
            name, count = parts[1], int(parts[2])
            if name not in {"vertex", "face"}:
                raise _InvalidPLY("ply_body_unsupported_element")
            if count > (_MAX_VERTICES if name == "vertex" else _MAX_FACES):
                raise _InvalidPLY("ply_body_record_budget_exceeded")
            elements.append(_Element(name, count, []))
        else:
            if len(elements[-1].properties) >= _MAX_PROPERTIES:
                raise _InvalidPLY("ply_body_property_budget_exceeded")
            if parts[1] == "list":
                prop = _Property(parts[4], count_type=parts[2], item_type=parts[3])
            else:
                prop = _Property(parts[2], scalar=parts[1])
            elements[-1].properties.append(prop)
    return encoding, elements


def _check_profile(elements: list[_Element]) -> tuple[int, int, dict[str, str]]:
    counts = {element.name: element.count for element in elements}
    vertex_types: dict[str, str] = {}
    minimum_values = 0
    for element in elements:
        lists = [prop for prop in element.properties if prop.scalar is None]
        minimum_values += element.count * len(element.properties)
        for prop in element.properties:
            types = (prop.scalar,) if prop.scalar is not None else (prop.count_type, prop.item_type)
            if any(value not in _PLY_TYPES or value not in _TYPE_SPECS for value in types):
                raise _InvalidPLY("ply_body_unsupported_scalar_type")
        if element.name == "vertex":
            if lists:
                raise _InvalidPLY("ply_body_vertex_lists_unsupported")
            vertex_types = {prop.name: prop.scalar for prop in element.properties if prop.scalar is not None}
            if element.count and not {"x", "y", "z"} <= vertex_types.keys():
                raise _InvalidPLY("ply_body_required_coordinates_missing")
        else:
            if len(lists) > 1 or (lists and lists[0].name not in _INDEX_PROPERTIES):
                raise _InvalidPLY("ply_body_face_list_unsupported")
            if element.count and not lists:
                raise _InvalidPLY("ply_body_face_indices_list_required")
            if lists and (lists[0].count_type in _PLY_FLOATS or lists[0].item_type in _PLY_FLOATS):
                raise _InvalidPLY("ply_body_face_indices_must_be_integer_typed")
    if minimum_values > _MAX_FIELD_VALUES:
        raise _InvalidPLY("ply_body_field_value_budget_exceeded")
    return counts.get("vertex", 0), counts.get("face", 0), vertex_types


class _Reader:
    def __init__(self, data: bytes, start: int, encoding: str) -> None:
        self.data = data
        self.position = start
        self.ascii = encoding == "ascii"
        self.count = 0
        endian = ">" if encoding == "binary_big_endian" else "<"
        self.structs = {name: struct.Struct(endian + spec[0]) for name, spec in _TYPE_SPECS.items()}

    def scalar(self, type_name: str) -> tuple[int | float, int, int]:
        if self.count >= _MAX_FIELD_VALUES:
            raise _InvalidPLY("ply_body_field_value_budget_exceeded")
        self.count += 1
        if self.ascii:
            token = _TOKEN.search(self.data, self.position)
            if token is None:
                raise _InvalidPLY("ply_body_truncated")
            start, end = token.span()
            raw = token.group()
            if len(raw) > _MAX_TOKEN_BYTES:
                raise _InvalidPLY("ply_body_scalar_token_budget_exceeded")
            code, minimum, maximum = _TYPE_SPECS[type_name]
            if minimum is not None:
                if _INTEGER.fullmatch(raw) is None:
                    raise _InvalidPLY("ply_body_invalid_integer_token")
                value: int | float = int(raw)
                if not minimum <= value <= maximum:
                    raise _InvalidPLY("ply_body_integer_out_of_range")
            else:
                if _FLOAT.fullmatch(raw) is None:
                    raise _InvalidPLY("ply_body_invalid_float_token")
                value = float(raw)
                if not math.isfinite(value):
                    raise _InvalidPLY("ply_body_nonfinite_scalar")
                if code == "f":
                    try:
                        value = struct.unpack("!f", struct.pack("!f", value))[0]
                    except (OverflowError, struct.error) as exc:
                        raise _InvalidPLY("ply_body_float32_out_of_range") from exc
                    if not math.isfinite(value):
                        raise _InvalidPLY("ply_body_float32_out_of_range")
        else:
            unpacker = self.structs[type_name]
            start, end = self.position, self.position + unpacker.size
            if end > len(self.data):
                raise _InvalidPLY("ply_body_truncated")
            value = unpacker.unpack_from(self.data, start)[0]
            if type(value) is float and not math.isfinite(value):
                raise _InvalidPLY("ply_body_nonfinite_scalar")
        self.position = end
        return value, start, end

    def finish(self) -> None:
        if self.ascii:
            if _TOKEN.search(self.data, self.position) is not None:
                raise _InvalidPLY("ply_body_trailing_data")
            self.position = len(self.data)
        elif self.position != len(self.data):
            raise _InvalidPLY("ply_body_trailing_data")


def _gaussian_schema(vertex_types: dict[str, str]) -> bool:
    if not all(vertex_types.get(name) in _PLY_FLOATS for name in _SPLAT_PROPERTIES):
        return False
    rest_indices: list[int] = []
    for name, scalar in vertex_types.items():
        if not name.startswith("f_rest_"):
            continue
        suffix = name[len("f_rest_"):]
        if (scalar not in _PLY_FLOATS or not suffix.isascii() or not suffix.isdigit()
                or len(suffix) > 3 or str(int(suffix)) != suffix):
            return False
        rest_indices.append(int(suffix))
    return len(rest_indices) % 3 == 0 and sorted(rest_indices) == list(range(len(rest_indices)))


def _validate_records(
    data: bytes, start: int, encoding: str, elements: list[_Element], vertices: int,
    vertex_types: dict[str, str],
) -> tuple[_Reader, dict[str, dict[str, Any]], int | None]:
    reader = _Reader(data, start, encoding)
    extrema: dict[str, dict[str, Any]] = {}
    rotations_known = all(vertex_types.get(name) in _PLY_FLOATS for name in _ROTATIONS)
    zero_rotations = 0 if rotations_known else None
    for element in elements:
        for row in range(1, element.count + 1):
            record_start: int | None = None
            record_end = reader.position
            selected: dict[str, int | float] = {}
            for prop in element.properties:
                if prop.scalar is not None:
                    value, scalar_start, record_end = reader.scalar(prop.scalar)
                    if record_start is None:
                        record_start = scalar_start
                    if element.name == "vertex" and prop.name in {"x", "y", "z", *_ROTATIONS}:
                        selected[prop.name] = value
                else:
                    count, scalar_start, record_end = reader.scalar(prop.count_type)
                    if record_start is None:
                        record_start = scalar_start
                    if not 3 <= count <= _MAX_FACE_ITEMS:
                        raise _InvalidPLY("ply_body_face_list_length_out_of_profile")
                    for _ in range(count):
                        index, _, record_end = reader.scalar(prop.item_type)
                        if not 0 <= index < vertices:
                            raise _InvalidPLY("ply_body_face_index_out_of_range")
            if element.name != "vertex":
                continue
            for axis in ("x", "y", "z"):
                value = selected[axis]
                entry = {"row": row, "field": axis, "value": value, "byte_range": [record_start, record_end]}
                for suffix, comparator in (("min", lambda old: value < old), ("max", lambda old: value > old)):
                    key = f"{axis}_{suffix}"
                    if key not in extrema or comparator(extrema[key]["value"]):
                        extrema[key] = entry
            if rotations_known and all(selected[name] == 0 for name in _ROTATIONS):
                zero_rotations += 1
    reader.finish()
    return reader, extrema, zero_rotations


def _tag(value: str, references: list[str], *, namespace: str = "representation") -> dict[str, Any]:
    return {"namespace": namespace, "value": value, "basis": "validated_record_values", "evidence_refs": references}


def probe_ply_body(data: bytes, *, complete: bool = True) -> dict[str, Any] | None:
    """Validate this PLY body profile atomically, preserving header candidates.

    Every body scalar (including list counts and indices) is typed and finite.
    A rejected body retains only header observations: no observed count, bound
    or body proof is returned. Empty face elements need no indices list.
    """
    header = probe_media(data, complete=complete)
    if header is None or header["format"] != "ply":
        return None
    report = deepcopy(header)
    report["spatial"] = None
    report["analysis_scope"] = "header_only"
    if not complete:
        report["issues"].append("ply_complete_source_required")
        return report
    if report["issues"]:
        report["issues"].append("ply_header_unusable")
        return report
    start = report["evidence"][0]["byte_range"][1]
    try:
        encoding, elements = _parse_header(data, start)
        vertices, faces, vertex_types = _check_profile(elements)
        reader, extrema, zero_rotations = _validate_records(data, start, encoding, elements, vertices, vertex_types)
    except _InvalidPLY as exc:
        report["issues"].append(str(exc))
        return report

    report["analysis_scope"] = "ply_body_coordinate_profile"
    report["issues"].append("ply_body_profile_not_full_geometry_validation")
    report["evidence"].append({
        "id": _BODY_EVIDENCE, "kind": "validated_ply_body", "byte_range": [start, reader.position],
        "profile": PROFILE_ID, "encoding": encoding, "vertex_count": vertices,
        "face_count": faces, "field_value_count": reader.count,
    })
    bounds = None
    if vertices:
        report["evidence"].append({
            "id": _EXTREMA_EVIDENCE, "kind": "ply_position_extrema", "byte_range": [start, reader.position],
            "profile": PROFILE_ID, "extrema": extrema,
        })
        bounds = {
            "min": [extrema[f"{axis}_min"]["value"] for axis in ("x", "y", "z")],
            "max": [extrema[f"{axis}_max"]["value"] for axis in ("x", "y", "z")],
            "axis_order": ["x", "y", "z"], "units": "unknown",
            "coordinate_frame": "file_local_unspecified",
        }
        report["tag_proposals"].append(_tag("has_local_positions", [_BODY_EVIDENCE, _EXTREMA_EVIDENCE], namespace="geometry"))
    if faces:
        report["tag_proposals"].append(_tag("mesh_structure", [_BODY_EVIDENCE]))
    elif vertices:
        report["tag_proposals"].append(_tag("point_cloud_structure", [_BODY_EVIDENCE]))
    gaussian_schema = _gaussian_schema(vertex_types)
    if vertices and gaussian_schema:
        report["tag_proposals"].append(_tag("gaussian_splat_body_candidate", [_BODY_EVIDENCE]))
    values = {
        "observed_vertex_count": vertices,
        "observed_face_count": faces,
        "geometry_bounds_xyz": bounds,
        "observed_ply_encoding": encoding,
        "observed_field_value_count": reader.count,
        "gaussian_parameters": {
            "schema_compatible": gaussian_schema,
            "record_count": vertices,
            "zero_rotation_records": zero_rotations,
        },
    }
    for name, value in values.items():
        report["metadata"].append({
            "name": name, "value": value, "basis": "validated_record_values",
            "evidence_ref": _EXTREMA_EVIDENCE if name == "geometry_bounds_xyz" and vertices else _BODY_EVIDENCE,
        })
    return report
