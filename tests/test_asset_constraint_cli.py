"""Separate CLI reports preserve existing audit semantics and explicit files."""

from copy import deepcopy
import json
import os
import subprocess
import sys

import pytest

from examples.asset_constraint_demo import run_demo
from tiberium_ai.asset_cli import main
from tiberium_ai.asset_expectation_constraints import verify_asset_expectation_constraints


def test_authored_demo_and_registry_receipts_reproduce_exactly():
    demo = run_demo()
    assert demo == run_demo()
    assert [case["report"]["status"] for case in demo["cases"]] == ["contradictory", "no_conflict_detected"]
    for case in demo["cases"]:
        assert case["verification"]["verdict"] is True
        assert verify_asset_expectation_constraints(case["expectations"], case["report"])
    revised_width = next(f for f in demo["cases"][1]["report"]["results"][0]["facts"] if f["fact"] == "metadata.width")
    assert revised_width["candidate"] == 512


@pytest.mark.parametrize("index", [0, 1])
def test_cli_reads_only_the_contract_and_returns_a_usable_report_for_both_outcomes(tmp_path, capsys, index):
    case = run_demo()["cases"][index]
    path = tmp_path / "expectations.json"
    path.write_text(json.dumps(case["expectations"]), encoding="utf-8")
    before = path.read_bytes()
    assert main(["check-expectations", str(path)]) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and json.loads(captured.out) == case["report"]
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("case", ["duplicate-json", "unsupported-fact", "oversize", "link", "missing"])
def test_cli_input_errors_produce_no_partial_report(tmp_path, capsys, case):
    request = deepcopy(run_demo()["cases"][0]["expectations"])
    path = tmp_path / "expectations.json"
    if case == "unsupported-fact": request["assets"][0]["checks"][0]["fact"] = "arbitrary.path"
    path.write_text(json.dumps(request), encoding="utf-8")
    if case == "duplicate-json": path.write_text('{"id":"a","id":"b"}', encoding="utf-8")
    elif case == "oversize": path.write_text(" " * (64*1024+1), encoding="utf-8")
    elif case == "missing": path.unlink()
    elif case == "link":
        link = tmp_path / "link.json"
        link.symlink_to(path)
        path = link
    assert main(["check-expectations", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and json.loads(captured.err)["error"]


def test_cli_ascii_output_budget_refuses_before_printing(tmp_path, capsys, monkeypatch):
    path = tmp_path / "expectations.json"
    path.write_text(json.dumps(run_demo()["cases"][0]["expectations"]), encoding="utf-8")
    monkeypatch.setattr("tiberium_ai.asset_cli.MAX_CONSISTENCY_BYTES", 10)
    assert main(["check-expectations", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "256 KiB" in json.loads(captured.err)["detail"]


def test_real_module_cli_and_demo_execute_in_an_ascii_environment(tmp_path):
    request = deepcopy(run_demo()["cases"][0]["expectations"])
    request["id"] = "attentes:forêt"
    request["assets"][0]["source"]["id"] = "image:été"
    path = tmp_path / "expectations.json"
    path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": "src", "PYTHONIOENCODING": "ascii:strict"}
    call = subprocess.run([sys.executable,"-m","tiberium_ai.asset_cli","check-expectations",str(path)],
                          capture_output=True, env=env, timeout=15, check=True)
    report = json.loads(call.stdout.decode("ascii"))
    assert call.stderr == b"" and verify_asset_expectation_constraints(request, report)
    demo = subprocess.run([sys.executable,"-m","examples.asset_constraint_demo"],
                          capture_output=True, env=env, timeout=15, check=True)
    assert demo.stderr == b"" and json.loads(demo.stdout.decode("ascii")) == run_demo()
