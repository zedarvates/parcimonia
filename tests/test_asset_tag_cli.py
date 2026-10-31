"""Exercise persisted review snapshots without changing the source catalogue."""

import json
import os
import subprocess
import sys

import pytest

from tiberium_ai.asset_cli import MAX_JOURNAL_BYTES, _write_journal_new, main
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import append_tag_decision, create_tag_journal, validate_tag_journal
from tiberium_ai.verification import hash_input


def _report():
    return inspect_asset(b"A robot.", filename="notes.txt", source_id="fixture", revision="v1", topic_terms={"robotique": ["robot"]})


def _setup(tmp_path):
    report = tmp_path / "report.json"
    catalogue = tmp_path / "catalogue.json"
    data = _report()
    report.write_text(json.dumps(data), encoding="utf-8")
    catalogue.write_text(json.dumps([data]), encoding="utf-8")
    return report, catalogue


def _decision_args(report, journal, output, *, action="accept", head="none", event="e1", actor="fixture:reviewer", reason="Fixture decision."):
    return ["review-tag", str(report), str(journal), "--tag", "topic:robotique", "--decision", action, "--actor", actor, "--reason", reason, "--event-id", event, "--expected-head", head, "--out", str(output)]


def test_decision_survives_file_reload_and_search(tmp_path, capsys):
    report, catalogue = _setup(tmp_path)
    initial, accepted = tmp_path / "journal0.json", tmp_path / "journal1.json"
    original = {path: path.read_bytes() for path in (report, catalogue)}
    assert main(["review-init", str(initial)]) == 0
    init_output = json.loads(capsys.readouterr().out)
    assert init_output["head_hash"] is None
    assert init_output["event_count"] == 0
    assert main(_decision_args(report, initial, accepted)) == 0
    written = json.loads(capsys.readouterr().out)
    assert written["event_created"] is True
    saved = json.loads(accepted.read_text(encoding="utf-8"))
    validate_tag_journal(saved)
    assert saved["head_hash"] == written["head_hash"]
    assert json.loads(initial.read_text(encoding="utf-8"))["events"] == []
    assert main(["search-reviewed", str(catalogue), str(accepted), "--tag", "topic:robotique"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found["count"] == 1
    assert found["matches"][0]["tag_states"][0]["status"] == "accepted"
    assert {path: path.read_bytes() for path in original} == original


@pytest.mark.parametrize("target", ["report", "catalogue", "journal"])
def test_existing_output_is_never_overwritten(tmp_path, capsys, target):
    report, catalogue = _setup(tmp_path)
    initial = tmp_path / "journal0.json"
    assert main(["review-init", str(initial)]) == 0
    capsys.readouterr()
    path = {"report": report, "catalogue": catalogue, "journal": initial}[target]
    before = path.read_bytes()
    assert main(_decision_args(report, initial, path)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"] == "FileExistsError"
    assert path.read_bytes() == before


def test_stale_expected_head_creates_no_output(tmp_path, capsys):
    report, _ = _setup(tmp_path)
    first, second, refused = [tmp_path / name for name in ("j0.json", "j1.json", "refused.json")]
    assert main(["review-init", str(first)]) == 0
    capsys.readouterr()
    assert main(_decision_args(report, first, second)) == 0
    capsys.readouterr()
    assert main(_decision_args(report, second, refused, action="reject", event="e2")) == 2
    assert not refused.exists()
    assert capsys.readouterr().out == ""


def test_old_idempotent_retry_does_not_restore_an_overridden_accept(tmp_path, capsys):
    report, catalogue = _setup(tmp_path)
    initial, first, second, retry = [tmp_path / name for name in ("j0.json", "j1.json", "j2.json", "retry.json")]
    assert main(["review-init", str(initial)]) == 0
    capsys.readouterr()
    assert main(_decision_args(report, initial, first)) == 0
    head = json.loads(capsys.readouterr().out)["head_hash"]
    assert main(_decision_args(report, first, second, action="reject", head=head, event="e2")) == 0
    capsys.readouterr()
    assert main(_decision_args(report, second, retry)) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["event_created"] is False
    assert output["event_count"] == 2
    assert main(["search-reviewed", str(catalogue), str(retry), "--tag", "topic:robotique"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 0
    assert main(["search-reviewed", str(catalogue), str(retry), "--tag", "topic:robotique", "--state", "rejected"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 1


def test_reset_preserves_history_and_returns_to_proposed(tmp_path, capsys):
    report, catalogue = _setup(tmp_path)
    initial, first, reset = [tmp_path / name for name in ("j0.json", "j1.json", "reset.json")]
    assert main(["review-init", str(initial)]) == 0
    capsys.readouterr()
    assert main(_decision_args(report, initial, first)) == 0
    head = json.loads(capsys.readouterr().out)["head_hash"]
    assert main(_decision_args(report, first, reset, action="reset", event="e2", head=head)) == 0
    capsys.readouterr()
    assert main(["review-view", str(catalogue), str(reset)]) == 0
    result = json.loads(capsys.readouterr().out)
    tag = next(t for t in result["assets"][0]["tags"] if t["namespace"] == "topic")
    assert tag["status"] == "proposed"
    assert tag["decision"]["event_id"] == "e2"
    assert len(json.loads(reset.read_text(encoding="utf-8"))["events"]) == 2


@pytest.mark.parametrize("content", ['{"schema":1,"schema":2}', '{"events":[NaN]}', '{', '[]'])
def test_malformed_journal_is_refused_without_output_file(tmp_path, capsys, content):
    report, _ = _setup(tmp_path)
    bad, output = tmp_path / "bad.json", tmp_path / "new.json"
    bad.write_text(content, encoding="utf-8")
    assert main(_decision_args(report, bad, output)) == 2
    assert capsys.readouterr().out == ""
    assert not output.exists()


def test_non_ascii_actor_reason_survive_utf8_storage_and_ascii_stdout(tmp_path):
    report, _ = _setup(tmp_path)
    initial, updated = tmp_path / "j0.json", tmp_path / "j1.json"
    command = [sys.executable, "-m", "tiberium_ai.asset_cli"]
    environment = dict(os.environ, PYTHONIOENCODING="ascii")
    first = subprocess.run(command + ["review-init", str(initial)], capture_output=True, env=environment, timeout=10)
    assert first.returncode == 0, first.stderr
    second = subprocess.run(command + _decision_args(report, initial, updated, actor="opérateur", reason="Révision vérifiée sur fixture."), capture_output=True, env=environment, timeout=10)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout.decode("ascii"))["event_count"] == 1
    saved = json.loads(updated.read_text(encoding="utf-8"))
    assert saved["events"][0]["actor_id"] == "opérateur"
    assert saved["events"][0]["reason"] == "Révision vérifiée sur fixture."


def test_demo_preserves_reviews_and_invalidates_changed_revision():
    result = subprocess.run([sys.executable, "examples/asset_tag_review_demo.py"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["before_review"]["count"] == 0
    assert report["after_review"]["count"] == 1
    assert report["rejected_tags"]["count"] == 1
    assert report["after_reset"]["count"] == 0
    assert report["history_preserved"] is True
    assert report["changed_revision"]["unapplied_events"]


def test_writer_refuses_a_valid_journal_that_its_reader_could_not_load(tmp_path):
    journal = append_tag_decision(
        create_tag_journal(), _report(), namespace="topic", value="robotique",
        action="accept", actor_id="🤖" * 256, reason="🤖" * 2048,
        event_id="e0", expected_head=None,
    )
    template = dict(journal["events"][0])
    for index in range(1, 900):
        event = dict(template, event_id=f"e{index}", sequence=index + 1, previous_hash=journal["head_hash"])
        event.pop("event_hash")
        event["event_hash"] = hash_input(event)
        journal["events"].append(event)
        journal["head_hash"] = event["event_hash"]
    validate_tag_journal(journal)
    assert len((json.dumps(journal, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")) > MAX_JOURNAL_BYTES
    target = tmp_path / "must-not-be-created.json"
    with pytest.raises(ValueError, match="8 MiB"):
        _write_journal_new(str(target), journal)
    assert not target.exists()
