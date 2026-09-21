import pytest

from tiberium_ai.continuation import LocalCapacity, QuotaMetrics, TaskDifficulty
from tiberium_ai.director import AstralDirector, DirectorMode
from tiberium_ai.kanban import KanbanStatus, KanbanTask, parse_kanban_markdown
from tiberium_ai.pipeline import ContinuityPipeline, PipelineContext, PipelineHalt
from tiberium_ai.surface import (
    CapabilityKind,
    CapabilitySpec,
    ComplianceVerdict,
    ProjectSurface,
    RuntimeAction,
    RuntimeState,
    TaskExpectation,
    UsageEvent,
    UsageStatus,
    compare_usage,
    expectation_from_kanban_task,
    ingest_turn_report,
    plan_runtime,
)


def _surface():
    return ProjectSurface(
        project_id="parcimonia",
        capabilities=(
            CapabilitySpec("route:rule", CapabilityKind.RULE),
            CapabilitySpec("route:knn", CapabilityKind.KNN, keep_warm=True),
            CapabilitySpec("route:nano", CapabilityKind.NANO, keep_warm=True, startup_cost=8.0),
            CapabilitySpec("route:micro", CapabilityKind.MICRO),
            CapabilitySpec("route:frontier", CapabilityKind.SERVER, idle_cost_per_min=2.0),
            CapabilitySpec("mcp:webbrain", CapabilityKind.MCP, idle_cost_per_min=0.5),
            CapabilitySpec("tool:schema_emit", CapabilityKind.TOOL),
            CapabilitySpec("skill:verification", CapabilityKind.SKILL),
            CapabilitySpec("plugin:director", CapabilityKind.PLUGIN),
            CapabilitySpec("tool:local_asset_bake", CapabilityKind.TOOL, idle_cost_per_min=1.0),
        ),
    )


def test_missing_required_is_drift_not_compliance():
    expectation = TaskExpectation(
        task_id="t1",
        required=("route:rule", "skill:verification"),
        allowed=("route:knn",),
    )
    report = compare_usage(_surface(), expectation, (UsageEvent("route:rule"),))
    assert report.verdict is ComplianceVerdict.DRIFT
    assert report.missing() == ("skill:verification",)


def test_empty_observation_is_not_compliance_when_required():
    expectation = TaskExpectation(task_id="t1", required=("route:rule",))
    report = compare_usage(_surface(), expectation, ())
    assert report.verdict is ComplianceVerdict.DRIFT
    assert report.used == ()


def test_unexpected_and_forbidden_are_violations():
    expectation = TaskExpectation(
        task_id="t1",
        required=("route:rule",),
        allowed=("route:knn",),
        forbidden=("tool:local_asset_bake",),
    )
    report = compare_usage(
        _surface(),
        expectation,
        (
            UsageEvent("route:rule"),
            UsageEvent("mcp:webbrain"),
            UsageEvent("tool:local_asset_bake"),
        ),
    )
    assert report.verdict is ComplianceVerdict.VIOLATION
    assert "mcp:webbrain" in report.unexpected()
    assert "tool:local_asset_bake" in report.forbidden_used()


def test_compliant_end_of_turn_uses_expected_tools():
    expectation = TaskExpectation(
        task_id="t1",
        required=("route:rule", "skill:verification"),
        allowed=("route:knn", "tool:schema_emit"),
    )
    report = compare_usage(
        _surface(),
        expectation,
        (UsageEvent("route:rule"), UsageEvent("skill:verification"), UsageEvent("route:knn")),
    )
    assert report.verdict is ComplianceVerdict.COMPLIANT
    assert report.forbidden_used() == ()
    assert report.missing() == ()


def test_runtime_plan_starts_required_and_stops_unused_costly():
    expectation = TaskExpectation(
        task_id="t1",
        required=("mcp:webbrain",),
        allowed=("route:rule",),
        forbidden=("route:frontier",),
    )
    current = {
        "mcp:webbrain": RuntimeState.STOPPED,
        "route:frontier": RuntimeState.RUNNING,
        "tool:local_asset_bake": RuntimeState.RUNNING,
        "route:knn": RuntimeState.RUNNING,
        "route:rule": RuntimeState.STOPPED,
    }
    plan = plan_runtime(_surface(), expectation, current)
    actions = plan.actions()
    assert plan.executed is False
    assert all(item.shadow for item in plan.items)
    assert actions["mcp:webbrain"] is RuntimeAction.START
    assert actions["route:frontier"] is RuntimeAction.STOP
    assert actions["tool:local_asset_bake"] is RuntimeAction.STOP
    assert actions["route:knn"] is RuntimeAction.IDLE
    assert actions["route:rule"] is RuntimeAction.KEEP


def test_runtime_plan_does_not_start_forbidden_even_if_observed():
    expectation = TaskExpectation(
        task_id="t1",
        required=("route:rule",),
        forbidden=("mcp:webbrain",),
    )
    plan = plan_runtime(
        _surface(),
        expectation,
        {"mcp:webbrain": RuntimeState.STOPPED, "route:rule": RuntimeState.RUNNING},
        observed=(UsageEvent("mcp:webbrain"), UsageEvent("route:rule")),
    )
    assert plan.actions()["mcp:webbrain"] is RuntimeAction.KEEP
    report = compare_usage(
        _surface(),
        expectation,
        (UsageEvent("mcp:webbrain"), UsageEvent("route:rule")),
    )
    assert report.verdict is ComplianceVerdict.VIOLATION


def test_kanban_webbrain_task_requires_mcp():
    task = KanbanTask(
        task_id="TASK-WEB",
        title="Read the pricing table",
        status=KanbanStatus.IN_PROGRESS,
        difficulty=TaskDifficulty.COMPACT,
        requires_browser=True,
    )
    expectation = expectation_from_kanban_task(task)
    assert "mcp:webbrain" in expectation.required
    assert "route:frontier" not in expectation.forbidden


def test_pipeline_attaches_usage_report_and_shadow_plan():
    director = AstralDirector(mode=DirectorMode.AUTO)
    pipeline = ContinuityPipeline(director=director)
    board = parse_kanban_markdown(
        """# Board
## En cours
- [ ] TASK-056 [P2] [difficulty: compact] [tool: webbrain]
  - title: Read the pricing table
"""
    )
    trace = pipeline.run_once(
        board,
        PipelineContext(
            quota=QuotaMetrics(remaining_percent=80.0, window_duration_mins=300),
            surface=_surface(),
            runtime_state={"mcp:webbrain": RuntimeState.STOPPED},
            usage_events=(),
        ),
    )
    assert trace.halt in (PipelineHalt.CONTINUE_READY, PipelineHalt.REQUIRE_HUMAN)
    assert trace.usage_report is not None
    assert trace.usage_report.verdict is ComplianceVerdict.DRIFT
    assert "mcp:webbrain" in trace.usage_report.missing()
    assert trace.runtime_plan is not None
    assert trace.runtime_plan.executed is False
    assert trace.runtime_plan.actions()["mcp:webbrain"] is RuntimeAction.START


def test_ingest_turn_report_prefixes_buckets():
    events = ingest_turn_report(
        {
            "schema_version": 1,
            "kind": "turn_usage",
            "task_id": "TASK-056",
            "skills": [{"id": "verification", "count": 1}],
            "tools": [{"id": "schema_emit", "count": 2, "tokens": 40}],
            "mcp": [{"id": "webbrain"}],
            "plugins": [],
            "routes": [{"id": "knn"}],
            "servers": [],
        }
    )
    ids = [event.capability_id for event in events]
    assert ids == ["skill:verification", "tool:schema_emit", "mcp:webbrain", "route:knn"]
    assert events[1].tokens == 40


def test_ingest_turn_report_rejects_unknown_keys():
    with pytest.raises(ValueError, match="exactly"):
        ingest_turn_report({"schema_version": 1, "kind": "turn_usage", "task_id": "t"})


def test_no_slots_withhold_start_and_stop_unused():
    expectation = TaskExpectation(
        task_id="t1",
        required=("mcp:webbrain",),
        allowed=("route:knn",),
    )
    current = {
        "mcp:webbrain": RuntimeState.STOPPED,
        "route:knn": RuntimeState.RUNNING,
        "tool:local_asset_bake": RuntimeState.RUNNING,
    }
    plan = plan_runtime(
        _surface(),
        expectation,
        current,
        capacity=LocalCapacity(concurrent_slots=0),
    )
    actions = plan.actions()
    assert actions["mcp:webbrain"] is RuntimeAction.KEEP
    assert actions["route:knn"] is RuntimeAction.STOP
    assert actions["tool:local_asset_bake"] is RuntimeAction.STOP
    assert plan.executed is False


def test_pipeline_ingests_turn_report():
    director = AstralDirector(mode=DirectorMode.AUTO)
    pipeline = ContinuityPipeline(director=director)
    board = parse_kanban_markdown(
        "# Board\n## En cours\n- [ ] TASK-056 [P2] [difficulty: compact]\n  - title: Compact adapter work\n"
    )
    trace = pipeline.run_once(
        board,
        PipelineContext(
            quota=QuotaMetrics(remaining_percent=80.0, window_duration_mins=300),
            surface=_surface(),
            turn_report={
                "schema_version": 1,
                "kind": "turn_usage",
                "task_id": "TASK-056",
                "skills": [{"id": "verification"}],
                "tools": [],
                "mcp": [],
                "plugins": [],
                "routes": [{"id": "rule"}, {"id": "knn"}],
                "servers": [],
            },
        ),
    )
    assert trace.usage_report is not None
    assert "skill:verification" in trace.usage_report.used
    assert "route:rule" in trace.usage_report.used
