"""Astral Resonance Director: supervisory loop adapter for agent continuation.

Implements the supervisory invariants adapted from vectal-labs/director:
- Separated counters for proposed, delivered, confirmed, and overridden actions.
- Silence is not approval.
- A previous approval never authorizes a new intervention.
- Propose is logged before approval.
- Native bridge with ContinuationArbiter and KanbanBoard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import uuid
from typing import Any, Mapping

from .contracts import Task
from .continuation import (
    ContinuationAction,
    ContinuationArbiter,
    ContinuationVerdict,
    QuotaMetrics,
    RouteKind,
    TaskDifficulty,
    TimeBudget,
    LocalCapacity,
)
from .kanban import KanbanBoard, KanbanTask

__all__ = [
    "AstralDirector",
    "DirectorCounters",
    "DirectorMode",
    "DirectorProposal",
]


class DirectorMode(str, Enum):
    OFF = "off"
    SEMI_AUTO = "semi-auto"
    AUTO = "auto"


@dataclass(frozen=True)
class DirectorCounters:
    proposed: int = 0
    delivered: int = 0
    confirmed: int = 0
    overridden: int = 0


@dataclass
class DirectorProposal:
    proposal_id: str
    task_id: str
    verdict: ContinuationVerdict
    task: Task
    approved: bool = False
    approved_by: str | None = None
    delivered: bool = False
    overridden: bool = False
    override_reason: str | None = None


class AstralDirector:
    """Supervises stopped agents, arbitrates continuation with Parcimonia, and tracks intervention lifecycle."""

    def __init__(
        self,
        mode: DirectorMode = DirectorMode.SEMI_AUTO,
        arbiter: ContinuationArbiter | None = None,
    ) -> None:
        if not isinstance(mode, DirectorMode):
            raise TypeError("mode must be a DirectorMode enum.")
        self.mode = mode
        self.arbiter = arbiter if arbiter is not None else ContinuationArbiter()
        self._proposals: dict[str, DirectorProposal] = {}
        self._proposed = 0
        self._delivered = 0
        self._confirmed = 0
        self._overridden = 0

    @property
    def counters(self) -> DirectorCounters:
        return DirectorCounters(
            proposed=self._proposed,
            delivered=self._delivered,
            confirmed=self._confirmed,
            overridden=self._overridden,
        )

    def propose(
        self,
        task: Task,
        quota: QuotaMetrics,
        difficulty: TaskDifficulty,
        *,
        consecutive_stalls: int = 0,
        requires_browser: bool = False,
        time_budget: TimeBudget | None = None,
        capacity: LocalCapacity | None = None,
    ) -> DirectorProposal:
        verdict = self.arbiter.evaluate(
            task,
            quota,
            difficulty,
            consecutive_stalls=consecutive_stalls,
            requires_browser=requires_browser,
            time_budget=time_budget,
            capacity=capacity,
        )
        proposal_id = f"prop_{uuid.uuid4().hex[:12]}"
        proposal = DirectorProposal(
            proposal_id=proposal_id,
            task_id=task.task_id,
            verdict=verdict,
            task=task,
        )
        self._proposals[proposal_id] = proposal
        self._proposed += 1
        return proposal

    def propose_from_kanban(
        self,
        board: KanbanBoard,
        quota: QuotaMetrics,
        *,
        consecutive_stalls: int = 0,
        time_budget: TimeBudget | None = None,
        capacity: LocalCapacity | None = None,
    ) -> DirectorProposal | None:
        eligible = board.get_next_eligible_task()
        if eligible is None:
            return None
        task = eligible.to_task()
        return self.propose(
            task,
            quota=quota,
            difficulty=eligible.difficulty,
            consecutive_stalls=consecutive_stalls,
            requires_browser=eligible.requires_browser,
            time_budget=time_budget,
            capacity=capacity,
        )

    def approve(self, proposal_id: str, approved_by: str = "operator") -> None:
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            raise KeyError(f"Unknown proposal_id: {proposal_id}")
        if proposal.overridden:
            raise ValueError("Cannot approve an overridden proposal.")
        proposal.approved = True
        proposal.approved_by = approved_by

    def override(self, proposal_id: str, operator: str = "operator", reason: str = "") -> None:
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            raise KeyError(f"Unknown proposal_id: {proposal_id}")
        proposal.overridden = True
        proposal.override_reason = reason
        self._overridden += 1

    def deliver(self, proposal_id: str) -> DirectorProposal:
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            raise KeyError(f"Unknown proposal_id: {proposal_id}")
        if proposal.delivered:
            raise ValueError("Proposal already delivered.")
        if proposal.overridden:
            raise ValueError("Cannot deliver an overridden proposal.")
        if self.mode == DirectorMode.OFF:
            raise ValueError("Cannot deliver action: mode is OFF.")

        if self.mode == DirectorMode.SEMI_AUTO:
            if not proposal.approved:
                raise ValueError("Cannot deliver: approval required in semi-auto mode.")
        elif self.mode == DirectorMode.AUTO:
            # High risk tasks still require human approval even in auto mode
            if proposal.task.risk_class in ("high", "critical") and not proposal.approved:
                raise ValueError("Cannot deliver: approval required for high-risk task.")

        proposal.delivered = True
        self._delivered += 1
        return proposal

    def confirm_outcome(self, proposal_id: str, verified: bool) -> bool:
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            raise KeyError(f"Unknown proposal_id: {proposal_id}")
        if not proposal.delivered:
            raise ValueError("Cannot confirm outcome for undelivered proposal.")
        if verified:
            self._confirmed += 1
            return True
        return False
