"""Local-first Kanban / task list parser and scheduler.

Provides an offline-capable, Git-versioned task backlog and dependency DAG
for supervisor loops (Astral Resonance Director) and Parcimonia routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import Task
from .continuation import TaskDifficulty

__all__ = [
    "KanbanBoard",
    "KanbanStatus",
    "KanbanTask",
    "parse_kanban_markdown",
    "kanban_to_jobs_payload",
    "export_kanban_mirror",
    "sync_kanban_mirror",
    "WorkClass",
    "Severity",
    "Horizon",
    "schedule_key",
]


class KanbanStatus(str, Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    BLOCKED = "BLOCKED"


class WorkClass(str, Enum):
    SECURITY = "security"
    BUG = "bug"
    FEATURE = "feature"
    CHORE = "chore"
    UNSPECIFIED = "unspecified"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNSPECIFIED = "unspecified"


class Horizon(str, Enum):
    NEAR = "near"
    MID = "mid"
    FAR = "far"
    UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class KanbanTask:
    task_id: str
    title: str
    status: KanbanStatus
    priority: str = "p1"
    difficulty: TaskDifficulty = TaskDifficulty.COMPACT
    requires_browser: bool = False
    dependencies: tuple[str, ...] = ()
    deadline: str | None = None
    work_class: WorkClass = WorkClass.UNSPECIFIED
    severity: Severity = Severity.UNSPECIFIED
    horizon: Horizon = Horizon.UNSPECIFIED
    goal_ids: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be a nonempty string.")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be a nonempty string.")
        if not isinstance(self.status, KanbanStatus):
            raise TypeError("status must be a KanbanStatus enum.")
        if not isinstance(self.difficulty, TaskDifficulty):
            raise TypeError("difficulty must be a TaskDifficulty enum.")
        if not isinstance(self.work_class, WorkClass):
            raise TypeError("work_class must be a WorkClass enum.")
        if not isinstance(self.severity, Severity):
            raise TypeError("severity must be a Severity enum.")
        if not isinstance(self.horizon, Horizon):
            raise TypeError("horizon must be a Horizon enum.")

    def to_task(self) -> Task:
        """Convert to a Parcimonia Task instance."""
        risk = "high" if self.priority.lower() == "p0" else "low"
        if self.work_class is WorkClass.SECURITY and self.severity is Severity.CRITICAL:
            risk = "critical"
        elif self.work_class in (WorkClass.SECURITY, WorkClass.BUG) and self.severity in (
            Severity.CRITICAL,
            Severity.HIGH,
        ):
            risk = "high"
        return Task(
            task_id=self.task_id,
            kind="kanban_job",
            inputs={"title": self.title, "priority": self.priority},
            risk_class=risk,
        )


def _fold(value: str) -> str:
    table = str.maketrans("éèêëàâäùûüôöîïç", "eeeeaaauuuooiic")
    return value.casefold().translate(table)


def _parse_work_class(raw: str) -> WorkClass:
    token = _fold(raw).strip()
    if token in ("securite", "security", "secu", "safety"):
        return WorkClass.SECURITY
    if token in ("bug", "defect", "regression", "faille"):
        return WorkClass.BUG
    if token in ("chore", "maintenance", "dette"):
        return WorkClass.CHORE
    if token in ("feature", "ajout", "enhancement", "fonctionnalite"):
        return WorkClass.FEATURE
    return WorkClass.UNSPECIFIED


def _parse_severity(raw: str) -> Severity:
    token = _fold(raw).strip()
    if token in ("critique", "critical", "crit", "p0-sec"):
        return Severity.CRITICAL
    if token in ("haute", "high", "haut", "majeur"):
        return Severity.HIGH
    if token in ("moyenne", "medium", "moyen", "modere"):
        return Severity.MEDIUM
    if token in ("basse", "low", "bas", "mineur"):
        return Severity.LOW
    return Severity.UNSPECIFIED


def _parse_horizon(raw: str) -> Horizon:
    token = _fold(raw).strip()
    if token in ("court", "near", "short", "jour", "semaine"):
        return Horizon.NEAR
    if token in ("moyen", "mid", "medium-term", "trimestre"):
        return Horizon.MID
    if token in ("long", "far", "long-term", "annee"):
        return Horizon.FAR
    return Horizon.UNSPECIFIED


def schedule_key(
    task: KanbanTask,
    goal_ranks: Mapping[str, int] | None = None,
) -> tuple[int, int, int, int, int, str]:
    """Lower is sooner: safety, in-progress, human goals, prio, horizon."""
    severity = task.severity
    if task.work_class is WorkClass.SECURITY and severity is Severity.UNSPECIFIED:
        severity = Severity.HIGH
    if task.work_class is WorkClass.BUG and severity is Severity.UNSPECIFIED:
        severity = Severity.MEDIUM
    class_rank = {
        (WorkClass.SECURITY, Severity.CRITICAL): 0,
        (WorkClass.BUG, Severity.CRITICAL): 1,
        (WorkClass.SECURITY, Severity.HIGH): 2,
        (WorkClass.BUG, Severity.HIGH): 3,
        (WorkClass.SECURITY, Severity.MEDIUM): 4,
        (WorkClass.BUG, Severity.MEDIUM): 5,
        (WorkClass.SECURITY, Severity.LOW): 6,
        (WorkClass.BUG, Severity.LOW): 7,
    }.get((task.work_class, severity), 8)
    status_rank = 0 if task.status is KanbanStatus.IN_PROGRESS else 1
    goal_rank = 999
    if task.goal_ids:
        known = [goal_ranks[gid] for gid in task.goal_ids if goal_ranks and gid in goal_ranks]
        goal_rank = min(known) if known else 998
    prio_rank = {"p0": 0, "p1": 1, "p2": 2, "p3": 3, "p4": 4}.get(task.priority.lower(), 4)
    horizon_rank = {
        Horizon.NEAR: 0,
        Horizon.UNSPECIFIED: 1,
        Horizon.MID: 2,
        Horizon.FAR: 3,
    }[task.horizon]
    return (class_rank, status_rank, goal_rank, prio_rank, horizon_rank, task.task_id)


def _section_status(heading: str) -> KanbanStatus:
    low = heading.lower()
    if any(k in low for k in ["terminé", "termine", "done", "completed"]):
        return KanbanStatus.DONE
    if any(k in low for k in ["en cours", "in progress", "active", "doing"]):
        return KanbanStatus.IN_PROGRESS
    if any(k in low for k in ["bloqué", "bloque", "blocked", "on hold"]):
        return KanbanStatus.BLOCKED
    return KanbanStatus.TODO


def parse_kanban_markdown(content: str) -> KanbanBoard:
    """Parse a markdown file formatted as a local-first Kanban board."""
    tasks: list[KanbanTask] = []
    current_status = KanbanStatus.TODO

    item_re = re.compile(r"^-\s*\[([ xX])\]\s*[`]?([A-Za-z0-9_-]+)[`]?\s*(.*)$")
    tag_prio_re = re.compile(r"\[(p[0-4])\]", re.IGNORECASE)
    tag_diff_re = re.compile(r"\[(?:difficulté|difficulte|difficulty):\s*([^\]]+)\]", re.IGNORECASE)
    tag_tool_re = re.compile(r"\[(?:outil|tool):\s*([a-zA-Z0-9_-]+)\]", re.IGNORECASE)
    tag_class_re = re.compile(r"\[(?:classe|class|kind):\s*([^\]]+)\]", re.IGNORECASE)
    tag_sev_re = re.compile(r"\[(?:severite|severity|sev):\s*([^\]]+)\]", re.IGNORECASE)
    tag_horizon_re = re.compile(r"\[(?:horizon|terme|term):\s*([^\]]+)\]", re.IGNORECASE)
    tag_goal_re = re.compile(r"\[(?:but|goal|mission):\s*([A-Za-z0-9_-]+)\]", re.IGNORECASE)
    tag_deadline_re = re.compile(r"\[(?:échéance|echeance|deadline):\s*([0-9T:Z-]+)\]", re.IGNORECASE)
    dep_re = re.compile(r"(?:dépendances|dependances|dependencies)\s*:\s*[`]?(.*?)[`]?$", re.IGNORECASE)

    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#"):
            heading_text = line.lstrip("#").strip()
            current_status = _section_status(heading_text)
            i += 1
            continue

        match = item_re.match(line)
        if match:
            checked, task_id, rest = match.groups()
            status = KanbanStatus.DONE if checked.lower() == "x" else current_status

            prio_m = tag_prio_re.search(rest)
            priority = prio_m.group(1).lower() if prio_m else "p1"

            diff_m = tag_diff_re.search(rest)
            if diff_m:
                raw_diff = diff_m.group(1).lower()
                if raw_diff in ("déterministe", "determinisite", "deterministic", "rule"):
                    difficulty = TaskDifficulty.DETERMINISTIC
                elif raw_diff in ("raisonnement", "reasoning", "frontier", "hard"):
                    difficulty = TaskDifficulty.REASONING
                else:
                    difficulty = TaskDifficulty.COMPACT
            else:
                difficulty = TaskDifficulty.COMPACT

            tool_m = tag_tool_re.search(rest)
            requires_browser = bool(tool_m and "webbrain" in tool_m.group(1).lower())

            deadline_m = tag_deadline_re.search(rest)
            deadline = deadline_m.group(1) if deadline_m else None

            folded_rest = _fold(rest)
            class_m = tag_class_re.search(rest) or tag_class_re.search(folded_rest)
            work_class = _parse_work_class(class_m.group(1)) if class_m else WorkClass.UNSPECIFIED
            sev_m = tag_sev_re.search(rest) or tag_sev_re.search(folded_rest)
            severity = _parse_severity(sev_m.group(1)) if sev_m else Severity.UNSPECIFIED
            horizon_m = tag_horizon_re.search(rest) or tag_horizon_re.search(folded_rest)
            horizon = _parse_horizon(horizon_m.group(1)) if horizon_m else Horizon.UNSPECIFIED
            goal_ids = tuple(dict.fromkeys(tag_goal_re.findall(rest)))

            title = re.sub(r"\[[^\]]+\]", "", rest).strip(" :-")
            if not title:
                title = task_id

            dependencies: list[str] = []
            metadata: dict[str, str] = {}

            j = i + 1
            while j < len(lines) and (lines[j].startswith("  ") or lines[j].startswith("	")):
                sub = lines[j].strip()
                if sub.startswith("-"):
                    sub_clean = sub.lstrip("- ").strip()
                    if re.match(r"^(?:intitulé|intitule|title)\s*:", sub_clean, re.IGNORECASE):
                        title = sub_clean.split(":", 1)[1].strip()
                    dep_match = dep_re.search(sub_clean)
                    if dep_match:
                        raw_deps = dep_match.group(1).strip()
                        if raw_deps.lower() not in ("aucune", "none"):
                            dependencies.extend(
                                [d.strip(" `") for d in raw_deps.split(",") if d.strip(" `")]
                            )
                j += 1
            i = j - 1

            tasks.append(
                KanbanTask(
                    task_id=task_id,
                    title=title,
                    status=status,
                    priority=priority,
                    difficulty=difficulty,
                    requires_browser=requires_browser,
                    dependencies=tuple(dependencies),
                    deadline=deadline,
                    work_class=work_class,
                    severity=severity,
                    horizon=horizon,
                    goal_ids=goal_ids,
                    metadata=metadata,
                )
            )
        i += 1

    return KanbanBoard(tasks=tuple(tasks))


@dataclass(frozen=True)
class KanbanBoard:
    tasks: tuple[KanbanTask, ...]

    def get_task(self, task_id: str) -> KanbanTask | None:
        for t in self.tasks:
            if t.task_id == task_id:
                return t
        return None

    def eligible_tasks(self, goal_ranks: Mapping[str, int] | None = None) -> tuple[KanbanTask, ...]:
        completed_ids = {t.task_id for t in self.tasks if t.status == KanbanStatus.DONE}
        open_tasks = [
            t for t in self.tasks if t.status in (KanbanStatus.TODO, KanbanStatus.IN_PROGRESS)
        ]
        eligible = [t for t in open_tasks if all(dep in completed_ids for dep in t.dependencies)]
        return tuple(sorted(eligible, key=lambda task: schedule_key(task, goal_ranks)))

    def get_next_eligible_task(self, goal_ranks: Mapping[str, int] | None = None) -> KanbanTask | None:
        """Return the highest priority uncompleted task whose dependencies are done."""
        eligible = self.eligible_tasks(goal_ranks)
        return eligible[0] if eligible else None


def kanban_to_jobs_payload(board: KanbanBoard, project_name: str) -> list[dict[str, Any]]:
    """Convert uncompleted Kanban tasks into a payload compatible with Kanboard Neo agent jobs."""
    if not isinstance(board, KanbanBoard):
        raise TypeError("board must be a KanbanBoard instance.")
    if not isinstance(project_name, str) or not project_name.strip():
        raise ValueError("project_name must be a nonempty string.")

    payload: list[dict[str, Any]] = []
    for t in board.tasks:
        if t.status in (KanbanStatus.TODO, KanbanStatus.IN_PROGRESS):
            payload.append({
                "job_id": t.task_id,
                "title": t.title,
                "project": project_name.strip(),
                "status": "in_progress" if t.status == KanbanStatus.IN_PROGRESS else "queued",
                "priority": t.priority,
                "difficulty": t.difficulty.value,
                "requires_browser": t.requires_browser,
                "dependencies": list(t.dependencies),
                "deadline": t.deadline,
                "work_class": t.work_class.value,
                "severity": t.severity.value,
                "horizon": t.horizon.value,
                "goal_ids": list(t.goal_ids),
                "risk_class": "high" if t.priority.lower() == "p0" else "low",
            })
    return payload


def export_kanban_mirror(board: KanbanBoard, project_name: str, target_path: str | Path) -> Path:
    """Export a normalized JSON mirror of the Kanban board for offline caching and bridge ingestion."""
    payload = kanban_to_jobs_payload(board, project_name)
    path = Path(target_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(
            {
                "version": 1,
                "project": project_name.strip(),
                "total_jobs": len(payload),
                "jobs": payload,
            },
            fh,
            indent=2,
        )
    return path


def sync_kanban_mirror(
    board: KanbanBoard,
    project_name: str,
    *,
    endpoint_url: str = "http://127.0.0.1:8080/api/jobs",
    mirror_path: str | Path | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Export the local board mirror and attempt non-blocking sync to Kanboard Neo.

    Always exports the local mirror file if mirror_path is provided.
    If the endpoint is unreachable or errors, fails gracefully without raising,
    preserving local-first offline operation.
    """
    import urllib.request
    import urllib.error

    if mirror_path is not None:
        export_kanban_mirror(board, project_name, mirror_path)

    payload = kanban_to_jobs_payload(board, project_name)
    envelope = {
        "version": 1,
        "project": project_name.strip(),
        "total_jobs": len(payload),
        "jobs": payload,
    }

    data = json.dumps(envelope).encode("utf-8")
    req = urllib.request.Request(
        endpoint_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = getattr(resp, "status", 200)
            return {
                "synced": True,
                "status_code": status_code,
                "count": len(payload),
                "endpoint": endpoint_url,
            }
    except Exception as exc:
        return {
            "synced": False,
            "error": f"{type(exc).__name__}: {exc}",
            "count": len(payload),
            "endpoint": endpoint_url,
        }
