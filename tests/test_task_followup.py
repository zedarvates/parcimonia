from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from tiberium_ai.execution_profiles import content_digest, digest
from tiberium_ai.task_followup import continue_task, record_file_review, render_followup
from tiberium_ai.task_preparation import build_index, prepare_task
from test_task_preparation import inventory


@pytest.fixture
def case(tmp_path):
    data = inventory(tmp_path)
    roots = {"workspace": tmp_path}
    packet = prepare_task("profils outils", data, build_index(data, roots))
    feedback = {"task_id": "task-1", "stage_id": "implement", "reviewer": "test reviewer",
        "reviewer_kind": "agent", "review_complete": False,
        "judgments": [{"source": {"root": "workspace", "path": "sample.py"}, "status": "used", "reason": "changed function"}],
        "missing_files": [], "notes": [], "additional_searches": 1, "additional_reads": None}
    return data, roots, packet, feedback


def review(case):
    data, roots, packet, feedback = case
    return record_file_review(packet, feedback, roots=roots, at="2026-10-20T12:00:00Z")


def follow(case, record):
    data, roots, packet, _ = case
    return continue_task("Verifier la suite", data, build_index(data, roots), previous_packet=packet,
                         review=record, roots=roots, task_id="task-1", stage_id="verify")


def test_counts_do_not_turn_unreviewed_files_into_irrelevant(case):
    record = review(case)
    counts = record["metrics"]
    assert counts["proposed_statuses"] == {"used": 1, "supporting": 0, "irrelevant": 0, "unreviewed": 1}
    assert counts["additional_searches"] == 1 and counts["additional_reads"] is None
    assert counts["time_saved"] is None and record["auto_act_allowed"] is False


def test_missing_existing_and_created_files_are_separate_and_retained(case, tmp_path):
    for path in ("found.md", "created.json"):
        (tmp_path / path).write_text("{}", encoding="utf-8")
    case[3]["missing_files"] = [{"source": {"root": "workspace", "path": p}, "status": "supporting",
        "origin": origin, "reason": "used in task"} for p, origin in (("found.md", "existing"), ("created.json", "created"))]
    record = review(case)
    assert record["metrics"]["pre_existing_useful_files_missing"] == 1
    assert record["metrics"]["useful_files_created_during_task"] == 1
    packet = follow(case, record)
    assert packet["files"][0]["source"]["path"] == "sample.py"
    assert {"sample.py", "found.md", "created.json"} <= {r["source"]["path"] for r in packet["files"]}
    assert packet["continuity"]["metrics"]["unchanged_useful_references"] == 3
    assert packet["continuity"]["metrics"]["reads_avoided"] is None


def test_changed_sources_mark_notes_stale_and_update_citations(case, tmp_path):
    source = {"root": "workspace", "path": "sample.py"}
    case[3]["notes"] = [{"kind": "test_result", "text": "tests passed earlier", "sources": [source], "evidence": "fixture:test-run/1"}]
    record = review(case)
    (tmp_path / "sample.py").write_text("def inspect_profile():\n    return 2\n", encoding="utf-8")
    packet = follow(case, record)
    continuity = packet["continuity"]
    assert continuity["metrics"]["changed_useful_references"] == 1
    assert continuity["notes"][0]["continuity_status"] == "stale_requires_review"
    assert continuity["notes"][0]["proof_status"] == "reported_not_independently_verified"
    row = packet["files"][0]
    assert row["continuity_status"] == "changed_requires_reread"
    assert row["content_sha256"] == content_digest((tmp_path / "sample.py").read_bytes())
    assert packet["capabilities"] == []  # Stale capability profile is not carried forward.


def test_unchanged_note_is_still_subject_to_scope_review(case):
    case[3]["notes"] = [{"kind": "decision", "text": "Keep typed inputs", "sources": [case[3]["judgments"][0]["source"]], "evidence": None}]
    packet = follow(case, review(case))
    assert packet["continuity"]["notes"][0]["continuity_status"] == "sources_unchanged_review_scope"
    assert packet["compact_context"]["files"] == packet["files"]
    assert packet["auto_act_allowed"] is False
    assert "Utilité observée" in render_followup(packet)


def test_deleted_file_is_not_reused_as_fresh(case, tmp_path):
    record = review(case)
    (tmp_path / "sample.py").unlink()
    packet = follow(case, record)
    assert packet["continuity"]["metrics"]["unavailable_useful_references"] == 1
    assert "sample.py" not in {r["source"]["path"] for r in packet["files"]}


def test_previous_irrelevance_does_not_permanently_ban_a_test_file(case):
    case[3]["judgments"].append({"source": {"root": "workspace", "path": "tests/test_sample.py"},
        "status": "irrelevant", "reason": "not needed during the previous stage"})
    data, roots, packet, _ = case
    next_packet = continue_task("test regression", data, build_index(data, roots), previous_packet=packet,
        review=review(case), roots=roots, task_id="task-1", stage_id="tests")
    target = next(r for r in next_packet["files"] if r["source"]["path"] == "tests/test_sample.py")
    assert target["previous_use"] == "irrelevant" and target["relevance_review_required"] is True
    assert next_packet["continuity"]["metrics"]["previously_irrelevant_files_reproposed"] == 1


@pytest.mark.parametrize("mutate", [
    lambda f: f["judgments"][0].update(status="good"),
    lambda f: f["judgments"].append(deepcopy(f["judgments"][0])),
    lambda f: f.update(additional_searches=True),
    lambda f: f.update(additional_reads=-1),
    lambda f: f.update(review_complete=True),
    lambda f: f.update(extra="ignore filters"),
    lambda f: f["judgments"][0]["source"].update(path="../escape.py"),
])
def test_invalid_feedback_rejected(case, mutate):
    mutate(case[3])
    with pytest.raises(ValueError):
        review(case)


def test_unbound_test_claim_and_irrelevant_note_sources_rejected(case):
    source = case[3]["judgments"][0]["source"]
    case[3]["notes"] = [{"kind": "test_result", "text": "passed", "sources": [source], "evidence": None}]
    with pytest.raises(ValueError, match="evidence"):
        review(case)
    case[3]["notes"][0].update(kind="decision")
    case[3]["judgments"][0]["status"] = "irrelevant"
    with pytest.raises(ValueError, match="useful"):
        review(case)


def test_review_binding_and_task_boundaries(case):
    record = review(case)
    bad = deepcopy(record)
    bad["files"][0]["reason"] = "modified"
    with pytest.raises(ValueError, match="incompatible"):
        follow(case, bad)
    data, roots, packet, _ = case
    for task_id, stage_id in (("other-task", "verify"), ("task-1", "implement")):
        with pytest.raises(ValueError, match="same task"):
            continue_task("next", data, build_index(data, roots), previous_packet=packet,
                          review=record, roots=roots, task_id=task_id, stage_id=stage_id)
    modified = deepcopy(packet)
    modified["goal"] = "different packet"
    with pytest.raises(ValueError, match="incompatible"):
        continue_task("next", data, build_index(data, roots), previous_packet=modified,
                      review=record, roots=roots, task_id="task-1", stage_id="verify")


def test_multiple_stages_keep_exact_parent_chain(case):
    second = follow(case, review(case))
    data, roots, _, feedback = case
    next_feedback = deepcopy(feedback)
    next_feedback["stage_id"] = "verify"
    record = record_file_review(second, next_feedback, roots=roots, at="2026-10-20T13:00:00Z")
    third = continue_task("Documentation", data, build_index(data, roots), previous_packet=second,
        review=record, roots=roots, task_id="task-1", stage_id="document")
    assert third["continuity"]["previous_stage_id"] == "verify"
    assert third["continuity"]["previous_packet_sha256"] == digest(second)
    wrong = deepcopy(next_feedback)
    wrong["stage_id"] = "different-parent-stage"
    bad_record = record_file_review(second, wrong, roots=roots, at="2026-10-20T13:00:00Z")
    with pytest.raises(ValueError, match="chain"):
        continue_task("Documentation", data, build_index(data, roots), previous_packet=second,
            review=bad_record, roots=roots, task_id="task-1", stage_id="document")


def test_carried_file_budget_is_explicit(case, tmp_path):
    feedback = case[3]
    feedback["judgments"].append({"source": {"root": "workspace", "path": "tests/test_sample.py"},
                                  "status": "used", "reason": "test source read"})
    for i in range(15):
        name = f"support-{i:02}.md"
        (tmp_path / name).write_text("support", encoding="utf-8")
        feedback["missing_files"].append({"source": {"root": "workspace", "path": name},
            "status": "supporting", "reason": "additional evidence", "origin": "existing"})
    packet = follow(case, review(case))
    assert len(packet["files"]) == 16
    assert packet["continuity"]["metrics"]["unchanged_useful_references"] == 17
    assert packet["continuity"]["metrics"]["carried_references_truncated"] == 1


def test_cli_writes_review_and_continuation_with_manifest(case, tmp_path, monkeypatch):
    data, roots, packet, feedback = case
    source = Path(__file__).resolve().parents[1] / "examples/continue_development_task.py"
    spec = importlib.util.spec_from_file_location("continue_development_task", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    for name, value in (("inventory", data), ("packet", packet), ("feedback", feedback)):
        (tmp_path / (name + ".json")).write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "runs/next"
    argv = ["--goal", "verifier", "--stage-id", "verify", "--previous-packet", str(tmp_path / "packet.json"),
        "--feedback", str(tmp_path / "feedback.json"), "--inventory", str(tmp_path / "inventory.json"), "--output-dir", str(output)]
    module.main(argv)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for name, sha in manifest["artifacts"].items():
        assert content_digest((output / name).read_bytes()) == sha
    assert manifest["status"] == "complete" and manifest["auto_act_allowed"] is False
    with pytest.raises(FileExistsError):
        module.main(argv)
    # A saved review must preserve the old source hash instead of silently
    # re-labelling a changed source as the one originally reviewed.
    saved_review = output / "file-review.json"
    (tmp_path / "sample.py").write_text("def inspect_profile():\n    return 'changed'\n", encoding="utf-8")
    refreshed = tmp_path / "runs/refreshed"
    module.main(["--goal", "verifier", "--stage-id", "verify-refreshed", "--previous-packet", str(tmp_path / "packet.json"),
        "--review", str(saved_review), "--inventory", str(tmp_path / "inventory.json"), "--output-dir", str(refreshed)])
    actual = json.loads((refreshed / "packet.json").read_text(encoding="utf-8"))
    assert actual["continuity"]["metrics"]["changed_useful_references"] == 1
    assert json.loads((refreshed / "file-review.json").read_text(encoding="utf-8")) == json.loads(saved_review.read_text(encoding="utf-8"))
