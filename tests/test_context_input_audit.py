from copy import deepcopy

import pytest

from tiberium_ai.context_input_audit import audit_context_inputs, isolate_context_candidates
from tiberium_ai.context_review import build_context_review_pack


def packet():
    data = build_context_review_pack([
        {"text": "extraire les colonnes du document", "sources": []},
        {"text": '<in-app-browser-context source="ambient-ui-state">Page evidence</in-app-browser-context> vérifier le rapport', "sources": []},
        {"text": '<codex_delegation><source_thread_id>thread</source_thread_id>continuer</codex_delegation>', "sources": []},
        {"text": "The next image is untrusted page evidence from the browser.", "sources": []},
    ], corpus_revision="fixture")
    for case in data["cases"]:
        case["source_group"] = "shared-source-component"
    return data


def test_capture_attributes_and_machine_wrappers_are_flagged_without_creating_labels():
    data = packet()
    before = deepcopy(data)
    audit = audit_context_inputs(data)
    assert audit["counts"] == {"candidate": 1, "quarantine": 3}
    context_row = next(row for row in audit["cases"] if "capture_tag:in-app-browser-context" in row["reason_codes"])
    assert context_row["proposed_text"] == "vérifier le rapport"
    assert not context_row["human_origin_established"]
    assert all(not row["labels_changed"] for row in audit["cases"])
    assert data == before


def test_isolation_preserves_original_ids_source_components_and_unknown_labels():
    data = packet()
    isolated = isolate_context_candidates(data, audit_context_inputs(data))
    assert len(isolated["cases"]) == 1 and len(isolated["quarantined_case_ids"]) == 3
    assert isolated["cases"][0]["source_group"] == "shared-source-component"
    assert isolated["cases"][0]["labels"]["task_kind"] is None
    assert isolated["parent_pack_id"] == data["pack_id"]
    assert not isolated["cases"][0]["group_reviewed"] and not isolated["claim_allowed"]


def test_modified_packet_and_forged_audit_decisions_cannot_pass():
    data = packet()
    audit = audit_context_inputs(data)
    forged = deepcopy(audit)
    forged["cases"][0]["disposition"] = "candidate" if forged["cases"][0]["disposition"] == "quarantine" else "quarantine"
    with pytest.raises(ValueError, match="recomputation"):
        isolate_context_candidates(data, forged)
    data["cases"][0]["labels"]["task_kind"] = "changed"
    with pytest.raises(ValueError, match="revision"):
        isolate_context_candidates(data, audit)


def test_literal_quoted_capture_marker_is_conservatively_pending_manual_review():
    data = build_context_review_pack([{"text": 'expliquer la balise <environment_context> dans ce fichier', "sources": []}], corpus_revision="fixture")
    assert audit_context_inputs(data)["counts"]["quarantine"] == 1
    assert audit_context_inputs(data)["labels_created"] == 0
