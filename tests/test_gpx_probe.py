"""GPX profile tests: provenance, exact placement and all-or-nothing geometry.

These fixtures check the supported extraction contract, not full GPX XSD
validation or semantic knowledge of the places named by a file.
"""

import json

import pytest

from tiberium_ai.gpx_probe import probe_gpx


NS = "http://www.topografix.com/GPX/1/1"


def document(body="", *, attributes='', creator='creator="fixture"', version="1.1"):
    return (
        f'<gpx xmlns="{NS}" xmlns:e="urn:fixture:extension" '
        f'version="{version}" {creator} {attributes}>{body}</gpx>'
    ).encode("utf-8")


def point(lat="48", lon="2", *, kind="wpt", body=""):
    return f'<{kind} lat="{lat}" lon="{lon}">{body}</{kind}>'


def positions(report):
    evidence = [item for item in report["evidence"] if item["id"] == "gpx:positions"]
    assert len(evidence) <= 1
    if not evidence:
        return []
    assert evidence[0]["kind"] == "parsed_gpx_positions"
    return evidence[0]["points"]


def tags(report):
    return {(tag["namespace"], tag["value"]) for tag in report["tag_proposals"]}


def invalid(data):
    report = probe_gpx(data)
    assert report is not None, "a recognized GPX root should retain format evidence"
    assert report["format"] == "gpx"
    assert report["issues"]
    assert report["spatial"] is None
    assert not positions(report)
    assert not any(item["id"] == "gpx:positions" for item in report["evidence"])
    assert ("spatial", "has_coordinates") not in tags(report)
    assert ("crs", "OGC:CRS84") not in tags(report)
    return report


def no_geography(data):
    report = probe_gpx(data)
    if report is not None:
        assert report["issues"]
        assert report["spatial"] is None
        assert not positions(report)
    return report


def test_waypoint_keeps_lon_lat_order_and_explicit_profile_limits():
    data = document(point("48.8", "2.3"))
    report = probe_gpx(data)
    assert report["format"] == "gpx"
    assert report["media_type"] == "application/gpx+xml"
    assert "geospatial" in report["modalities"]
    assert report["spatial"] == {
        "crs": "OGC:CRS84", "axis_order": ["longitude", "latitude"],
        "units": "degrees", "position_count": 1, "bbox": [2.3, 48.8, 2.3, 48.8],
    }
    assert positions(report) == [{"path": "/gpx[1]/wpt[1]", "coordinates": [2.3, 48.8]}]
    assert any(item["id"] == "gpx:structure" for item in report["evidence"])
    assert "gpx_schema_not_fully_validated" in report["issues"]
    assert ("spatial", "has_coordinates") in tags(report)


def test_waypoint_route_and_track_segments_preserve_order_and_1_based_paths():
    data = document(
        point("10", "1") + point("11", "2")
        + '<rte><name>first</name>'
        + point("12", "3", kind="rtept") + point("13", "4", kind="rtept")
        + '</rte><rte>' + point("14", "5", kind="rtept") + '</rte>'
        + '<trk><trkseg>' + point("15", "6", kind="trkpt")
        + point("16", "7", kind="trkpt") + '</trkseg><trkseg>'
        + point("17", "8", kind="trkpt") + '</trkseg></trk>'
        + '<trk><trkseg>' + point("18", "9", kind="trkpt") + '</trkseg></trk>'
    )
    report = probe_gpx(data)
    assert [item["path"] for item in positions(report)] == [
        "/gpx[1]/wpt[1]", "/gpx[1]/wpt[2]",
        "/gpx[1]/rte[1]/rtept[1]", "/gpx[1]/rte[1]/rtept[2]",
        "/gpx[1]/rte[2]/rtept[1]",
        "/gpx[1]/trk[1]/trkseg[1]/trkpt[1]",
        "/gpx[1]/trk[1]/trkseg[1]/trkpt[2]",
        "/gpx[1]/trk[1]/trkseg[2]/trkpt[1]",
        "/gpx[1]/trk[2]/trkseg[1]/trkpt[1]",
    ]
    assert [item["coordinates"] for item in positions(report)] == [
        [longitude, latitude] for longitude, latitude in zip(range(1, 10), range(10, 19))
    ]
    assert report["spatial"]["position_count"] == 9
    assert report["spatial"]["bbox"] == [1, 10, 9, 18]


def test_empty_segments_still_contribute_to_later_segment_indices():
    report = probe_gpx(document(
        '<trk><trkseg/><trkseg>' + point(kind="trkpt") + '</trkseg></trk>'
    ))
    assert positions(report) == [{
        "path": "/gpx[1]/trk[1]/trkseg[2]/trkpt[1]", "coordinates": [2, 48],
    }]


@pytest.mark.parametrize("body", ["", "<rte/>", "<trk/>", "<trk><trkseg/></trk>"])
def test_empty_gpx_never_invents_a_location(body):
    report = probe_gpx(document(body))
    assert report["spatial"] == {
        "crs": "OGC:CRS84", "axis_order": ["longitude", "latitude"],
        "units": "degrees", "position_count": 0, "bbox": None,
    }
    assert positions(report) == []
    assert ("spatial", "has_coordinates") not in tags(report)


def test_creator_attribute_may_be_empty_but_is_not_optional():
    assert probe_gpx(document(point(), creator='creator=""'))["spatial"]["position_count"] == 1
    invalid(document(point(), creator=""))


def test_creator_size_is_bounded_without_leaking_previous_positions():
    invalid(document(point(), creator='creator="' + "x" * 4097 + '"'))


@pytest.mark.parametrize("version", ["1.0", "2.0", "", "1.1 "])
def test_recognized_root_with_unsupported_version_has_only_format_evidence(version):
    invalid(document(point(), version=version))


def test_explicit_xml_prefix_has_the_same_canonical_paths():
    data = (
        f'<x:gpx xmlns:x="{NS}" version="1.1" creator="fixture">'
        '<x:trk><x:trkseg><x:trkpt lat="48" lon="2"/></x:trkseg></x:trk>'
        '</x:gpx>'
    ).encode("utf-8")
    assert positions(probe_gpx(data)) == [{
        "path": "/gpx[1]/trk[1]/trkseg[1]/trkpt[1]", "coordinates": [2, 48],
    }]


def test_utf8_bom_and_xml_1_0_declaration_are_supported():
    data = b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>' + document(point())
    assert probe_gpx(data)["spatial"]["bbox"] == [2, 48, 2, 48]


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_bomless_utf16_autodetection_cannot_bypass_the_utf8_profile(encoding):
    # All ASCII characters become UTF-8-decodable bytes containing NULs. An
    # unpinned Expat parser can nevertheless autodetect UTF-16 and extract GPS.
    data = document(point()).decode("ascii").encode(encoding)
    assert not data.startswith((b"\xff\xfe", b"\xfe\xff"))
    no_geography(data)


@pytest.mark.parametrize("data", [
    b"", b"\xff", b"{}", b"latitude,longitude\n48,2", b"<gpx/>",
    b'<gpx xmlns="http://www.topografix.com/GPX/1/0" version="1.1" creator="x"/>',
    b'<gpx xmlns="urn:other" version="1.1" creator="x"/>',
    f'<metadata xmlns="{NS}"/>'.encode("utf-8"),
])
def test_non_gpx_or_unrecognizable_content_returns_none(data):
    assert probe_gpx(data) is None


def test_declared_partial_input_never_yields_format_or_positions():
    assert probe_gpx(document(point()), complete=False) is None
    assert probe_gpx(document(point())[:-4], complete=False) is None


def test_late_xml_syntax_error_does_not_leak_the_first_point():
    data = document(point() + "<trk>")
    invalid(data)


@pytest.mark.parametrize("declaration", [
    '<?xml version="1.1" encoding="UTF-8"?>',
    '<?xml version="1.0" encoding="ISO-8859-1"?>',
])
def test_unsupported_xml_profile_never_yields_geography(declaration):
    no_geography(declaration.encode("ascii") + document(point()))


def test_foreign_point_names_outside_extensions_refuse_extraction():
    data = document('<e:wpt lat="999" lon="999"/>' + point())
    invalid(data)


def test_foreign_route_and_track_points_are_not_geographic_positions():
    data = document(
        '<rte><e:rtept lat="999" lon="999"/>' + point(kind="rtept") + '</rte>'
        '<trk><trkseg><e:trkpt lat="999" lon="999"/>'
        + point(kind="trkpt") + '</trkseg></trk>'
    )
    invalid(data)


def test_extensions_are_ignored_even_when_they_contain_standard_named_points():
    data = document(
        point() + '<extensions><e:data>' + point("999", "999", kind="trkpt")
        + '<trk><trkseg>' + point("999", "999", kind="trkpt")
        + '</trkseg></trk></e:data></extensions>'
    )
    report = probe_gpx(data)
    assert positions(report) == [{"path": "/gpx[1]/wpt[1]", "coordinates": [2, 48]}]
    assert report["spatial"]["position_count"] == 1


@pytest.mark.parametrize("misplaced", [
    point(kind="rtept"), point(kind="trkpt"), "<trkseg/>",
    '<rte>' + point() + '</rte>',
    '<trk>' + point(kind="trkpt") + '</trk>',
    '<rte><trk><trkseg/></trk></rte>',
    '<metadata>' + point() + '</metadata>',
    '<e:wrapper>' + point() + '</e:wrapper>',
])
def test_standard_gpx_points_and_containers_in_wrong_places_are_refused(misplaced):
    invalid(document(point("1", "2") + misplaced))


@pytest.mark.parametrize("lat,lon,coordinates", [
    ("90", "-180", [-180, 90]),
    ("-90", "179.5", [179.5, -90]),
    ("+48.800", "+002.300", [2.3, 48.8]),
    (".5", "2.", [2, 0.5]),
    (" \t48\n", "\r 2 ", [2, 48]),
    ("-0", "-0.000", [0, 0]),
])
def test_ascii_xsd_decimal_and_xml_whitespace_are_supported(lat, lon, coordinates):
    report = probe_gpx(document(point(lat, lon)))
    assert positions(report)[0]["coordinates"] == coordinates


@pytest.mark.parametrize("lat,lon", [
    ("90.0001", "2"), ("-90.0001", "2"), ("48", "180"), ("48", "-180.0001"),
    ("48", "181"), ("120", "48"),
    ("4.8e1", "2"), ("48", "2E0"),
    ("NaN", "2"), ("48", "Infinity"), ("-INF", "2"),
    ("٤٨", "2"), ("48", "２"),
    ("\u00a048", "2"), ("48", "2\u2003"),
    ("4 8", "2"), ("48", "+ 2"), ("", "2"),
    ("0x30", "2"), ("48", "2_0"),
    ("48", "179.999999999999999999999999999999999999"),
    ("90.000000000000000000000000001", "2"),
    ("48", "-180.000000000000000000000000001"),
])
def test_invalid_or_unrepresentable_coordinates_refuse_all_positions(lat, lon):
    invalid(document(point("1", "1") + point(lat, lon)))


def test_decimal_token_length_budget_is_checked_before_numeric_conversion():
    report = probe_gpx(document(point("48", "0" * 127 + "1")))
    assert positions(report)[0]["coordinates"] == [1, 48]
    invalid(document(point("48", "0" * 128 + "1")))


def test_xml_character_references_are_decoded_before_decimal_validation():
    report = probe_gpx(document(point("&#57;0", "&#50;")))
    assert positions(report)[0]["coordinates"] == [2, 90]
    invalid(document(point("&#xff19;0", "2")))


def test_predefined_xml_entities_in_non_geographic_fields_are_harmless():
    report = probe_gpx(document(point(body="<name>A &amp; B</name>"), creator='creator="A &amp; B"'))
    assert report["spatial"]["position_count"] == 1


def test_markup_looking_text_and_comments_do_not_create_points_or_dtds():
    body = '<!-- <!DOCTYPE gpx SYSTEM "https://example.invalid/not-a-real-dtd"> -->'
    body += '<metadata><desc><![CDATA[<wpt lat="48" lon="2"/>]]></desc></metadata>'
    report = probe_gpx(document(body))
    assert report["spatial"]["position_count"] == 0
    assert positions(report) == []


@pytest.mark.parametrize("body", [
    '<wpt lon="2"/>', '<wpt lat="48"/>',
    '<wpt xmlns:g="urn:attribute" g:lat="48" g:lon="2"/>',
])
def test_required_coordinate_attributes_are_unqualified_and_present(body):
    invalid(document(point("1", "1") + body))


def test_altitude_time_and_declared_bounds_do_not_change_2d_computed_positions():
    data = document(
        '<metadata><name>private location name</name>'
        '<bounds minlat="0" minlon="0" maxlat="0" maxlon="0"/></metadata>'
        + point("48", "2", body='<ele>999999</ele><time>2099-01-01T00:00:00Z</time>')
    )
    report = probe_gpx(data)
    assert positions(report) == [{"path": "/gpx[1]/wpt[1]", "coordinates": [2, 48]}]
    assert report["spatial"]["bbox"] == [2, 48, 2, 48]
    encoded = json.dumps(report)
    assert "999999" not in encoded
    assert "2099-01-01" not in encoded
    assert "private location name" not in encoded


def test_declared_bounds_without_positions_are_not_a_computed_location():
    data = document('<metadata><bounds minlat="1" minlon="2" maxlat="3" maxlon="4"/></metadata>')
    report = probe_gpx(data)
    assert report["spatial"]["position_count"] == 0
    assert report["spatial"]["bbox"] is None
    assert positions(report) == []


def test_minmax_envelope_is_conservative_across_antimeridian():
    report = probe_gpx(document(point("10", "179") + point("20", "-179")))
    assert report["spatial"]["bbox"] == [-179, 10, 179, 20]
    assert not any(tag["namespace"] == "place" for tag in report["tag_proposals"])


@pytest.mark.parametrize("doctype", [
    '<!DOCTYPE gpx [<!ENTITY coordinate "48">]>',
    '<!DOCTYPE gpx SYSTEM "https://example.invalid/never-fetch.dtd">',
])
def test_dtd_is_refused_without_geographic_extraction(doctype):
    no_geography(doctype.encode("ascii") + document(point()))


def test_external_entity_is_not_read_even_from_local_file(tmp_path, monkeypatch):
    private = tmp_path / "private-coordinate.txt"
    private.write_text("48", encoding="utf-8")
    doctype = f'<!DOCTYPE gpx [<!ENTITY latitude SYSTEM "{private.as_uri()}">]>'
    data = doctype.encode("ascii") + document(point("&latitude;", "2"))

    def forbidden(*args, **kwargs):
        raise AssertionError("GPX probe attempted filesystem access")

    with monkeypatch.context() as guard:
        guard.setattr("builtins.open", forbidden)
        guard.setattr(type(private), "open", forbidden)
        report = no_geography(data)
    if report is not None:
        assert private.as_uri() not in json.dumps(report)


def test_schema_and_links_are_declarations_only(monkeypatch):
    import socket
    import urllib.request

    def forbidden(*args, **kwargs):
        raise AssertionError("GPX probe attempted network access")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    data = document(
        '<metadata><link href="https://example.invalid/never-fetch"><text>label</text></link></metadata>'
        + point(),
        attributes='xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://www.topografix.com/GPX/1/1 https://example.invalid/gpx.xsd"',
    )
    assert probe_gpx(data)["spatial"]["position_count"] == 1


def test_position_budget_allows_2000_and_refuses_2001_without_partial_success():
    assert probe_gpx(document(point() * 2000))["spatial"]["position_count"] == 2000
    invalid(document(point() * 2001))


def test_ignored_extension_elements_still_count_toward_the_element_budget():
    at_limit = document('<extensions>' + '<e:x/>' * 19998 + '</extensions>')
    assert probe_gpx(at_limit)["spatial"]["position_count"] == 0
    over_limit = document(point() + '<extensions>' + '<e:x/>' * 19998 + '</extensions>')
    invalid(over_limit)


def test_ignored_extension_depth_counts_root_as_depth_one():
    at_limit = document('<extensions>' + '<e:x>' * 30 + '</e:x>' * 30 + '</extensions>')
    assert probe_gpx(at_limit)["spatial"]["position_count"] == 0
    over_limit = document(point() + '<extensions>' + '<e:x>' * 31 + '</e:x>' * 31 + '</extensions>')
    invalid(over_limit)


@pytest.mark.parametrize("data,complete", [
    ("<gpx/>", True), (bytearray(b"<gpx/>"), True), (memoryview(b"<gpx/>"), True),
    (b"", 1), (b"", None), (b" " * (1024 * 1024 + 1), True),
])
def test_api_types_and_raw_byte_budget_are_strict(data, complete):
    with pytest.raises(ValueError):
        probe_gpx(data, complete=complete)


def test_repeatable_report_has_no_unknown_evidence_references():
    data = document(point("48.8", "2.3"))
    report = probe_gpx(data)
    assert report == probe_gpx(data)
    ids = {item["id"] for item in report["evidence"]}
    assert {"gpx:structure", "gpx:positions"} <= ids
    for tag in report["tag_proposals"]:
        assert set(tag["evidence_refs"]) <= ids
    for item in report["metadata"]:
        assert item["evidence_ref"] in ids
    assert json.loads(json.dumps(report, allow_nan=False)) == report
