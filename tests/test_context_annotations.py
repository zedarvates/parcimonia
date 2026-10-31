from copy import deepcopy
from hashlib import sha256

import pytest

from tiberium_ai.context_annotations import apply_context_review
from tiberium_ai.context_review import build_context_review_pack
from tiberium_ai.decision_json import canonical_json


def packet():
    result = build_context_review_pack([{"text": f"requête de contrôle numéro {i}", "sources": []} for i in range(3)], corpus_revision="fixture")
    result["parent_pack_id"] = "fixture-parent"
    result["paraphrase_candidates"] = []
    for i, case in enumerate(result["cases"]):
        case.update(source_group=f"source-{i}", provenance_status="recovered")
    return result


def review(data):
    return {"kind": "context_human_review", "packet_id": data["pack_id"], "parent_pack_id": data["parent_pack_id"],
        "annotations": {case["case_id"]: {"source_group": case["source_group"], "group_reviewed": True,
            "complete": True, "language": "fr", "labeler_id": "fixture-reviewer", "rationale": "Authored test",
            "evidence_basis": "recorded_input", "labels": {"task_kind": "verify", "provided_fields": [],
                "required_context": ["document"], "missing_context": [], "unknown_context": ["document"]},
            "paraphrase_group": None} for case in data["cases"]}, "pair_decisions": {}}


def test_complete_fixture_review_can_freeze_a_split_but_cannot_claim_quality():
    data = packet()
    result = apply_context_review(data, review(data), require_complete=True)
    assert result["reviewed_cases"] == 3 and result["split_status"] == "frozen"
    assert result["quality_metrics"] is None and not result["independent_labels_established"]
    assert not result["claim_allowed"] and all(case["label_origin"] == "human_review" for case in result["cases"])
    assert all(case["labels"]["provided_fields"] == [] for case in result["cases"])


def test_incomplete_review_and_unknown_labels_remain_explicit():
    data, annotations = packet(), None
    annotations = review(data)
    annotations["annotations"].pop(data["cases"][0]["case_id"])
    result = apply_context_review(data, annotations)
    assert result["pending_cases"] == 1 and result["split_manifest"] is None
    with pytest.raises(ValueError, match="review_incomplete"):
        apply_context_review(data, annotations, require_complete=True)


def test_manual_paraphrase_group_is_kept_together():
    data = packet()
    annotations = review(data)
    first, second = data["cases"][:2]
    for case in (first, second):
        annotations["annotations"][case["case_id"]]["paraphrase_group"] = "same-intent"
    result = apply_context_review(data, annotations, require_complete=True)
    cases = {case["case_id"]: case for case in result["cases"]}
    assert cases[first["case_id"]]["split"] == cases[second["case_id"]]["split"]


def test_frozen_split_hashes_bind_the_final_records_including_the_assigned_split():
    data = packet()
    result = apply_context_review(data, review(data), require_complete=True)
    for case in result["cases"]:
        assert result["split_manifest"]["case_hashes"][case["case_id"]] == sha256(canonical_json(case).encode()).hexdigest()


@pytest.mark.parametrize("change", ["foreign-packet", "source", "annotator", "overlap", "unreviewed-source"])
def test_invalid_reviews_cannot_freeze_a_split(change):
    data = packet()
    annotations = review(data)
    first = annotations["annotations"][data["cases"][0]["case_id"]]
    if change == "foreign-packet": annotations["packet_id"] = "wrong"
    elif change == "source": first["source_group"] = "another-source"
    elif change == "annotator": first["labeler_id"] = ""
    elif change == "overlap": first["labels"]["missing_context"] = ["document"]
    else: first["group_reviewed"] = False
    with pytest.raises(ValueError):
        apply_context_review(data, annotations, require_complete=True)
