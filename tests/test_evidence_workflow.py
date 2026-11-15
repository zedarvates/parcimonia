from hashlib import sha256
import json
import subprocess

import pytest

from tiberium_ai import evidence_run as run
from tiberium_ai import evidence_workflow as flow
from tiberium_ai.repo_evidence import select_repository_evidence


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "sources"
    root.mkdir()
    (root / "tests").mkdir()
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    (root / "calc.py").write_text("def increment(value):\n    return value + 1\n", encoding="utf-8")
    (root / "README.md").write_text("# Sample project\n", encoding="utf-8")
    (root / "tests/test_calc.py").write_text(
        "from calc import increment\n\ndef test_increment():\n    assert increment(1) in (2, 3)\n",
        encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Local fixture", "-c", "user.email=fixture@example.invalid",
         "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    return root


def test_diff_and_resume_track_real_coverage_and_invalidate_changed_results(checkout, tmp_path):
    pytest.importorskip("pytest_cov")
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = --invalid-parent-option\n", encoding="ascii")
    target = checkout / "calc.py"
    target.write_text("def increment(value):\n    return value + 2\n", encoding="utf-8")
    before = flow.diff_packet(checkout, "HEAD", [])
    change = before["files"][0]
    assert change["preview"] == ["-    return value + 1", "+    return value + 2"]
    assert change["test_candidates"][0]["test"] == "test_increment"
    assert "test trouvé, résultat non vérifié" in flow.render(before)
    folder = tmp_path / "run"
    proof = run.capture_pytest(checkout, "tests/test_calc.py::test_increment", folder)
    receipt = folder / "receipt.json"
    assert proof["outcome"] == "passed" and proof["bound"], (folder / "pytest.log").read_text()
    observed = flow.diff_packet(checkout, "HEAD", [receipt])["files"][0]
    assert observed["observed_tests"][0]["lines"] == [2]
    assert observed["changed_lines_without_execution_trace"] == 0
    source_packet = select_repository_evidence("Find `calc.py` and README", {
        "calc.py": target.read_bytes(), "README.md": (checkout / "README.md").read_bytes()})
    packet_path = tmp_path / "previous.json"
    packet_path.write_text(json.dumps(source_packet), encoding="utf-8")
    saved = tmp_path / "checkpoint.json"
    flow.checkpoint(checkout, ["calc.py", "README.md"], [receipt], saved, evidence=packet_path)
    unchanged = flow.resume(checkout, saved)
    assert unchanged["files_unchanged"] == 2 and not unchanged["files_to_review"]
    assert unchanged["source_references_unchanged"] == 2
    assert unchanged["valid_test_evidence"][0]["status"] == "passed"
    target.write_text("def increment(value):\n    return value + 3\n", encoding="utf-8")
    changed = flow.resume(checkout, saved)
    assert changed["files_to_review"] == [{"path": "calc.py", "state": "changed_requires_reread"}]
    assert changed["source_references_unchanged"] == changed["source_references_stale"] == 1
    assert not changed["valid_test_evidence"] and len(changed["tests_to_rerun"]) == 1
    after = flow.diff_packet(checkout, "HEAD", [receipt])
    assert not after["files"][0]["observed_tests"]
    assert after["files"][0]["changed_lines_without_execution_trace"] == 1


def test_environment_untracked_and_tampering_cannot_reuse_result(checkout, tmp_path, monkeypatch):
    folder = tmp_path / "run"
    proof = run.capture_pytest(checkout, "tests/test_calc.py::test_increment", folder, coverage=False)
    assert proof["bound"] and proof["outcome"] == "passed"
    saved = folder / "receipt.json"
    monkeypatch.setenv("PARCIMONIA_TEST_ENV_TEST", "changed")
    assert run.current_receipt(saved, run.snapshot(checkout))["reason"] == "stale_revision_tree_or_environment"
    (checkout / "local.py").write_text("x = 1\n")
    assert run.current_receipt(saved, run.snapshot(checkout))["reason"] == "scope_unverified"
    (folder / "junit.xml").write_text("<testsuite/>")
    with pytest.raises(ValueError, match="artifact changed"):
        run.current_receipt(saved, run.snapshot(checkout))


def test_logs_keep_distinct_quiet_runs_and_first_error_context(tmp_path):
    log = tmp_path / "pytest.log"
    text = ("start first\nE   ValueError: address 0x1\nE   ValueError: address 0x2\n"
            "1 failed in 0.02s\nstart second\nE   ValueError: address 0x1\n1 failed in 0.03s\n")
    log.write_bytes(text.encode())
    packet = flow.log_packet(log)
    assert [r["errors"][0]["count"] for r in packet["segments"]] == [2, 1]
    assert [r["errors"][0]["first_line"] for r in packet["segments"]] == [2, 6]
    assert packet["segments"][0]["errors"][0]["excerpt"][0]["line"] == 1
    assert str(log.as_posix()) + ":2" in flow.render(packet)
    assert packet["sha256"] == sha256(log.read_bytes()).hexdigest() and log.read_bytes() == text.encode()


def test_auto_log_prefers_complete_short_text_but_bounds_large_raw_output(tmp_path):
    log = tmp_path / "pytest.log"
    log.write_bytes(b"\x1b[31mE   ValueError: wrong value\x1b[0m\n1 failed in 0.02s\n")
    auto = flow.log_packet(log, view="auto")
    assert auto["view"] == "raw" and auto["terminal_controls_removed"]
    assert auto["lines"] == ["E   ValueError: wrong value", "1 failed in 0.02s"]
    assert auto["first_errors"] == [1] and "\x1b" not in flow.render(auto)
    assert b"\x1b" in log.read_bytes()
    log.write_text("ordinary output\n" * 4000 + "1 passed in 0.02s\n")
    assert flow.log_packet(log, view="auto")["view"] == "excerpts"
    with pytest.raises(ValueError, match="raw display"):
        flow.log_packet(log, view="raw")


def test_unrecognized_log_keeps_short_source_and_discloses_long_unknown_format(tmp_path):
    log = tmp_path / "unknown.log"
    log.write_text("text without a recognized marker\n")
    assert flow.log_packet(log, view="auto")["view"] == "raw"
    log.write_text("text without a recognized marker\n" * 4000)
    packet = flow.log_packet(log, view="auto")
    assert packet["view"] == "excerpts" and not packet["recognized"]
    assert "Aucun résumé ni motif d’erreur reconnu" in flow.render(packet)


def test_resume_rechecks_membership_after_git_index_changes(checkout, tmp_path, monkeypatch):
    saved = tmp_path / "checkpoint.json"
    flow.checkpoint(checkout, ["calc.py"], [], saved)
    original = flow.tracked
    calls = []

    def count(root):
        calls.append(root)
        return original(root)

    monkeypatch.setattr(flow, "tracked", count)
    assert flow.resume(checkout, saved)["files_unchanged"] == 1
    assert not calls
    _git(checkout, "rm", "--cached", "--", "calc.py")
    assert (checkout / "calc.py").is_file()
    assert flow.resume(checkout, saved)["files_to_review"] == [{"path": "calc.py", "state": "unavailable"}]
    assert len(calls) == 1


def test_resume_finds_external_changes_without_replaying_preexisting_edits(checkout, tmp_path):
    (checkout / "draft.md").write_text("already here\n", encoding="ascii")
    (checkout / "README.md").write_text("already dirty\n", encoding="ascii")
    saved = tmp_path / "checkpoint.json"
    flow.checkpoint(checkout, ["calc.py"], [], saved)
    assert flow.resume(checkout, saved)["repository_delta"]["files"] == []
    (checkout / "README.md").write_text("edited since checkpoint\n", encoding="ascii")
    (checkout / "new.py").write_text("new_feature = True\n", encoding="ascii")
    (checkout / "tests/test_calc.py").unlink()
    (checkout / ".env").write_text("SECRET=value\n", encoding="ascii")
    delta = flow.resume(checkout, saved)["repository_delta"]
    assert delta["status"] == "ready"
    assert [(f["path"], f["state"]) for f in delta["files"]] == [
        ("new.py", "new"), ("README.md", "modified"), ("tests/test_calc.py", "deleted")]
    assert all(f["test_result"] == "unverified" for f in delta["files"])
    assert flow.resume(checkout, saved, repository_delta=False)["repository_delta"]["status"] == "disabled"


def test_resume_finds_committed_new_and_modified_files_across_revisions(checkout, tmp_path):
    saved = tmp_path / "checkpoint.json"
    flow.checkpoint(checkout, ["calc.py"], [], saved)
    (checkout / "README.md").write_text("doc update\n", encoding="ascii")
    (checkout / "new.py").write_text("new_feature = True\n", encoding="ascii")
    _git(checkout, "add", ".")
    _git(checkout, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "-c", "commit.gpgsign=false", "commit", "-qm", "next")
    delta = flow.resume(checkout, saved)["repository_delta"]
    assert [(f["path"], f["state"]) for f in delta["files"]] == [("new.py", "new"), ("README.md", "modified")]


def test_exact_references_get_reserved_slots_and_ambiguity_stays_visible():
    files = {"README.md": b"# Manual\n", "docs/README.md": b"# Docs\n",
             "src/worker.py": b"def archive_receipt():\n    return True\n",
             "src/lexical.py": b"transaction transaction transaction\n"}
    out = select_repository_evidence("Transaction, README and `archive_receipt`", files, limit=2)
    assert [f["path"] for lane in out["roles"].values() for f in lane] == ["src/worker.py", "README.md"]
    assert all(ref["status"] == "selected" for ref in out["exact_references"])
    files["src/duplicate.py"] = files["src/worker.py"]
    out = select_repository_evidence("Archive receipts", files, references=["@archive_receipt"])
    ref = out["exact_references"][0]
    assert ref["status"] == "ambiguous" and len(ref["candidates"]) == 2
    assert any(gap["reason"] == "exact_reference_ambiguous" for gap in out["missing"])
