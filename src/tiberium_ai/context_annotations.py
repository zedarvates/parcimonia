"""Validate a blind human review; freeze groups only after explicit completion."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any, Mapping

from .context_review import LABEL_FIELDS, freeze_context_review_split
from .decision_json import canonical_json


def apply_context_review(packet: Mapping[str, Any], review: Mapping[str, Any], *,
                         require_complete: bool = False) -> dict[str, Any]:
    if review.get("kind") != "context_human_review" or review.get("packet_id") != packet.get("pack_id"):
        raise ValueError("review does not match this packet")
    if review.get("parent_pack_id") != packet.get("parent_pack_id"):
        raise ValueError("review has a different parent pack")
    if type(require_complete) is not bool:
        raise TypeError("require_complete must be a boolean")
    annotations = review.get("annotations")
    if not isinstance(annotations, Mapping):
        raise TypeError("annotations must be a mapping")
    cases = {case["case_id"]: case for case in packet["cases"]}
    if set(annotations) - set(cases):
        raise ValueError("review contains foreign cases")
    result = deepcopy(dict(packet))
    completed = set()
    for case in result["cases"]:
        annotation = annotations.get(case["case_id"])
        if annotation is None:
            continue
        if not isinstance(annotation, Mapping):
            raise TypeError("case annotations must be mappings")
        if annotation.get("source_group") != case.get("source_group"):
            raise ValueError("review changed a recovered source group")
        if annotation.get("complete") is not True:
            continue
        if annotation.get("group_reviewed") is not True or case.get("provenance_status") != "recovered":
            raise ValueError("completed review needs recovered and reviewed provenance")
        if annotation.get("language") not in {"fr", "mixed", "other", "unknown"}:
            raise ValueError("completed review needs a language decision")
        if not isinstance(annotation.get("labeler_id"), str) or not annotation["labeler_id"].strip():
            raise ValueError("completed review needs an identified annotator")
        if not isinstance(annotation.get("rationale"), str) or not annotation["rationale"].strip():
            raise ValueError("completed review needs a rationale")
        basis = annotation.get("evidence_basis")
        if basis not in {"recorded_input", "verified_outcome", "unknown"}:
            raise ValueError("completed review needs an evidence basis")
        if basis == "verified_outcome" and not annotation.get("outcome_ref"):
            raise ValueError("outcome-backed labels need an outcome reference")
        labels = annotation.get("labels")
        if not isinstance(labels, Mapping) or set(labels) != set(LABEL_FIELDS):
            raise ValueError("review must declare every label, including unknowns")
        cleaned = {}
        for name in LABEL_FIELDS:
            value = labels[name]
            if name == "task_kind":
                if value is not None and (not isinstance(value, str) or not value.strip()):
                    raise ValueError("task_kind must be a nonempty string or null")
            elif value is not None:
                if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() or v != v.strip() for v in value) or len(set(value)) != len(value):
                    raise ValueError("field labels must be unique names or null")
            cleaned[name] = deepcopy(value)
        required, missing, unknown = (cleaned[name] for name in ("required_context", "missing_context", "unknown_context"))
        if missing is not None and unknown is not None and set(missing) & set(unknown):
            raise ValueError("missing and unknown context must be distinct")
        if required is not None and any(value is not None and set(value) - set(required) for value in (missing, unknown)):
            raise ValueError("missing and unknown fields must be required")
        contract_id, version = annotation.get("contract_id") or None, annotation.get("contract_version") or None
        if (contract_id is None) != (version is None):
            raise ValueError("a context contract needs an identity and version")
        group = annotation.get("paraphrase_group") or None
        if group is not None and not isinstance(group, str):
            raise ValueError("paraphrase_group must be text or null")
        case.update(labels=cleaned, language_review_required=False, language=annotation["language"],
            labeler_id=annotation["labeler_id"], label_origin="human_review", rationale=annotation["rationale"],
            evidence_basis=basis, outcome_ref=annotation.get("outcome_ref"), group_reviewed=True,
            contract_id=contract_id, contract_version=version, paraphrase_group=group,
            context_snapshot_note=annotation.get("context_note"), review_status="completed")
        completed.add(case["case_id"])
    pairs = review.get("pair_decisions", {})
    allowed_pairs = {":".join(sorted((p["left"], p["right"]))) for p in packet.get("paraphrase_candidates", [])}
    if not isinstance(pairs, Mapping) or set(pairs) - allowed_pairs or any(value not in {"", "same_group", "different", "unknown"} for value in pairs.values()):
        raise ValueError("review contains unknown paraphrase decisions")
    pending = len(cases) - len(completed)
    undecided_pairs = sum(pairs.get(key, "") in {"", "unknown"} for key in allowed_pairs)
    if require_complete and (pending or undecided_pairs):
        raise ValueError(f"review_incomplete: {pending} cases and {undecided_pairs} pairs remain")
    split = None
    if not pending and not undecided_pairs:
        # Source groups, manual groups and confirmed pairs form one conservative graph.
        parent = {case_id: case_id for case_id in cases}
        def find(key):
            while parent[key] != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key
        seen = {}
        for case in result["cases"]:
            keys = [("source", case["source_group"])]
            if case["paraphrase_group"]:
                keys.append(("manual", case["paraphrase_group"]))
            for key in keys:
                if key in seen:
                    parent[find(case["case_id"])] = find(seen[key])
                else:
                    seen[key] = case["case_id"]
        for key, decision in pairs.items():
            if decision == "same_group":
                left, right = key.split(":")
                parent[find(left)] = find(right)
        components = {}
        for case_id in sorted(cases):
            components.setdefault(find(case_id), []).append(case_id)
        group_for = {case_id: sha256(canonical_json(group).encode()).hexdigest()
                     for group in components.values() for case_id in group}
        for case in result["cases"]:
            case["reviewed_paraphrase_group"] = case["paraphrase_group"]
            case["paraphrase_group"] = "review-" + group_for[case["case_id"]]
        split = freeze_context_review_split(result["cases"], seed=packet["seed"])
        heldout = set(split["heldout"])
        for case in result["cases"]:
            case["split"] = "heldout" if case["case_id"] in heldout else "development"
        # Bind the stored final rows, including their derived split assignment.
        split["case_hashes"] = {case["case_id"]: sha256(canonical_json(case).encode()).hexdigest()
                                for case in result["cases"]}
        split["case_hash_scope"] = "final_case_record/1"
    result.update(reviewed_cases=len(completed), pending_cases=pending, undecided_pairs=undecided_pairs,
        labelled_cases=sum(case["case_id"] in completed and case["labels"]["task_kind"] is not None for case in result["cases"]),
        split_status="frozen" if split else "awaiting_independent_review", split_manifest=split,
        independent_labels_established=False, quality_metrics=None, claim_allowed=False, auto_act_allowed=False)
    result["parent_review_packet_id"] = packet["pack_id"]
    result["pack_id"] = sha256(canonical_json({"parent": packet["pack_id"], "cases": result["cases"]}).encode()).hexdigest()
    return result
