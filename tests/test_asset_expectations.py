"""Explicit expectations must not turn missing evidence into negative facts."""

from copy import deepcopy
import json

import pytest

from examples.asset_catalog_demo import _png, _wav
from examples.ply_catalog_demo import cloud_fixture, mesh_fixture
from tiberium_ai.asset_expectations import EXPECTATIONS_SCHEMA, audit_asset_expectations
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import validated_review_report_hash
from tiberium_ai.verification import hash_input


def report(data=None, *, source="asset", revision="v1", filename="asset.png", **options):
    return inspect_asset(_png() if data is None else data, filename=filename,
                         source_id=source, revision=revision, **options)


def check(fact="metadata.width", op="gte", value=1, *, identity="width"):
    return {"id": identity, "fact": fact, "op": op, "value": value}


def contract(*checks, source="asset", revision="v1"):
    return {"schema": EXPECTATIONS_SCHEMA, "id": "fixture:expectations", "assets": [
        {"source": {"id": source, "revision": revision}, "checks": list(checks) or [check()]},
    ]}


def result(reports, expectations):
    return audit_asset_expectations(reports, expectations)["results"][0]


@pytest.mark.parametrize("data,name,fact,op,value,state,actual,basis", [
    (_png(), "image.jpg", "format.detected", "eq", "png", "satisfied", "png", "header_only"),
    (_png(), "image.jpg", "format.detected", "eq", "jpeg", "contradicted", "png", "header_only"),
    (_png(), "image.png", "metadata.width", "gte", 1, "satisfied", 1, "parsed_header"),
    (_png(), "image.png", "metadata.height", "gte", 512, "contradicted", 1, "parsed_header"),
    (_wav(), "sound.wav", "metadata.channels", "eq", 1, "satisfied", 1, "declared_header"),
    (_wav(), "sound.wav", "metadata.sample_rate", "lte", 7999, "contradicted", 8000, "declared_header"),
    (_wav(), "sound.wav", "metadata.bits_per_sample", "eq", 16, "satisfied", 16, "declared_header"),
    (_wav(), "sound.wav", "metadata.declared_frames", "eq", 16, "satisfied", 16, "declared_header"),
    (cloud_fixture(), "cloud.ply", "metadata.observed_vertex_count", "eq", 3, "satisfied", 3, "validated_record_values"),
    (cloud_fixture(), "cloud.ply", "metadata.observed_face_count", "gte", 1, "contradicted", 0, "validated_record_values"),
    (mesh_fixture("big"), "mesh.ply", "metadata.observed_face_count", "gte", 1, "satisfied", 1, "validated_record_values"),
    (mesh_fixture("big"), "mesh.ply", "metadata.observed_ply_encoding", "eq", "binary_big_endian", "satisfied", "binary_big_endian", "validated_record_values"),
    (b'{"type":"Point","coordinates":[2,48]}', "point.geojson", "spatial.crs", "eq", "OGC:CRS84", "satisfied", "OGC:CRS84", "spatial_declaration"),
    (b'{"type":"Point","coordinates":[2,48]}', "point.geojson", "spatial.position_count", "eq", 1, "satisfied", 1, "spatial_declaration"),
    (b'{"type":"Point","coordinates":[2,48]}', "point.geojson", "metadata.position_count", "eq", 1, "satisfied", 1, "parsed_structure"),
])
def test_observed_declarations_compare_without_upgrading_their_basis(data, name, fact, op, value, state, actual, basis):
    supplied = report(data, filename=name)
    entry = result([supplied], contract(check(fact, op, value)))
    assert entry["status"] == state
    observed = entry["checks"][0]["observation"]
    assert observed["value"] == actual and observed["basis"] == basis
    assert entry["report_hash"] == validated_review_report_hash(supplied)
    for ref in observed["evidence_refs"]:
        assert ref in {item["id"] for item in supplied["evidence"]}
    for pointer in observed["paths"]:
        found = supplied
        for component in pointer.split("/")[1:]:
            found = found[int(component)] if type(found) is list else found[component]
        assert found == actual


@pytest.mark.parametrize("op,expected,state", [
    ("eq", 1, "satisfied"), ("eq", 0, "contradicted"),
    ("gte", 1, "satisfied"), ("gte", 2, "contradicted"),
    ("lte", 1, "satisfied"), ("lte", 0, "contradicted"),
])
def test_integer_boundaries_are_inclusive(op, expected, state):
    assert result([report()], contract(check(op=op, value=expected)))["status"] == state


@pytest.mark.parametrize("fact", ["metadata.width", "spatial.crs", "metadata.observed_face_count", "tag:topic:forest"])
def test_missing_fact_stays_unknown_even_for_a_complete_source(fact):
    value = True if fact.startswith("tag:") else "OGC:CRS84" if fact.endswith("crs") else 1
    supplied = report(b"unrelated text", filename="text.txt")
    entry = result([supplied], contract(check(fact, "eq", value)))
    assert entry["status"] == "unknown" and entry["checks"][0]["observation"] is None
    assert entry["checks"][0]["reason"] == "fact_not_available"


def test_atomic_ply_failure_cannot_be_confused_with_zero_observed_faces():
    supplied = report(cloud_fixture() + b"extra", filename="broken.ply")
    entry = result([supplied], contract(check("metadata.observed_face_count", "eq", 0)))
    assert entry["status"] == "unknown"


def test_local_xyz_and_even_a_gps_looking_comment_do_not_create_a_crs():
    data = cloud_fixture().replace(b"format ascii 1.0\n", b"format ascii 1.0\ncomment EPSG:4326\n")
    assert result([report(data, filename="points.ply")], contract(check("spatial.crs", "eq", "OGC:CRS84")))["status"] == "unknown"


def test_prefix_has_known_sample_size_and_incomplete_flag_but_no_full_body_facts():
    supplied = report(cloud_fixture(), filename="prefix.ply", complete=False, total_bytes=1000)
    checks = [check("sample.complete", "eq", True, identity="full"),
              check("sample.bytes", "eq", len(cloud_fixture()), identity="size"),
              check("metadata.observed_vertex_count", "gte", 1, identity="positions")]
    entry = result([supplied], contract(*checks))
    assert [item["status"] for item in entry["checks"]] == ["contradicted", "satisfied", "unknown"]
    assert entry["status"] == "contradicted"


@pytest.mark.parametrize("supplied", [[], [report(source="other")], [report(revision="v0")]])
def test_missing_report_is_only_an_exact_identity_gap_in_the_supplied_array(supplied):
    entry = result(supplied, contract())
    assert entry["status"] == "missing_report" and entry["report_hash"] is None
    assert entry["checks"][0]["status"] == "unknown"
    assert entry["checks"][0]["reason"] == "report_not_supplied"


def test_two_revisions_are_allowed_and_only_the_exact_revision_is_used():
    old, current = report(revision="v0"), report(b"plain text", revision="v1", filename="note.txt")
    assert result([old, current], contract())["status"] == "unknown"
    assert result([current, old], contract(revision="v0"))["status"] == "satisfied"


def test_filename_is_not_a_target_identity_and_hints_remain_proposals():
    supplied = report(filename="misnamed.jpg")
    entry = result([supplied], contract(check("tag:format_hint:jpeg", "eq", True)))
    observed = entry["checks"][0]["observation"]
    assert entry["status"] == "satisfied"
    assert observed["basis"] == "proposal_presence" and observed["proposal_bases"] == ["extension_hint"]
    assert supplied["format"]["detected"] == "png"
    assert all(tag["status"] == "proposed" for tag in supplied["tag_proposals"])


def test_repeated_proposals_merge_proofs_but_do_not_infer_absence():
    supplied = report()
    tag = deepcopy(supplied["tag_proposals"][0])
    supplied["tag_proposals"].append(tag)
    fact = f"tag:{tag['namespace']}:{tag['value']}"
    observed = result([supplied], contract(check(fact, "eq", True)))["checks"][0]["observation"]
    assert len(observed["paths"]) == 2
    assert observed["evidence_refs"] == sorted(set(tag["evidence_refs"]))


def test_summary_priority_and_every_check_remain_visible():
    supplied = [report(source="ok"), report(source="bad"), report(b"text", source="unknown", filename="a.txt")]
    expectations = contract()
    expectations["assets"] = [contract(source=name)["assets"][0] for name in ["ok", "bad", "unknown", "absent"]]
    expectations["assets"][1]["checks"] = [check(value=512), check("tag:topic:forest", "eq", True, identity="topic")]
    audit = audit_asset_expectations(supplied, expectations)
    assert audit["summary"] == {"satisfied": 1, "contradicted": 1, "unknown": 1, "missing_report": 1}
    assert [c["status"] for c in audit["results"][1]["checks"]] == ["contradicted", "unknown"]


def test_exact_hashes_change_with_contract_body_or_unselected_report_and_no_aliases():
    supplied, expectations = [report()], contract()
    before = deepcopy((supplied, expectations))
    first = audit_asset_expectations(supplied, expectations)
    assert first == audit_asset_expectations(supplied, expectations)
    assert first["input_hash"] == hash_input({"analyser": first["analyser"], "reports": supplied, "expectations": expectations})
    assert first["expectations"]["hash"] == hash_input(expectations)
    assert json.loads(json.dumps(first, allow_nan=False)) == first
    altered = deepcopy(expectations)
    altered["assets"][0]["checks"][0]["value"] = 512
    assert audit_asset_expectations(supplied, altered)["input_hash"] != first["input_hash"]
    changed = deepcopy(supplied)
    changed[0]["limits"]["extra_declaration"] = "new"
    assert audit_asset_expectations(changed, expectations)["results"][0]["report_hash"] != first["results"][0]["report_hash"]
    extra = audit_asset_expectations([*supplied, report(source="unselected")], expectations)
    assert extra["input_hash"] != first["input_hash"] and extra["results"] == first["results"]
    first["reports"][0]["source"]["filename"] = "changed"
    first["results"][0]["checks"][0]["value"] = 999
    assert (supplied, expectations) == before


def test_pure_api_never_opens_files_or_starts_processes(monkeypatch):
    supplied, expectations = [report()], contract()
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected I/O")
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    assert audit_asset_expectations(supplied, expectations)["summary"]["satisfied"] == 1


@pytest.mark.parametrize("fact,op,value", [
    ("metadata.unlisted", "eq", 1), ("../metadata.width", "eq", 1),
    ("modalities", "eq", "image"), ("tag:missing", "eq", True),
    ("tag::value", "eq", True), ("tag:ns: value", "eq", True),
    ("tag:ns:value", "eq", False), ("tag:ns:value", "eq", 1),
    ("metadata.width", "eq", True), ("metadata.width", "gte", 1.0),
    ("metadata.width", "gte", -1), ("metadata.width", "eq", 2**63),
    ("metadata.width", "between", 1), ("metadata.width", [], 1),
    ("sample.complete", "gte", True), ("sample.complete", "eq", 1),
    ("format.detected", "gte", "png"), ("format.detected", "eq", None),
    ("format.detected", "eq", " png"), ("format.detected", "eq", "\ud800"),
])
def test_invalid_or_unsupported_checks_are_input_errors(fact, op, value):
    with pytest.raises(ValueError):
        audit_asset_expectations([report()], contract(check(fact, op, value)))


@pytest.mark.parametrize("mutation", [
    lambda e: e.update(extra=True), lambda e: e.update(schema="future"),
    lambda e: e.update(assets=[]), lambda e: e.update(assets=()),
    lambda e: e["assets"].append(deepcopy(e["assets"][0])),
    lambda e: e["assets"][0].update(extra=True),
    lambda e: e["assets"][0]["source"].update(filename="unexpected.png"),
    lambda e: e["assets"][0]["source"].update(revision=""),
    lambda e: e["assets"][0].update(checks=[]),
    lambda e: e["assets"][0]["checks"].append(deepcopy(e["assets"][0]["checks"][0])),
    lambda e: e["assets"][0]["checks"][0].update(extra=1),
    lambda e: e["assets"][0]["checks"][0].update(id=" "),
])
def test_closed_contract_fields_and_unambiguous_identifiers(mutation):
    expectations = contract()
    mutation(expectations)
    with pytest.raises(ValueError):
        audit_asset_expectations([], expectations)


@pytest.mark.parametrize("bad", [True, 1.0, -1, 2**63, "1", [], {}])
def test_selected_malformed_numeric_declarations_are_not_silently_unknown(bad):
    supplied = report()
    next(item for item in supplied["metadata"] if item["name"] == "width")["value"] = bad
    with pytest.raises(ValueError):
        audit_asset_expectations([supplied], contract())


@pytest.mark.parametrize("mutation", [
    lambda item: item.update(evidence_ref="missing"),
    lambda item: item.pop("evidence_ref"), lambda item: item.update(basis=1),
    lambda item: item.update(extra=True),
])
def test_selected_metadata_requires_clear_provenance_shape(mutation):
    supplied = report()
    mutation(next(item for item in supplied["metadata"] if item["name"] == "width"))
    with pytest.raises(ValueError):
        audit_asset_expectations([supplied], contract())


def test_duplicate_selected_metadata_is_ambiguous_and_null_is_unknown():
    supplied = report()
    item = next(item for item in supplied["metadata"] if item["name"] == "width")
    item["value"] = None
    assert result([supplied], contract())["status"] == "unknown"
    supplied["metadata"].append(deepcopy(item))
    with pytest.raises(ValueError, match="ambiguous"):
        audit_asset_expectations([supplied], contract())


@pytest.mark.parametrize("case", ["duplicate", "foreign", "nan", "cycle", "tuple", "int-key", "oversize"])
def test_even_unselected_reports_must_pass_the_shared_report_boundary(case):
    supplied = report(source="unselected")
    reports = [supplied]
    if case == "duplicate":
        reports.append(deepcopy(supplied))
    elif case == "foreign":
        supplied["analyser"]["id"] = "foreign"
    elif case == "nan":
        supplied["limits"]["bad"] = float("nan")
    elif case == "cycle":
        supplied["limits"]["bad"] = supplied
    elif case == "tuple":
        supplied["limits"]["bad"] = (1, 2)
    elif case == "int-key":
        supplied["limits"][3] = "bad"
    else:
        supplied["limits"]["bad"] = "x" * (2 * 1024 * 1024)
    with pytest.raises(ValueError):
        audit_asset_expectations(reports, contract())


def test_report_array_aggregate_budget_and_count_are_enforced():
    with pytest.raises(ValueError, match="at most 256"):
        audit_asset_expectations([report()] * 257, contract())
    supplied = [report(source=str(i)) for i in range(9)]
    for item in supplied:
        item["limits"]["large"] = "x" * 1_900_000
    with pytest.raises(ValueError, match="Report array"):
        audit_asset_expectations(supplied, contract())


@pytest.mark.parametrize("assets,checks,valid", [(64, 1, True), (65, 1, False), (8, 32, True), (9, 32, False), (1, 33, False)])
def test_asset_per_asset_and_total_check_budgets(assets, checks, valid):
    expectations = contract()
    expectations["assets"] = [{"source": {"id": str(i), "revision": "v1"},
        "checks": [check(identity=str(j)) for j in range(checks)]} for i in range(assets)]
    if valid:
        assert audit_asset_expectations([], expectations)["summary"]["missing_report"] == assets
    else:
        with pytest.raises(ValueError):
            audit_asset_expectations([], expectations)


def test_contract_canonical_byte_budget_is_enforced():
    expectations = contract()
    expectations["assets"] = [{"source": {"id": str(i), "revision": "v1"}, "checks": [
        check("tag:" + "n" * 128 + ":" + "v" * 256, "eq", True, identity=str(j) + "i" * 120)
        for j in range(32)]} for i in range(4)]
    with pytest.raises(ValueError, match="Expectations canonical"):
        audit_asset_expectations([], expectations)


def test_selected_proof_budget_prevents_repeating_large_declarations_for_every_check():
    supplied = report()
    prototype = supplied["tag_proposals"][0]
    supplied["tag_proposals"] = [{**deepcopy(prototype), "basis": str(i) + "b" * 1000} for i in range(32)]
    fact = f"tag:{prototype['namespace']}:{prototype['value']}"
    validated_review_report_hash(supplied)
    with pytest.raises(ValueError, match="Selected fact proof"):
        audit_asset_expectations([supplied], contract(check(fact, "eq", True)))
