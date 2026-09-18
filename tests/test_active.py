import pytest

from tiberium_ai.active import (
    ActivePolicy,
    ActiveRouter,
    Authorization,
    KillSwitch,
    Sandbox,
)
from tiberium_ai.contracts import Task
from tiberium_ai.escalation import Budget
from tiberium_ai.measurement import Environment
from tiberium_ai.observations import replay_observation
from tiberium_ai.registry import RouteRegistry
from tiberium_ai.verification import VerifierRegistry, exact_match_verifier


def clock_from(*ticks):
    return iter(ticks).__next__


def build(
    *,
    rule_output=3,
    rule_fails=False,
    risk_classes=("low",),
    budget=None,
    sandbox_routes=("baseline", "rule"),
    auto_risk_classes=("low",),
):
    verifiers = VerifierRegistry()
    verifiers.register("math/exact", "1", exact_match_verifier({"total": 3}))
    constraints = {
        "risk_classes": list(risk_classes),
        "evidence_levels": ["normal"],
        "localities": ["any"],
    }
    manifests = {
        "routes": [
            {
                "route_id": route_id,
                "capability_ids": ["math"],
                "estimated_cost": cost,
                "estimated_latency_ms": latency,
                "confidence": 0.99,
                "constraints": constraints,
                "verifier": {"verifier_id": "math/exact", "verifier_version": "1"},
            }
            for route_id, cost, latency in (("rule", 0.01, 5.0), ("baseline", 0.5, 100.0))
        ]
    }
    registry = RouteRegistry.from_manifest(
        {"schema_version": 1, "registry_version": "active/1", "routes": manifests["routes"]},
        verifiers=verifiers,
    )

    def rule():
        if rule_fails:
            raise ValueError("route failed")
        return {"total": rule_output}

    available = {"rule": rule, "baseline": lambda: {"total": 3}}
    sandbox = Sandbox({route_id: available[route_id] for route_id in sandbox_routes})
    router = ActiveRouter(
        policy=ActivePolicy(
            budget=budget
            or Budget(max_cost=1.0, max_escalations=1, max_attempts=3, max_latency_ms=None),
            baseline_route_id="baseline",
            auto_risk_classes=auto_risk_classes,
        ),
        sandbox=sandbox,
        kill_switch=KillSwitch(),
        registry=registry,
        verifiers=verifiers,
        environment=Environment("active-machine", {"python": "3.14.0"}),
        clock=clock_from(0.0, 0.001, 0.002, 0.003, 0.004, 0.005, 0.006, 0.007),
        cost_unit="unit/task",
    )
    return router


def test_active_mode_requires_policy_budgets_and_a_kill_switch():
    with pytest.raises(TypeError):
        ActivePolicy()
    with pytest.raises(ValueError, match="budget"):
        ActivePolicy(budget="none", baseline_route_id="baseline")
    with pytest.raises(ValueError, match="kill_switch"):
        ActiveRouter(
            policy=ActivePolicy(
                budget=Budget(max_cost=1.0, max_escalations=0, max_attempts=1),
                baseline_route_id="baseline",
            ),
            sandbox=Sandbox({"rule": lambda: None}),
            kill_switch=None,
            registry=None,
            verifiers=None,
            environment=Environment("m", {}),
            clock=clock_from(0.0, 0.0),
            cost_unit="unit/task",
        )


def test_the_kill_switch_blocks_execution_and_can_be_released():
    router = build()
    router.kill_switch.engage("operator stop")
    blocked = router.execute(Task("t1", "math", {}), idempotency_key="k1")
    assert blocked.status == "refused"
    assert blocked.reason_code == "kill_switch_engaged"
    with pytest.raises(ValueError):
        router.kill_switch.release("")
    router.kill_switch.release("reviewed")
    assert router.execute(Task("t1", "math", {}), idempotency_key="k2").status == "executed"


def test_an_idempotency_key_is_required_and_single_use():
    router = build()
    with pytest.raises(ValueError, match="idempotency"):
        router.execute(Task("t1", "math", {}), idempotency_key="")
    assert router.execute(Task("t1", "math", {}), idempotency_key="k1").status == "executed"
    reused = router.execute(Task("t1", "math", {}), idempotency_key="k1")
    assert reused.status == "refused"
    assert reused.reason_code == "idempotency_key_reused"


def test_a_supervised_risk_class_requires_a_matching_authorization():
    router = build(auto_risk_classes=())
    task = Task("t1", "math", {})
    refused = router.execute(task, idempotency_key="k1")
    assert refused.status == "refused"
    assert refused.reason_code == "approval_required"
    mismatched = router.execute(
        task,
        idempotency_key="k2",
        authorization=Authorization("a1", "other-task", "rule", "operator"),
    )
    assert mismatched.reason_code == "authorization_mismatch"
    approved = router.execute(
        task,
        idempotency_key="k3",
        authorization=Authorization("a2", "t1", "rule", "operator"),
    )
    assert approved.status == "executed"
    assert approved.authorization_id == "a2"
    consumed = router.execute(
        task,
        idempotency_key="k4",
        authorization=Authorization("a2", "t1", "rule", "operator"),
    )
    assert consumed.reason_code == "authorization_consumed"


def test_a_low_risk_task_runs_without_an_authorization_and_leaves_an_audit_trail():
    router = build()
    result = router.execute(Task("t1", "math", {}), idempotency_key="k1")
    assert result.status == "executed"
    assert result.route_id == "rule"
    assert result.attempts == 1
    assert result.escalations == 0
    assert result.authorization_id is None
    assert replay_observation(result.observation).selected_route_id == "rule"
    assert result.measurements[0]["data_origin"] == "measured"
    audit = result.to_audit_record()
    assert audit["idempotency_key"] == "k1"
    assert audit["routes"] == ["rule"]
    assert audit["observation"] == result.observation


def test_a_rejected_result_escalates_inside_the_budget():
    router = build(rule_output=4)
    result = router.execute(Task("t1", "math", {}), idempotency_key="k1")
    assert result.status == "executed"
    assert result.route_id == "baseline"
    assert result.attempts == 2
    assert result.escalations == 1
    assert [measurement["route_id"] for measurement in result.measurements] == [
        "rule",
        "baseline",
    ]


def test_the_attempt_budget_stops_a_rejected_result():
    router = build(
        rule_output=4,
        budget=Budget(max_cost=1.0, max_escalations=1, max_attempts=1, max_latency_ms=None),
    )
    result = router.execute(Task("t1", "math", {}), idempotency_key="k1")
    assert result.status == "failed"
    assert result.reason_code == "attempt_budget_exhausted"
    assert result.attempts == 1


def test_a_route_outside_the_sandbox_is_refused():
    router = build(sandbox_routes=("baseline",))
    result = router.execute(Task("t1", "math", {}), idempotency_key="k1")
    assert result.status == "refused"
    assert result.reason_code == "route_not_in_sandbox"
    assert result.measurements == ()


def test_a_task_without_an_eligible_route_abstains_without_executing():
    router = build()
    result = router.execute(
        Task("t1", "math", {}, evidence_level="strict"), idempotency_key="k1"
    )
    assert result.status == "abstained"
    assert result.reason_code == "no_eligible_route"
    assert result.measurements == ()


def test_cancellation_stops_before_the_next_attempt():
    router = build(rule_output=4)

    def cancelling_rule():
        router.cancel("operator cancelled")
        return {"total": 4}

    router.sandbox.routes["rule"] = cancelling_rule
    result = router.execute(Task("t1", "math", {}), idempotency_key="k1")
    assert result.status == "cancelled"
    assert result.reason_code == "cancelled"
    assert result.attempts == 1
    assert len(result.measurements) == 1


def test_the_observation_records_the_shadow_proposal_with_baseline_evidence_when_run():
    router = build(rule_output=4)
    result = router.execute(Task("t1", "math", {}), idempotency_key="k1")
    assert result.observation["baseline_evidence"] is not None
    assert result.observation["proposal_evidence"]["route_id"] == "rule"
