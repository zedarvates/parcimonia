"""Review decisions bind exact reports and filter tags without rewriting them."""

from copy import deepcopy

import pytest

from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import append_tag_decision, create_tag_journal
from tiberium_ai.asset_tag_review import project_tag_reviews, search_reviewed_assets
from tiberium_ai.verification import hash_input


class _MetadataDict(dict):
    pass


class _MetadataList(list):
    pass


class _MetadataString(str):
    pass


def _report(identifier="asset", revision="v1", data=b"robot in garden", **options):
    return inspect_asset(
        data, filename="notes.txt", source_id=identifier, revision=revision,
        topic_terms={"robotique": ["robot"]}, **options,
    )


def _decide(report, action="accept", journal=None, tag="topic:robotique", **options):
    journal = create_tag_journal() if journal is None else journal
    namespace, value = tag.split(":", 1)
    return append_tag_decision(
        journal, report, namespace=namespace, value=value, action=action,
        actor_id=options.get("actor_id", "fixture-reviewer"),
        reason=options.get("reason", "Fixture review decision"),
        event_id=options.get("event_id", f"event-{len(journal['events']) + 1}"),
        expected_head=journal["head_hash"],
    )


def _tag(asset, namespace="topic", value="robotique"):
    return next(tag for tag in asset["tags"] if (tag["namespace"], tag["value"]) == (namespace, value))


def _rehash_event(journal):
    event = journal["events"][0]
    event["event_hash"] = hash_input({key: value for key, value in event.items() if key != "event_hash"})
    journal["head_hash"] = event["event_hash"]


def test_empty_projection_and_catalogue_are_valid():
    journal = create_tag_journal()
    projected = project_tag_reviews([], journal)
    assert projected["schema"] == "parcimonia.asset-tag-review/v1"
    assert projected["assets"] == [] and projected["unapplied_events"] == []
    assert search_reviewed_assets([], journal)["count"] == 0


def test_default_state_is_proposed_and_not_accepted_for_tag_search():
    report = _report()
    journal = create_tag_journal()
    projected = project_tag_reviews([report], journal)
    tag = _tag(projected["assets"][0])
    assert tag["status"] == "proposed" and tag["decision"] is None
    assert search_reviewed_assets([report], journal, tags=["topic:robotique"])["count"] == 0
    assert search_reviewed_assets([report], journal, tags=["topic:robotique"], states=["proposed"])["count"] == 1


def test_acceptance_contains_declared_actor_provenance_and_exact_report_hash():
    report = _report()
    journal = _decide(report)
    projected = project_tag_reviews([report], journal)
    asset = projected["assets"][0]
    assert asset["report_hash"] == hash_input(report)
    tag = _tag(asset)
    assert tag["status"] == "accepted"
    assert tag["decision"] == {
        "event_id": "event-1", "event_hash": journal["head_hash"],
        "sequence": 1, "actor_id": "fixture-reviewer", "reason": "Fixture review decision",
    }
    assert projected["journal_head"] == journal["head_hash"]
    assert projected["limits"]["acceptance"] == "recorded_review_not_source_truth"


def test_accepted_tag_search_carries_review_evidence():
    report = _report()
    journal = _decide(report)
    result = search_reviewed_assets([report], journal, tags=["topic:robotique"])
    assert result["schema"] == "parcimonia.asset-reviewed-search/v1"
    assert result["query"]["states"] == ["accepted"]
    assert result["count"] == 1
    match = result["matches"][0]
    assert match["report_hash"] == hash_input(report)
    assert match["tag_states"] == [{
        "tag": "topic:robotique", "status": "accepted",
        "decision_event_id": "event-1", "decision_event_hash": journal["head_hash"],
    }]


def test_rejection_is_excluded_by_default_and_can_be_requested_explicitly():
    report = _report()
    journal = _decide(report, "reject")
    assert search_reviewed_assets([report], journal, tags=["topic:robotique"])["count"] == 0
    rejected = search_reviewed_assets([report], journal, tags=["topic:robotique"], states=["rejected"])
    assert rejected["count"] == 1
    assert rejected["matches"][0]["tag_states"][0]["status"] == "rejected"


def test_latest_decision_wins_and_reset_preserves_its_provenance():
    report = _report()
    journal = _decide(report)
    journal = _decide(report, "reject", journal)
    assert _tag(project_tag_reviews([report], journal)["assets"][0])["status"] == "rejected"
    journal = _decide(report, "reset", journal)
    tag = _tag(project_tag_reviews([report], journal)["assets"][0])
    assert tag["status"] == "proposed"
    assert tag["decision"]["event_id"] == "event-3"
    assert len(journal["events"]) == 3
    assert search_reviewed_assets([report], journal, tags=["topic:robotique"])["count"] == 0
    assert search_reviewed_assets([report], journal, tags=["topic:robotique"], states=["proposed"])["count"] == 1


@pytest.mark.parametrize("change", ["bytes", "lexicon", "metadata", "filename"])
def test_same_identity_with_changed_report_does_not_inherit_acceptance(change):
    old = _report()
    journal = _decide(old)
    if change == "bytes":
        current = _report(data=b"robot in another garden")
    elif change == "lexicon":
        current = inspect_asset(b"robot in garden", filename="notes.txt", source_id="asset", revision="v1", topic_terms={"robotique": ["robot", "robotique"]})
    else:
        current = deepcopy(old)
        if change == "metadata":
            current["metadata"].append({"name": "parser_note", "value": "changed"})
        else:
            current["source"]["filename"] = "renamed.txt"
    view = project_tag_reviews([current], journal)
    assert _tag(view["assets"][0])["status"] == "proposed"
    assert view["unapplied_events"] == [{"event_id": "event-1", "source": {"id": "asset", "revision": "v1"}, "reason": "report_changed"}]
    assert search_reviewed_assets([current], journal, tags=["topic:robotique"])["count"] == 0


def test_prefix_and_complete_report_with_same_sample_hash_stay_distinct():
    prefix = _report(data=b"robot ", complete=False, total_bytes=9)
    complete = _report(data=b"robot ")
    assert prefix["sample"]["sha256"] == complete["sample"]["sha256"]
    journal = _decide(prefix)
    projected = project_tag_reviews([complete], journal)
    assert projected["unapplied_events"][0]["reason"] == "report_changed"
    assert _tag(projected["assets"][0])["status"] == "proposed"


def test_revision_changes_are_stale_even_when_content_is_identical():
    old = _report()
    current = _report(revision="v2")
    journal = _decide(old)
    projected = project_tag_reviews([current], journal)
    assert projected["unapplied_events"][0]["reason"] == "source_revision_changed"
    assert _tag(projected["assets"][0])["status"] == "proposed"


def test_explicit_historical_and_current_revisions_can_coexist():
    old, current = _report(revision="v1"), _report(revision="v2")
    journal = _decide(old)
    result = search_reviewed_assets([current, old], journal, tags=["topic:robotique"])
    assert [match["source"]["revision"] for match in result["matches"]] == ["v1"]
    assert project_tag_reviews([current, old], journal)["unapplied_events"] == []


def test_same_bytes_different_asset_identity_never_transfers_a_decision():
    old, other = _report("one"), _report("two")
    assert old["sample"]["sha256"] == other["sample"]["sha256"]
    journal = _decide(old)
    assert project_tag_reviews([other], journal)["unapplied_events"][0]["reason"] == "source_not_in_catalogue"
    result = search_reviewed_assets([old, other], journal, tags=["topic:robotique"])
    assert [match["source"]["id"] for match in result["matches"]] == ["one"]


def test_unrelated_journal_events_do_not_poison_an_applicable_later_event():
    old, current = _report("old"), _report("current")
    journal = _decide(old)
    journal = _decide(current, journal=journal)
    view = project_tag_reviews([current], journal)
    assert view["unapplied_events"][0]["event_id"] == "event-1"
    assert _tag(view["assets"][0])["decision"]["event_id"] == "event-2"


def test_matching_report_hash_with_an_unknown_tag_is_an_error():
    report = _report()
    journal = _decide(report)
    journal["events"][0]["tag"]["value"] = "not-proposed"
    _rehash_event(journal)
    with pytest.raises(ValueError, match="unknown tag"):
        project_tag_reviews([report], journal)


def test_multiple_proposal_bases_group_evidence_for_one_review_state():
    report = _report()
    duplicate = deepcopy(next(t for t in report["tag_proposals"] if t["namespace"] == "topic"))
    duplicate.update(basis="alternate_fixture", evidence_refs=["fixture:alternate"])
    report["tag_proposals"].append(duplicate)
    report["evidence"].append({"id": "fixture:alternate", "kind": "fixture"})
    journal = _decide(report)
    view = project_tag_reviews([report], journal)
    tags = [t for t in view["assets"][0]["tags"] if t["namespace"] == "topic"]
    assert len(tags) == 1 and tags[0]["status"] == "accepted"
    assert "fixture:alternate" in tags[0]["evidence_refs"]
    assert len(tags[0]["evidence_refs"]) == 2


def test_tag_filters_keep_exact_and_semantics_across_states():
    report = _report()
    journal = _decide(report)
    assert search_reviewed_assets([report], journal, tags=["topic:robotique", "modality:text"])["count"] == 0
    result = search_reviewed_assets([report], journal, tags=["topic:robotique", "modality:text"], states=["proposed", "accepted"])
    assert result["count"] == 1
    assert {item["status"] for item in result["matches"][0]["tag_states"]} == {"proposed", "accepted"}
    assert search_reviewed_assets([report], journal, tags=["topic:Robotique"])["count"] == 0


def test_no_tag_filter_lists_assets_without_implying_acceptance():
    report = _report()
    result = search_reviewed_assets([report], create_tag_journal())
    assert result["count"] == 1
    assert result["matches"][0]["tag_states"] == []
    assert result["limits"]["listing_without_tag_filter"] == "does_not_imply_approval"


def test_spatial_search_reuses_envelope_policy_without_a_tag_approval_claim():
    report = inspect_asset(b'{"type":"Point","coordinates":[2,48]}', filename="map.geojson", source_id="map", revision="v1")
    journal = create_tag_journal()
    result = search_reviewed_assets([report], journal, bbox=[1,47,3,49])
    assert result["count"] == 1
    assert result["matches"][0]["spatial_match"] == "envelope_overlap_candidate"
    assert search_reviewed_assets([report], journal, tags=["spatial:has_coordinates"], bbox=[1,47,3,49])["count"] == 0
    journal = _decide(report, tag="spatial:has_coordinates")
    assert search_reviewed_assets([report], journal, tags=["spatial:has_coordinates"], bbox=[1,47,3,49])["count"] == 1
    assert search_reviewed_assets([report], journal, bbox=[3,48,4,50])["count"] == 0


def test_projection_and_search_do_not_mutate_inputs_or_return_mutable_aliases():
    report = _report()
    journal = _decide(report)
    before = deepcopy((report, journal))
    projected = project_tag_reviews([report], journal)
    result = search_reviewed_assets([report], journal, tags=["topic:robotique"])
    projected["assets"][0]["source"]["id"] = "changed"
    tag = _tag(projected["assets"][0])
    tag["decision"]["reason"] = "changed"
    tag["evidence_refs"].append("made-up")
    result["matches"][0]["source"]["id"] = "changed"
    result["matches"][0]["tag_states"][0]["status"] = "changed"
    assert (report, journal) == before


def test_hash_binds_journal_report_and_normalized_query_state():
    report = _report()
    journal = create_tag_journal()
    before = project_tag_reviews([report], journal)
    after = project_tag_reviews([report], _decide(report))
    assert before["input_hash"] != after["input_hash"]
    accepted = search_reviewed_assets([report], journal, states=["accepted"])
    proposed = search_reviewed_assets([report], journal, states=["proposed"])
    assert accepted["input_hash"] != proposed["input_hash"]
    duplicate = search_reviewed_assets([report], journal, states=["accepted", "accepted"])
    assert duplicate == accepted


def test_stable_sort_limit_and_truncation_are_preserved():
    reports = [_report("z"), _report("b"), _report("a")]
    result = search_reviewed_assets(reports, create_tag_journal(), limit=2)
    assert [m["source"]["id"] for m in result["matches"]] == ["a", "b"]
    assert result["count"] == 2 and result["truncated"] is True


@pytest.mark.parametrize("states", [[], "accepted", ["verified"], [True], ("accepted",), [" accepted"], ["accepted"] * 257])
def test_invalid_state_filters_are_rejected(states):
    with pytest.raises(ValueError):
        search_reviewed_assets([_report()], create_tag_journal(), states=states)


@pytest.mark.parametrize("reports", [None, (), [_report()] * 257, [_report(), _report()]])
def test_catalogue_bounds_and_duplicate_identity_are_reused(reports):
    with pytest.raises(ValueError):
        project_tag_reviews(reports, create_tag_journal())


def test_excessive_proposals_are_refused_before_projection():
    report = _report()
    report["tag_proposals"] = [deepcopy(report["tag_proposals"][0]) for _ in range(257)]
    with pytest.raises(ValueError, match="256 tag proposals"):
        project_tag_reviews([report], create_tag_journal())


@pytest.mark.parametrize("field,value", [("schema", "unknown"), ("input_hash", "bad"), ("mode", "active")])
def test_inspection_contract_is_not_relaxed_for_review(field, value):
    report = _report()
    report[field] = value
    with pytest.raises(ValueError):
        project_tag_reviews([report], create_tag_journal())


def test_invalid_journal_cannot_be_used_to_search_or_project():
    report = _report()
    journal = _decide(report)
    journal["events"][0]["action"] = "reject"
    with pytest.raises(ValueError):
        project_tag_reviews([report], journal)
    with pytest.raises(ValueError):
        search_reviewed_assets([report], journal)


@pytest.mark.parametrize("value", [
    object(), float("nan"), {1, 2}, b"binary", (1, 2),
    {1: "integer-key"}, {True: "boolean-key"},
    _MetadataDict(value=1), _MetadataList([1, 2]), _MetadataString("text"),
])
def test_non_json_metadata_is_rejected_as_invalid_input(value):
    report = _report()
    report["metadata"].append({"value": value})
    with pytest.raises(ValueError):
        project_tag_reviews([report], create_tag_journal())


@pytest.mark.parametrize("bbox", [[True,0,1,1], [0,0,float("nan"),1], [170,0,-170,1]])
def test_invalid_spatial_query_remains_refused(bbox):
    with pytest.raises(ValueError):
        search_reviewed_assets([_report()], create_tag_journal(), bbox=bbox)
