"""Authored GPX coordinates exercise inspection and its existing consumers.

All coordinates below are synthetic fixtures, not a user's GPS records.
Detailed XML/coordinate parsing cases belong to test_gpx_probe.py.
"""

from copy import deepcopy
import hashlib
import json
import socket
import urllib.request

import pytest

from examples.asset_catalog_demo import _png
from tiberium_ai.asset_catalog import search_asset_reports
from tiberium_ai.asset_catalog_snapshot import (
    create_asset_catalog, export_asset_reports, put_asset_report, validate_asset_catalog,
)
from tiberium_ai.asset_cli import main
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import (
    append_tag_decision, create_tag_journal, validated_review_report_hash,
)
from tiberium_ai.asset_tag_review import project_tag_reviews, search_reviewed_assets
from tiberium_ai.gpx_probe import PROFILE_ID
from tiberium_ai.verification import hash_input


NAMESPACE = "http://www.topografix.com/GPX/1/1"
BODY = (
    '<wpt lat="48.25" lon="2.5"/>'
    '<rte><rtept lat="-4" lon="-10"/></rte>'
    '<trk><trkseg><trkpt lat="50" lon="12"/></trkseg></trk>'
)
BOUNDS = [-10.0, -4.0, 12.0, 50.0]


def _gpx(body=BODY, *, attributes=""):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<gpx xmlns="{NAMESPACE}" version="1.1" creator="authored-fixture" {attributes}>'
        f'{body}</gpx>'
    ).encode("utf-8")


def _inspect(data=None, *, filename="authored.gpx", revision="v1", **options):
    return inspect_asset(
        _gpx() if data is None else data, filename=filename,
        source_id="fixture:synthetic-gpx", revision=revision, **options,
    )


def _tags(report):
    return {(tag["namespace"], tag["value"]) for tag in report["tag_proposals"]}


def _accept(report):
    return append_tag_decision(
        create_tag_journal(), report, namespace="format", value="gpx", action="accept",
        actor_id="fixture:reviewer", reason="Authored coordinate profile reviewed",
        event_id="gpx-format-review", expected_head=None,
    )


def _select(report):
    empty = create_asset_catalog("fixture:gpx-catalog")
    return put_asset_report(empty, report, expected_head=empty["snapshot_hash"], expected_report_hash=None)


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _ok(capsys, *args):
    assert main([str(arg) for arg in args]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    return json.loads(output.out)


def _node_count(value):
    if type(value) is dict:
        return 1 + sum(_node_count(item) for item in value.values())
    if type(value) is list:
        return 1 + sum(_node_count(item) for item in value)
    return 1


def _track(count):
    points = "".join(f'<trkpt lat="10.{index:04}" lon="20.{index:04}"/>' for index in range(count))
    return _gpx(f"<trk><trkseg>{points}</trkseg></trk>")


@pytest.mark.parametrize("filename,conflict", [("route.gpx", False), ("route.jpg", True), ("route", None)])
def test_xml_profile_wins_over_filename_hints(filename, conflict):
    report = _inspect(filename=filename)
    assert report["format"]["detected"] == "gpx"
    assert report["format"]["basis"] == "gpx_1_1_coordinate_profile"
    assert report["format"]["extension_conflict"] is conflict
    assert ("format", "gpx") in _tags(report)
    assert ("modality", "geospatial") in _tags(report)
    assert report["analyser"] == {"id": "asset-gpx-inspection", "version": "1"}
    assert report["spatial"]["bbox"] == BOUNDS
    assert validated_review_report_hash(report) == hash_input(report)


def test_full_source_hash_proposed_tags_and_all_evidence_links_are_preserved():
    data = _gpx()
    report = _inspect(data)
    digest = hashlib.sha256(data).hexdigest()
    assert report["sample"] == {"sha256": digest, "bytes": len(data), "complete": True, "total_bytes": len(data), "content_sha256": digest}
    assert report["source"] == {"id": "fixture:synthetic-gpx", "revision": "v1", "filename": "authored.gpx"}
    assert report["mode"] == "shadow"
    assert all(tag["status"] == "proposed" for tag in report["tag_proposals"])
    evidence = {item["id"] for item in report["evidence"]}
    assert len(evidence) == len(report["evidence"])
    assert all(tag["evidence_refs"] and set(tag["evidence_refs"]) <= evidence for tag in report["tag_proposals"])
    assert all(item["evidence_ref"] in evidence for item in report["metadata"] if "evidence_ref" in item)
    assert report["limits"]["model_calls"] == 0
    assert report["limits"]["file_mutations"] == 0
    assert report["limits"]["gpx_profile"] == PROFILE_ID
    assert report["limits"]["gpx_schema"] == "coordinate_profile_not_full_xsd_validation"
    assert report["limits"]["external_xml_access"] == "not_performed"
    assert report["limits"]["geometry"] == "point_envelope_not_route_intersection"


def test_spatial_contract_keeps_longitude_latitude_order_for_all_supported_point_kinds():
    report = _inspect()
    assert report["spatial"] == {
        "crs": "OGC:CRS84", "axis_order": ["longitude", "latitude"],
        "units": "degrees", "position_count": 3, "bbox": BOUNDS,
    }
    assert ("spatial", "has_coordinates") in _tags(report)
    assert ("crs", "OGC:CRS84") in _tags(report)
    assert not any(tag["namespace"] in {"place", "address", "country"} for tag in report["tag_proposals"])
    positions = next(item for item in report["evidence"] if item["kind"] == "parsed_gpx_positions")
    assert positions["axis_order"] == ["longitude", "latitude"]
    assert positions["byte_range"] == [0, len(_gpx())]
    assert positions["points"] == [
        {"path": "/gpx[1]/wpt[1]", "coordinates": [2.5, 48.25]},
        {"path": "/gpx[1]/rte[1]/rtept[1]", "coordinates": [-10.0, -4.0]},
        {"path": "/gpx[1]/trk[1]/trkseg[1]/trkpt[1]", "coordinates": [12.0, 50.0]},
    ]
    coordinate_tags = [tag for tag in report["tag_proposals"] if tag["namespace"] in {"spatial", "crs"}]
    assert all(tag["evidence_refs"] == [positions["id"]] for tag in coordinate_tags)


@pytest.mark.parametrize("topics", [None, {"synthetic": ["authored"]}])
def test_gpx_input_hash_binds_the_profile_in_addition_to_existing_inputs(topics):
    report = _inspect(topic_terms=topics)
    old_inputs = {"source": report["source"], "sample": report["sample"], "topic_terms": topics}
    assert report["input_hash"] == hash_input(dict(old_inputs, gpx_profile=PROFILE_ID))
    assert report["input_hash"] != hash_input(old_inputs)
    assert report["analyser"] == {"id": "asset-gpx-inspection", "version": "1"}


@pytest.mark.parametrize("data,filename", [
    (b"Authored robot notes.", "notes.txt"),
    (b"def fixture():\n    return 1\n", "fixture.py"),
    (_png(), "fixture.png"),
])
def test_existing_non_gpx_analyser_and_input_hash_remain_unchanged(data, filename):
    topics = {"robotique": ["robot"]}
    report = _inspect(data, filename=filename, topic_terms=topics)
    assert report["analyser"] == {"id": "asset-inspection", "version": "1"}
    assert report["input_hash"] == hash_input({"source": report["source"], "sample": report["sample"], "topic_terms": topics})
    assert "gpx_profile" not in report["limits"]


@pytest.mark.parametrize("bbox,expected", [([-11, -5, 13, 51], 1), ([2, 48, 3, 49], 1), ([48, 2, 49, 3], 0), ([100, 70, 110, 80], 0)])
def test_existing_bbox_search_treats_gpx_as_an_envelope_candidate(bbox, expected):
    report = _inspect()
    found = search_asset_reports([report], tags=["format:gpx"], bbox=bbox)
    assert found["count"] == expected
    if expected:
        assert found["matches"][0]["spatial_match"] == "envelope_overlap_candidate"
        assert found["matches"][0]["sample_sha256"] == report["sample"]["sha256"]


def test_gpx_report_survives_catalogue_and_review_json_reload(tmp_path):
    report = _inspect()
    snapshot, journal = _select(report), _accept(report)
    stored_snapshot = _write(tmp_path / "catalog.json", snapshot)
    stored_journal = _write(tmp_path / "review.json", journal)
    reloaded_snapshot, reloaded_journal = _load(stored_snapshot), _load(stored_journal)
    assert validate_asset_catalog(reloaded_snapshot) is None
    reports = export_asset_reports(reloaded_snapshot)
    assert reports == [report]
    assert search_reviewed_assets(reports, create_tag_journal(), tags=["format:gpx"], bbox=BOUNDS)["count"] == 0
    found = search_reviewed_assets(reports, reloaded_journal, tags=["format:gpx"], bbox=BOUNDS)
    assert found["count"] == 1
    assert found["matches"][0]["report_hash"] == hash_input(report)
    assert found["matches"][0]["tag_states"][0]["status"] == "accepted"
    assert reloaded_snapshot == snapshot and reloaded_journal == journal


@pytest.mark.parametrize("revision,reason", [("v1", "report_changed"), ("v2", "source_revision_changed")])
def test_changed_coordinates_invalidate_review_while_historical_catalogue_still_works(tmp_path, revision, reason):
    report = _inspect()
    old_snapshot, journal = _select(report), _accept(report)
    old_path = _write(tmp_path / "historical.json", old_snapshot)
    old_bytes = old_path.read_bytes()
    changed = _inspect(_gpx('<wpt lat="-30" lon="140"/>'), revision=revision)
    current = put_asset_report(old_snapshot, changed, expected_head=old_snapshot["snapshot_hash"], expected_report_hash=hash_input(report))
    current_path = _write(tmp_path / "current.json", current)
    assert current["snapshot_hash"] != old_snapshot["snapshot_hash"]
    assert changed["input_hash"] != report["input_hash"]
    current_reports = export_asset_reports(_load(current_path))
    assert search_reviewed_assets(current_reports, journal, tags=["format:gpx"], bbox=[139, -31, 141, -29])["count"] == 0
    assert search_reviewed_assets(current_reports, journal, tags=["format:gpx"], states=["proposed"], bbox=[139, -31, 141, -29])["count"] == 1
    projected = project_tag_reviews(current_reports, journal)
    assert projected["unapplied_events"][0]["reason"] == reason
    assert search_reviewed_assets(export_asset_reports(_load(old_path)), journal, tags=["format:gpx"], bbox=BOUNDS)["count"] == 1
    assert old_path.read_bytes() == old_bytes


@pytest.mark.parametrize("body", ["", '<wpt lat="1" lon="2"/><wpt lat="bad" lon="3"/>'])
def test_empty_or_late_invalid_coordinates_never_produce_a_bbox_candidate(body):
    report = _inspect(_gpx(body))
    assert report["format"]["detected"] == "gpx"
    assert report["spatial"] is None or (report["spatial"]["bbox"] is None and report["spatial"]["position_count"] == 0)
    assert ("spatial", "has_coordinates") not in _tags(report)
    assert search_asset_reports([report], bbox=[-180, -90, 180, 90])["count"] == 0
    assert search_reviewed_assets([report], _accept(report), tags=["format:gpx"], bbox=[-180, -90, 180, 90])["count"] == 0
    assert validated_review_report_hash(report) == hash_input(report)


@pytest.mark.parametrize("truncated", [False, True])
def test_prefix_gpx_is_never_promoted_to_complete_coordinate_evidence(truncated):
    full = _gpx()
    data = full[:-8] if truncated else full
    report = _inspect(data, complete=False, total_bytes=len(full) + 10)
    assert report["sample"]["complete"] is False
    assert report["sample"]["content_sha256"] is None
    assert report["sample"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert report["spatial"] is None
    assert ("spatial", "has_coordinates") not in _tags(report)
    assert search_asset_reports([report], bbox=BOUNDS)["count"] == 0


def test_external_xml_references_and_extension_points_are_not_opened_or_counted(tmp_path, monkeypatch):
    external = tmp_path / "external.xml"
    external.write_bytes(b'<wpt lat="88" lon="177"/>')
    payload = _gpx(
        '<metadata><link href="https://example.invalid/remote.gpx"/></metadata>'
        '<wpt lat="12" lon="34"/>'
        f'<extensions><wpt lat="88" lon="177"/><x:wpt xmlns:x="urn:fixture" lat="bad" lon="bad"/></extensions>',
        attributes=f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="{NAMESPACE} {external.as_uri()}"',
    )
    def forbidden(*args, **kwargs):
        raise AssertionError("Inspection must not access an XML reference")
    before = external.read_bytes()
    with monkeypatch.context() as blocked:
        blocked.setattr("builtins.open", forbidden)
        blocked.setattr("pathlib.Path.open", forbidden)
        blocked.setattr(urllib.request, "urlopen", forbidden)
        blocked.setattr(socket, "create_connection", forbidden)
        report = _inspect(payload)
    assert external.read_bytes() == before
    assert report["spatial"]["position_count"] == 1
    assert report["spatial"]["bbox"] == [34.0, 12.0, 34.0, 12.0]
    assert report["limits"]["external_xml_access"] == "not_performed"
    assert validated_review_report_hash(report) == hash_input(report)


def test_two_thousand_positions_fit_the_full_report_and_existing_consumers(tmp_path):
    data = _track(2000)
    report = _inspect(data)
    assert report["sample"]["complete"] is True
    assert report["spatial"]["position_count"] == 2000
    assert report["spatial"]["bbox"] == [20.0, 10.0, 20.1999, 10.1999]
    positions = next(item for item in report["evidence"] if item["kind"] == "parsed_gpx_positions")
    assert len(positions["points"]) == 2000
    assert positions["points"][0] == {"path": "/gpx[1]/trk[1]/trkseg[1]/trkpt[1]", "coordinates": [20.0, 10.0]}
    assert positions["points"][-1] == {"path": "/gpx[1]/trk[1]/trkseg[1]/trkpt[2000]", "coordinates": [20.1999, 10.1999]}
    assert _node_count(report) <= 20_000
    assert validated_review_report_hash(report) == hash_input(report)
    snapshot, journal = _select(report), _accept(report)
    stored = _write(tmp_path / "max-profile.json", snapshot)
    reloaded = _load(stored)
    assert validate_asset_catalog(reloaded) is None
    found = search_reviewed_assets(export_asset_reports(reloaded), journal, tags=["format:gpx"], bbox=[20, 10, 21, 11])
    assert found["count"] == 1 and found["matches"][0]["spatial_match"] == "envelope_overlap_candidate"


@pytest.mark.parametrize("count", [3, 2000])
def test_cli_inspect_catalogue_review_and_bbox_search_preserve_exact_gpx_source(tmp_path, capsys, count):
    source = tmp_path / "synthetic.gpx"
    source.write_bytes(_track(count))
    before = source.read_bytes()
    report = _ok(capsys, "inspect", source, "--source-id", "fixture:cli-gpx", "--revision", "fixture-v1")
    assert report["format"]["detected"] == "gpx" and report["spatial"]["position_count"] == count
    report_path = _write(tmp_path / "report.json", report)
    empty, selected = tmp_path / "catalog-0.json", tmp_path / "catalog-1.json"
    head = _ok(capsys, "catalog-init", empty, "--catalog-id", "fixture:gpx")["snapshot_hash"]
    _ok(capsys, "catalog-put", empty, report_path, "--expected-head", head, "--expected-report-hash", "none", "--out", selected)
    initial_journal, journal = tmp_path / "journal-0.json", tmp_path / "journal-1.json"
    _ok(capsys, "review-init", initial_journal)
    before_review = _ok(capsys, "catalog-search", selected, initial_journal, "--tag", "format:gpx", "--bbox", "20", "10", "21", "11")
    assert before_review["result"]["count"] == 0
    _ok(capsys, "review-tag", report_path, initial_journal, "--tag", "format:gpx", "--decision", "accept", "--actor", "fixture:reviewer", "--reason", "Authored GPX fixture reviewed", "--event-id", "cli-gpx-review", "--expected-head", "none", "--out", journal)
    result = _ok(capsys, "catalog-search", selected, journal, "--tag", "format:gpx", "--bbox", "20", "10", "21", "11")
    assert result["catalog"]["snapshot_hash"] == _load(selected)["snapshot_hash"]
    assert result["result"]["count"] == 1
    match = result["result"]["matches"][0]
    assert match["report_hash"] == hash_input(report)
    assert match["spatial_match"] == "envelope_overlap_candidate"
    assert match["tag_states"][0]["status"] == "accepted"
    assert match["source"] == report["source"]
    assert source.read_bytes() == before


def test_cli_missing_gpx_file_uses_existing_read_error_contract(tmp_path, capsys):
    assert main(["inspect", str(tmp_path / "missing.gpx"), "--source-id", "fixture:missing", "--revision", "v1"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and json.loads(output.err)["error"] == "FileNotFoundError"


@pytest.mark.parametrize("version", ["2", "01"])
def test_catalogue_whitelist_does_not_admit_unrecognized_gpx_analyser_versions(version):
    report = deepcopy(_inspect())
    report["analyser"]["version"] = version
    with pytest.raises(ValueError):
        validated_review_report_hash(report)
    with pytest.raises(ValueError):
        _select(report)
