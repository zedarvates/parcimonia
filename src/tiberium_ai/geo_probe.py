"""Bounded GeoJSON structure and coordinate extraction, without geocoding.

Coordinates retain RFC 7946's longitude/latitude order. The computed envelope
is conservative: it is not a geometry-intersection test or an optimized
antimeridian envelope. Sources and semantic place names are never inferred.
"""

from __future__ import annotations

import json
import math
from typing import Any

__all__ = ["probe_geojson"]

_MAX_BYTES = 1024 * 1024
_MAX_DEPTH = 32
_MAX_NODES = 20_000
_MAX_POSITIONS = 10_000
_GEOMETRIES = {
    "Point", "MultiPoint", "LineString", "MultiLineString",
    "Polygon", "MultiPolygon", "GeometryCollection",
}
_TYPES = _GEOMETRIES | {"Feature", "FeatureCollection"}
_EVIDENCE = "geojson:structure"


class _InvalidGeoJSON(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("nonfinite_json_constant")


def _check_tree(root: Any) -> None:
    pending = [(root, 0)]
    nodes = 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_NODES:
            raise _InvalidGeoJSON("json_node_budget_exceeded")
        if depth > _MAX_DEPTH:
            raise _InvalidGeoJSON("json_depth_budget_exceeded")
        if type(value) is float and not math.isfinite(value):
            raise _InvalidGeoJSON("nonfinite_json_number")
        if type(value) is dict:
            pending.extend((item, depth + 1) for item in value.values())
        elif type(value) is list:
            pending.extend((item, depth + 1) for item in value)


def _array(value: Any) -> list[Any]:
    if type(value) is not list:
        raise _InvalidGeoJSON("invalid_coordinate_nesting")
    return value


def _position(value: Any) -> list[int | float]:
    position = _array(value)
    if len(position) not in (2, 3):
        raise _InvalidGeoJSON("invalid_position_dimension")
    for component in position:
        if type(component) not in (int, float):
            raise _InvalidGeoJSON("invalid_coordinate_number")
        if type(component) is float and not math.isfinite(component):
            raise _InvalidGeoJSON("nonfinite_coordinate")
    if not -180 <= position[0] <= 180 or not -90 <= position[1] <= 90:
        raise _InvalidGeoJSON("coordinate_out_of_range")
    return position


def _coordinate_positions(kind: str, coordinates: Any) -> list[list[int | float]]:
    """Validate bounded geometry nesting; no topological validity is claimed."""
    coordinates = _array(coordinates)
    # RFC 7946 permits processors to interpret empty coordinate arrays as null.
    if not coordinates:
        return []
    if kind == "Point":
        return [_position(coordinates)]

    result: list[list[int | float]] = []
    if kind in {"MultiPoint", "LineString"}:
        if kind == "LineString" and len(coordinates) < 2:
            raise _InvalidGeoJSON("linestring_too_short")
        return [_position(item) for item in coordinates]

    pending: list[tuple[str, Any]] = [(kind, coordinates)]
    while pending:
        current_kind, current = pending.pop()
        current = _array(current)
        if current_kind == "MultiLineString":
            for line in current:
                line = _array(line)
                if len(line) < 2:
                    raise _InvalidGeoJSON("linestring_too_short")
                result.extend(_position(item) for item in line)
        elif current_kind == "Polygon":
            for ring in current:
                ring = _array(ring)
                if len(ring) < 4:
                    raise _InvalidGeoJSON("linear_ring_too_short")
                positions = [_position(item) for item in ring]
                if positions[0] != positions[-1]:
                    raise _InvalidGeoJSON("linear_ring_not_closed")
                result.extend(positions)
        elif current_kind == "MultiPolygon":
            for polygon in current:
                polygon = _array(polygon)
                if not polygon:
                    raise _InvalidGeoJSON("empty_polygon_member")
                pending.append(("Polygon", polygon))
    return result


def _extract(root: dict[str, Any]) -> tuple[int, list[int | float] | None, bool, list[str]]:
    pending: list[tuple[Any, str]] = [(root, "root")]
    count = 0
    bounds: list[int | float] | None = None
    altitude = False
    geometry_types: set[str] = set()
    while pending:
        node, expected = pending.pop()
        if type(node) is not dict or type(node.get("type")) is not str:
            raise _InvalidGeoJSON("invalid_geojson_object")
        kind = node["type"]
        if kind not in _TYPES:
            raise _InvalidGeoJSON("unsupported_geojson_type")
        if expected == "feature" and kind != "Feature":
            raise _InvalidGeoJSON("feature_collection_member_not_feature")
        if expected == "geometry" and kind not in _GEOMETRIES:
            raise _InvalidGeoJSON("geometry_member_not_geometry")
        if "crs" in node:
            raise _InvalidGeoJSON("legacy_crs_unsupported")
        if kind == "FeatureCollection":
            features = node.get("features")
            if type(features) is not list:
                raise _InvalidGeoJSON("invalid_feature_collection")
            pending.extend((item, "feature") for item in features)
        elif kind == "Feature":
            if "geometry" not in node or "properties" not in node:
                raise _InvalidGeoJSON("missing_feature_member")
            if node["properties"] is not None and type(node["properties"]) is not dict:
                raise _InvalidGeoJSON("invalid_feature_properties")
            if "id" in node and type(node["id"]) not in (str, int, float):
                raise _InvalidGeoJSON("invalid_feature_id")
            if node["geometry"] is not None:
                pending.append((node["geometry"], "geometry"))
        elif kind == "GeometryCollection":
            geometry_types.add(kind)
            geometries = node.get("geometries")
            if type(geometries) is not list:
                raise _InvalidGeoJSON("invalid_geometry_collection")
            pending.extend((item, "geometry") for item in geometries)
        else:
            geometry_types.add(kind)
            if "coordinates" not in node:
                raise _InvalidGeoJSON("missing_coordinates")
            for position in _coordinate_positions(kind, node["coordinates"]):
                count += 1
                if count > _MAX_POSITIONS:
                    raise _InvalidGeoJSON("position_budget_exceeded")
                longitude, latitude = position[:2]
                altitude = altitude or len(position) == 3
                if bounds is None:
                    bounds = [longitude, latitude, longitude, latitude]
                else:
                    bounds[0] = min(bounds[0], longitude)
                    bounds[1] = min(bounds[1], latitude)
                    bounds[2] = max(bounds[2], longitude)
                    bounds[3] = max(bounds[3], latitude)
    return count, bounds, altitude, sorted(geometry_types)


def _tag(namespace: str, value: str) -> dict[str, Any]:
    return {"namespace": namespace, "value": value, "basis": "parsed_structure", "evidence_refs": [_EVIDENCE]}


def probe_geojson(data: bytes, *, complete: bool = True) -> dict[str, Any] | None:
    """Inspect one complete UTF-8 GeoJSON sample without external access.

    None means no safely recognizable complete GeoJSON object. A recognized
    object with unsupported/invalid coordinates retains only format evidence,
    lists its issue and has spatial=None. No partial coordinate success leaks.
    """
    if type(data) is not bytes or len(data) > _MAX_BYTES:
        raise ValueError("data must be bytes containing at most 1 MiB.")
    if type(complete) is not bool:
        raise ValueError("complete must be a boolean.")
    if not complete:
        return None
    try:
        root = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError, MemoryError):
        return None
    if type(root) is not dict or type(root.get("type")) is not str or root["type"] not in _TYPES:
        return None
    report: dict[str, Any] = {
        "format": "geojson",
        "media_type": "application/geo+json",
        "modalities": ["geospatial", "text"],
        "metadata": [],
        "tag_proposals": [_tag("format", "geojson"), _tag("modality", "geospatial"), _tag("modality", "text")],
        "evidence": [{"id": _EVIDENCE, "kind": "parsed_json_structure", "byte_range": [0, len(data)]}],
        "issues": [],
        "analysis_scope": "parsed_structure",
        "spatial": None,
    }
    try:
        _check_tree(root)
        count, bbox, altitude, geometry_types = _extract(root)
    except _InvalidGeoJSON as exc:
        report["issues"] = [str(exc)]
        return report
    report["spatial"] = {
        "crs": "OGC:CRS84",
        "axis_order": ["longitude", "latitude"],
        "units": "degrees",
        "position_count": count,
        "bbox": bbox,
    }
    values = {"geometry_types": geometry_types, "position_count": count, "bbox": bbox, "altitude_present": altitude}
    if altitude:
        values["altitude_units"] = "metres_above_wgs84_ellipsoid"
    report["metadata"] = [{"name": name, "value": value, "basis": "parsed_structure", "evidence_ref": _EVIDENCE} for name, value in values.items()]
    if count:
        report["tag_proposals"].extend([_tag("spatial", "has_coordinates"), _tag("crs", "OGC:CRS84")])
    return report
