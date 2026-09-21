from tiberium_ai.continuation import QuotaMetrics, RouteKind, TimeBudget
from tiberium_ai.director import AstralDirector, DirectorMode
from tiberium_ai.kanban import parse_kanban_markdown
from tiberium_ai.pipeline import ContinuityPipeline, PipelineContext, PipelineHalt
from tiberium_ai.reflex import CalibrationSnapshot, InjectedReflexBackend, ReflexEngine
from tiberium_ai.schema_emit import ProposedCall, ToolParameter, ToolSpec
from tiberium_ai.webbrain import WebBrainMode
from tiberium_ai.world_model import ActionDescriptor, GateRecommendation, StateVector


BOARD = """# Board

## Termine

- [x] TASK-055 [P2] [difficulty: reasoning]
  - title: World model gate

## En cours

- [ ] TASK-056 [P2] [difficulty: compact]
  - title: End-to-end continuation wiring
  - dependencies: TASK-055

## Backlog

- [ ] TASK-057 [P3] [difficulty: compact]
  - title: Integrations doc
  - dependencies: TASK-056

- [ ] TASK-WEB [P1] [difficulty: compact] [tool: webbrain]
  - title: Read the pricing table
  - dependencies: TASK-055
"""


def _board():
    return parse_kanban_markdown(BOARD)


def _quota(remaining=80.0):
    return QuotaMetrics(remaining_percent=remaining, window_duration_mins=300)


def _reflex():
    return ReflexEngine(
        InjectedReflexBackend(
            answers={
                "difficulty": {
                    "choice": "compact",
                    "probabilities": {"deterministic": 0.1, "compact": 0.8, "reasoning": 0.1},
                    "confidence": 0.8,
                },
                "should_continue": {
                    "noul": 0.9,
                    "probabilities": {"false": 0.1, "true": 0.9},
                    "confidence": 0.9,
                },
                "needs_browser": {
                    "noul": 0.05,
                    "probabilities": {"false": 0.95, "true": 0.05},
                    "confidence": 0.9,
                },
            }
        )
    )


def test_auto_low_risk_delivers_after_gate():
    director = AstralDirector(mode=DirectorMode.AUTO)
    pipeline = ContinuityPipeline(director=director, reflex=_reflex())
    action = ActionDescriptor(name="edit", target="src/pipeline.py", is_mutation=True)
    trace = pipeline.run_once(
        _board(),
        PipelineContext(
            quota=_quota(),
            source_text="wire director continuation webbrain and world model",
            current_state=StateVector((0.0, 0.0)),
            predicted_next_state=StateVector((1.0, 0.0)),
            target_state=StateVector((2.0, 0.0)),
            proposed_action=action,
        ),
    )
    assert trace.halt == PipelineHalt.CONTINUE_READY
    assert trace.proposal is not None
    assert trace.proposal.task_id == "TASK-056"
    assert trace.continuation.target_route == RouteKind.LOCAL_SMALL
    assert trace.gate is not None
    assert trace.gate.recommendation == GateRecommendation.ADMIT
    assert trace.counters.proposed == 1
    assert trace.counters.delivered == 1
    assert trace.webbrain_request is None


def test_semi_auto_silence_is_not_approval():
    director = AstralDirector(mode=DirectorMode.SEMI_AUTO)
    pipeline = ContinuityPipeline(director=director)
    trace = pipeline.run_once(_board(), PipelineContext(quota=_quota()))
    assert trace.halt == PipelineHalt.WAITING_APPROVAL
    assert trace.counters.proposed == 1
    assert trace.counters.delivered == 0
    assert "Silence is not approval" in trace.reason


def test_dead_click_is_pruned_before_delivery():
    director = AstralDirector(mode=DirectorMode.AUTO)
    pipeline = ContinuityPipeline(director=director)
    action = ActionDescriptor(name="click", target="#submit", is_mutation=True)
    trace = pipeline.run_once(
        _board(),
        PipelineContext(
            quota=_quota(),
            current_state=StateVector((1.0, 1.0)),
            predicted_next_state=StateVector((1.0, 1.01)),
            proposed_action=action,
        ),
    )
    assert trace.halt == PipelineHalt.PRUNED
    assert trace.gate.recommendation == GateRecommendation.PRUNE_LOOP
    assert trace.counters.delivered == 0


def test_critical_quota_freezes_reasoning_not_compact():
    markdown = """# Board
## Backlog
- [ ] TASK-R [P2] [difficulty: reasoning]
  - title: Architecture rewrite
"""
    director = AstralDirector(mode=DirectorMode.AUTO)
    pipeline = ContinuityPipeline(director=director)
    trace = pipeline.run_once(
        parse_kanban_markdown(markdown),
        PipelineContext(quota=_quota(10.0)),
    )
    assert trace.halt == PipelineHalt.FROZEN_QUOTA
    assert trace.counters.delivered == 0


def test_trust_reflex_fails_closed_without_calibration():
    director = AstralDirector(mode=DirectorMode.AUTO)
    pipeline = ContinuityPipeline(director=director, reflex=_reflex())
    trace = pipeline.run_once(
        _board(),
        PipelineContext(quota=_quota(), trust_reflex=True, calibration=CalibrationSnapshot("family", False)),
    )
    assert trace.halt == PipelineHalt.UNCALIBRATED
    assert trace.counters.delivered == 0


def test_time_budget_blocks_browser_in_short_interactive_window():
    markdown = """# Board
## Backlog
- [ ] TASK-WEB [P1] [difficulty: compact] [tool: webbrain]
  - title: Read the pricing table
"""
    director = AstralDirector(mode=DirectorMode.AUTO)
    pipeline = ContinuityPipeline(director=director)
    trace = pipeline.run_once(
        parse_kanban_markdown(markdown),
        PipelineContext(
            quota=_quota(),
            time_budget=TimeBudget(remaining_seconds=12.0, interactive=True),
            webbrain_mode=WebBrainMode.ASK,
        ),
    )
    assert trace.halt == PipelineHalt.REQUIRE_HUMAN
    assert trace.webbrain_request is None
    assert trace.counters.delivered == 0


def test_webbrain_request_is_built_not_sent():
    markdown = """# Board
## Backlog
- [ ] TASK-WEB [P1] [difficulty: compact] [tool: webbrain]
  - title: Read the pricing table
"""
    director = AstralDirector(mode=DirectorMode.AUTO)
    pipeline = ContinuityPipeline(director=director)
    trace = pipeline.run_once(
        parse_kanban_markdown(markdown),
        PipelineContext(
            quota=_quota(),
            time_budget=TimeBudget(remaining_seconds=600.0, interactive=False),
            webbrain_mode=WebBrainMode.ASK,
        ),
    )
    assert trace.halt == PipelineHalt.CONTINUE_READY
    assert trace.continuation.target_route == RouteKind.WEBBRAIN_MCP
    assert trace.webbrain_request is not None
    assert trace.webbrain_request.tool_name == "webbrain_run"
    assert trace.webbrain_request.arguments["mode"] == "ask"


def test_schema_emit_refuse_stops_pipeline():
    director = AstralDirector(mode=DirectorMode.AUTO)
    pipeline = ContinuityPipeline(director=director)
    tools = (
        ToolSpec(
            name="set_lights",
            description="lights",
            parameters=(ToolParameter("room", "string", required=True),),
        ),
    )
    trace = pipeline.run_once(
        _board(),
        PipelineContext(
            quota=_quota(),
            source_text="unrelated chatter",
            tools=tools,
            proposed_call=ProposedCall(name="launch_missiles", arguments={"room": "nowhere"}),
        ),
    )
    assert trace.halt == PipelineHalt.REFUSED_EMIT
    assert trace.counters.delivered == 0


def test_past_approval_does_not_leak_into_next_task():
    director = AstralDirector(mode=DirectorMode.SEMI_AUTO)
    pipeline = ContinuityPipeline(director=director)
    first = pipeline.run_once(_board(), PipelineContext(quota=_quota()))
    director.approve(first.proposal.proposal_id)
    director.deliver(first.proposal.proposal_id)
    second = pipeline.run_once(_board(), PipelineContext(quota=_quota()))
    assert second.halt == PipelineHalt.WAITING_APPROVAL
    assert second.counters.proposed == 2
    assert second.counters.delivered == 1

