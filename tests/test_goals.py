from tiberium_ai.goals import parse_goals_markdown
from tiberium_ai.kanban import parse_kanban_markdown
from tiberium_ai.roadmap import plan_day

GOALS = """
# Buts ultimes

- [x] GOAL-SHIP [rank: 1] [horizon: long]
  - title: Ship a local-first router with evidence gates
  - constraints: local-first, no-private-publish

- [x] GOAL-SIDE [rank: 2] [horizon: mid]
  - title: Keep the side experiments from eating the week

- [ ] GOAL-OLD [rank: 1] [horizon: long] [parked]
  - title: An old mission that must not steal rank
"""

CARDS = """
# Board
## Backlog
- [ ] TASK-A [P1] [class: feature] [horizon: near] [goal: GOAL-SIDE]
  - title: Side experiment
- [ ] TASK-B [P2] [class: feature] [horizon: near] [goal: GOAL-SHIP]
  - title: Evidence gate for the router
- [ ] TASK-C [P0] [class: feature] [horizon: near]
  - title: Unlinked shiny P0
- [ ] TASK-SEC [P3] [class: security] [severity: critical] [horizon: near] [goal: GOAL-SIDE]
  - title: Auth hole in a side project
"""


def test_parse_goals_active_ranks_and_parked():
    goals = parse_goals_markdown(GOALS)
    assert goals.get("GOAL-SHIP").rank == 1
    assert "local-first" in goals.get("GOAL-SHIP").constraints
    ranks = goals.ranks_for_schedule()
    assert ranks["GOAL-SHIP"] == 1
    assert ranks["GOAL-SIDE"] == 2
    assert ranks["GOAL-OLD"] > 100


def test_orchestrator_needs_goals_to_prefer_the_mission():
    board = parse_kanban_markdown(CARDS)
    goals = parse_goals_markdown(GOALS)
    without = board.get_next_eligible_task()
    assert without is not None
    assert without.task_id == "TASK-SEC"
    with_goals = board.get_next_eligible_task(goals.ranks_for_schedule())
    assert with_goals.task_id == "TASK-SEC"
    plan = plan_day(board, day="2026-09-21", wip_limit=2, goal_ranks=goals.ranks_for_schedule())
    assert plan.selected_ids()[0] == "TASK-SEC"
    assert "TASK-B" in plan.selected_ids()
    assert "TASK-C" not in plan.selected_ids()
    assert "TASK-A" not in plan.selected_ids()


def test_unknown_goal_does_not_become_rank_one():
    board = parse_kanban_markdown(
        "# B\n## Backlog\n"
        "- [ ] TASK-X [P0] [goal: GOAL-MISSING]\n  - title: Fake mission\n"
        "- [ ] TASK-Y [P2] [goal: GOAL-SHIP]\n  - title: Real mission work\n"
    )
    nxt = board.get_next_eligible_task({"GOAL-SHIP": 1})
    assert nxt is not None
    assert nxt.task_id == "TASK-Y"


def test_missing_rank_is_rejected():
    import pytest
    with pytest.raises(ValueError, match="rank"):
        parse_goals_markdown("- [x] GOAL-X\n  - title: Oops\n")
