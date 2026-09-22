import pytest

from tiberium_ai.decision_clock import (
    DecisionBudget,
    DecisionTiming,
    TimingStatus,
    assess_decision_timing,
)


def test_budget_rejects_negative_values():
    with pytest.raises(ValueError, match="budget_ms"):
        DecisionBudget(-1.0)
    with pytest.raises(ValueError, match="max_state_age_ms"):
        DecisionBudget(10.0, -1.0)
    with pytest.raises(ValueError, match="fallback_route_id"):
        DecisionBudget(10.0, fallback_route_id="  ")
    with pytest.raises(ValueError, match="elapsed_ms"):
        DecisionTiming(-0.5)


def test_within_budget_when_inside_the_deadline():
    verdict = assess_decision_timing(
        DecisionBudget(250.0, fallback_route_id="route.rule"),
        DecisionTiming(elapsed_ms=210.0, state_age_ms=5.0),
    )
    assert verdict.status is TimingStatus.WITHIN_BUDGET
    assert verdict.reason_code == "within_budget"
    assert verdict.usable is True
    assert verdict.fallback_required is False
    assert verdict.remaining_ms == 40.0


def test_a_missed_deadline_reports_a_signed_remainder():
    verdict = assess_decision_timing(
        DecisionBudget(250.0, fallback_route_id="route.rule"),
        DecisionTiming(elapsed_ms=260.0),
    )
    assert verdict.status is TimingStatus.DEADLINE_MISSED
    assert verdict.reason_code == "elapsed_exceeds_budget"
    assert verdict.remaining_ms == -10.0
    assert verdict.fallback_required is True
    assert verdict.fallback_route_id == "route.rule"


def test_zero_budget_only_admits_an_instant_answer():
    budget = DecisionBudget(0.0)
    assert assess_decision_timing(budget, DecisionTiming(elapsed_ms=0.0)).usable is True
    assert assess_decision_timing(budget, DecisionTiming(elapsed_ms=0.1)).usable is False


def test_stale_state_is_judged_before_the_clock():
    verdict = assess_decision_timing(
        DecisionBudget(250.0, max_state_age_ms=1000.0),
        DecisionTiming(elapsed_ms=1.0, state_age_ms=1500.0),
    )
    assert verdict.status is TimingStatus.STATE_STALE
    assert verdict.reason_code == "state_age_exceeds_bound"
    assert verdict.usable is False


def test_an_unobserved_age_fails_closed_against_a_declared_bound():
    verdict = assess_decision_timing(
        DecisionBudget(250.0, max_state_age_ms=1000.0),
        DecisionTiming(elapsed_ms=1.0),
    )
    assert verdict.status is TimingStatus.STATE_STALE
    assert verdict.reason_code == "state_age_unknown"


def test_state_age_is_ignored_when_no_bound_is_declared():
    verdict = assess_decision_timing(
        DecisionBudget(250.0),
        DecisionTiming(elapsed_ms=1.0, state_age_ms=99_000.0),
    )
    assert verdict.usable is True
    assert verdict.reason_code == "within_budget"


def test_assessment_requires_the_declared_types():
    with pytest.raises(TypeError, match="budget must be"):
        assess_decision_timing(object(), DecisionTiming(elapsed_ms=1.0))
    with pytest.raises(TypeError, match="timing must be"):
        assess_decision_timing(DecisionBudget(1.0), object())


def test_a_within_budget_verdict_cannot_carry_another_reason():
    from tiberium_ai.decision_clock import TimingVerdict

    with pytest.raises(ValueError, match="within-budget code"):
        TimingVerdict(
            status=TimingStatus.WITHIN_BUDGET,
            reason_code="elapsed_exceeds_budget",
            elapsed_ms=1.0,
            remaining_ms=1.0,
            state_age_ms=None,
            fallback_route_id=None,
        )


def test_the_record_is_flat_and_reportable():
    verdict = assess_decision_timing(
        DecisionBudget(250.0, 1000.0, "route.rule"),
        DecisionTiming(200.0, 10.0),
    )
    record = verdict.to_record()
    assert record["status"] == "within_budget"
    assert record["fallback_route_id"] == "route.rule"
    assert record["state_age_ms"] == 10.0
