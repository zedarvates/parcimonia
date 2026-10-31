from dataclasses import replace

import pytest

from tiberium_ai.contracts import Verification
from tiberium_ai.task_context import (
    ContextContract, ContextField, assess_context, enrich_signature_context, reference_payload,
)
from tiberium_ai.task_signature import TaskSignature
from tiberium_ai.verification import VerifierRegistry, hash_input


def contract():
    return ContextContract("extract.csv-columns", "1", "extract", (
        ContextField("document", "Actual CSV content, not a filename"),
        ContextField("budget", "Declared cost ceiling", "number"),
        ContextField("allow_network", "Explicit host flag", "bool"),
    ), ("document",))


def signature(prompt="extraire les colonnes de ce fichier"):
    return TaskSignature("legacy-fixture", hash_input(prompt), "extract", .95, (), {},
        ("path", "schema"), {"path": 1., "schema": 1.}, None, None, False, None,
        "fixture", "1", "fixture")


def proof_for(declared, revision="snapshot-1", reference="document-1", verdict=True):
    registry = VerifierRegistry()
    registry.register("host.document-availability", "1", lambda descriptor: verdict)
    payload = reference_payload(declared, field="document", reference_id=reference, context_revision=revision)
    if verdict is None:
        proof = Verification("host.document-availability", "1", None, hash_input(payload), "unavailable_status")
    else:
        proof = registry.verify("host.document-availability", "1", payload)
    return registry, proof


def test_mention_and_legacy_fields_do_not_supply_actual_values():
    legacy = signature()
    record = enrich_signature_context(legacy, "extraire les colonnes de ce fichier", contract(),
        context_revision="snapshot-1", values={}, context_complete=True).to_record()
    assert record["signature"]["fields"] == ["path", "schema"]
    assert record["context"]["provided_fields"] == []
    assert record["context"]["required_context"] == ["document"]
    assert record["context"]["missing_context"] == ["document"]
    assert record["status"] == "missing_context" and not record["ready"]
    assert not record["auto_act_allowed"]
    assert record["signature"] == legacy.to_record()


def test_supplied_values_and_explicit_zero_false_are_preserved():
    result = assess_context(contract(), context_revision="snapshot-1",
        values={"document": "name,age\nAda,36", "budget": 0, "allow_network": False})
    assert result.ready and result.provided_fields == ("document", "budget", "allow_network")
    assert result.available_context == result.provided_fields
    assert result.missing_context == result.unknown_context == ()
    assert not result.to_record()["auto_act_allowed"]


@pytest.mark.parametrize("value", [None, "", "   ", False, 0, []])
def test_present_but_unusable_document_is_separate_from_absent(value):
    result = assess_context(contract(), context_revision="snapshot-1", values={"document": value})
    assert result.provided_fields == ("document",)
    assert result.invalid_fields == ("document",)
    assert result.missing_context == ("document",) and result.status == "invalid_context"


def test_unknown_snapshot_is_not_treated_as_empty_complete_context():
    unknown = assess_context(contract(), context_revision="uncaptured")
    assert unknown.unknown_context == ("document",) and unknown.missing_context == ()
    empty = assess_context(contract(), context_revision="complete", context_complete=True)
    assert empty.missing_context == ("document",) and empty.unknown_context == ()


def test_references_require_registered_bound_host_evidence_without_running_a_verifier():
    declared = contract()
    registry = VerifierRegistry()
    calls = []
    def host_check(payload):
        calls.append(payload)
        return True
    registry.register("host.document-availability", "1", host_check)
    descriptor = reference_payload(declared, field="document", reference_id="document-1", context_revision="snapshot-1")
    proof = registry.verify("host.document-availability", "1", descriptor)
    result = assess_context(declared, context_revision="snapshot-1", references={"document": "document-1"},
        reference_evidence={"document": proof}, verifiers=registry)
    assert result.ready and result.available_context == ("document",)
    assert result.provided_fields == () and result.referenced_fields == ("document",)
    assert calls == [descriptor]
    assert result.to_record()["reference_verification"]["document"] == proof.to_record()
    assert not result.to_record()["auto_act_allowed"]


@pytest.mark.parametrize("verdict,expected", [(False, "missing_context"), (None, "context_unknown")])
def test_false_and_unknown_reference_evidence_are_distinct(verdict, expected):
    declared = contract()
    registry, proof = proof_for(declared, verdict=verdict)
    result = assess_context(declared, context_revision="snapshot-1", references={"document": "document-1"},
        reference_evidence={"document": proof}, verifiers=registry)
    assert result.status == expected and not result.ready


@pytest.mark.parametrize("changed", ["snapshot", "reference", "contract"])
def test_reference_evidence_cannot_be_reused_for_a_different_descriptor(changed):
    declared = contract()
    registry, proof = proof_for(declared)
    result = assess_context(replace(declared, version="2") if changed == "contract" else declared,
        context_revision="snapshot-2" if changed == "snapshot" else "snapshot-1",
        references={"document": "document-2" if changed == "reference" else "document-1"},
        reference_evidence={"document": proof}, verifiers=registry)
    assert result.unknown_context == ("document",)
    assert result.field_status["document"] == "reference_input_mismatch"


def test_reference_evidence_without_a_known_verifier_cannot_supply_context():
    declared = contract()
    _, proof = proof_for(declared)
    for registry in (None, VerifierRegistry()):
        result = assess_context(declared, context_revision="snapshot-1", references={"document": "document-1"},
            reference_evidence={"document": proof}, verifiers=registry)
        assert result.status == "context_unknown"


@pytest.mark.parametrize("kwargs", [
    {"values": {"undeclared": 3}}, {"values": {"document": "csv"}, "references": {"document": "ref"}},
    {"reference_evidence": {"document": "not a proof"}}, {"values": {"budget": float("nan")}},
    {"context_complete": "true"}, {"references": {"document": ""}},
])
def test_invalid_or_conflicting_declarations_are_rejected(kwargs):
    with pytest.raises((ValueError, TypeError)):
        assess_context(contract(), context_revision="snapshot-1", **kwargs)


def test_signature_prompt_kind_and_abstention_remain_gates():
    declared, legacy = contract(), signature()
    ready = {"context_revision": "snapshot-1", "values": {"document": "csv"}}
    with pytest.raises(ValueError, match="prompt"):
        enrich_signature_context(legacy, "another prompt", declared, **ready)
    mismatched = enrich_signature_context(replace(legacy, kind="format"),
        "extraire les colonnes de ce fichier", declared, **ready)
    assert mismatched.status == "kind_contract_mismatch"
    abstained = enrich_signature_context(replace(legacy, kind=None, abstained=True, reason_code="unknown"),
        "extraire les colonnes de ce fichier", declared, **ready)
    assert abstained.status == "signature_abstained" and not abstained.to_record()["ready"]


def test_context_identity_and_public_assessment_do_not_expose_values_or_reference_ids():
    declared = contract()
    first = assess_context(declared, context_revision="snapshot-1", values={"document": "private text"})
    second = assess_context(declared, context_revision="snapshot-1", values={"document": "other text"})
    assert first.input_hash != second.input_hash
    assert "private text" not in str(first.to_record())
    assert declared.fingerprint() != replace(declared, required_context=()).fingerprint()
