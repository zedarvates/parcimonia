"""Catalogue snapshots bind exact current reports without rewriting old reviews."""

from copy import deepcopy
import hashlib
import json

import pytest

from tiberium_ai.asset_catalog import search_asset_reports
from tiberium_ai.asset_catalog_snapshot import (
    MAX_REPORT_BYTES,
    MAX_REPORTS,
    MAX_SNAPSHOT_BYTES,
    MAX_SNAPSHOT_DEPTH,
    MAX_SNAPSHOT_NODES,
    SNAPSHOT_SCHEMA,
    create_asset_catalog,
    export_asset_reports,
    put_asset_report,
    remove_asset_report,
    validate_asset_catalog,
)
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import (
    append_tag_decision,
    create_tag_journal,
    validated_review_report_hash,
)
from tiberium_ai.asset_tag_review import project_tag_reviews, search_reviewed_assets


class _String(str):
    pass


class _Integer(int):
    pass


class _Array(list):
    pass


class _Object(dict):
    pass


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _rehash(snapshot):
    snapshot["snapshot_hash"] = _hash({
        key: value for key, value in snapshot.items() if key != "snapshot_hash"
    })
    return snapshot


def _report(identifier="notes", revision="v1", payload=b"robot dans le jardin"):
    return inspect_asset(
        payload, filename="notes.txt", source_id=identifier, revision=revision,
        topic_terms={"robotique": ["robot"]},
    )


def _geo_report(identifier="map"):
    return inspect_asset(
        b'{"type":"Point","coordinates":[2,48]}', filename="map.geojson",
        source_id=identifier, revision="map revision is opaque",
    )


def _snapshot(reports, *, generation=1):
    return _rehash({
        "schema": SNAPSHOT_SCHEMA, "catalog_id": "catalogue-é",
        "generation": generation, "parent_hash": "a" * 64,
        "reports": reports, "snapshot_hash": "0" * 64,
    })


def _put(snapshot, report, expected_report_hash=None, **options):
    return put_asset_report(
        snapshot, report, expected_head=options.get("expected_head", snapshot["snapshot_hash"]),
        expected_report_hash=expected_report_hash,
    )


def _decide(journal, report, *, namespace="topic", value="robotique", event_id="review-1"):
    return append_tag_decision(
        journal, report, namespace=namespace, value=value, action="accept",
        actor_id="fixture-reviewer", reason="Explicit fixture review",
        event_id=event_id, expected_head=journal["head_hash"],
    )


def _topic_status(projected, identifier="notes"):
    asset = next(item for item in projected["assets"] if item["source"]["id"] == identifier)
    return next(tag["status"] for tag in asset["tags"] if tag["namespace"] == "topic")


def _sized_report(size, identifier="notes"):
    report = _report(identifier)
    report["metadata"].append({"value": ""})
    gap = size - len(_canonical(report))
    assert gap >= 0
    report["metadata"][-1]["value"] = "é" * (gap // 2) + "x" * (gap % 2)
    assert len(_canonical(report)) == size
    return report


def _node_count(value):
    if type(value) is dict:
        return 1 + sum(_node_count(item) for item in value.values())
    if type(value) is list:
        return 1 + sum(_node_count(item) for item in value)
    return 1


def test_create_has_closed_canonical_generation_zero_and_no_shared_state():
    first, second = create_asset_catalog("catalogue-é"), create_asset_catalog("catalogue-é")
    assert first == {
        "schema": "parcimonia.asset-catalog-snapshot/v1",
        "catalog_id": "catalogue-é", "generation": 0, "parent_hash": None,
        "reports": [], "snapshot_hash": _hash({
            "schema": "parcimonia.asset-catalog-snapshot/v1", "catalog_id": "catalogue-é",
            "generation": 0, "parent_hash": None, "reports": [],
        }),
    }
    assert validate_asset_catalog(first) is None
    assert export_asset_reports(first) == []
    first["reports"].append({})
    assert second["reports"] == []


def test_put_and_remove_form_new_generations_with_the_exact_previous_head():
    report = _report()
    empty = create_asset_catalog("catalogue")
    stored = _put(empty, report)
    removed = remove_asset_report(
        stored, "notes", expected_head=stored["snapshot_hash"], expected_report_hash=_hash(report),
    )
    assert [item["generation"] for item in (empty, stored, removed)] == [0, 1, 2]
    assert stored["parent_hash"] == empty["snapshot_hash"]
    assert removed["parent_hash"] == stored["snapshot_hash"]
    assert stored["reports"] == [report] and removed["reports"] == []
    for snapshot in (empty, stored, removed):
        assert validate_asset_catalog(snapshot) is None
        assert snapshot["snapshot_hash"] == _hash({
            key: value for key, value in snapshot.items() if key != "snapshot_hash"
        })


def test_json_readback_exports_exact_text_and_geojson_reports_for_existing_search():
    text, geo = _report(), _geo_report()
    snapshot = _put(_put(create_asset_catalog("catalogue"), text), geo)
    restored = json.loads(_canonical(snapshot))
    assert validate_asset_catalog(restored) is None
    reports = export_asset_reports(restored)
    assert reports == [geo, text]
    result = search_asset_reports(reports, tags=["format:geojson"], bbox=[1, 47, 3, 49])
    assert [item["source"]["id"] for item in result["matches"]] == ["map"]
    assert result["matches"][0]["spatial_match"] == "envelope_overlap_candidate"


def test_one_current_report_per_source_and_revisions_have_no_implicit_order():
    old = _report(revision="z newer-looking")
    replacement = _report(revision="a older-looking")
    first = _put(create_asset_catalog("catalogue"), old)
    second = _put(first, replacement, _hash(old))
    assert export_asset_reports(second) == [replacement]
    assert export_asset_reports(first) == [old]
    assert second["generation"] == first["generation"] + 1


def test_source_order_is_stable_and_report_object_key_order_does_not_change_hash():
    a, z = _report("a"), _report("z")
    first = _put(_put(create_asset_catalog("catalogue"), z), a)
    second = _put(_put(create_asset_catalog("catalogue"), a), z)
    assert export_asset_reports(first) == export_asset_reports(second) == [a, z]
    assert first["snapshot_hash"] != second["snapshot_hash"]  # Different parent histories.
    reordered = dict(reversed(list(a.items())))
    assert _put(first, reordered, _hash(a)) == first
    restored = dict(reversed(list(first.items())))
    assert validate_asset_catalog(restored) is None


def test_new_revision_does_not_inherit_review_but_old_snapshot_and_other_source_do():
    old, current, geo = _report(revision="v1"), _report(revision="v2"), _geo_report()
    snapshot = _put(_put(create_asset_catalog("catalogue"), old), geo)
    journal = _decide(create_tag_journal(), old)
    journal = _decide(journal, geo, namespace="format", value="geojson", event_id="review-2")
    updated = _put(snapshot, current, _hash(old))
    current_reports = export_asset_reports(updated)
    view = project_tag_reviews(current_reports, journal)
    assert _topic_status(view) == "proposed"
    assert view["unapplied_events"] == [{
        "event_id": "review-1", "source": {"id": "notes", "revision": "v1"},
        "reason": "source_revision_changed",
    }]
    assert search_reviewed_assets(current_reports, journal, tags=["topic:robotique"])["count"] == 0
    assert search_reviewed_assets(current_reports, journal, tags=["format:geojson"])["count"] == 1
    assert validate_asset_catalog(snapshot) is None
    historical = export_asset_reports(snapshot)
    assert _topic_status(project_tag_reviews(historical, journal)) == "accepted"
    assert search_reviewed_assets(historical, journal, tags=["topic:robotique"])["count"] == 1


def test_changed_body_with_same_source_and_revision_does_not_inherit_review():
    old = _report()
    changed = deepcopy(old)
    changed["metadata"].append({"name": "new-inspection-note", "value": "évidence supplémentaire"})
    first = _put(create_asset_catalog("catalogue"), old)
    journal = _decide(create_tag_journal(), old)
    updated = _put(first, changed, _hash(old))
    view = project_tag_reviews(export_asset_reports(updated), journal)
    assert _topic_status(view) == "proposed"
    assert view["unapplied_events"][0]["reason"] == "report_changed"
    assert _topic_status(project_tag_reviews(export_asset_reports(first), journal)) == "accepted"


def test_remove_keeps_journal_history_and_exact_reinsertion_can_reapply_its_review():
    report = _report()
    stored = _put(create_asset_catalog("catalogue"), report)
    journal = _decide(create_tag_journal(), report)
    original_journal = deepcopy(journal)
    removed = remove_asset_report(
        stored, "notes", expected_head=stored["snapshot_hash"], expected_report_hash=_hash(report),
    )
    absent = project_tag_reviews(export_asset_reports(removed), journal)
    assert absent["assets"] == []
    assert absent["unapplied_events"][0]["reason"] == "source_not_in_catalogue"
    reinserted = _put(removed, deepcopy(report))
    assert _topic_status(project_tag_reviews(export_asset_reports(reinserted), journal)) == "accepted"
    assert journal == original_journal
    assert validate_asset_catalog(stored) is None


def test_exact_put_is_a_deep_copy_noop_but_requires_both_current_preconditions():
    report = _report()
    snapshot = _put(create_asset_catalog("catalogue"), report)
    same = _put(snapshot, deepcopy(report), _hash(report))
    assert same == snapshot and same is not snapshot
    same["reports"][0]["metadata"].append({"value": "mutated output"})
    assert snapshot["reports"][0]["metadata"] == report["metadata"]
    for expected_hash in (None, "b" * 64):
        with pytest.raises(ValueError):
            _put(snapshot, report, expected_hash)
    with pytest.raises(ValueError, match="head"):
        _put(snapshot, report, _hash(report), expected_head="c" * 64)


def test_stale_head_is_rejected_before_report_or_report_hash_validation():
    snapshot = _put(create_asset_catalog("catalogue"), _report())
    original = deepcopy(snapshot)
    with pytest.raises(ValueError, match="head"):
        put_asset_report(snapshot, None, expected_head="b" * 64, expected_report_hash=True)
    with pytest.raises(ValueError, match="head"):
        remove_asset_report(snapshot, None, expected_head="b" * 64, expected_report_hash=True)
    assert snapshot == original


def test_insert_replacement_and_remove_cannot_use_another_sources_report_hash():
    a, b = _report("a"), _report("b")
    first = _put(create_asset_catalog("catalogue"), a)
    snapshot = _put(first, b)
    original = deepcopy(snapshot)
    with pytest.raises(ValueError):
        _put(first, b, _hash(a))
    with pytest.raises(ValueError):
        _put(snapshot, _report("a", revision="v2"), _hash(b))
    with pytest.raises(ValueError):
        remove_asset_report(snapshot, "a", expected_head=snapshot["snapshot_hash"], expected_report_hash=_hash(b))
    with pytest.raises(ValueError):
        remove_asset_report(snapshot, "missing", expected_head=snapshot["snapshot_hash"], expected_report_hash=_hash(a))
    assert snapshot == original


def test_put_export_and_remove_never_alias_or_mutate_their_inputs():
    first_report, second_report = _report("a"), _report("b")
    empty = create_asset_catalog("catalogue")
    first = _put(empty, first_report)
    first_before, report_before = deepcopy(first), deepcopy(second_report)
    second = _put(first, second_report)
    assert first == first_before and second_report == report_before
    second["reports"][0]["source"]["filename"] = "mutated-output.txt"
    assert first == first_before
    first_report["metadata"].append({"value": "mutated-input"})
    assert first == first_before
    exported = export_asset_reports(first)
    exported[0]["evidence"][0]["id"] = "changed"
    assert first == first_before
    removed = remove_asset_report(first, "a", expected_head=first["snapshot_hash"], expected_report_hash=_hash(first_before["reports"][0]))
    removed["reports"].append({})
    assert first == first_before and empty["reports"] == []


@pytest.mark.parametrize("identifier", [None, True, 1, "", " catalog", "catalog ", "x" * 4097, "bad\ud800", _String("catalog")])
def test_catalog_id_requires_exact_trimmed_bounded_utf8_string(identifier):
    with pytest.raises(ValueError):
        create_asset_catalog(identifier)


def test_catalog_id_exact_length_boundary_is_accepted():
    assert validate_asset_catalog(create_asset_catalog("x" * 4096)) is None


@pytest.mark.parametrize("value", [None, True, [], _Object(), {"schema": SNAPSHOT_SCHEMA}])
def test_snapshot_envelope_requires_exact_object_and_all_fields(value):
    with pytest.raises(ValueError):
        validate_asset_catalog(value)


@pytest.mark.parametrize("mutation", ["extra", "missing", "wrong-schema"])
def test_envelope_is_closed_even_with_a_coherent_payload_hash(mutation):
    snapshot = create_asset_catalog("catalogue")
    if mutation == "extra":
        snapshot["unrecognized"] = "field"
    elif mutation == "missing":
        del snapshot["parent_hash"]
    else:
        snapshot["schema"] = "parcimonia.asset-catalog-snapshot/v2"
    _rehash(snapshot)
    with pytest.raises(ValueError):
        validate_asset_catalog(snapshot)


@pytest.mark.parametrize("generation", [None, False, True, -1, 1.0, "1", 2**63, _Integer(1)])
def test_generation_is_a_strict_nonnegative_63bit_integer(generation):
    snapshot = _snapshot([], generation=generation)
    with pytest.raises(ValueError):
        validate_asset_catalog(snapshot)


def test_generation_zero_cannot_have_reports_or_a_parent_and_positive_needs_parent():
    bad_snapshots = [
        _snapshot([_report()], generation=0),
        _snapshot([], generation=0),
        dict(_snapshot([]), parent_hash=None),
    ]
    bad_snapshots[0]["parent_hash"] = None
    for snapshot in bad_snapshots:
        _rehash(snapshot)
        with pytest.raises(ValueError):
            validate_asset_catalog(snapshot)


def test_maximum_generation_reads_back_but_cannot_advance_and_exact_noop_survives():
    report = _report()
    snapshot = _snapshot([report], generation=2**63 - 1)
    assert validate_asset_catalog(snapshot) is None
    assert _put(snapshot, report, _hash(report)) == snapshot
    with pytest.raises(ValueError):
        _put(snapshot, _report("other"))
    with pytest.raises(ValueError):
        remove_asset_report(snapshot, "notes", expected_head=snapshot["snapshot_hash"], expected_report_hash=_hash(report))


@pytest.mark.parametrize("field", ["snapshot_hash", "parent_hash"])
@pytest.mark.parametrize("value", [None, True, "a", "A" * 64, "g" * 64, _String("a" * 64)])
def test_hash_fields_are_strict_lowercase_sha256(field, value):
    snapshot = _snapshot([])
    snapshot[field] = value
    if field != "snapshot_hash":
        _rehash(snapshot)
    with pytest.raises(ValueError):
        validate_asset_catalog(snapshot)


def test_tampered_payload_or_hash_is_refused_and_a_hash_is_not_authentication():
    snapshot = _put(create_asset_catalog("catalogue"), _report())
    tampered = deepcopy(snapshot)
    tampered["reports"][0]["source"]["revision"] = "changed"
    with pytest.raises(ValueError):
        validate_asset_catalog(tampered)
    tampered["snapshot_hash"] = "b" * 64
    with pytest.raises(ValueError):
        export_asset_reports(tampered)
    _rehash(tampered)
    assert validate_asset_catalog(tampered) is None  # Coherence, not authenticated history.


@pytest.mark.parametrize("reports", [None, (), _Array(), [_report("z"), _report("a")], [_report(), _report(revision="v2")]])
def test_reports_require_exact_list_sorted_unique_source_ids(reports):
    with pytest.raises(ValueError):
        validate_asset_catalog(_snapshot(reports))


@pytest.mark.parametrize("field,value", [
    ("expected_head", None), ("expected_head", True), ("expected_head", "A" * 64),
    ("expected_report_hash", True), ("expected_report_hash", "A" * 64),
    ("expected_report_hash", _String("a" * 64)),
])
def test_update_preconditions_are_not_coerced(field, value):
    snapshot = create_asset_catalog("catalogue")
    options = {"expected_head": snapshot["snapshot_hash"], "expected_report_hash": None}
    options[field] = value
    with pytest.raises(ValueError):
        put_asset_report(snapshot, _report(), **options)


@pytest.mark.parametrize("source_id", [None, True, "", " notes", "x" * 4097, "bad\ud800", _String("notes")])
def test_remove_requires_exact_source_id(source_id):
    report = _report()
    snapshot = _put(create_asset_catalog("catalogue"), report)
    with pytest.raises(ValueError):
        remove_asset_report(snapshot, source_id, expected_head=snapshot["snapshot_hash"], expected_report_hash=_hash(report))


@pytest.mark.parametrize("value", [
    b"bytes", (1, 2), {1: "value"}, {1, 2}, float("inf"), float("nan"),
    "bad\ud800", _String("text"), _Integer(1), _Array([1]), _Object(value=1),
])
def test_reports_refuse_python_coercions_subclasses_nonfinite_or_invalid_utf8(value):
    report = _report()
    report["metadata"].append({"value": value})
    with pytest.raises(ValueError):
        _put(create_asset_catalog("catalogue"), report)
    # Loading a coherent envelope must enforce the same report boundary.
    if type(value) not in (bytes, set) and not (type(value) is float) and not (type(value) is str and "\ud800" in value):
        snapshot = _snapshot([report])
        with pytest.raises(ValueError):
            validate_asset_catalog(snapshot)


def test_exact_json_null_booleans_and_shared_acyclic_values_are_preserved():
    report = _report()
    shared = {"value": [None, True, False, 1, 1.5]}
    report["metadata"].extend([shared, shared])
    snapshot = _put(create_asset_catalog("catalogue"), report)
    assert export_asset_reports(snapshot) == [report]
    assert validated_review_report_hash(report) == _hash(report)


def test_foreign_python_objects_are_refused_before_copying_or_comparing_them():
    class Foreign:
        def __deepcopy__(self, memo):
            raise AssertionError("Rejected report data must not execute a copy hook")

        def __eq__(self, other):
            raise AssertionError("Rejected report data must not execute equality")

    report = _report()
    report["metadata"].append({"value": Foreign()})
    with pytest.raises(ValueError):
        _put(create_asset_catalog("catalogue"), report)


def test_cycle_depth_and_expanded_report_node_budgets_are_enforced():
    circular = []
    circular.append(circular)
    report = _report()
    report["metadata"].append({"value": circular})
    with pytest.raises(ValueError, match="cycle"):
        _put(create_asset_catalog("catalogue"), report)
    report = _report()
    nested = 0
    for _ in range(65):
        nested = [nested]
    report["metadata"].append({"value": nested})
    with pytest.raises(ValueError, match="depth"):
        _put(create_asset_catalog("catalogue"), report)
    report = _report()
    shared = [0] * 10_001
    report["metadata"].append({"value": [shared, shared]})
    with pytest.raises(ValueError, match="nodes"):
        _put(create_asset_catalog("catalogue"), report)


def test_snapshot_depth_counts_the_envelope_not_just_each_report():
    assert MAX_SNAPSHOT_DEPTH == 64
    def report_at_depth(nesting):
        report = _report()
        value = 0
        for _ in range(nesting):
            value = [value]
        report["metadata"].append({"value": value})
        return report
    exact, too_deep = report_at_depth(59), report_at_depth(60)
    assert validated_review_report_hash(too_deep) == _hash(too_deep)
    assert validate_asset_catalog(_snapshot([exact])) is None
    with pytest.raises(ValueError, match="depth"):
        validate_asset_catalog(_snapshot([too_deep]))
    with pytest.raises(ValueError, match="depth"):
        _put(create_asset_catalog("catalogue"), too_deep)


def test_snapshot_node_limit_counts_expanded_reports_at_exact_boundary():
    assert MAX_SNAPSHOT_NODES == 200_000
    reports = []
    for index in range(10):
        report = _report(f"asset-{index:02}")
        report["metadata"].append({"value": [0] * 19_000})
        reports.append(report)
    tail = _report("asset-10")
    tail["metadata"].append({"value": []})
    reports.append(tail)
    snapshot = _snapshot(reports)
    remaining = MAX_SNAPSHOT_NODES - _node_count(snapshot)
    assert 0 < remaining < 19_000
    tail["metadata"][-1]["value"].extend([0] * remaining)
    _rehash(snapshot)
    assert _node_count(snapshot) == MAX_SNAPSHOT_NODES
    assert validate_asset_catalog(snapshot) is None
    before = _snapshot(reports[:-1])
    written = _put(before, tail)
    assert _node_count(written) == MAX_SNAPSHOT_NODES
    assert validate_asset_catalog(json.loads(_canonical(written))) is None
    tail["metadata"][-1]["value"].append(0)
    _rehash(snapshot)
    with pytest.raises(ValueError, match="nodes"):
        validate_asset_catalog(snapshot)
    with pytest.raises(ValueError, match="nodes"):
        _put(before, tail)


def test_256_report_boundary_refuses_only_new_sources_and_allows_exact_noop():
    assert MAX_REPORTS == 256
    reports = [_report(f"asset-{index:03}") for index in range(MAX_REPORTS)]
    snapshot = _snapshot(reports)
    assert validate_asset_catalog(snapshot) is None
    assert len(export_asset_reports(snapshot)) == MAX_REPORTS
    assert _put(snapshot, reports[0], _hash(reports[0])) == snapshot
    with pytest.raises(ValueError):
        _put(snapshot, _report("extra"))
    replacement = _report("asset-000", revision="v2")
    assert len(export_asset_reports(_put(snapshot, replacement, _hash(reports[0])))) == MAX_REPORTS
    oversized = _snapshot(reports + [_report("extra")])
    with pytest.raises(ValueError):
        validate_asset_catalog(oversized)


def test_report_byte_limit_is_canonical_utf8_and_inclusive():
    assert MAX_REPORT_BYTES == 2 * 1024 * 1024
    report = _sized_report(MAX_REPORT_BYTES)
    snapshot = _put(create_asset_catalog("catalogue"), report)
    assert export_asset_reports(snapshot) == [report]
    oversized = deepcopy(report)
    oversized["metadata"][-1]["value"] += "x"
    assert len(_canonical(oversized)) == MAX_REPORT_BYTES + 1
    with pytest.raises(ValueError):
        _put(create_asset_catalog("catalogue"), oversized)
    with pytest.raises(ValueError):
        validate_asset_catalog(_snapshot([oversized]))


def test_snapshot_byte_limit_includes_the_hash_and_counts_compact_utf8():
    assert MAX_SNAPSHOT_BYTES == 16 * 1024 * 1024
    reports = [_sized_report(MAX_REPORT_BYTES, f"asset-{index}") for index in range(8)]
    snapshot = _snapshot(reports)
    excess = len(_canonical(snapshot)) - MAX_SNAPSHOT_BYTES
    assert excess > 0
    reports[-1] = _sized_report(MAX_REPORT_BYTES - excess, "asset-7")
    _rehash(snapshot)
    assert len(_canonical(snapshot)) == MAX_SNAPSHOT_BYTES
    assert validate_asset_catalog(snapshot) is None
    before = _snapshot(reports[:-1])
    written = _put(before, reports[-1])
    assert len(_canonical(written)) == MAX_SNAPSHOT_BYTES
    assert validate_asset_catalog(json.loads(_canonical(written))) is None
    reports[-1]["metadata"][-1]["value"] += "x"
    _rehash(snapshot)
    assert len(_canonical(snapshot)) == MAX_SNAPSHOT_BYTES + 1
    with pytest.raises(ValueError):
        validate_asset_catalog(snapshot)
    with pytest.raises(ValueError):
        _put(before, reports[-1])


def test_every_reader_and_writer_rejects_an_invalid_snapshot_without_repair():
    report = _report()
    snapshot = _put(create_asset_catalog("catalogue"), report)
    snapshot["snapshot_hash"] = "a" * 64
    original = deepcopy(snapshot)
    calls = [
        lambda: validate_asset_catalog(snapshot),
        lambda: export_asset_reports(snapshot),
        lambda: _put(snapshot, report, _hash(report)),
        lambda: remove_asset_report(snapshot, "notes", expected_head=snapshot["snapshot_hash"], expected_report_hash=_hash(report)),
    ]
    for call in calls:
        with pytest.raises(ValueError):
            call()
        assert snapshot == original
