from copy import deepcopy
from hashlib import sha256

import pytest

from tiberium_ai.context_annotations import apply_context_review
from tiberium_ai.context_comparison import assess_context_comparison
from tiberium_ai.context_review import build_context_review_pack
from tiberium_ai.decision_json import canonical_json
from tiberium_ai.route_experiment import ArmAvailability, ExperimentArm


ARMS = (ExperimentArm("baseline", ("rule",), ArmAvailability.READY, "fixture.rule", "1"),
        ExperimentArm("candidate", ("typed",), ArmAvailability.READY, "fixture.candidate", "1"))


def reviewed_packet():
    data = build_context_review_pack([{"text": f"extraire le document de contrôle numéro {i}", "sources": []} for i in range(4)], corpus_revision="fixture")
    data["parent_pack_id"] = "fixture-parent"
    data["paraphrase_candidates"] = []
    for i, case in enumerate(data["cases"]):
        case.update(source_group=f"source-{i}", provenance_status="recovered")
    review = {"kind": "context_human_review", "packet_id": data["pack_id"], "parent_pack_id": data["parent_pack_id"],
        "annotations": {case["case_id"]: {"source_group": case["source_group"], "group_reviewed": True,
        "complete": True, "language": "fr", "labeler_id": "fixture-reviewer", "rationale": "Authored fixture",
        "evidence_basis": "recorded_input", "labels": {"task_kind": "extract", "provided_fields": [],
        "required_context": ["document"], "missing_context": [], "unknown_context": ["document"]}}
        for case in data["cases"]}}
    return apply_context_review(data, review, require_complete=True)


def assess(packet, **kwargs):
    return assess_context_comparison(packet, ARMS, baseline_arm_id="baseline", min_heldout=1, **kwargs)


def test_complete_fixture_plan_still_needs_paired_capture_and_cannot_claim_quality():
    result = assess(reviewed_packet())
    assert result["kind_capture_ready"] and result["context_capture_ready"]
    assert result["capture_gate"]["measured_pairs"] == 0
    assert "missing_paired_outcomes" in result["capture_gate"]["reason_codes"]
    assert result["quality_metrics"] is None and result["cost_savings"] is None
    assert not result["claim_allowed"] and not result["independence_certified"]


def test_unreviewed_packet_never_produces_placeholder_scores():
    data = build_context_review_pack([{"text": "extraire les colonnes du document", "sources": []}], corpus_revision="fixture")
    result = assess(data)
    assert not result["kind_capture_ready"]
    assert set(result["reason_codes"]) >= {"split_not_frozen", "human_review_incomplete", "insufficient_labelled_heldout"}
    assert result["quality_metrics"] is None


def test_modified_final_case_invalidates_heldout_evidence():
    data = reviewed_packet()
    data["cases"][0]["labels"]["provided_fields"] = ["changed"]
    result = assess(data)
    assert "split_case_hash_mismatch" in result["reason_codes"] and not result["kind_capture_ready"]


def test_rehashed_case_cannot_claim_another_split_assignment():
    data = reviewed_packet()
    case = data["cases"][0]
    case["split"] = "heldout" if case["split"] == "development" else "development"
    data["split_manifest"]["case_hashes"][case["case_id"]] = sha256(canonical_json(case).encode()).hexdigest()
    assert "split_case_assignment_mismatch" in assess(data)["reason_codes"]


def test_completed_annotation_without_recovered_source_remains_ineligible():
    data = reviewed_packet()
    case = data["cases"][0]
    case["provenance_status"] = "not_found"
    data["split_manifest"]["case_hashes"][case["case_id"]] = sha256(canonical_json(case).encode()).hexdigest()
    assert "source_provenance_incomplete" in assess(data)["reason_codes"]


def test_rehashed_group_crossing_is_still_rejected():
    data = reviewed_packet()
    for case in data["cases"]:
        case["source_group"] = "shared"
        data["split_manifest"]["case_hashes"][case["case_id"]] = sha256(canonical_json(case).encode()).hexdigest()
    result = assess(data)
    assert "split_group_leakage" in result["reason_codes"]


def test_training_case_from_test_set_blocks_comparison():
    data = reviewed_packet()
    result = assess(data, training_case_ids=data["split_manifest"]["heldout"])
    assert "training_heldout_leakage" in result["reason_codes"] and not result["kind_capture_ready"]


def test_unknown_context_labels_do_not_become_empty_sets_or_full_context_ready():
    data = reviewed_packet()
    for case in data["cases"]:
        case["labels"]["provided_fields"] = None
        data["split_manifest"]["case_hashes"][case["case_id"]] = sha256(canonical_json(case).encode()).hexdigest()
    result = assess(data)
    assert result["kind_capture_ready"] and not result["context_capture_ready"]
    assert result["full_context_labelled_heldout_cases"] == 0


def test_unavailable_model_is_not_given_a_synthetic_result():
    data = reviewed_packet()
    unavailable = ExperimentArm("absent", ("model",), ArmAvailability.UNAVAILABLE)
    result = assess_context_comparison(data, (ARMS[0], unavailable), baseline_arm_id="baseline", min_heldout=1)
    assert "arm_unavailable" in result["reason_codes"] and result["capture_gate"] is None
