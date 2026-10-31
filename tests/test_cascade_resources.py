from dataclasses import replace

import pytest

from tiberium_ai.cascade_resources import CascadeResourceControl, CostReceipt, StageEstimate
from tiberium_ai.decision_clock import DecisionBudget
from tiberium_ai.escalation import Budget
from tiberium_ai.measurement import Environment
from tiberium_ai.reflex import ReflexKind
from tiberium_ai.signature_cascade import SignatureCascadeBackend
from tiberium_ai.task_context import ContextContract, ContextField
from tiberium_ai.task_signature import DeclaredItem, SignatureSchema

SCHEMA = SignatureSchema("resource-fixture", (DeclaredItem("extract"), DeclaredItem("verify")))
CONTRACT = ContextContract("extract.fixture", "1", "extract", (ContextField("document", "Contents"),), ("document",))


class Clock:
    def __init__(self): self.value = 0.0
    def __call__(self): return self.value


class Predictor:
    latin_only = False
    def __init__(self, clock, probability=.95, duration_ms=4):
        self.clock, self.probability, self.duration_ms, self.calls = clock, probability, duration_ms, 0
    def evaluate(self, state, questions):
        self.calls += 1
        self.clock.value += self.duration_ms / 1000
        return {q.name: {"choice": "extract", "confidence": None,
            "probabilities": {"extract": self.probability, "verify": 1-self.probability}} for q in questions}


def control(clock, **changes):
    values = dict(budget=Budget(3, 1, 2, max_latency_ms=100), deadline=DecisionBudget(100),
        baseline=StageEstimate(1, 5), fallback=StageEstimate(1, 5), cost_unit="fixture-unit",
        environment=Environment("synthetic-clock-fixture", {"clock": "injected"}), clock=clock,
        observe_cost=lambda role, backend: CostReceipt(1, "fixture-unit", "fixture-observer"),
        now=lambda: "2026-10-07T00:00:00+00:00")
    return CascadeResourceControl(**{**values, **changes})


def invoke(resource, baseline_probability=.95, baseline_ms=4, fallback_ms=4):
    clock = resource.clock
    baseline, fallback = Predictor(clock, baseline_probability, baseline_ms), Predictor(clock, .95, fallback_ms)
    cascade = SignatureCascadeBackend(baseline, fallback)
    result = cascade.propose_signature("extraire le document", schema=SCHEMA, contract=CONTRACT,
        baseline_identity=("fixture.baseline", "1"), fallback_identity=("fixture.fallback", "1"),
        context_revision="fixture-snapshot", values={"document": "content"}, resource_control=resource)
    return result, baseline, fallback


def test_confident_baseline_has_a_canonical_measurement_and_distinct_estimate():
    clock = Clock()
    result, baseline, fallback = invoke(control(clock))
    record = result.to_record()
    assert result.status == "selected" and result.selected_route == "baseline"
    assert baseline.calls == 1 and fallback.calls == 0
    measurement = record["resource_trace"]["measurements"][0]
    assert measurement["schema_version"] == 2 and measurement["latency_ms"] == 4
    assert measurement["cost"] == 1 and record["measured_cost"] == 1
    assert record["resource_trace"]["policy"]["estimates"]["baseline"]["latency_ms"] == 5
    assert record["measured_latency_ms"] == 4 and not record["auto_act_allowed"]


def test_uncertain_baseline_uses_native_escalation_only_with_known_remaining_resources():
    result, baseline, fallback = invoke(control(Clock()), baseline_probability=.6)
    assert result.selected_route == "fallback" and baseline.calls == fallback.calls == 1
    assert result.to_record()["measured_cost"] == 2
    decisions = result.resource_trace["escalation_decisions"]
    assert decisions[0]["state"] == "ESCALATE" and decisions[0]["reason_code"] == "abstained_escalate"
    assert decisions[0]["next_route_id"] == "fixture.fallback"


@pytest.mark.parametrize("estimate,reason", [(StageEstimate(None, 5), "unknown_cost"), (StageEstimate(1, None), "unknown_latency"),
    (StageEstimate(5, 5), "cost_budget_exhausted"), (StageEstimate(1, 200), "latency_budget_exhausted")])
def test_baseline_preflight_blocks_unpriced_or_unbudgeted_calls(estimate, reason):
    result, baseline, fallback = invoke(control(Clock(), baseline=estimate))
    assert result.reason_code == reason and result.backend_calls == baseline.calls == fallback.calls == 0


@pytest.mark.parametrize("estimate,reason", [(StageEstimate(None, 5), "abstained_no_verdict"),
    (StageEstimate(5, 5), "abstained_no_verdict"), (StageEstimate(1, 200), "abstained_no_verdict")])
def test_fallback_preflight_does_not_run_an_unaffordable_model(estimate, reason):
    result, baseline, fallback = invoke(control(Clock(), fallback=estimate), baseline_probability=.6)
    assert result.reason_code == reason and result.signature is None
    assert baseline.calls == 1 and fallback.calls == 0


def test_cost_limit_reached_by_actual_receipt_discards_even_a_confident_answer():
    observer = lambda *args: CostReceipt(4, "fixture-unit", "fixture-observer")
    result, baseline, fallback = invoke(control(Clock(), observe_cost=observer))
    assert result.reason_code == "cost_budget_exhausted" and result.signature is None
    assert baseline.calls == 1 and fallback.calls == 0 and result.to_record()["measured_cost"] == 4


def test_missing_actual_cost_is_never_filled_with_the_estimate_or_zero():
    result, baseline, fallback = invoke(control(Clock(), observe_cost=None), baseline_probability=.6)
    assert result.reason_code == "unknown_observed_cost" and result.signature is None
    assert result.to_record()["measured_cost"] is None
    assert result.resource_trace["measurements"][0]["cost"] is None
    assert baseline.calls == 1 and fallback.calls == 0
    assert result.status == "abstained"


def test_late_confident_baseline_is_unusable_and_does_not_escalate():
    result, baseline, fallback = invoke(control(Clock(), deadline=DecisionBudget(5)), baseline_ms=6)
    assert result.reason_code == "elapsed_exceeds_budget" and result.signature is None
    assert baseline.calls == 1 and fallback.calls == 0
    assert result.resource_trace["timing"]["remaining_ms"] == -1


def test_fallback_is_refused_when_its_estimate_exceeds_remaining_time():
    result, baseline, fallback = invoke(control(Clock(), deadline=DecisionBudget(8)), baseline_probability=.6)
    assert result.reason_code == "latency_budget_exhausted" and fallback.calls == 0 and baseline.calls == 1


def test_late_fallback_is_measured_but_not_selected():
    result, baseline, fallback = invoke(control(Clock(), deadline=DecisionBudget(10)), baseline_probability=.6, fallback_ms=10)
    assert result.reason_code == "elapsed_exceeds_budget" and result.selected_route is None
    assert baseline.calls == fallback.calls == 1 and result.to_record()["measured_latency_ms"] == 14


def test_unknown_snapshot_age_blocks_before_call_and_aging_snapshot_discards_returned_answer():
    result, baseline, fallback = invoke(control(Clock(), deadline=DecisionBudget(100, max_state_age_ms=5)))
    assert result.status == "collect_context" and result.reason_code == "state_age_unknown" and baseline.calls == 0
    result, baseline, fallback = invoke(control(Clock(), deadline=DecisionBudget(100, max_state_age_ms=5), state_age_ms=2))
    assert result.status == "collect_context" and result.reason_code == "state_age_exceeds_bound" and baseline.calls == 1


def test_previous_spend_and_attempts_are_not_reset_to_make_a_fallback_affordable():
    result, baseline, fallback = invoke(control(Clock(), spent_cost_before=2), baseline_probability=.6)
    assert baseline.calls == 1 and fallback.calls == 0
    assert result.resource_trace["spent_cost_total"] == 3
    result, baseline, fallback = invoke(control(Clock(), attempts_before=2, escalations_before=1))
    assert result.reason_code == "attempt_budget_exhausted" and baseline.calls == 0


def test_wrong_cost_unit_or_observer_error_does_not_echo_private_messages_or_retry():
    def broken(*args): raise ValueError("PRIVATE COST CREDENTIAL")
    for observer in (broken, lambda *args: CostReceipt(1, "another-unit", "fixture")):
        result, baseline, fallback = invoke(control(Clock(), observe_cost=observer))
        assert result.status == "backend_error" and baseline.calls == 1 and fallback.calls == 0
        assert "PRIVATE" not in str(result.to_record())
        assert result.to_record()["measured_cost"] is None


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -1])
def test_invalid_cost_values_are_rejected(value):
    with pytest.raises(ValueError): CostReceipt(value, "unit", "observer")
    with pytest.raises(ValueError): StageEstimate(value, 1)


def test_missing_context_skips_all_predictors_and_measurement_records():
    clock = Clock()
    baseline, fallback = Predictor(clock), Predictor(clock)
    cascade = SignatureCascadeBackend(baseline, fallback)
    result = cascade.propose_signature("extraire le document", schema=SCHEMA, contract=CONTRACT,
        baseline_identity=("fixture.baseline", "1"), fallback_identity=("fixture.fallback", "1"),
        context_revision="fixture", context_complete=True, resource_control=control(clock))
    assert result.status == "collect_context" and baseline.calls == fallback.calls == 0
    assert result.resource_trace["measurements"] == []
    assert result.to_record()["measured_latency_ms"] is None


def test_invalid_clock_between_preflight_and_run_does_not_count_a_predictor_call():
    class UnstableClock(Clock):
        def __init__(self): super().__init__(); self.reads = 0
        def __call__(self):
            self.reads += 1
            return float("nan") if self.reads == 3 else self.value
    result, baseline, fallback = invoke(control(UnstableClock()))
    assert result.status == "backend_error" and result.backend_calls == baseline.calls == fallback.calls == 0
    assert result.to_record()["measured_latency_ms"] is None


def test_backwards_clock_after_a_run_cannot_leave_a_confident_selected_signature():
    class BackwardsClock(Clock):
        def __init__(self): super().__init__(); self.reads = 0
        def __call__(self):
            self.reads += 1
            return self.value - .01 if self.reads == 4 else self.value
    result, baseline, fallback = invoke(control(BackwardsClock()))
    assert result.status == "backend_error" and result.signature is None
    assert baseline.calls == 1 and fallback.calls == 0
    assert result.to_record()["measured_cost"] is None


def test_failed_predictor_measurement_keeps_error_type_and_paid_cost_without_a_retry():
    clock = Clock()
    baseline, fallback = Predictor(clock), Predictor(clock)
    def fail(state, questions):
        baseline.calls += 1
        clock.value += .004
        raise ValueError("PRIVATE PROVIDER PAYLOAD")
    baseline.evaluate = fail
    cascade = SignatureCascadeBackend(baseline, fallback)
    result = cascade.propose_signature("extraire", schema=SCHEMA, contract=CONTRACT,
        baseline_identity=("fixture.baseline", "1"), fallback_identity=("fixture.fallback", "1"),
        context_revision="fixture", values={"document": "csv"}, resource_control=control(clock))
    assert result.status == "backend_error" and baseline.calls == 1 and fallback.calls == 0
    measurement = result.resource_trace["measurements"][0]
    assert measurement["outcome"] == {"ok": False, "error_type": "ValueError"}
    assert measurement["cost"] == 1 and "PRIVATE" not in str(result.to_record())


def test_resource_policy_and_prior_spend_are_part_of_the_request_identity():
    a, _, _ = invoke(control(Clock()))
    b, _, _ = invoke(control(Clock(), spent_cost_before=.5))
    assert a.request_hash != b.request_hash


def test_zero_escalation_budget_is_enforced_without_a_fallback_call():
    result, baseline, fallback = invoke(control(Clock(), budget=Budget(3, 0, 2, 100)), baseline_probability=.6)
    assert baseline.calls == 1 and fallback.calls == 0 and result.signature is None
    assert result.resource_trace["escalation_decisions"][0]["state"] == "ABSTAIN"
    assert result.resource_trace["policy"]["budget"]["max_escalations"] == 0


def test_monotonic_clock_can_have_a_negative_reference_point():
    clock = Clock()
    clock.value = -10.0
    result, baseline, fallback = invoke(control(clock))
    assert result.status == "selected" and baseline.calls == 1 and fallback.calls == 0
    assert result.to_record()["measured_latency_ms"] == pytest.approx(4)


def test_environment_and_policy_records_are_snapshots_when_observer_changes_shared_metadata():
    clock = Clock()
    environment = Environment("fixture", {"runtime": "before"})
    def observer(*args):
        environment.runtime_versions["runtime"] = "after"
        return CostReceipt(1, "fixture-unit", "fixture-observer")
    result, _, _ = invoke(control(clock, environment=environment, observe_cost=observer))
    assert result.resource_trace["policy"]["environment"]["runtime_versions"] == {"runtime": "before"}
    assert result.resource_trace["measurements"][0]["environment"]["runtime_versions"] == {"runtime": "before"}
