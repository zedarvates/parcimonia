import pytest

from tiberium_ai.contracts import Task
from tiberium_ai.continuation import (
    ContinuationAction,
    ContinuationArbiter,
    ContinuationVerdict,
    QuotaMetrics,
    RouteKind,
    TaskDifficulty,
    TimeBudget,
    LocalCapacity,
)


def test_quota_metrics_validation():
    with pytest.raises(ValueError, match="remaining_percent must be a finite number"):
        QuotaMetrics(remaining_percent=-1.0, window_duration_mins=300)
    with pytest.raises(ValueError, match="remaining_percent must be a finite number"):
        QuotaMetrics(remaining_percent=101.0, window_duration_mins=300)
    with pytest.raises(ValueError, match="window_duration_mins must be a positive integer"):
        QuotaMetrics(remaining_percent=50.0, window_duration_mins=0)
    with pytest.raises(ValueError, match="tokens_remaining must be null or a nonnegative integer"):
        QuotaMetrics(remaining_percent=50.0, window_duration_mins=300, tokens_remaining=-10)

    valid = QuotaMetrics(
        remaining_percent=45.5,
        window_duration_mins=300,
        resets_in_seconds=1200.0,
        tokens_remaining=50000,
    )
    assert valid.remaining_percent == 45.5
    assert valid.window_duration_mins == 300


def test_arbiter_deterministic_zero_cost():
    arbiter = ContinuationArbiter()
    task = Task(task_id="t1", kind="test_run", inputs={"cmd": "pytest"})
    # Even under 0% quota, deterministic tasks run on local rule
    quota = QuotaMetrics(remaining_percent=0.0, window_duration_mins=300)
    verdict = arbiter.evaluate(task, quota, TaskDifficulty.DETERMINISTIC)

    assert verdict.action == ContinuationAction.CONTINUE
    assert verdict.target_route == RouteKind.RULE
    assert verdict.max_step_tokens == 0


def test_arbiter_critical_quota_freeze_reasoning():
    arbiter = ContinuationArbiter(critical_quota_percent=15.0)
    task = Task(task_id="t2", kind="refactor", inputs={})
    quota = QuotaMetrics(remaining_percent=10.0, window_duration_mins=300)
    verdict = arbiter.evaluate(task, quota, TaskDifficulty.REASONING)

    assert verdict.action == ContinuationAction.FREEZE_QUOTA
    assert verdict.target_route == RouteKind.NONE
    assert "Quota critical" in verdict.reason


def test_arbiter_critical_quota_downgrade_compact():
    arbiter = ContinuationArbiter(critical_quota_percent=15.0)
    task = Task(task_id="t3", kind="syntax_fix", inputs={})
    quota = QuotaMetrics(remaining_percent=10.0, window_duration_mins=300)
    verdict = arbiter.evaluate(task, quota, TaskDifficulty.COMPACT, allow_local_fallback=True)

    assert verdict.action == ContinuationAction.CONTINUE
    assert verdict.target_route == RouteKind.LOCAL_SMALL
    assert verdict.max_step_tokens == 1000


def test_zero_slots_block_compact_and_browser_not_rules():
    arbiter = ContinuationArbiter()
    quota = QuotaMetrics(remaining_percent=80.0, window_duration_mins=300)
    empty = LocalCapacity(concurrent_slots=0)
    task = Task(task_id="t12", kind="code", inputs={})

    rule = arbiter.evaluate(task, quota, TaskDifficulty.DETERMINISTIC, capacity=empty)
    assert rule.action == ContinuationAction.CONTINUE
    assert rule.target_route == RouteKind.RULE

    compact = arbiter.evaluate(task, quota, TaskDifficulty.COMPACT, capacity=empty)
    assert compact.action == ContinuationAction.REQUIRE_HUMAN

    browser = arbiter.evaluate(
        task, quota, TaskDifficulty.COMPACT, requires_browser=True, capacity=empty
    )
    assert browser.action == ContinuationAction.REQUIRE_HUMAN

    reasoning = arbiter.evaluate(task, quota, TaskDifficulty.REASONING, capacity=empty)
    assert reasoning.action == ContinuationAction.CONTINUE
    assert reasoning.target_route == RouteKind.FRONTIER


def test_low_vram_blocks_local_models():
    arbiter = ContinuationArbiter()
    quota = QuotaMetrics(remaining_percent=80.0, window_duration_mins=300)
    task = Task(task_id="t13", kind="code", inputs={})
    low = LocalCapacity(vram_free_mb=64.0, concurrent_slots=2, min_vram_for_local_mb=256.0)
    verdict = arbiter.evaluate(task, quota, TaskDifficulty.COMPACT, capacity=low)
    assert verdict.action == ContinuationAction.REQUIRE_HUMAN


def test_arbiter_critical_quota_compact_fallback_disabled():
    arbiter = ContinuationArbiter(critical_quota_percent=15.0)
    task = Task(task_id="t4", kind="syntax_fix", inputs={})
    quota = QuotaMetrics(remaining_percent=10.0, window_duration_mins=300)
    verdict = arbiter.evaluate(task, quota, TaskDifficulty.COMPACT, allow_local_fallback=False)

    assert verdict.action == ContinuationAction.FREEZE_QUOTA
    assert verdict.target_route == RouteKind.NONE


def test_arbiter_browser_delegation_to_webbrain():
    arbiter = ContinuationArbiter()
    task = Task(task_id="t5", kind="web_fill", inputs={"url": "https://example.com"})
    quota = QuotaMetrics(remaining_percent=50.0, window_duration_mins=300)
    verdict = arbiter.evaluate(task, quota, TaskDifficulty.COMPACT, requires_browser=True)

    assert verdict.action == ContinuationAction.CONTINUE
    assert verdict.target_route == RouteKind.WEBBRAIN_MCP
    assert "WebBrain" in verdict.reason


def test_arbiter_browser_critical_quota_freeze():
    arbiter = ContinuationArbiter(critical_quota_percent=15.0)
    task = Task(task_id="t6", kind="web_fill", inputs={})
    quota = QuotaMetrics(remaining_percent=5.0, window_duration_mins=300)
    verdict = arbiter.evaluate(task, quota, TaskDifficulty.COMPACT, requires_browser=True)

    assert verdict.action == ContinuationAction.FREEZE_QUOTA
    assert verdict.target_route == RouteKind.NONE


def test_arbiter_anti_loop_stall_detection():
    arbiter = ContinuationArbiter(max_consecutive_stalls=2)
    task = Task(task_id="t7", kind="code_fix", inputs={})
    quota = QuotaMetrics(remaining_percent=80.0, window_duration_mins=300)
    # 2 consecutive stalls without progress -> STOP and require human
    verdict = arbiter.evaluate(
        task, quota, TaskDifficulty.REASONING, consecutive_stalls=2
    )

    assert verdict.action == ContinuationAction.REQUIRE_HUMAN
    assert verdict.target_route == RouteKind.NONE
    assert "Desynchronization detected" in verdict.reason


def test_arbiter_high_risk_requires_human():
    arbiter = ContinuationArbiter()
    task = Task(task_id="t8", kind="deploy", inputs={}, risk_class="critical")
    quota = QuotaMetrics(remaining_percent=90.0, window_duration_mins=300)
    verdict = arbiter.evaluate(task, quota, TaskDifficulty.REASONING)

    assert verdict.action == ContinuationAction.REQUIRE_HUMAN
    assert verdict.target_route == RouteKind.NONE
    assert "requires human approval" in verdict.reason


def test_arbiter_nominal_reasoning():
    arbiter = ContinuationArbiter()
    task = Task(task_id="t9", kind="architecture", inputs={})
    quota = QuotaMetrics(remaining_percent=75.0, window_duration_mins=300)
    verdict = arbiter.evaluate(task, quota, TaskDifficulty.REASONING)

    assert verdict.action == ContinuationAction.CONTINUE
    assert verdict.target_route == RouteKind.FRONTIER
    assert verdict.max_step_tokens is None


def test_time_budget_zero_allows_deterministic_only():
    arbiter = ContinuationArbiter()
    task = Task(task_id="t10", kind="lint", inputs={})
    quota = QuotaMetrics(remaining_percent=80.0, window_duration_mins=300)
    budget = TimeBudget(remaining_seconds=0.0, interactive=True)

    rule = arbiter.evaluate(task, quota, TaskDifficulty.DETERMINISTIC, time_budget=budget)
    assert rule.action == ContinuationAction.CONTINUE
    assert rule.target_route == RouteKind.RULE

    compact = arbiter.evaluate(task, quota, TaskDifficulty.COMPACT, time_budget=budget)
    assert compact.action == ContinuationAction.REQUIRE_HUMAN


def test_short_interactive_window_downgrades_reasoning():
    arbiter = ContinuationArbiter()
    task = Task(task_id="t11", kind="architecture", inputs={})
    quota = QuotaMetrics(remaining_percent=80.0, window_duration_mins=300)
    budget = TimeBudget(remaining_seconds=20.0, interactive=True)
    verdict = arbiter.evaluate(task, quota, TaskDifficulty.REASONING, time_budget=budget)
    assert verdict.action == ContinuationAction.CONTINUE
    assert verdict.target_route == RouteKind.LOCAL_SMALL
    assert verdict.max_step_tokens == 1000
