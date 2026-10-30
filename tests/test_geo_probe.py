"""Geographic metadata must not be fabricated from hints or invalid content."""

import json

import pytest

from tiberium_ai.geo_probe import probe_geojson


def _data(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


def _point(coordinates):
    return {"type": "Point", "coordinates": coordinates}


def _tags(report):
    return {(tag["namespace"], tag["value"]) for tag in report["tag_proposals"]}


def _invalid(value, issue=None):
    report = probe_geojson(_data(value))
    assert report is not None
    assert report["issues"]
    if issue:
        assert issue in report["issues"]
    assert report["spatial"] is None
    assert report["metadata"] == []
    assert ("spatial", "has_coordinates") not in _tags(report)
    assert ("crs", "OGC:CRS84") not in _tags(report)
    return report


def test_point_keeps_longitude_latitude_order_and_evidence():
    data = _data(_point([2.3, 48.8]))
    report = probe_geojson(data)
    assert report["spatial"] == {
        "crs": "OGC:CRS84", "axis_order": ["longitude", "latitude"],
        "units": "degrees", "position_count": 1, "bbox": [2.3, 48.8, 2.3, 48.8],
    }
    assert not report["issues"]
    assert ("spatial", "has_coordinates") in _tags(report)
    assert report["evidence"] == [{"id": "geojson:structure", "kind": "parsed_json_structure", "byte_range": [0, len(data)]}]
    assert {item["evidence_ref"] for item in report["metadata"]} == {"geojson:structure"}


def test_axis_values_are_never_swapped_to_make_them_valid():
    _invalid(_point([48, 120]), "coordinate_out_of_range")


def test_two_plausible_axes_keep_the_declared_geojson_order():
    report = probe_geojson(_data(_point([48, 2])))
    assert report["spatial"]["bbox"] == [48, 2, 48, 2]


@pytest.mark.parametrize("coordinate", [
    [True, 2], [2, False], ["2", 48], [2, None], [181, 0], [-181, 0],
    [0, 91], [0, -91], [0], [0, 0, 0, 0], {"longitude": 2, "latitude": 48},
])
def test_invalid_coordinate_never_produces_spatial_tags(coordinate):
    _invalid(_point(coordinate))


def test_altitude_is_optional_and_has_explicit_units():
    report = probe_geojson(_data(_point([2, 48, 100])))
    values = {item["name"]: item["value"] for item in report["metadata"]}
    assert values["altitude_present"] is True
    assert values["altitude_units"] == "metres_above_wgs84_ellipsoid"
    assert report["spatial"]["bbox"] == [2, 48, 2, 48]


@pytest.mark.parametrize("geometry,expected_count,expected_bbox", [
    ({"type": "MultiPoint", "coordinates": [[2, 48], [-2, 49]]}, 2, [-2, 48, 2, 49]),
    ({"type": "LineString", "coordinates": [[2, 48], [3, 49]]}, 2, [2, 48, 3, 49]),
    ({"type": "MultiLineString", "coordinates": [[[2, 48], [3, 49]], [[0, 0], [1, 1]]]}, 4, [0, 0, 3, 49]),
    ({"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 0]]]}, 4, [0, 0, 2, 2]),
    ({"type": "MultiPolygon", "coordinates": [[[[0, 0], [2, 0], [2, 2], [0, 0]]]]}, 4, [0, 0, 2, 2]),
    ({"type": "GeometryCollection", "geometries": [_point([2, 48]), _point([-2, 49])]}, 2, [-2, 48, 2, 49]),
])
def test_supported_geometries_recompute_spatial_extent(geometry, expected_count, expected_bbox):
    report = probe_geojson(_data(geometry))
    assert report["spatial"]["position_count"] == expected_count
    assert report["spatial"]["bbox"] == expected_bbox


def test_supplied_false_bbox_is_not_trusted():
    point = _point([2.3, 48.8])
    point["bbox"] = [0, 0, 0, 0]
    assert probe_geojson(_data(point))["spatial"]["bbox"] == [2.3, 48.8, 2.3, 48.8]


def test_antimeridian_envelope_is_conservative_not_a_place_inference():
    report = probe_geojson(_data({"type": "LineString", "coordinates": [[170, 10], [-170, 20]]}))
    assert report["spatial"]["bbox"] == [-170, 10, 170, 20]
    assert not any(tag["namespace"] == "place" for tag in report["tag_proposals"])


@pytest.mark.parametrize("kind", ["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"])
def test_empty_coordinates_are_explicitly_coordinate_free(kind):
    report = probe_geojson(_data({"type": kind, "coordinates": []}))
    assert report["spatial"]["position_count"] == 0
    assert report["spatial"]["bbox"] is None
    assert ("spatial", "has_coordinates") not in _tags(report)


@pytest.mark.parametrize("value", [
    {"type": "Feature", "properties": {}, "geometry": None},
    {"type": "Feature", "properties": None, "geometry": None},
    {"type": "FeatureCollection", "features": []},
    {"type": "GeometryCollection", "geometries": []},
])
def test_empty_and_null_geometries_do_not_invent_a_location(value):
    report = probe_geojson(_data(value))
    assert report["spatial"]["bbox"] is None
    assert report["spatial"]["position_count"] == 0
    assert not report["issues"]


def test_feature_collection_extracts_every_geometry_without_copying_properties():
    data = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "private place"}, "geometry": _point([2, 48])},
        {"type": "Feature", "properties": None, "geometry": _point([3, 49])},
    ]}
    report = probe_geojson(_data(data))
    assert report["spatial"]["position_count"] == 2
    assert "private place" not in json.dumps(report)


def test_invalid_geometry_does_not_leak_partial_coordinate_success():
    collection = {"type": "GeometryCollection", "geometries": [_point([2, 48]), _point([2, 100])]}
    _invalid(collection, "coordinate_out_of_range")


@pytest.mark.parametrize("geometry,issue", [
    ({"type": "LineString", "coordinates": [[1, 2]]}, "linestring_too_short"),
    ({"type": "MultiLineString", "coordinates": [[[1, 2]]]}, "linestring_too_short"),
    ({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]}, "linear_ring_too_short"),
    ({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}, "linear_ring_not_closed"),
    ({"type": "MultiPolygon", "coordinates": [[]]}, "empty_polygon_member"),
    ({"type": "GeometryCollection", "geometries": [None]}, "invalid_geojson_object"),
    ({"type": "FeatureCollection", "features": [_point([1, 2])]}, "feature_collection_member_not_feature"),
    ({"type": "Feature", "geometry": _point([1, 2])}, "missing_feature_member"),
    ({"type": "Feature", "properties": [], "geometry": None}, "invalid_feature_properties"),
    ({"type": "Feature", "properties": {}, "geometry": None, "id": True}, "invalid_feature_id"),
])
def test_invalid_nesting_and_geometry_shapes(geometry, issue):
    _invalid(geometry, issue)


def test_legacy_crs_is_not_silently_treated_as_wgs84():
    value = _point([2, 48])
    value["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
    _invalid(value, "legacy_crs_unsupported")


def test_nested_legacy_crs_is_also_refused():
    value = _point([2, 48])
    value["crs"] = None
    _invalid({"type": "GeometryCollection", "geometries": [value]}, "legacy_crs_unsupported")


def test_crs_named_property_is_not_a_geometry_crs_member():
    feature = {"type": "Feature", "properties": {"crs": "a customer field"}, "geometry": _point([2, 48])}
    assert probe_geojson(_data(feature))["spatial"]["position_count"] == 1


@pytest.mark.parametrize("data", [
    b"", b"{}", b"[]", b"null", b"latitude,longitude\n48,2", b"{", b"\xff",
    b'{"type":"Point","type":"Point","coordinates":[1,2]}',
    b'{"type":"Point","coordinates":[NaN,2]}',
    b'{"type":"Point","coordinates":[Infinity,2]}',
    b'{"type":"Point","coordinates":[1,2],"p":{"x":1,"x":2}}',
    b'{"type":"Unknown","coordinates":[1,2]}', b'{"type":[],"coordinates":[1,2]}',
])
def test_not_safely_recognizable_json_returns_none(data):
    assert probe_geojson(data) is None


def test_overflowed_number_in_an_unused_property_is_not_accepted():
    report = probe_geojson(b'{"type":"Point","coordinates":[1,2],"p":1e999}')
    assert report["issues"] == ["nonfinite_json_number"]
    assert report["spatial"] is None


def test_truncated_or_declared_partial_input_never_yields_coordinates():
    data = _data(_point([2, 48]))
    assert probe_geojson(data, complete=False) is None
    assert probe_geojson(data[:-1]) is None


def test_nested_json_depth_is_bounded_before_geographic_extraction():
    property_value = 0
    for _ in range(35):
        property_value = [property_value]
    data = _point([2, 48])
    data["properties"] = property_value
    _invalid(data, "json_depth_budget_exceeded")


def test_node_budget_is_bounded_before_any_spatial_success():
    data = _point([2, 48])
    data["payload"] = [0] * 20_000
    _invalid(data, "json_node_budget_exceeded")


@pytest.mark.parametrize("data,complete", [("{}", True), (bytearray(b"{}"), True), (b"{}", 1), (b" " * (1024 * 1024 + 1), True)])
def test_api_types_and_byte_budget_are_strict(data, complete):
    with pytest.raises(ValueError):
        probe_geojson(data, complete=complete)


def test_repeatability_and_input_is_not_mutated():
    data = _data({"type": "Feature", "properties": {"label": "échantillon"}, "geometry": _point([2, 48])})
    assert probe_geojson(data) == probe_geojson(data)
