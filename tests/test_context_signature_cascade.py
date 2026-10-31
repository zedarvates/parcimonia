from dataclasses import replace

import pytest

from tiberium_ai.reflex import ReflexKind
from tiberium_ai.signature_cascade import SignatureCascadeBackend
from tiberium_ai.task_context import ContextContract, ContextField
from tiberium_ai.task_signature import DeclaredItem, SignatureSchema, signature_questions


SCHEMA = SignatureSchema("context-cascade-fixture", (DeclaredItem("extract"), DeclaredItem("verify")),
                         fields=(DeclaredItem("path"),))
CONTRACT = ContextContract("extract.csv-columns", "1", "extract",
                           (ContextField("document", "Concrete CSV contents"),), ("document",))


class CountingBackend:
    latin_only = False

    def __init__(self, choice="extract", probability=.95, *, broken=False, field_probability=.1):
        self.choice, self.probability, self.broken = choice, probability, broken
        self.field_probability = field_probability
        self.calls = 0
        self.last_state = None

    def evaluate(self, state, questions):
        self.calls += 1
        self.last_state = state
        if self.broken:
            raise ValueError("provider failure with private data that must not be exposed")
        return {q.name: {"choice": self.choice, "confidence": None,
                    "probabilities": {name: self.probability if name == self.choice else 1-self.probability for name in q.option_keys}}
                if q.kind == ReflexKind.CHOICE else {"noul": self.field_probability,
                    "probabilities": {"false": 1-self.field_probability, "true": self.field_probability}}
                for q in questions}


def run(cascade, **context):
    method = getattr(cascade, "propose_signature", None)
    assert callable(method), "context-aware signature cascade is missing"
    return method("récupère les colonnes du document", schema=SCHEMA, contract=CONTRACT,
        baseline_identity=("fixture.baseline", "1"), fallback_identity=("fixture.fallback", "1"),
        **{"context_revision": "snapshot-1", **context})


def test_missing_context_stops_before_any_predictor_or_fallback_call():
    baseline, fallback = CountingBackend(), CountingBackend()
    cascade = SignatureCascadeBackend(baseline, fallback)
    result = run(cascade, values={}, context_complete=True)
    assert result.status == "collect_context" and result.context.missing_context == ("document",)
    assert result.signature is None and result.selected_route is None
    assert baseline.calls == fallback.calls == cascade.calls == cascade.fallback_calls == 0
    assert not result.to_record()["auto_act_allowed"]


def test_available_context_keeps_the_confident_baseline_and_legacy_field_semantics():
    baseline, fallback = CountingBackend(), CountingBackend(broken=True)
    cascade = SignatureCascadeBackend(baseline, fallback)
    result = run(cascade, values={"document": "a,b\n1,2"})
    assert result.status == "selected" and result.selected_route == "baseline"
    assert result.signature.kind == "extract" and result.signature.fields == ()
    assert result.context.provided_fields == ("document",)
    assert baseline.calls == 1 and fallback.calls == 0
    assert baseline.last_state == "récupère les colonnes du document"


def test_confident_kind_contract_mismatch_uses_a_complete_fallback_batch():
    baseline, fallback = CountingBackend("verify"), CountingBackend(field_probability=.95)
    cascade = SignatureCascadeBackend(baseline, fallback)
    result = run(cascade, values={"document": "csv"})
    assert result.status == "selected" and result.selected_route == "fallback"
    assert result.signature.kind == "extract" and fallback.calls == 1
    assert result.signature.fields == ("path",)
    assert result.stages[0]["decision"] == "kind_contract_mismatch"


def test_uncertain_fallback_is_an_explicit_abstention_not_a_selected_batch():
    baseline, fallback = CountingBackend(probability=.6), CountingBackend(probability=.7)
    cascade = SignatureCascadeBackend(baseline, fallback)
    result = run(cascade, values={"document": "csv"})
    assert result.status == "abstained" and result.reason_code == "fallback_low_kind_confidence"
    assert result.signature is None and result.selected_route is None
    assert cascade.fallback_calls == 1


def test_failed_fallback_is_counted_without_retry_or_private_error_echo():
    baseline, fallback = CountingBackend(probability=.6), CountingBackend(broken=True)
    cascade = SignatureCascadeBackend(baseline, fallback)
    result = run(cascade, values={"document": "csv"})
    assert result.status == "backend_error" and cascade.fallback_calls == 1 and fallback.calls == 1
    assert "private data" not in str(result.to_record())


def test_unobserved_context_does_not_become_confirmed_absence_or_a_model_call():
    baseline, fallback = CountingBackend(), CountingBackend()
    cascade = SignatureCascadeBackend(baseline, fallback)
    result = run(cascade)
    assert result.status == "collect_context" and result.context.unknown_context == ("document",)
    assert result.context.missing_context == ()
    assert baseline.calls == fallback.calls == result.backend_calls == 0


def test_invalid_inline_context_is_returned_for_repair_before_predictors():
    baseline, fallback = CountingBackend(), CountingBackend()
    result = run(SignatureCascadeBackend(baseline, fallback), values={"document": None})
    assert result.status == "repair_context" and result.context.invalid_fields == ("document",)
    assert baseline.calls == fallback.calls == 0


def test_zero_prediction_and_fallback_budgets_produce_typed_refusals():
    baseline, fallback = CountingBackend(probability=.6), CountingBackend()
    result = run(SignatureCascadeBackend(baseline, fallback, max_calls=0), values={"document": "csv"})
    assert result.status == "budget_exhausted" and result.reason_code == "call_budget_exhausted"
    assert baseline.calls == fallback.calls == 0
    result = run(SignatureCascadeBackend(baseline, fallback, max_fallback_calls=0), values={"document": "csv"})
    assert result.reason_code == "fallback_budget_exhausted" and result.signature is None
    assert baseline.calls == 1 and fallback.calls == 0


def test_call_caps_are_shared_with_legacy_evaluate_and_stage_records_are_snapshots():
    baseline, fallback = CountingBackend(), CountingBackend()
    cascade = SignatureCascadeBackend(baseline, fallback, max_calls=1)
    first = run(cascade, values={"document": "csv"})
    assert first.status == "selected"
    with pytest.raises(ValueError, match="call_budget"):
        cascade.evaluate("legacy request", signature_questions(SCHEMA))
    assert first.stages[0]["decision"] == "selected"
    assert first.stages[0]["status"] == "validated"


def test_confident_fallback_of_another_kind_is_not_selected():
    baseline, fallback = CountingBackend(probability=.6), CountingBackend("verify")
    result = run(SignatureCascadeBackend(baseline, fallback), values={"document": "csv"})
    assert result.status == "abstained" and result.reason_code == "fallback_kind_contract_mismatch"
    assert result.signature is None and fallback.calls == 1


def test_context_mode_never_lowers_the_signature_schema_threshold():
    baseline, fallback = CountingBackend(probability=.95), CountingBackend(probability=.995)
    cascade = SignatureCascadeBackend(baseline, fallback, threshold=.9)
    result = cascade.propose_signature("extraire les colonnes", schema=replace(SCHEMA, min_kind_confidence=.99), contract=CONTRACT,
        baseline_identity=("fixture.baseline", "1"), fallback_identity=("fixture.fallback", "1"),
        context_revision="snapshot-1", values={"document": "csv"})
    assert result.selected_route == "fallback" and baseline.calls == fallback.calls == 1


def test_backend_identity_disagreement_is_rejected_before_an_attempt():
    baseline, fallback = CountingBackend(), CountingBackend()
    baseline.backend_id = "actual-baseline"
    cascade = SignatureCascadeBackend(baseline, fallback)
    with pytest.raises(ValueError, match="identity"):
        run(cascade, values={"document": "csv"})
    assert baseline.calls == fallback.calls == cascade.calls == 0


def test_unsupported_script_skips_baseline_but_a_declared_multilingual_fallback_can_run():
    baseline, fallback = CountingBackend(), CountingBackend()
    baseline.latin_only = True
    cascade = SignatureCascadeBackend(baseline, fallback)
    result = cascade.propose_signature("សួស្តី នេះជាកិច្ចការ", schema=SCHEMA, contract=CONTRACT,
        baseline_identity=("fixture.baseline", "1"), fallback_identity=("fixture.fallback", "1"),
        context_revision="snapshot-1", values={"document": "csv"})
    assert result.selected_route == "fallback" and result.backend_calls == 1
    assert baseline.calls == 0 and fallback.calls == 1
    assert result.stages[0]["decision"] == "script_unsupported"


def test_no_supported_script_route_is_an_abstention_without_a_backend_call():
    baseline, fallback = CountingBackend(), CountingBackend()
    baseline.latin_only = fallback.latin_only = True
    cascade = SignatureCascadeBackend(baseline, fallback)
    result = cascade.propose_signature("សួស្តី នេះជាកិច្ចការ", schema=SCHEMA, contract=CONTRACT,
        baseline_identity=("fixture.baseline", "1"), fallback_identity=("fixture.fallback", "1"),
        context_revision="snapshot-1", values={"document": "csv"})
    assert result.status == "abstained" and result.backend_calls == 0
    assert baseline.calls == fallback.calls == cascade.fallback_calls == 0


def test_unverified_reference_and_different_context_revision_cannot_be_reused():
    baseline, fallback = CountingBackend(), CountingBackend()
    cascade = SignatureCascadeBackend(baseline, fallback)
    missing = run(cascade, references={"document": "attachment-1"})
    assert missing.status == "collect_context" and baseline.calls == 0
    first = run(cascade, values={"document": "csv-A"})
    second = run(SignatureCascadeBackend(CountingBackend(), CountingBackend()),
                 values={"document": "csv-A"}, context_revision="snapshot-2")
    third = run(SignatureCascadeBackend(CountingBackend(), CountingBackend()), values={"document": "csv-B"})
    assert first.request_hash != second.request_hash
    assert first.request_hash != third.request_hash
    assert "csv-A" not in str(first.to_record())


def test_invalid_baseline_protocol_is_not_hidden_by_a_fallback():
    baseline, fallback = CountingBackend(choice="undeclared"), CountingBackend()
    result = run(SignatureCascadeBackend(baseline, fallback), values={"document": "csv"})
    assert result.status == "backend_error" and baseline.calls == 1 and fallback.calls == 0


def test_refusal_record_cannot_be_forged_into_a_selected_signature():
    result = run(SignatureCascadeBackend(CountingBackend(), CountingBackend()))
    with pytest.raises(ValueError, match="selection"):
        replace(result, status="selected", selected_route="baseline")


def test_consumed_call_budget_changes_request_identity_for_the_same_input():
    cascade = SignatureCascadeBackend(CountingBackend(), CountingBackend(), max_calls=1)
    selected = run(cascade, values={"document": "csv"})
    exhausted = run(cascade, values={"document": "csv"})
    assert selected.status == "selected" and exhausted.status == "budget_exhausted"
    assert selected.request_hash != exhausted.request_hash
