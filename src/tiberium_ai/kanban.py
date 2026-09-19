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
]


class KanbanStatus(str, Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    BLOCKED = "BLOCKED"


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

    def to_task(self) -> Task:
        """Convert to a Parcimonia Task instance."""
        risk = "high" if self.priority.lower() == "p0" else "low"
        return Task(
            task_id=self.task_id,
            kind="kanban_job",
            inputs={"title": self.title, "priority": self.priority},
            risk_class=risk,
        )


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
                    if re.match(r"^(?:intitulé|intitule|title)s*:", sub_clean, re.IGNORECASE):
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

    def get_next_eligible_task(self) -> KanbanTask | None:
        """Return the highest priority uncompleted task whose dependencies are done."""
        completed_ids = {t.task_id for t in self.tasks if t.status == KanbanStatus.DONE}

        candidates = [
            t for t in self.tasks if t.status in (KanbanStatus.TODO, KanbanStatus.IN_PROGRESS)
        ]

        eligible = [
            t for t in candidates if all(dep in completed_ids for dep in t.dependencies)
        ]

        if not eligible:
            return None

        def prio_key(task: KanbanTask) -> int:
            # IN_PROGRESS takes precedence over TODO (finish active work before pulling new)
            status_penalty = 0 if task.status == KanbanStatus.IN_PROGRESS else 10
            p = task.priority.lower()
            if p == "p0":
                return status_penalty + 0
            if p == "p1":
                return status_penalty + 1
            if p == "p2":
                return status_penalty + 2
            return status_penalty + 3

        return min(eligible, key=prio_key)


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
