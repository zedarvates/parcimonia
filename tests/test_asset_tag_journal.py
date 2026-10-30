"""Review declarations remain source-bound, replayable and explicit."""

from copy import deepcopy

import pytest

from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_catalog import _report as validate_inspection_report
from tiberium_ai.asset_tag_journal import (
    MAX_EVENTS,
    MAX_TAG_PROPOSALS,
    append_tag_decision,
    create_tag_journal,
    validate_tag_journal,
    validated_review_report_hash,
)
from tiberium_ai.verification import hash_input


def _report(**kwargs):
    return inspect_asset(
        b"robot", filename="notes.txt", source_id="fixture", revision="v1",
        topic_terms={"robotique": ["robot"]}, **kwargs,
    )


def _append(journal, report=None, **kwargs):
    values = {
        "namespace": "topic", "value": "robotique", "action": "accept",
        "actor_id": "reviewer", "reason": "Fixture reviewed", "event_id": "event-1",
        "expected_head": journal["head_hash"],
    }
    values.update(kwargs)
    return append_tag_decision(journal, _report() if report is None else report, **values)


def _rehash(journal):
    previous = None
    for event in journal["events"]:
        event["previous_hash"] = previous
        event["event_hash"] = hash_input({key: value for key, value in event.items() if key != "event_hash"})
        previous = event["event_hash"]
    journal["head_hash"] = previous


def test_empty_journal_is_fresh_and_has_no_automatic_decision():
    first = create_tag_journal()
    second = create_tag_journal()
    assert first == {"schema": "parcimonia.asset-tag-journal/v1", "events": [], "head_hash": None}
    assert validate_tag_journal(first) is None
    first["events"].append({})
    assert second["events"] == []


def test_accept_reject_reset_keep_the_history_and_exact_report():
    report = _report()
    journals = [create_tag_journal()]
    for index, action in enumerate(("accept", "reject", "reset"), start=1):
        journals.append(_append(journals[-1], report, action=action, event_id=f"event-{index}"))
    result = journals[-1]
    assert [event["action"] for event in result["events"]] == ["accept", "reject", "reset"]
    assert [event["sequence"] for event in result["events"]] == [1, 2, 3]
    assert all(event["report_hash"] == hash_input(report) for event in result["events"])
    assert result["events"][0]["previous_hash"] is None
    assert result["events"][1]["previous_hash"] == result["events"][0]["event_hash"]
    assert result["head_hash"] == result["events"][-1]["event_hash"]
    assert validate_tag_journal(result) is None
    assert [len(journal["events"]) for journal in journals] == [0, 1, 2, 3]


def test_append_does_not_mutate_or_alias_the_journal_or_report():
    journal, report = create_tag_journal(), _report()
    original = deepcopy(report)
    result = _append(journal, report)
    assert journal["events"] == [] and report == original
    result["events"][0]["source"]["id"] = "changed"
    result["events"].append({})
    assert journal["events"] == [] and report == original


def test_retry_is_idempotent_even_after_a_later_opposite_decision():
    journal = _append(create_tag_journal())
    current = _append(journal, action="reject", event_id="event-2")
    result = _append(current, expected_head=None)
    assert result == current and result is not current
    assert result["events"][-1]["action"] == "reject"
    result["events"][-1]["source"]["id"] = "changed"
    assert current["events"][-1]["source"]["id"] == "fixture"


@pytest.mark.parametrize("changes", [
    {"action": "reject"}, {"actor_id": "other"}, {"reason": "different reason"},
    {"namespace": "format", "value": "text"},
])
def test_event_id_cannot_be_reused_for_a_different_declaration(changes):
    current = _append(create_tag_journal())
    with pytest.raises(ValueError, match="event_id"):
        _append(current, expected_head=None, **changes)


def test_retry_requires_the_original_previous_head_not_the_current_head():
    current = _append(create_tag_journal())
    with pytest.raises(ValueError, match="expected head"):
        _append(current)


def test_new_event_rejects_a_stale_head_without_changing_anything():
    current = _append(create_tag_journal())
    original = deepcopy(current)
    with pytest.raises(ValueError, match="stale"):
        _append(current, event_id="event-2", expected_head=None)
    assert current == original


def test_tag_not_proposed_in_the_exact_report_is_refused():
    with pytest.raises(ValueError, match="existing proposed tag"):
        _append(create_tag_journal(), namespace="object", value="robot")


def test_colons_in_tag_values_are_supported_but_not_in_namespaces():
    report = inspect_asset(b'{"type":"Point","coordinates":[0,0]}', filename="map.geojson", source_id="map", revision="v1")
    result = _append(create_tag_journal(), report, namespace="crs", value="OGC:CRS84")
    assert result["events"][0]["tag"]["value"] == "OGC:CRS84"
    with pytest.raises(ValueError):
        _append(create_tag_journal(), namespace="topic:bad")


@pytest.mark.parametrize("field,new_value", [
    ("source", {"id": "fixture", "revision": "v2", "filename": "notes.txt"}),
    ("input_hash", "a" * 64),
    ("limits", {"updated": "policy"}),
])
def test_same_event_cannot_be_retried_for_a_changed_report(field, new_value):
    report = _report()
    current = _append(create_tag_journal(), report)
    changed = deepcopy(report)
    changed[field] = new_value
    with pytest.raises(ValueError, match="event_id"):
        _append(current, changed, expected_head=None)


def test_prefix_decision_is_not_a_review_of_the_full_file():
    prefix = inspect_asset(b"robot ", filename="notes.txt", source_id="fixture", revision="v1", complete=False, total_bytes=12, topic_terms={"robotique": ["robot"]})
    full = inspect_asset(b"robot suite!", filename="notes.txt", source_id="fixture", revision="v1", topic_terms={"robotique": ["robot"]})
    current = _append(create_tag_journal(), prefix)
    assert current["events"][0]["report_hash"] == hash_input(prefix)
    assert hash_input(prefix) != hash_input(full)
    with pytest.raises(ValueError, match="event_id"):
        _append(current, full, expected_head=None)


@pytest.mark.parametrize("field,value", [
    ("action", "accepted"), ("action", True), ("action", ""),
    ("actor_id", ""), ("actor_id", " actor"), ("actor_id", "a" * 257),
    ("actor_id", "bad\ud800"), ("reason", ""), ("reason", "a" * 2049),
    ("reason", "bad\ud800"), ("event_id", ""), ("event_id", "a" * 129),
    ("event_id", 1), ("namespace", ""), ("value", ""),
    ("expected_head", True), ("expected_head", "a"), ("expected_head", "A" * 64),
])
def test_append_rejects_malformed_declaration_fields(field, value):
    with pytest.raises(ValueError):
        _append(create_tag_journal(), **{field: value})


@pytest.mark.parametrize("sequence", [True, 1.0, 0, 2, "1"])
def test_sequence_is_a_strict_contiguous_integer_even_after_rehash(sequence):
    journal = _append(create_tag_journal())
    journal["events"][0]["sequence"] = sequence
    _rehash(journal)
    with pytest.raises(ValueError):
        validate_tag_journal(journal)


@pytest.mark.parametrize("change", ["extra_journal_field", "extra_event_field", "extra_source_field", "extra_tag_field", "event_schema", "journal_schema", "duplicate_event_id"])
def test_closed_records_and_unique_event_ids(change):
    journal = _append(_append(create_tag_journal()), event_id="event-2")
    if change == "extra_journal_field":
        journal["extra"] = 1
    elif change == "extra_event_field":
        journal["events"][0]["extra"] = 1
    elif change == "extra_source_field":
        journal["events"][0]["source"]["filename"] = "notes.txt"
    elif change == "extra_tag_field":
        journal["events"][0]["tag"]["confidence"] = 1
    elif change == "event_schema":
        journal["events"][0]["schema"] = "unknown"
    elif change == "journal_schema":
        journal["schema"] = "unknown"
    else:
        journal["events"][1]["event_id"] = "event-1"
    _rehash(journal)
    with pytest.raises(ValueError):
        validate_tag_journal(journal)


@pytest.mark.parametrize("field,new_value", [
    ("action", "reject"), ("actor_id", "other"), ("reason", "changed"),
    ("report_hash", "f" * 64), ("event_hash", "f" * 64),
    ("previous_hash", "f" * 64),
])
def test_tampered_record_does_not_validate_with_old_hashes(field, new_value):
    journal = _append(create_tag_journal())
    journal["events"][0][field] = new_value
    with pytest.raises(ValueError):
        validate_tag_journal(journal)


def test_rehashing_one_earlier_event_breaks_the_remaining_chain():
    journal = _append(_append(create_tag_journal()), event_id="event-2")
    first = journal["events"][0]
    first["reason"] = "changed"
    first["event_hash"] = hash_input({k: v for k, v in first.items() if k != "event_hash"})
    with pytest.raises(ValueError):
        validate_tag_journal(journal)


def test_head_and_truncated_history_must_agree():
    journal = _append(_append(create_tag_journal()), event_id="event-2")
    journal["events"].pop()
    with pytest.raises(ValueError, match="head_hash"):
        validate_tag_journal(journal)


def test_coherent_rewrite_is_not_claimed_to_authenticate_an_actor():
    journal = _append(create_tag_journal())
    journal["events"][0]["actor_id"] = "claimed-other-actor"
    _rehash(journal)
    assert validate_tag_journal(journal) is None


@pytest.mark.parametrize("journal", [None, [], {}, {"schema": "parcimonia.asset-tag-journal/v1", "events": (), "head_hash": None}, {"schema": "parcimonia.asset-tag-journal/v1", "events": [], "head_hash": "a" * 64}])
def test_malformed_or_inconsistent_empty_journals(journal):
    with pytest.raises(ValueError):
        validate_tag_journal(journal)


def _full_journal(report):
    journal = create_tag_journal()
    previous = None
    for index in range(MAX_EVENTS):
        event = {
            "schema": "parcimonia.asset-tag-decision/v1", "event_id": f"event-{index + 1}",
            "sequence": index + 1, "previous_hash": previous,
            "source": {"id": "fixture", "revision": "v1"}, "report_hash": hash_input(report),
            "tag": {"namespace": "topic", "value": "robotique"}, "action": "accept",
            "actor_id": "reviewer", "reason": "Fixture reviewed",
        }
        event["event_hash"] = hash_input(event)
        journal["events"].append(event)
        previous = event["event_hash"]
    journal["head_hash"] = previous
    return journal


def test_journal_limit_refuses_new_events_but_allows_exact_retry():
    report = _report()
    journal = _full_journal(report)
    assert validate_tag_journal(journal) is None
    with pytest.raises(ValueError, match="limited"):
        _append(journal, report, event_id="overflow")
    assert _append(journal, report, expected_head=None) == journal
    oversized = deepcopy(journal)
    oversized["events"].append(deepcopy(journal["events"][-1]))
    with pytest.raises(ValueError, match="at most"):
        validate_tag_journal(oversized)


def test_report_requires_finite_json_and_a_valid_proposal_record():
    report = _report()
    report["metadata"].append({"value": float("nan")})
    with pytest.raises(ValueError, match="finite UTF-8 JSON"):
        _append(create_tag_journal(), report)
    report = _report()
    report["tag_proposals"][0]["status"] = "accepted"
    with pytest.raises(ValueError):
        _append(create_tag_journal(), report)


def _report_with_proposals(count):
    report = _report()
    evidence_id = report["evidence"][0]["id"]
    for index in range(count - len(report["tag_proposals"])):
        report["tag_proposals"].append({
            "namespace": "topic", "value": f"candidate-{index}", "status": "proposed",
            "basis": "fixture", "evidence_refs": [evidence_id],
        })
    return report


def test_producer_refuses_257_proposals_accepted_by_the_old_catalogue_contract():
    report = _report_with_proposals(MAX_TAG_PROPOSALS + 1)
    validate_inspection_report(report)
    journal = create_tag_journal()
    original_journal, original_report = deepcopy(journal), deepcopy(report)
    with pytest.raises(ValueError, match="256 tag proposals"):
        _append(journal, report)
    assert journal == original_journal
    assert report == original_report


def test_producer_accepts_the_exact_256_proposal_boundary():
    report = _report_with_proposals(MAX_TAG_PROPOSALS)
    journal = _append(create_tag_journal(), report)
    assert len(journal["events"]) == 1
    assert journal["events"][0]["report_hash"] == hash_input(report)


@pytest.mark.parametrize("non_json,json_value", [
    ((1, 2), [1, 2]), ({1: "value"}, {"1": "value"}),
])
def test_python_coercions_cannot_share_a_review_hash(non_json, json_value):
    valid = _report()
    valid["metadata"].append({"value": json_value})
    invalid = deepcopy(valid)
    invalid["metadata"][-1]["value"] = non_json
    assert hash_input(valid) == hash_input(invalid)
    journal = _append(create_tag_journal(), valid)
    assert validated_review_report_hash(valid) == hash_input(valid)
    with pytest.raises(ValueError):
        validated_review_report_hash(invalid)
    with pytest.raises(ValueError):
        _append(journal, invalid, expected_head=None)


@pytest.mark.parametrize("value", [
    b"bytes", {1, 2}, float("inf"), float("nan"), "bad\ud800",
])
def test_report_boundary_rejects_non_json_and_nonfinite_nested_values(value):
    report = _report()
    report["metadata"].append({"value": value})
    with pytest.raises(ValueError):
        validated_review_report_hash(report)


def test_report_boundary_rejects_invalid_unicode_object_keys():
    report = _report()
    report["metadata"].append({"bad\ud800": "value"})
    with pytest.raises(ValueError):
        validated_review_report_hash(report)


def test_report_boundary_rejects_exact_type_subclasses():
    class String(str):
        pass
    class Integer(int):
        pass
    class Array(list):
        pass
    class Object(dict):
        pass
    for value in (String("value"), Integer(1), Array([1]), Object(value=1)):
        report = _report()
        report["metadata"].append({"value": value})
        with pytest.raises(ValueError):
            validated_review_report_hash(report)


def test_report_boundary_rejects_foreign_types_without_calling_their_equality():
    class Trap(type):
        def __eq__(cls, other):
            raise AssertionError("A rejected Python type must not be compared by user code")
    class Foreign(metaclass=Trap):
        pass
    report = _report()
    report["metadata"].append({"value": Foreign()})
    with pytest.raises(ValueError, match="exact JSON types"):
        validated_review_report_hash(report)


def test_report_boundary_detects_cycles_but_accepts_shared_acyclic_values():
    report = _report()
    shared = {"value": [1, 2]}
    report["metadata"].extend([shared, shared])
    assert validated_review_report_hash(report) == hash_input(report)
    circular = []
    circular.append(circular)
    report["metadata"].append({"value": circular})
    with pytest.raises(ValueError, match="cycles"):
        validated_review_report_hash(report)


def test_report_boundary_limits_depth_and_expanded_shared_nodes():
    report = _report()
    nested = 1
    for _ in range(65):
        nested = [nested]
    report["metadata"].append({"value": nested})
    with pytest.raises(ValueError, match="depth"):
        validated_review_report_hash(report)
    report = _report()
    shared = [0] * 10_001
    report["metadata"].append({"value": [shared, shared]})
    with pytest.raises(ValueError, match="nodes"):
        validated_review_report_hash(report)
