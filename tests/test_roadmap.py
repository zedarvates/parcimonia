from tiberium_ai.kanban import (
    Horizon,
    KanbanStatus,
    Severity,
    WorkClass,
    parse_kanban_markdown,
)
from tiberium_ai.roadmap import close_day, export_roadmap_views, plan_day, render_daily_markdown


BOARD = """
# Board

## En cours

- [ ] TASK-WIP [P1] [difficulty: compact] [class: feature] [severity: medium] [horizon: near]
  - title: Finish the adapter already started

## Backlog

- [ ] TASK-SEC [P2] [difficulty: compact] [class: security] [severity: critical] [horizon: near]
  - title: Close the auth bypass

- [ ] TASK-BUG [P1] [difficulty: compact] [class: bug] [severity: high] [horizon: near]
  - title: Fix crash on empty kanban

- [ ] TASK-FEAT [P0] [difficulty: compact] [class: feature] [severity: high] [horizon: near]
  - title: Add a shiny dashboard

- [ ] TASK-FAR [P0] [difficulty: reasoning] [class: feature] [horizon: far]
  - title: Rewrite the platform in a new language

- [ ] TASK-BLOCK [P0] [class: bug] [severity: critical] [horizon: near]
  - title: Waiting on a dependency
  - dependencies: TASK-MISSING
"""


def test_security_critical_outranks_in_progress_feature():
    board = parse_kanban_markdown(BOARD)
    nxt = board.get_next_eligible_task()
    assert nxt is not None
    assert nxt.task_id == "TASK-SEC"
    sec = board.get_task("TASK-SEC")
    assert sec is not None
    assert sec.work_class is WorkClass.SECURITY
    assert sec.severity is Severity.CRITICAL
    assert sec.to_task().risk_class == "critical"


def test_daily_plan_picks_hot_defects_within_wip():
    board = parse_kanban_markdown(BOARD)
    plan = plan_day(board, day="2026-09-21", wip_limit=2)
    assert plan.selected_ids() == ("TASK-SEC", "TASK-BUG")
    deferred_ids = {item.task.task_id: item.reason for item in plan.deferred}
    assert "TASK-FEAT" in deferred_ids
    assert deferred_ids["TASK-FAR"] == "far_horizon_with_hot_defects"
    assert any(task.task_id == "TASK-BLOCK" for task in plan.blocked)


def test_unfinished_day_is_carried_and_critical_can_displace_feature():
    board = parse_kanban_markdown(BOARD)
    first = plan_day(board, day="2026-09-21", wip_limit=2)
    # Pretend the team instead started the feature (not in this plan) and left SEC open.
    report = close_day(board, first)
    assert "TASK-SEC" in report.carry_ids
    assert report.next_day == "2026-09-22"

    second = plan_day(board, day="2026-09-22", wip_limit=2, previous=first)
    assert "TASK-SEC" in second.selected_ids()
    assert "TASK-SEC" in second.carried[0].task_id or second.carried[0].task_id in second.selected_ids()


def test_export_horizon_views_are_generated(tmp_path):
    board = parse_kanban_markdown(BOARD)
    plan = plan_day(board, day="2026-09-21", wip_limit=2)
    written = export_roadmap_views(board, tmp_path, daily=plan)
    near = written["roadmap-near.md"].read_text(encoding="utf-8")
    far = written["roadmap-far.md"].read_text(encoding="utf-8")
    daily = written["daily-2026-09-21.md"].read_text(encoding="utf-8")
    assert "Do not edit" in near
    assert "TASK-SEC" in near
    assert "TASK-FAR" in far
    assert "TASK-SEC" in daily
    assert "generated slice" in daily


def test_render_daily_mentions_carry_marker():
    board = parse_kanban_markdown(BOARD)
    first = plan_day(board, day="2026-09-21", wip_limit=2)
    second = plan_day(board, day="2026-09-22", wip_limit=2, previous=first)
    text = render_daily_markdown(second, close_day(board, second))
    assert "carried" in text
    assert "carry to 2026-09-23" in text

