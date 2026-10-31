"""Readiness of a paired comparison; no scores, model calls or promotion from metadata."""
from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping, Sequence

from .context_input_audit import audit_context_inputs
from .decision_json import canonical_json
from .route_experiment import ArmAvailability, ExperimentArm, ExperimentPlan, assess_experiment


def assess_context_comparison(packet: Mapping[str, Any], arms: Sequence[ExperimentArm], *,
                              baseline_arm_id: str, min_heldout: int = 20,
                              training_case_ids: Sequence[str] = ()) -> dict[str, Any]:
    if packet.get("kind") != "context_review_pack" or not isinstance(packet.get("cases"), list):
        raise ValueError("a context review packet is required")
    if type(min_heldout) is not int or min_heldout < 1:
        raise ValueError("min_heldout must be a positive integer")
    if len(arms) < 2 or not all(isinstance(arm, ExperimentArm) for arm in arms) or len({arm.arm_id for arm in arms}) != len(arms):
        raise ValueError("at least two distinct experiment arms are required")
    if baseline_arm_id not in {arm.arm_id for arm in arms}:
        raise ValueError("the baseline must be declared")
    cases = {case["case_id"]: case for case in packet["cases"]}
    if len(cases) != len(packet["cases"]):
        raise ValueError("case ids must be unique")
    # Source text identity and capture-envelope rules are recomputed even for reviewed data.
    audit = audit_context_inputs(packet)
    reasons = []
    if audit["counts"]["quarantine"]:
        reasons.append("capture_envelopes_pending_review")
    manifest = packet.get("split_manifest")
    heldout, development = set(), set()
    split_valid = packet.get("split_status") == "frozen" and isinstance(manifest, Mapping)
    if not split_valid:
        reasons.append("split_not_frozen")
    else:
        development = set(manifest.get("development", []))
        heldout = set(manifest.get("heldout", []))
        if not development or not heldout or development & heldout or development | heldout != set(cases):
            reasons.append("invalid_split_partition")
            split_valid = False
        if any(case.get("split") != ("heldout" if case_id in heldout else "development") for case_id, case in cases.items()):
            reasons.append("split_case_assignment_mismatch")
            split_valid = False
        if any(manifest.get("case_hashes", {}).get(case_id) != sha256(canonical_json(case).encode()).hexdigest()
               for case_id, case in cases.items()):
            reasons.append("split_case_hash_mismatch")
            split_valid = False
        for key in ("source_group", "paraphrase_group"):
            before = {cases[i].get(key) for i in development if i in cases and cases[i].get(key)}
            after = {cases[i].get(key) for i in heldout if i in cases and cases[i].get(key)}
            if before & after:
                reasons.append("split_group_leakage")
                split_valid = False
        before_threads = {p["thread_id"] for i in development if i in cases for p in cases[i].get("provenance", [])}
        after_threads = {p["thread_id"] for i in heldout if i in cases for p in cases[i].get("provenance", [])}
        if before_threads & after_threads:
            reasons.append("split_source_thread_leakage")
            split_valid = False
    reviewed = [case for case in cases.values() if case.get("group_reviewed") is True
                and case.get("review_status") == "completed" and isinstance(case.get("labeler_id"), str)
                and case["labeler_id"].strip()]
    if len(reviewed) != len(cases):
        reasons.append("human_review_incomplete")
    if any(case.get("provenance_status") != "recovered" for case in cases.values()):
        reasons.append("source_provenance_incomplete")
    eligible = [cases[i] for i in sorted(heldout) if i in cases and cases[i].get("language") in {"fr", "mixed"}
                and cases[i] in reviewed and cases[i].get("labels", {}).get("task_kind") is not None]
    if len(eligible) < min_heldout:
        reasons.append("insufficient_labelled_heldout")
    full_context = [case for case in eligible if all(isinstance(case.get("labels", {}).get(key), list)
                    for key in ("provided_fields", "required_context", "missing_context", "unknown_context"))]
    if len(full_context) < min_heldout:
        reasons.append("context_labels_incomplete")
    training_ids = set(training_case_ids)
    if training_ids - development:
        reasons.append("training_ids_outside_development")
    if training_ids & heldout:
        reasons.append("training_heldout_leakage")
    if any(arm.availability is not ArmAvailability.READY for arm in arms):
        reasons.append("arm_unavailable")
    blocking_kind = set(reasons) - {"context_labels_incomplete"}
    kind_ready = split_valid and not blocking_kind
    context_ready = kind_ready and len(full_context) >= min_heldout
    capture_gate = None
    if kind_ready:
        plan = ExperimentPlan(packet["pack_id"], tuple(case["case_id"] for case in eligible), baseline_arm_id, tuple(arms))
        gate = assess_experiment(plan)
        capture_gate = {"comparable": gate.comparable, "reason_codes": list(gate.reason_codes),
                        "required_pairs": gate.required_pairs, "measured_pairs": gate.measured_pairs}
    return {"schema_version": 1, "kind": "context_comparison_readiness", "packet_id": packet["pack_id"],
        "cases": len(cases), "human_reviewed_cases": len(reviewed), "heldout_cases": len(heldout),
        "kind_labelled_heldout_cases": len(eligible), "full_context_labelled_heldout_cases": len(full_context),
        "min_heldout": min_heldout, "capture_envelope_cases": audit["counts"]["quarantine"],
        "kind_capture_ready": kind_ready, "context_capture_ready": context_ready,
        "reason_codes": list(dict.fromkeys(reasons)), "capture_gate": capture_gate,
        "baseline_arm_id": baseline_arm_id, "arms": [{"arm_id": arm.arm_id, "availability": arm.availability.value,
            "backend_id": arm.backend_id, "backend_version": arm.backend_version} for arm in arms],
        "metric_basis": "agreement with declared review labels only", "quality_metrics": None,
        "independence_certified": False, "claim_allowed": False, "auto_act_allowed": False,
        "model_inference_executed": False, "cost_savings": None}
