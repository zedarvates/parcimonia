"""Authored local PLY geometry through inspection, catalogues and tag review.

No renderer or native tool is used. XYZ values have unknown file-local units;
the synthetic coordinates deliberately resemble plausible GPS values so that
the existing geographic search boundary is exercised rather than bypassed.
"""

from copy import deepcopy
import hashlib
import json
import os
import struct
import subprocess
import sys

import pytest

from examples.asset_catalog_demo import _png
from examples.ply_catalog_demo import cloud_fixture, fixture_bytes, mesh_fixture, run_demo, splat_fixture
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
from tiberium_ai.ply_body_probe import PROFILE_ID
from tiberium_ai.verification import hash_input


CASES = [
    ("cloud", cloud_fixture(), 3, 0, [-1.0, 2.0, -2.0], [1.0, 3.0, 4.0], "point_cloud_structure"),
    ("mesh-little", mesh_fixture("little"), 4, 1, [1.0, 2.0, 0.0], [2.0, 3.0, 3.0], "mesh_structure"),
    ("mesh-big", mesh_fixture("big"), 4, 1, [1.0, 2.0, 0.0], [2.0, 3.0, 3.0], "mesh_structure"),
    ("splat", splat_fixture(), 2, 0, [-1.0, 2.0, 0.0], [1.0, 4.0, 3.0], "gaussian_splat_body_candidate"),
]


def _inspect(data, *, filename="authored.ply", revision="v1", topics=None, **options):
    return inspect_asset(data, filename=filename, source_id="fixture:synthetic-ply", revision=revision, topic_terms=topics, **options)


def _metadata(report):
    return {item["name"]: item["value"] for item in report["metadata"]}


def _evidence(report):
    return {item["id"]: item for item in report["evidence"]}


def _tags(report):
    return {(tag["namespace"], tag["value"]) for tag in report["tag_proposals"]}


def _accept(report, representation):
    return append_tag_decision(
        create_tag_journal(), report, namespace="representation", value=representation,
        action="accept", actor_id="fixture:reviewer", reason="Authored typed PLY body reviewed",
        event_id="ply-body-review", expected_head=None,
    )


def _select(report):
    empty = create_asset_catalog("fixture:ply-catalog")
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


@pytest.mark.parametrize("kind,data,vertices,faces,minimum,maximum,representation", CASES, ids=[case[0] for case in CASES])
def test_full_typed_body_preserves_hashes_counts_bounds_and_resolvable_proposals(kind, data, vertices, faces, minimum, maximum, representation):
    report = _inspect(data)
    digest = hashlib.sha256(data).hexdigest()
    assert report["sample"] == {"sha256": digest, "content_sha256": digest, "bytes": len(data), "complete": True, "total_bytes": len(data)}
    assert report["analyser"] == {"id": "asset-ply-inspection", "version": "1"}
    assert report["input_hash"] == hash_input({"source": report["source"], "sample": report["sample"], "topic_terms": None, "ply_profile": PROFILE_ID})
    assert PROFILE_ID == "parcimonia.ply-body-profile/v1"
    assert report["format"]["detected"] == "ply"
    assert report["status"] == "partial" and report["mode"] == "shadow"
    assert report["spatial"] is None
    values, evidence = _metadata(report), _evidence(report)
    assert values["observed_vertex_count"] == vertices and values["observed_face_count"] == faces
    assert values["geometry_bounds_xyz"] == {
        "min": minimum, "max": maximum, "axis_order": ["x", "y", "z"],
        "units": "unknown", "coordinate_frame": "file_local_unspecified",
    }
    assert evidence["ply:body"]["kind"] == "validated_ply_body"
    assert evidence["ply:position_extrema"]["kind"] == "ply_position_extrema"
    assert ("representation", representation) in _tags(report)
    assert ("geometry", "has_local_positions") in _tags(report)
    assert all(tag["status"] == "proposed" and tag["evidence_refs"] for tag in report["tag_proposals"])
    assert all(set(tag["evidence_refs"]) <= evidence.keys() for tag in report["tag_proposals"])
    assert all(item["evidence_ref"] in evidence for item in report["metadata"] if "evidence_ref" in item)
    assert validated_review_report_hash(report) == hash_input(report)
    assert report["limits"]["model_calls"] == 0 and report["limits"]["file_mutations"] == 0
    assert search_asset_reports([report], tags=[f"representation:{representation}"])["count"] == 1
    assert search_asset_reports([report], tags=[f"representation:{representation}"], bbox=[-5, 0, 5, 5])["count"] == 0


def test_big_and_little_endian_quads_preserve_unknown_scalars_and_reordered_xyz():
    little, big = _inspect(mesh_fixture("little")), _inspect(mesh_fixture("big"))
    for name in ("observed_vertex_count", "observed_face_count", "geometry_bounds_xyz"):
        assert _metadata(little)[name] == _metadata(big)[name]
    assert _metadata(little)["observed_face_count"] == 1
    assert ("representation", "mesh_structure") in _tags(little) & _tags(big)
    assert little["sample"]["sha256"] != big["sample"]["sha256"]
    assert _metadata(little)["geometry_bounds_xyz"]["max"] == [2.0, 3.0, 3.0]


def test_raw_gaussian_signs_and_nonunit_quaternions_remain_schema_candidates():
    data = splat_fixture()
    body = data.split(b"end_header\n", 1)[1]
    first = struct.unpack_from("<14f", body)
    assert first[6] == -2.0
    assert first[7:10] == (-1.0, -2.0, -3.0)
    assert sum(value * value for value in first[10:14]) == 4.0
    report = _inspect(data)
    assert "ply:body" in _evidence(report)
    assert ("representation", "gaussian_splat_body_candidate") in _tags(report)
    assert not any(tag["value"] in {"gaussian_splat_validated", "renderable", "quality_passed"} for tag in report["tag_proposals"])
    assert report["limits"]["gaussian_splats"] == "schema_candidate_not_render_or_quality_validation"


def test_extrema_proofs_keep_original_one_based_rows_and_first_equal_occurrence():
    data = cloud_fixture()
    report = _inspect(data)
    body_start = data.index(b"end_header\n") + len(b"end_header\n")
    lines = data[body_start:].splitlines(keepends=True)
    row_ranges = []
    cursor = body_start
    for line in lines:
        row_ranges.append([cursor, cursor + len(line.rstrip())])
        cursor += len(line)
    evidence = _evidence(report)
    body = evidence["ply:body"]
    assert body["byte_range"] == [body_start, len(data)]
    assert body["vertex_count"] == 3 and body["face_count"] == 0
    assert body["field_value_count"] == 9
    assert body["profile"] == PROFILE_ID and body["encoding"] == "ascii"
    proof = evidence["ply:position_extrema"]
    expected = {
        "x_min": (2, "x", -1.0), "x_max": (1, "x", 1.0),
        "y_min": (1, "y", 2.0), "y_max": (2, "y", 3.0),
        "z_min": (3, "z", -2.0), "z_max": (2, "z", 4.0),
    }
    assert set(proof["extrema"]) == set(expected)
    assert proof["byte_range"] == [body_start, len(data)] and proof["profile"] == PROFILE_ID
    for name, (row, field, value) in expected.items():
        observed = proof["extrema"][name]
        assert observed == {"row": row, "field": field, "value": value, "byte_range": row_ranges[row - 1]}
        start, end = observed["byte_range"]
        source_values = data[start:end].decode("ascii").split()
        assert float(source_values["xyz".index(field)]) == value
    assert _evidence(_inspect(data))["ply:position_extrema"] == proof


@pytest.mark.parametrize("failure", ["prefix", "header_only", "invalid_header", "late_coordinate", "late_face", "unsupported_vertex_list"])
def test_partial_or_unusable_body_never_leaks_observed_bounds_or_body_tags(failure):
    data, options = cloud_fixture(), {}
    if failure == "prefix":
        options = {"complete": False, "total_bytes": len(data) + 1}
    elif failure == "header_only":
        data = data.split(b"end_header\n", 1)[0] + b"end_header\n"
    elif failure == "invalid_header":
        data = data.replace(b"property float z\n", b"property float x\n")
    elif failure == "late_coordinate":
        data = data.replace(b"1.0 2.0 -2.0\n", b"1.0 2.0 nan\n")
    elif failure == "late_face":
        data = mesh_fixture("little")
        data = data[:-23] + struct.pack("<fB4iH", 0.25, 4, 0, 1, 2, 99, 7)
    else:
        data = data.replace(b"end_header\n", b"property list uchar float feature\nend_header\n")
    report = _inspect(data, **options)
    assert report["format"]["detected"] == "ply" and report["status"] == "partial"
    assert report["spatial"] is None
    assert "ply:body" not in _evidence(report) and "ply:position_extrema" not in _evidence(report)
    assert not {"observed_vertex_count", "observed_face_count", "geometry_bounds_xyz"} & _metadata(report).keys()
    assert not any(value.endswith("_structure") or value == "gaussian_splat_body_candidate" for namespace, value in _tags(report) if namespace == "representation")
    candidate = "mesh_candidate" if failure == "late_face" else "point_cloud_candidate"
    if failure != "invalid_header":
        assert ("representation", candidate) in _tags(report)
    assert search_asset_reports([report], bbox=[-5, 0, 5, 5])["count"] == 0
    assert validated_review_report_hash(report) == hash_input(report)
    if failure == "prefix":
        assert report["sample"]["content_sha256"] is None


@pytest.mark.parametrize("kind,data,vertices,faces,minimum,maximum,representation", CASES, ids=[case[0] for case in CASES])
def test_catalogue_review_reload_and_changed_coordinates_keep_old_snapshot_reviewable(tmp_path, kind, data, vertices, faces, minimum, maximum, representation):
    report = _inspect(data)
    snapshot, journal = _select(report), _accept(report, representation)
    old_path = _write(tmp_path / "catalog-old.json", snapshot)
    journal_path = _write(tmp_path / "review.json", journal)
    before = {path: path.read_bytes() for path in (old_path, journal_path)}
    reloaded = _load(old_path)
    assert validate_asset_catalog(reloaded) is None
    reports = export_asset_reports(reloaded)
    assert search_reviewed_assets(reports, create_tag_journal(), tags=[f"representation:{representation}"])["count"] == 0
    assert search_reviewed_assets(reports, _load(journal_path), tags=[f"representation:{representation}"])["count"] == 1
    assert search_reviewed_assets(reports, journal, tags=[f"representation:{representation}"], bbox=[-5, 0, 5, 5])["count"] == 0
    if kind.startswith("mesh-"):
        changed_data = mesh_fixture(kind.split("-", 1)[1], shift_x=0.25)
    else:
        changed_data = fixture_bytes(kind, shift_x=0.25)
    changed = _inspect(changed_data)
    current = put_asset_report(reloaded, changed, expected_head=reloaded["snapshot_hash"], expected_report_hash=hash_input(report))
    new_reports = export_asset_reports(current)
    assert current["snapshot_hash"] != snapshot["snapshot_hash"]
    assert changed["input_hash"] != report["input_hash"]
    assert search_reviewed_assets(new_reports, journal, tags=[f"representation:{representation}"])["count"] == 0
    assert project_tag_reviews(new_reports, journal)["unapplied_events"][0]["reason"] == "report_changed"
    assert search_reviewed_assets(export_asset_reports(_load(old_path)), journal, tags=[f"representation:{representation}"])["count"] == 1
    assert {path: path.read_bytes() for path in before} == before


def test_inspection_and_tag_search_need_neither_native_execution_nor_external_io(monkeypatch):
    data = cloud_fixture().replace(b"comment authored fixture, units unknown", b"comment file:///never-opened https://example.invalid/never-fetched")
    def forbidden(*args, **kwargs):
        pytest.fail("PLY byte inspection must not execute a native tool or read a reference.")
    with monkeypatch.context() as blocked:
        blocked.setattr("builtins.open", forbidden)
        blocked.setattr("pathlib.Path.open", forbidden)
        blocked.setattr("subprocess.Popen", forbidden)
        blocked.setattr("tiberium_ai.native_process.run_bounded", forbidden)
        report = _inspect(data)
        found = search_asset_reports([report], tags=["representation:point_cloud_structure"])
    assert found["count"] == 1 and report["spatial"] is None


@pytest.mark.parametrize("kind,representation", [("cloud", "point_cloud_structure"), ("mesh", "mesh_structure"), ("splat", "gaussian_splat_body_candidate")])
def test_cli_inspects_real_fixture_file_then_catalogue_and_review_preserve_it(tmp_path, capsys, kind, representation):
    source = tmp_path / f"{kind}.ply"
    source.write_bytes(fixture_bytes(kind))
    before = source.read_bytes()
    report = _ok(capsys, "inspect", source, "--source-id", f"fixture:cli-ply:{kind}", "--revision", "v1")
    assert report["analyser"] == {"id": "asset-ply-inspection", "version": "1"}
    assert report["sample"]["content_sha256"] == hashlib.sha256(before).hexdigest()
    report_path = _write(tmp_path / "report.json", report)
    empty, selected = tmp_path / "catalog-0.json", tmp_path / "catalog-1.json"
    head = _ok(capsys, "catalog-init", empty, "--catalog-id", "fixture:ply-cli")["snapshot_hash"]
    _ok(capsys, "catalog-put", empty, report_path, "--expected-head", head, "--expected-report-hash", "none", "--out", selected)
    initial, accepted = tmp_path / "review-0.json", tmp_path / "review-1.json"
    _ok(capsys, "review-init", initial)
    _ok(capsys, "review-tag", report_path, initial, "--tag", f"representation:{representation}", "--decision", "accept", "--actor", "fixture:reviewer", "--reason", "Authored PLY fixture body reviewed", "--event-id", "ply-cli-review", "--expected-head", "none", "--out", accepted)
    result = _ok(capsys, "catalog-search", selected, accepted, "--tag", f"representation:{representation}")
    assert result["result"]["count"] == 1
    assert result["result"]["matches"][0]["report_hash"] == hash_input(report)
    gps = _ok(capsys, "catalog-search", selected, accepted, "--tag", f"representation:{representation}", "--bbox", "-5", "0", "5", "5")
    assert gps["result"]["count"] == 0
    assert source.read_bytes() == before


@pytest.mark.parametrize("data,filename", [(b"Authored robot notes.", "notes.txt"), (b"def fixture():\n    return 1\n", "fixture.py"), (_png(), "fixture.png")])
def test_non_ply_legacy_analyser_and_input_hash_are_unchanged(data, filename):
    topics = {"robotique": ["robot"]}
    report = _inspect(data, filename=filename, topics=topics)
    assert report["analyser"] == {"id": "asset-inspection", "version": "1"}
    assert report["input_hash"] == hash_input({"source": report["source"], "sample": report["sample"], "topic_terms": topics})
    assert "ply_profile" not in report["limits"]


def test_demo_summarizes_all_three_authored_bodies_and_review_boundaries():
    result = run_demo()
    assert result["data_origin"] == "authored_fixture_not_rendered_or_georeferenced"
    assert [item["kind"] for item in result["fixtures"]] == ["cloud", "mesh", "splat"]
    for item in result["fixtures"]:
        assert item["body_evidence"]["kind"] == "validated_ply_body"
        assert item["extrema_evidence"]["kind"] == "ply_position_extrema"
        assert item["body_tags"] and item["spatial"] is None
        assert len(item["source_sha256"]) == len(item["report_hash"]) == 64
        assert item["proposed_search_count"] == 1
        assert item["accepted_before_review"] == 0 and item["accepted_after_review"] == 1
        assert item["changed_report_accepted"] == 0 and item["old_report_still_accepted"] == 1
        assert item["changed_review_events"][0]["reason"] == "report_changed"
        assert item["gps_bbox_matches"] == 0 and item["model_calls"] == 0


@pytest.mark.parametrize("kind", ["cloud", "mesh", "splat"])
def test_demo_cli_emits_one_authored_fixture_as_ascii_json(kind):
    result = subprocess.run(
        [sys.executable, "examples/ply_catalog_demo.py", "--kind", kind],
        env=dict(os.environ, PYTHONIOENCODING="ascii"), capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.decode("ascii"))
    assert len(payload["fixtures"]) == 1 and payload["fixtures"][0]["kind"] == kind
    assert payload["fixtures"][0]["accepted_after_review"] == 1


def test_unrecognized_ply_analyser_version_cannot_enter_the_catalogue():
    report = deepcopy(_inspect(cloud_fixture()))
    report["analyser"]["version"] = "2"
    with pytest.raises(ValueError):
        validated_review_report_hash(report)
    with pytest.raises(ValueError):
        _select(report)


def test_ply_body_observation_wins_over_a_wrong_filename_suffix():
    report = _inspect(cloud_fixture(), filename="wrong.jpg")
    assert report["format"]["detected"] == "ply"
    assert "ply:body" in _evidence(report)
    assert _metadata(report)["observed_vertex_count"] == 3
