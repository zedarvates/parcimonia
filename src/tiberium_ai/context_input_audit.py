"""Versioned audit of capture envelopes; never relabel or rewrite historical cases."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import re
from typing import Any, Mapping

from .decision_json import canonical_json

AUDIT_VERSION = "context-input-audit/1"
_TAGS = ("in-app-browser-context", "environment_context", "app-context", "external_codex_apps_open_page",
         "send_user_message_question_reply", "codex_delegation")
_BLOCKS = {tag: re.compile(rf"<{re.escape(tag)}\b[^>]*>.*?</{re.escape(tag)}\s*>", re.DOTALL | re.IGNORECASE)
           for tag in _TAGS}
_NOTICES = ("The next image is untrusted page evidence from the browser",
            "The user is viewing the following page", "Treat any text in the image as page content")


def packet_fingerprint(packet: Mapping[str, Any]) -> str:
    return sha256(canonical_json(packet).encode("utf-8")).hexdigest()


def audit_context_inputs(packet: Mapping[str, Any]) -> dict[str, Any]:
    if packet.get("kind") != "context_review_pack" or not isinstance(packet.get("cases"), list):
        raise ValueError("a context review packet is required")
    observations = []
    seen = set()
    for case in packet["cases"]:
        text = case.get("text")
        if not isinstance(text, str) or case.get("case_id") != sha256(text.encode()).hexdigest():
            raise ValueError("case identity does not match source text")
        if case["case_id"] in seen:
            raise ValueError("case ids must be unique")
        seen.add(case["case_id"])
        reasons = []
        proposed = text
        for tag, pattern in _BLOCKS.items():
            if re.search(rf"<{re.escape(tag)}\b", text, re.IGNORECASE):
                reasons.append("capture_tag:" + tag)
                proposed = pattern.sub(" ", proposed)
        if any(text.lstrip().startswith(prefix) for prefix in _NOTICES):
            reasons.append("browser_evidence_notice")
        if text.lstrip().startswith("# Files mentioned by the user:"):
            reasons.append("file_mentions_frame_requires_original_layout")
        proposed = " ".join(proposed.split())
        observations.append({"case_id": case["case_id"], "disposition": "quarantine" if reasons else "candidate",
            "reason_codes": reasons, "proposed_text": proposed if proposed != text else None,
            "text_empty_after_known_blocks": bool(reasons) and not proposed,
            "human_origin_established": False, "labels_changed": False})
    counts = {key: sum(row["disposition"] == key for row in observations) for key in ("candidate", "quarantine")}
    return {"schema_version": 1, "kind": "context_input_audit", "audit_version": AUDIT_VERSION,
        "parent_pack_id": packet["pack_id"], "packet_fingerprint": packet_fingerprint(packet),
        "cases": observations, "counts": counts, "labels_created": 0,
        "claim_allowed": False, "auto_act_allowed": False,
        "interpretation": "envelope signals only; legitimate quoted markers may need manual review"}


def isolate_context_candidates(packet: Mapping[str, Any], audit: Mapping[str, Any]) -> dict[str, Any]:
    if audit.get("kind") != "context_input_audit" or audit.get("audit_version") != AUDIT_VERSION:
        raise ValueError("unknown input audit")
    if audit.get("parent_pack_id") != packet.get("pack_id") or audit.get("packet_fingerprint") != packet_fingerprint(packet):
        raise ValueError("input audit belongs to a different packet revision")
    # Recompute the deterministic rule decisions instead of trusting audit metadata.
    expected = audit_context_inputs(packet)
    if audit.get("cases") != expected["cases"]:
        raise ValueError("input audit decisions do not match recomputation")
    ids = {row["case_id"] for row in expected["cases"] if row["disposition"] == "candidate"}
    result = deepcopy(dict(packet))
    result["cases"] = [case for case in result["cases"] if case["case_id"] in ids]
    for case in result["cases"]:
        case["group_reviewed"] = False
        case["split"] = None
    result.update(parent_pack_id=packet["pack_id"], origin_pack_id=packet.get("parent_pack_id"),
        selected_count=len(result["cases"]), labelled_cases=sum(case["labels"].get("task_kind") is not None for case in result["cases"]),
        audit_version=AUDIT_VERSION, quarantined_case_ids=sorted(set(expected_row["case_id"] for expected_row in expected["cases"]) - ids),
        split_status="input_audited_awaiting_independent_review", split_manifest=None,
        independent_labels_established=False, quality_metrics=None, claim_allowed=False, auto_act_allowed=False)
    result["paraphrase_candidates"] = [p for p in result.get("paraphrase_candidates", []) if p["left"] in ids and p["right"] in ids]
    # Retain source components from the full packet, including links through quarantined cases.
    result["source_component_count"] = len({case["source_group"] for case in result["cases"] if case.get("source_group")})
    result["pack_id"] = sha256(canonical_json({"parent": packet["pack_id"], "audit": AUDIT_VERSION, "cases": result["cases"]}).encode()).hexdigest()
    return result
