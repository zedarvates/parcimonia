"""Human-authored ultimate goals for orchestration.

The orchestrator does not invent missions. A missing, parked or unknown
goal never becomes rank 1. Safety-critical work still outranks goals.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from pathlib import Path
from typing import Mapping

from .kanban import Horizon, _fold, _parse_horizon

__all__ = ["Goal", "GoalSet", "parse_goals_markdown", "load_goals"]

_MAX_GOALS = 12


class GoalStatus(str, Enum):
    ACTIVE = "active"
    PARKED = "parked"


@dataclass(frozen=True)
class Goal:
    goal_id: str
    title: str
    rank: int
    horizon: Horizon = Horizon.UNSPECIFIED
    status: GoalStatus = GoalStatus.ACTIVE
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.goal_id, str) or not self.goal_id.strip():
            raise ValueError("goal_id must be a nonempty string.")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be a nonempty string.")
        if type(self.rank) is not int or self.rank < 1:
            raise ValueError("rank must be a positive integer (1 = highest).")


@dataclass(frozen=True)
class GoalSet:
    goals: tuple[Goal, ...]

    def __post_init__(self) -> None:
        if len(self.goals) > _MAX_GOALS:
            raise ValueError("at most 12 ultimate goals; merge rather than expand.")
        ids = [goal.goal_id for goal in self.goals]
        if len(set(ids)) != len(ids):
            raise ValueError("goal ids must be unique.")
        ranks = [goal.rank for goal in self.goals if goal.status is GoalStatus.ACTIVE]
        if len(set(ranks)) != len(ranks):
            raise ValueError("active goal ranks must be unique.")

    def get(self, goal_id: str) -> Goal | None:
        for goal in self.goals:
            if goal.goal_id == goal_id:
                return goal
        return None

    def ranks_for_schedule(self) -> dict[str, int]:
        """Lower is sooner. Parked and unknown stay out of the top ranks."""
        out: dict[str, int] = {}
        for goal in self.goals:
            if goal.status is GoalStatus.ACTIVE:
                out[goal.goal_id] = goal.rank
            else:
                out[goal.goal_id] = 500 + goal.rank
        return out

    def constraints_for(self, goal_ids: tuple[str, ...]) -> tuple[str, ...]:
        found: list[str] = []
        seen: set[str] = set()
        for goal_id in goal_ids:
            goal = self.get(goal_id)
            if goal is None:
                continue
            for item in goal.constraints:
                if item not in seen:
                    seen.add(item)
                    found.append(item)
        return tuple(found)


def parse_goals_markdown(content: str) -> GoalSet:
    item_re = re.compile(r"^-\s*\[([ xX])\]\s*[`]?([A-Za-z0-9_-]+)[`]?\s*(.*)$")
    rank_re = re.compile(r"\[rank:\s*(\d+)\]", re.IGNORECASE)
    horizon_re = re.compile(r"\[(?:horizon|terme):\s*([^\]]+)\]", re.IGNORECASE)
    parked_re = re.compile(r"\[(parked|pause|inactif)\]", re.IGNORECASE)
    title_re = re.compile(r"^(?:intitule|title)\s*:", re.IGNORECASE)
    constr_re = re.compile(r"^(?:contraintes|constraints)\s*:\s*(.*)$", re.IGNORECASE)

    goals: list[Goal] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = item_re.match(line)
        if not match:
            i += 1
            continue
        checked, goal_id, rest = match.groups()
        status = GoalStatus.ACTIVE if checked.lower() == "x" else GoalStatus.PARKED
        if parked_re.search(rest):
            status = GoalStatus.PARKED
        rank_m = rank_re.search(rest)
        if rank_m is None:
            raise ValueError(f"goal {goal_id!r} must declare [rank: N].")
        rank = int(rank_m.group(1))
        horizon_m = horizon_re.search(rest) or horizon_re.search(_fold(rest))
        horizon = _parse_horizon(horizon_m.group(1)) if horizon_m else Horizon.UNSPECIFIED
        title = re.sub(r"\[[^\]]+\]", "", rest).strip(" :-") or goal_id
        constraints: list[str] = []
        j = i + 1
        while j < len(lines) and (lines[j].startswith("  ") or lines[j].startswith("\t")):
            sub = lines[j].strip().lstrip("- ").strip()
            if title_re.match(_fold(sub)):
                title = sub.split(":", 1)[1].strip()
            constr_m = constr_re.match(_fold(sub))
            if constr_m is None:
                constr_m = constr_re.match(sub)
            if constr_m:
                raw = sub.split(":", 1)[1].strip()
                constraints.extend([c.strip() for c in raw.split(",") if c.strip()])
            j += 1
        i = j - 1
        goals.append(
            Goal(
                goal_id=goal_id,
                title=title,
                rank=rank,
                horizon=horizon,
                status=status,
                constraints=tuple(constraints),
            )
        )
        i += 1
    return GoalSet(goals=tuple(goals))


def load_goals(path: str | Path) -> GoalSet:
    return parse_goals_markdown(Path(path).read_text(encoding="utf-8"))
