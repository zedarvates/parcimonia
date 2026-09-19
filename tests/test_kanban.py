import pytest

from tiberium_ai.continuation import TaskDifficulty
from tiberium_ai.kanban import (
    KanbanBoard,
    KanbanStatus,
    KanbanTask,
    parse_kanban_markdown,
    kanban_to_jobs_payload,
    export_kanban_mirror,
)


SAMPLE_KANBAN = """# Local Project Tasks

## Backlog

- [ ] TASK-101 [P0] [difficulté: raisonnement] [échéance: 2026-09-25]
  - Intitulé : Refactorisation du superviseur
  - Dépendances : TASK-100

- [ ] TASK-102 [P2] [difficulté: déterministe]
  - Intitulé : Linter et typage
  - Dépendances : aucune

- [ ] TASK-103 [P1] [difficulté: compact] [outil: webbrain]
  - Intitulé : Audit du formulaire web

## En cours

- [ ] TASK-100 [P1] [difficulté: compact]
  - Intitulé : Setup de la base locale

## Terminé

- [x] TASK-099 [P0]
  - Intitulé : Initialisation du projet
"""


def test_parse_kanban_structure():
    board = parse_kanban_markdown(SAMPLE_KANBAN)
    assert len(board.tasks) == 5

    t99 = board.get_task("TASK-099")
    assert t99 is not None
    assert t99.status == KanbanStatus.DONE
    assert t99.priority == "p0"

    t100 = board.get_task("TASK-100")
    assert t100 is not None
    assert t100.status == KanbanStatus.IN_PROGRESS
    assert t100.difficulty == TaskDifficulty.COMPACT

    t101 = board.get_task("TASK-101")
    assert t101 is not None
    assert t101.priority == "p0"
    assert t101.difficulty == TaskDifficulty.REASONING
    assert t101.dependencies == ("TASK-100",)
    assert t101.deadline == "2026-09-25"

    t102 = board.get_task("TASK-102")
    assert t102 is not None
    assert t102.difficulty == TaskDifficulty.DETERMINISTIC
    assert t102.dependencies == ()

    t103 = board.get_task("TASK-103")
    assert t103 is not None
    assert t103.requires_browser is True


def test_get_next_eligible_task_with_dependencies():
    board = parse_kanban_markdown(SAMPLE_KANBAN)
    next_task = board.get_next_eligible_task()
    assert next_task is not None
    assert next_task.task_id == "TASK-100"


def test_get_next_eligible_when_dependency_resolved():
    updated = SAMPLE_KANBAN.replace("- [ ] TASK-100", "- [x] TASK-100")
    board = parse_kanban_markdown(updated)
    next_task = board.get_next_eligible_task()
    assert next_task is not None
    assert next_task.task_id == "TASK-101"


def test_to_parcimonia_task():
    board = parse_kanban_markdown(SAMPLE_KANBAN)
    t101 = board.get_task("TASK-101")
    assert t101 is not None
    task_obj = t101.to_task()
    assert task_obj.task_id == "TASK-101"
    assert task_obj.risk_class == "high"


def test_export_kanban_mirror(tmp_path):
    from tiberium_ai.kanban import export_kanban_mirror, kanban_to_jobs_payload
    import json

    board = parse_kanban_markdown(SAMPLE_KANBAN)
    payload = kanban_to_jobs_payload(board, "parcimonia")
    assert len(payload) == 4  # 4 uncompleted tasks

    out_path = tmp_path / "mirror.json"
    exported = export_kanban_mirror(board, "parcimonia", out_path)
    assert exported.exists()

    data = json.loads(exported.read_text(encoding="utf-8"))
    assert data["project"] == "parcimonia"
    assert data["total_jobs"] == 4
    assert data["jobs"][0]["job_id"] == "TASK-101"


def test_kanban_to_jobs_payload_and_export(tmp_path):
    board = parse_kanban_markdown(SAMPLE_KANBAN)
    # Only uncompleted tasks (TODO and IN_PROGRESS) are included (4 out of 5)
    payload = kanban_to_jobs_payload(board, "TiberiumAI")
    assert len(payload) == 4

    job_ids = [j["job_id"] for j in payload]
    assert "TASK-099" not in job_ids  # TASK-099 is DONE
    assert "TASK-100" in job_ids
    assert "TASK-101" in job_ids

    job_101 = next(j for j in payload if j["job_id"] == "TASK-101")
    assert job_101["priority"] == "p0"
    assert job_101["risk_class"] == "high"
    assert job_101["dependencies"] == ["TASK-100"]
    assert job_101["project"] == "TiberiumAI"

    # Test mirror export
    mirror_file = tmp_path / "jobs_mirror.json"
    exported = export_kanban_mirror(board, "TiberiumAI", mirror_file)
    assert exported.is_file()
    assert exported.stat().st_size > 0

    import json
    data = json.loads(exported.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["project"] == "TiberiumAI"
    assert data["total_jobs"] == 4
