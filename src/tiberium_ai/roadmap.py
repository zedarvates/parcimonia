"""Project roadmap views and daily work plans.

kanban.md remains the source of truth. Near / mid / far files are generated
projections. The daily plan carries unfinished work forward and only pulls
new items into remaining WIP slots, with security and critical bugs first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import json
from typing import Any

from .kanban import (
    Horizon,
    KanbanBoard,
    KanbanStatus,
    KanbanTask,
    Severity,
    WorkClass,
    schedule_key,
    parse_kanban_markdown,
)
from .goals import GoalSet, load_goals

__all__ = [
    "DailyPlan",
    "DayReport",
    "DeferredItem",
    "close_day",
    "export_roadmap_views",
    "plan_day",
    "render_daily_markdown",
    "render_horizon_markdown",
    "DailySnapshot",
    "orchestrate_day",
    "read_daily_snapshot",
    "write_daily_snapshot",
]


def _is_critical_defect(task: KanbanTask) -> bool:
    return task.work_class in (WorkClass.SECURITY, WorkClass.BUG) and task.severity is Severity.CRITICAL


def _is_hot_defect(task: KanbanTask) -> bool:
    return task.work_class in (WorkClass.SECURITY, WorkClass.BUG) and task.severity in (
        Severity.CRITICAL,
        Severity.HIGH,
    )


@dataclass(frozen=True)
class DeferredItem:
    task: KanbanTask
    reason: str


@dataclass(frozen=True)
class DailyPlan:
    day: str
    project_id: str
    wip_limit: int
    selected: tuple[KanbanTask, ...]
    carried: tuple[KanbanTask, ...]
    deferred: tuple[DeferredItem, ...]
    blocked: tuple[KanbanTask, ...]

    def selected_ids(self) -> tuple[str, ...]:
        return tuple(task.task_id for task in self.selected)


@dataclass(frozen=True)
class DayReport:
    day: str
    next_day: str
    done_ids: tuple[str, ...]
    carry_ids: tuple[str, ...]
    deferred: tuple[DeferredItem, ...]
    notes: str


@dataclass(frozen=True)
class DailySnapshot:
    """Recorded daily selection; the kanban remains the task source of truth."""

    day: str
    project_id: str
    wip_limit: int
    selected_ids: tuple[str, ...]
    source: str = "kanban.md"

    def __post_init__(self) -> None:
        date.fromisoformat(self.day)
        if not self.project_id or not self.project_id.strip():
            raise ValueError("project_id must be nonempty.")
        if type(self.wip_limit) is not int or self.wip_limit < 1:
            raise ValueError("wip_limit must be a positive integer.")
        if len(set(self.selected_ids)) != len(self.selected_ids):
            raise ValueError("selected_ids must be unique.")
        if any(not isinstance(item, str) or not item.strip() for item in self.selected_ids):
            raise ValueError("selected_ids must contain nonempty strings.")
        if not self.source or not self.source.strip():
            raise ValueError("source must be nonempty.")

    @classmethod
    def from_plan(cls, plan: DailyPlan) -> "DailySnapshot":
        return cls(plan.day, plan.project_id, plan.wip_limit, plan.selected_ids())

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "daily_snapshot",
            "day": self.day,
            "project_id": self.project_id,
            "wip_limit": self.wip_limit,
            "selected_ids": list(self.selected_ids),
            "source": self.source,
        }


def plan_day(
    board: KanbanBoard,
    *,
    day: str,
    project_id: str = "parcimonia",
    wip_limit: int = 3,
    previous: DailyPlan | None = None,
    goal_ranks: dict[str, int] | None = None,
) -> DailyPlan:
    """Build today slice. Carried work keeps a slot; critical defects can displace features."""
    if type(wip_limit) is not int or wip_limit < 1:
        raise ValueError("wip_limit must be a positive integer.")
    if not isinstance(day, str) or not day.strip():
        raise ValueError("day must be a nonempty ISO date string.")

    eligible = list(board.eligible_tasks(goal_ranks))
    eligible_ids = {task.task_id for task in eligible}
    blocked = tuple(
        task
        for task in board.tasks
        if task.status in (KanbanStatus.TODO, KanbanStatus.IN_PROGRESS, KanbanStatus.BLOCKED)
        and task.task_id not in eligible_ids
        and task.status is not KanbanStatus.DONE
    )

    carried: list[KanbanTask] = []
    if previous is not None:
        by_id = {task.task_id: task for task in board.tasks}
        for task in previous.selected:
            current = by_id.get(task.task_id)
            if current is not None and current.status in (KanbanStatus.TODO, KanbanStatus.IN_PROGRESS):
                if current.task_id in eligible_ids:
                    carried.append(current)

    incoming_critical = [
        task for task in eligible if _is_critical_defect(task) and task.task_id not in {c.task_id for c in carried}
    ]
    hot_waiting = any(_is_hot_defect(task) for task in eligible)

    selected: list[KanbanTask] = []
    deferred: list[DeferredItem] = []
    selected_ids: set[str] = set()

    def _take(task: KanbanTask) -> None:
        if task.task_id in selected_ids:
            return
        selected.append(task)
        selected_ids.add(task.task_id)

    for task in carried:
        if _is_hot_defect(task):
            _take(task)

    for task in incoming_critical:
        if len(selected) < wip_limit:
            _take(task)

    for task in carried:
        if task.task_id in selected_ids:
            continue
        if len(selected) >= wip_limit:
            reason = "displaced_by_critical" if incoming_critical and not _is_hot_defect(task) else "wip_limit"
            deferred.append(DeferredItem(task, reason))
            continue
        _take(task)

    for task in eligible:
        if task.task_id in selected_ids:
            continue
        if len(selected) >= wip_limit:
            reason = "far_horizon_with_hot_defects" if task.horizon is Horizon.FAR and hot_waiting else "wip_limit"
            deferred.append(DeferredItem(task, reason))
            continue
        if task.horizon is Horizon.FAR and hot_waiting:
            deferred.append(DeferredItem(task, "far_horizon_with_hot_defects"))
            continue
        _take(task)

    return DailyPlan(
        day=day.strip(),
        project_id=project_id,
        wip_limit=wip_limit,
        selected=tuple(selected),
        carried=tuple(carried),
        deferred=tuple(deferred),
        blocked=blocked,
    )


def close_day(board: KanbanBoard, plan: DailyPlan) -> DayReport:
    """Report what finished and what must be planned again tomorrow."""
    by_id = {task.task_id: task for task in board.tasks}
    done: list[str] = []
    carry: list[str] = []
    for task in plan.selected:
        current = by_id.get(task.task_id)
        if current is None or current.status is KanbanStatus.DONE:
            done.append(task.task_id)
        else:
            carry.append(task.task_id)
    parsed = date.fromisoformat(plan.day)
    nxt = (parsed + timedelta(days=1)).isoformat()
    if carry:
        notes = "Unfinished selected work is carried to the next day; do not drop it silently."
    else:
        notes = "Daily slice completed; pull a new ranked slice tomorrow."
    return DayReport(
        day=plan.day,
        next_day=nxt,
        done_ids=tuple(done),
        carry_ids=tuple(carry),
        deferred=plan.deferred,
        notes=notes,
    )


def render_daily_markdown(plan: DailyPlan, report: DayReport | None = None) -> str:
    lines = [
        f"# Daily plan {plan.day}",
        "",
        f"Project: {plan.project_id}",
        f"WIP limit: {plan.wip_limit}",
        "Source: kanban.md (this file is a generated slice, do not edit as a backlog).",
        "",
        "## Today",
        "",
    ]
    if not plan.selected:
        lines.append("- (empty)")
    for task in plan.selected:
        carried = " carried" if task.task_id in {item.task_id for item in plan.carried} else ""
        lines.append(
            f"- [ ] `{task.task_id}` [{task.work_class.value}/{task.severity.value}/{task.horizon.value}]{carried} {task.title}"
        )
    lines.extend(["", "## Deferred", ""])
    if not plan.deferred:
        lines.append("- (none)")
    for item in plan.deferred:
        lines.append(f"- `{item.task.task_id}` ({item.reason}) {item.task.title}")
    if report is not None:
        done = ", ".join(report.done_ids) if report.done_ids else "(none)"
        carry = ", ".join(report.carry_ids) if report.carry_ids else "(none)"
        lines.extend(
            [
                "",
                "## Close of day",
                "",
                f"- done: {done}",
                f"- carry to {report.next_day}: {carry}",
                f"- {report.notes}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def render_horizon_markdown(board: KanbanBoard, horizon: Horizon, *, source: str = "kanban.md") -> str:
    labels = {Horizon.NEAR: "court terme", Horizon.MID: "moyen terme", Horizon.FAR: "long terme"}
    label = labels[horizon]
    lines = [
        f"# Roadmap — {label}",
        "",
        f"Generated from {source}. Do not edit; change the kanban instead.",
        "Order: security/bug critical and high, then other work.",
        "",
    ]
    matching = [
        task
        for task in board.tasks
        if task.status is not KanbanStatus.DONE and task.horizon is horizon
    ]
    matching.sort(key=schedule_key)
    if not matching:
        lines.append("(empty)")
        lines.append("")
        return "\n".join(lines)
    for task in matching:
        mark = "x" if task.status is KanbanStatus.DONE else " "
        lines.append(
            f"- [{mark}] `{task.task_id}` [{task.work_class.value}/{task.severity.value}] {task.title}"
        )
    lines.append("")
    return "\n".join(lines)


def export_roadmap_views(
    board: KanbanBoard,
    directory: str | Path,
    *,
    source: str = "kanban.md",
    daily: DailyPlan | None = None,
) -> dict[str, Path]:
    """Write generated near/mid/far views. Never the source of truth."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    mapping = {
        "roadmap-near.md": Horizon.NEAR,
        "roadmap-mid.md": Horizon.MID,
        "roadmap-far.md": Horizon.FAR,
    }
    for name, horizon in mapping.items():
        path = root / name
        path.write_text(render_horizon_markdown(board, horizon, source=source), encoding="utf-8", newline="\n")
        written[name] = path
    if daily is not None:
        path = root / f"daily-{daily.day}.md"
        path.write_text(render_daily_markdown(daily), encoding="utf-8", newline="\n")
        written[path.name] = path
    return written


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r} in daily snapshot.")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite value {value!r} in daily snapshot.")


def write_daily_snapshot(path: str | Path, plan: DailyPlan) -> Path:
    """Persist the selection once; never overwrite a daily snapshot."""
    snapshot = DailySnapshot.from_plan(plan)
    target = Path(path)
    payload = json.dumps(snapshot.to_record(), ensure_ascii=False, indent=2) + "\n"
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
    return target


def read_daily_snapshot(path: str | Path) -> DailySnapshot:
    raw = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_constant,
    )
    required = {
        "schema_version",
        "kind",
        "day",
        "project_id",
        "wip_limit",
        "selected_ids",
        "source",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise ValueError("daily snapshot has missing or unknown fields.")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("daily snapshot schema_version must be 1.")
    if raw["kind"] != "daily_snapshot":
        raise ValueError("daily snapshot kind must be daily_snapshot.")
    if not isinstance(raw["selected_ids"], list):
        raise ValueError("selected_ids must be a list.")
    return DailySnapshot(
        day=raw["day"],
        project_id=raw["project_id"],
        wip_limit=raw["wip_limit"],
        selected_ids=tuple(raw["selected_ids"]),
        source=raw["source"],
    )


def orchestrate_day(
    project_dir: str | Path,
    *,
    day: str,
    wip_limit: int = 3,
    project_id: str = "parcimonia",
) -> DailyPlan:
    """Read project goals and yesterday's snapshot before ranking today's work.

    This read-only function refuses a malformed snapshot. Missing goals mean
    no goal ranks. A missing snapshot means no carried selection.
    """
    root = Path(project_dir)
    board = parse_kanban_markdown((root / "kanban.md").read_text(encoding="utf-8"))
    goal_path = root / "buts.md"
    goals: GoalSet | None = load_goals(goal_path) if goal_path.is_file() else None
    previous_day = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    snapshot_path = root / "planning" / f"daily-{previous_day}.json"
    previous: DailyPlan | None = None
    if snapshot_path.is_file():
        snapshot = read_daily_snapshot(snapshot_path)
        if snapshot.day != previous_day or snapshot.project_id != project_id:
            raise ValueError("yesterday's snapshot does not match this project and day.")
        by_id = {task.task_id: task for task in board.tasks}
        previous = DailyPlan(
            day=snapshot.day,
            project_id=snapshot.project_id,
            wip_limit=snapshot.wip_limit,
            selected=tuple(by_id[task_id] for task_id in snapshot.selected_ids if task_id in by_id),
            carried=(),
            deferred=(),
            blocked=(),
        )
    return plan_day(
        board,
        day=day,
        project_id=project_id,
        wip_limit=wip_limit,
        previous=previous,
        goal_ranks=goals.ranks_for_schedule() if goals is not None else None,
    )
