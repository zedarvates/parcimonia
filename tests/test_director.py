import pytest

from tiberium_ai.continuation import (
    ContinuationAction,
    ContinuationArbiter,
    QuotaMetrics,
    RouteKind,
    TaskDifficulty,
)
from tiberium_ai.contracts import Task
from tiberium_ai.director import (
    AstralDirector,
    DirectorCounters,
    DirectorMode,
    DirectorProposal,
)
from tiberium_ai.kanban import KanbanBoard, KanbanStatus, KanbanTask, parse_kanban_markdown


def nominal_quota():
    return QuotaMetrics(remaining_percent=80.0, window_duration_mins=300)


def test_director_initial_counters():
    director = AstralDirector()
    assert director.counters == DirectorCounters(proposed=0, delivered=0, confirmed=0, overridden=0)
    assert director.mode == DirectorMode.SEMI_AUTO


def test_propose_increments_proposed_counter_only():
    director = AstralDirector()
    task = Task("t1", "formatting", {})
    proposal = director.propose(task, quota=nominal_quota(), difficulty=TaskDifficulty.DETERMINISTIC)

    assert isinstance(proposal, DirectorProposal)
    assert proposal.task_id == "t1"
    assert proposal.verdict.action == ContinuationAction.CONTINUE
    assert proposal.verdict.target_route == RouteKind.RULE
    assert proposal.approved is False
    assert proposal.delivered is False

    assert director.counters.proposed == 1
    assert director.counters.delivered == 0
    assert director.counters.confirmed == 0
    assert director.counters.overridden == 0


def test_semi_auto_delivery_refused_without_approval():
    director = AstralDirector(mode=DirectorMode.SEMI_AUTO)
    task = Task("t1", "code", {})
    proposal = director.propose(task, quota=nominal_quota(), difficulty=TaskDifficulty.COMPACT)

    # Silence is not approval: cannot deliver unapproved proposal
    with pytest.raises(ValueError, match="approval required"):
        director.deliver(proposal.proposal_id)

    assert director.counters.proposed == 1
    assert director.counters.delivered == 0


def test_approval_allows_delivery_in_semi_auto():
    director = AstralDirector(mode=DirectorMode.SEMI_AUTO)
    task = Task("t1", "code", {})
    proposal = director.propose(task, quota=nominal_quota(), difficulty=TaskDifficulty.COMPACT)

    director.approve(proposal.proposal_id, approved_by="operator")
    delivered_proposal = director.deliver(proposal.proposal_id)

    assert delivered_proposal.delivered is True
    assert director.counters.proposed == 1
    assert director.counters.delivered == 1
    assert director.counters.confirmed == 0


def test_past_approval_does_not_authorize_new_intervention():
    director = AstralDirector(mode=DirectorMode.SEMI_AUTO)
    task1 = Task("t1", "code", {})
    task2 = Task("t2", "code", {})

    p1 = director.propose(task1, quota=nominal_quota(), difficulty=TaskDifficulty.COMPACT)
    director.approve(p1.proposal_id, approved_by="operator")
    director.deliver(p1.proposal_id)

    # Cannot deliver p1 again
    with pytest.raises(ValueError, match="already delivered"):
        director.deliver(p1.proposal_id)

    # Second proposal cannot piggyback on prior approval
    p2 = director.propose(task2, quota=nominal_quota(), difficulty=TaskDifficulty.COMPACT)
    with pytest.raises(ValueError, match="approval required"):
        director.deliver(p2.proposal_id)

    assert director.counters.proposed == 2
    assert director.counters.delivered == 1


def test_deny_or_override_increments_overridden_counter():
    director = AstralDirector(mode=DirectorMode.SEMI_AUTO)
    task = Task("t1", "code", {})
    proposal = director.propose(task, quota=nominal_quota(), difficulty=TaskDifficulty.COMPACT)

    director.override(proposal.proposal_id, operator="operator", reason="skip this task")

    assert director.counters.proposed == 1
    assert director.counters.delivered == 0
    assert director.counters.overridden == 1

    # Overridden proposal cannot be delivered
    with pytest.raises(ValueError, match="overridden"):
        director.deliver(proposal.proposal_id)


def test_confirm_outcome_increments_confirmed_counter():
    director = AstralDirector(mode=DirectorMode.SEMI_AUTO)
    task = Task("t1", "code", {})
    p = director.propose(task, quota=nominal_quota(), difficulty=TaskDifficulty.COMPACT)
    director.approve(p.proposal_id, approved_by="operator")
    director.deliver(p.proposal_id)

    # If verification passed
    confirmed = director.confirm_outcome(p.proposal_id, verified=True)
    assert confirmed is True
    assert director.counters.confirmed == 1

    # An unverified outcome does not increment confirmed
    p2 = director.propose(Task("t2", "code", {}), quota=nominal_quota(), difficulty=TaskDifficulty.COMPACT)
    director.approve(p2.proposal_id, approved_by="operator")
    director.deliver(p2.proposal_id)
    confirmed2 = director.confirm_outcome(p2.proposal_id, verified=False)
    assert confirmed2 is False
    assert director.counters.confirmed == 1


def test_off_mode_allows_propose_but_blocks_delivery():
    director = AstralDirector(mode=DirectorMode.OFF)
    task = Task("t1", "code", {})
    p = director.propose(task, quota=nominal_quota(), difficulty=TaskDifficulty.COMPACT)

    director.approve(p.proposal_id, approved_by="operator")
    with pytest.raises(ValueError, match="mode is OFF"):
        director.deliver(p.proposal_id)

    assert director.counters.proposed == 1
    assert director.counters.delivered == 0


def test_auto_mode_allows_preauthorized_low_risk_delivery():
    director = AstralDirector(mode=DirectorMode.AUTO)
    low_risk = Task("t_low", "code", {}, risk_class="low")

    # In AUTO mode, low risk continues directly without manual approve call
    p_low = director.propose(low_risk, quota=nominal_quota(), difficulty=TaskDifficulty.COMPACT)
    deliv = director.deliver(p_low.proposal_id)
    assert deliv.delivered is True
    assert director.counters.proposed == 1
    assert director.counters.delivered == 1

    # High risk task in AUTO mode STILL requires human approval
    high_risk = Task("t_high", "deploy", {}, risk_class="critical")
    p_high = director.propose(high_risk, quota=nominal_quota(), difficulty=TaskDifficulty.REASONING)
    with pytest.raises(ValueError, match="approval required"):
        director.deliver(p_high.proposal_id)


def test_propose_from_kanban():
    markdown = """# Board
## Backlog
- [ ] TASK-01 [P1] [difficulté: déterministe]
  - Intitulé : Vérification linters
"""
    board = parse_kanban_markdown(markdown)
    director = AstralDirector()
    proposal = director.propose_from_kanban(board, quota=nominal_quota())

    assert proposal is not None
    assert proposal.task_id == "TASK-01"
    assert proposal.verdict.target_route == RouteKind.RULE
    assert director.counters.proposed == 1
