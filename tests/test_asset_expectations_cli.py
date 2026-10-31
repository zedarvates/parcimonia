"""Real CLI-to-snapshot audits produce advice without editing input files."""

import json
import os
import subprocess
import sys

import pytest

from examples.asset_expectations_demo import run_demo
from tiberium_ai.asset_catalog_snapshot import create_asset_catalog, put_asset_report
from tiberium_ai.asset_cli import main
from tiberium_ai.asset_expectations import audit_asset_expectations
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import validated_review_report_hash
from examples.asset_catalog_demo import _png
from tiberium_ai.verification import hash_input


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return path


def test_four_state_demo_is_reproducible_and_proofs_resolve():
    demo = run_demo()
    assert demo == run_demo()
    assert demo["audit"] == audit_asset_expectations(demo["reports"], demo["expectations"])
    assert demo["audit"]["summary"] == {"satisfied": 1, "contradicted": 1, "unknown": 1, "missing_report": 1}
    assert [row["status"] for row in demo["audit"]["results"]] == ["satisfied", "contradicted", "unknown", "missing_report"]
    contradicted = demo["audit"]["results"][1]["checks"][0]
    assert contradicted["observation"]["value"] == 0
    assert contradicted["observation"]["evidence_refs"] == ["ply:body"]
    assert demo["audit"]["results"][2]["checks"][0]["observation"] is None


def test_cli_report_array_matches_pure_api_even_when_requirements_fail(tmp_path, capsys):
    demo = run_demo()
    reports = dump(tmp_path / "reports.json", demo["reports"])
    expectations = dump(tmp_path / "expectations.json", demo["expectations"])
    before = {path: path.read_bytes() for path in (reports, expectations)}
    assert main(["audit-expectations", str(reports), str(expectations)]) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and json.loads(captured.out) == demo["audit"]
    assert {path: path.read_bytes() for path in before} == before
    assert set(tmp_path.iterdir()) == set(before)


def test_persisted_catalogue_audit_binds_exact_generation_and_preserves_old_snapshots(tmp_path, capsys):
    demo = run_demo()
    snapshot = create_asset_catalog("fixture:delivery")
    for report in demo["reports"]:
        snapshot = put_asset_report(snapshot, report, expected_head=snapshot["snapshot_hash"], expected_report_hash=None)
    old = dump(tmp_path / "old.json", snapshot)
    expectations = dump(tmp_path / "expectations.json", demo["expectations"])
    before = old.read_bytes()
    args = ["audit-expectations", str(old), str(expectations), "--catalog"]
    assert main(args) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    initial = json.loads(captured.out)
    assert initial["schema"] == "parcimonia.asset-catalog-expectation-audit/v1"
    assert initial["catalog"] == {"id": snapshot["catalog_id"], "generation": 3, "snapshot_hash": snapshot["snapshot_hash"]}
    assert initial["result"]["summary"] == demo["audit"]["summary"]
    assert initial["input_hash"] == hash_input({"catalog": initial["catalog"], "audit_input_hash": initial["result"]["input_hash"]})
    changed = inspect_asset(_png(), filename="image.png", source_id="fixture:image", revision="v2")
    current_hash = validated_review_report_hash(demo["reports"][0])
    next_snapshot = put_asset_report(snapshot, changed, expected_head=snapshot["snapshot_hash"], expected_report_hash=current_hash)
    current = dump(tmp_path / "current.json", next_snapshot)
    assert main(["audit-expectations", str(current), str(expectations), "--catalog"]) == 0
    updated = json.loads(capsys.readouterr().out)
    assert updated["result"]["summary"]["missing_report"] == 2
    assert updated["input_hash"] != initial["input_hash"]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == initial and old.read_bytes() == before


@pytest.mark.parametrize("case", ["duplicate-json", "foreign-schema", "late-bad-fact", "oversize", "link", "missing", "wrong-mode", "corrupt-snapshot"])
def test_cli_rejects_bad_inputs_without_partial_output_or_writes(tmp_path, capsys, case):
    demo = run_demo()
    reports = dump(tmp_path / "reports.json", demo["reports"])
    expectations = dump(tmp_path / "expectations.json", demo["expectations"])
    extra = []
    if case == "duplicate-json":
        expectations.write_text('{"schema":"a","schema":"b"}', encoding="utf-8")
    elif case == "foreign-schema":
        demo["expectations"]["schema"] = "future"
        dump(expectations, demo["expectations"])
    elif case == "late-bad-fact":
        demo["expectations"]["assets"][-1]["checks"][0]["fact"] = "arbitrary.path"
        dump(expectations, demo["expectations"])
    elif case == "oversize":
        expectations.write_bytes(b" " * (64 * 1024 + 1))
    elif case == "link":
        link = tmp_path / "link.json"
        link.symlink_to(expectations)
        expectations = link
    elif case == "missing":
        expectations.unlink()
    elif case == "wrong-mode":
        extra = ["--catalog"]
    else:
        snapshot = create_asset_catalog("fixture:corrupt")
        snapshot["snapshot_hash"] = "0" * 64
        dump(reports, snapshot)
        extra = ["--catalog"]
    before = {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert main(["audit-expectations", str(reports), str(expectations), *extra]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and json.loads(captured.err)["error"]
    assert {path: path.read_bytes() for path in before} == before
    assert set(tmp_path.iterdir()) == set(before)


def test_real_module_cli_and_demo_entry_point(tmp_path):
    demo = run_demo()
    reports = dump(tmp_path / "reports.json", demo["reports"])
    expectations = dump(tmp_path / "expectations.json", demo["expectations"])
    env = {**os.environ, "PYTHONPATH": "src"}
    completed = subprocess.run([sys.executable, "-m", "tiberium_ai.asset_cli", "audit-expectations", str(reports), str(expectations)],
                               env=env, capture_output=True, text=True, timeout=15, check=True)
    assert completed.stderr == "" and json.loads(completed.stdout) == demo["audit"]
    executed = subprocess.run([sys.executable, "-m", "examples.asset_expectations_demo", "--summary"],
                              env=env, capture_output=True, text=True, timeout=15, check=True)
    assert executed.stderr == "" and json.loads(executed.stdout)["summary"] == demo["audit"]["summary"]


def test_ascii_stdout_budget_fails_before_any_partial_json_is_printed(tmp_path, capsys, monkeypatch):
    demo = run_demo()
    reports = dump(tmp_path / "reports.json", demo["reports"])
    expectations = dump(tmp_path / "expectations.json", demo["expectations"])
    monkeypatch.setattr("tiberium_ai.asset_cli.MAX_AUDIT_BYTES", 10)
    assert main(["audit-expectations", str(reports), str(expectations)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "audit output" in json.loads(captured.err)["detail"]
