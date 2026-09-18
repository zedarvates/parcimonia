import pytest

from tiberium_ai.escalation import (
    Budget,
    EscalationPolicy,
    EscalationState,
)


def budget(**overrides):
    values = {
        "max_cost": 1.0,
        "max_escalations": 1,
        "max_attempts": 3,
        "max_latency_ms": 1000.0,
    }
    values.update(overrides)
    return Budget(**values)


BASE = dict(
    run_ok=True,
    verdict=True,
    attempts=1,
    escalations=0,
    spent_cost=0.0,
    spent_latency_ms=0.0,
    retry_safe=False,
    next_route_id=None,
    next_estimated_cost=None,
    next_estimated_latency_ms=None,
    task_specified=True,
)


def decide(**overrides):
    arguments = dict(BASE)
    arguments.update(overrides)
    return EscalationPolicy(budget()).decide(**arguments)


@pytest.mark.parametrize("overrides,state,reason", [
    ({}, EscalationState.ACCEPT, "verified_accept"),
    (
        {"verdict": False, "next_route_id": "llm", "next_estimated_cost": 0.5,
         "next_estimated_latency_ms": 100.0},
        EscalationState.ESCALATE,
        "rejected_escalate",
    ),
    (
        {"verdict": False},
        EscalationState.FAIL_HARD,
        "rejected_no_alternative",
    ),
    (
        {"verdict": False, "attempts": 2, "escalations": 1, "next_route_id": "llm",
         "next_estimated_cost": 0.5, "next_estimated_latency_ms": 100.0},
        EscalationState.FAIL_HARD,
        "rejected_escalation_budget_exhausted",
    ),
    (
        {"verdict": False, "spent_cost": 0.8, "next_route_id": "llm",
         "next_estimated_cost": 0.5, "next_estimated_latency_ms": 100.0},
        EscalationState.FAIL_HARD,
        "rejected_cost_budget_exhausted",
    ),
    (
        {"verdict": False, "next_route_id": "llm"},
        EscalationState.FAIL_HARD,
        "rejected_unknown_cost",
    ),
    (
        {"verdict": False, "spent_latency_ms": 900.0, "next_route_id": "llm",
         "next_estimated_cost": 0.5, "next_estimated_latency_ms": 200.0},
        EscalationState.FAIL_HARD,
        "rejected_latency_budget_exhausted",
    ),
    (
        {"verdict": False, "next_route_id": "llm", "next_estimated_cost": 0.5},
        EscalationState.FAIL_HARD,
        "rejected_unknown_latency",
    ),
    (
        {"run_ok": False, "verdict": None, "retry_safe": True},
        EscalationState.RETRY,
        "route_failed_retry",
    ),
    (
        {"run_ok": False, "verdict": None, "next_route_id": "llm",
         "next_estimated_cost": 0.5, "next_estimated_latency_ms": 100.0},
        EscalationState.ESCALATE,
        "route_failed_escalate",
    ),
    (
        {"run_ok": False, "verdict": None},
        EscalationState.ABSTAIN,
        "route_failed_abstain",
    ),
    (
        {"run_ok": True, "verdict": None, "next_route_id": "llm",
         "next_estimated_cost": 0.5, "next_estimated_latency_ms": 100.0},
        EscalationState.ESCALATE,
        "abstained_escalate",
    ),
    (
        {"run_ok": True, "verdict": None, "retry_safe": True},
        EscalationState.RETRY,
        "abstained_retry",
    ),
    (
        {"run_ok": True, "verdict": None},
        EscalationState.ABSTAIN,
        "abstained_no_verdict",
    ),
    (
        {"attempts": 3, "verdict": None, "next_route_id": "llm",
         "next_estimated_cost": 0.5, "next_estimated_latency_ms": 100.0},
        EscalationState.FAIL_HARD,
        "attempt_budget_exhausted",
    ),
    (
        {"attempts": 3},
        EscalationState.ACCEPT,
        "verified_accept",
    ),
    (
        {"task_specified": False},
        EscalationState.FAIL_HARD,
        "ill_specified_task",
    ),
])
def test_escalation_table(overrides, state, reason):
    decision = decide(**overrides)
    assert decision.state is state
    assert decision.reason_code == reason
    assert decision.detail


def test_escalation_names_the_next_route():
    decision = decide(
        verdict=False,
        next_route_id="llm",
        next_estimated_cost=0.5,
        next_estimated_latency_ms=100.0,
    )
    assert decision.next_route_id == "llm"


def test_decisions_are_deterministic():
    arguments = dict(
        verdict=False,
        next_route_id="llm",
        next_estimated_cost=0.5,
        next_estimated_latency_ms=100.0,
    )
    assert decide(**arguments) == decide(**arguments)


def test_unknown_cost_never_escalates_even_with_room_in_the_budget():
    decision = decide(
        verdict=False,
        spent_cost=0.0,
        next_route_id="llm",
        next_estimated_cost=None,
        next_estimated_latency_ms=10.0,
    )
    assert decision.state is EscalationState.FAIL_HARD


@pytest.mark.parametrize("overrides", [
    {"attempts": 0},
    {"escalations": -1},
    {"attempts": 1, "escalations": 1},
    {"spent_cost": -1},
    {"spent_cost": float("nan")},
    {"spent_latency_ms": -1},
    {"verdict": "true"},
    {"run_ok": False, "verdict": True},
    {"run_ok": True, "verdict": False, "next_estimated_cost": -1},
])
def test_invalid_inputs_are_rejected(overrides):
    with pytest.raises(ValueError):
        decide(**overrides)


@pytest.mark.parametrize("overrides", [
    {"max_cost": -1},
    {"max_cost": float("inf")},
    {"max_cost": True},
    {"max_escalations": -1},
    {"max_attempts": 0},
    {"max_latency_ms": -1},
])
def test_invalid_budgets_are_rejected(overrides):
    with pytest.raises(ValueError):
        budget(**overrides)


def test_latency_budget_is_optional():
    policy = EscalationPolicy(budget(max_latency_ms=None))
    decision = policy.decide(**{**BASE, "verdict": False, "next_route_id": "llm",
                                "next_estimated_cost": 0.5})
    assert decision.state is EscalationState.ESCALATE


def test_escalate_requires_a_next_route():
    from tiberium_ai.escalation import EscalationDecision

    with pytest.raises(ValueError, match="next_route_id"):
        EscalationDecision(
            state=EscalationState.ESCALATE, reason_code="x", detail="x"
        )


def test_accept_cannot_carry_a_next_route():
    from tiberium_ai.escalation import EscalationDecision

    with pytest.raises(ValueError, match="next_route_id"):
        EscalationDecision(
            state=EscalationState.ACCEPT,
            reason_code="verified_accept",
            next_route_id="llm",
            detail="x",
        )
