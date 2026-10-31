"""Exercise the public file/CLI boundary rather than the solver internals."""

import json
import os
import subprocess
import sys

import pytest

from tiberium_ai.diagnostics import MAX_INPUT_BYTES, main


def _request():
    return {
        "schema": "parcimonia.feasibility-request/v1",
        "task_id": "fixture-cli",
        "scope_id": "fixture",
        "revision": "v1",
        "variables": ["ready"],
        "constraints": [
            {"id": "goal", "kind": "require", "variable": "ready", "value": True, "source": "fixture:goal"}
        ],
        "observations": [
            {"variable": "ready", "value": False, "source": "fixture:state", "revision": "v1"}
        ],
    }


def _json_file(tmp_path, value):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_completed_analysis_is_not_a_successful_project(tmp_path, capsys):
    path = _json_file(tmp_path, _request())
    assert main(["feasibility", str(path)]) == 0
    output = capsys.readouterr()
    assert not output.err
    report = json.loads(output.out)
    assert report["feasibility"] == "blocked_current_state"
    assert report["completeness"] == "missing_prerequisites"
    assert report["quality"] == "indeterminate"


def test_impossibility_is_reported_as_analysis_not_process_failure(tmp_path, capsys):
    request = _request()
    request["constraints"].append(
        {"id": "opposite", "kind": "require", "variable": "ready", "value": False, "source": "fixture:opposite"}
    )
    path = _json_file(tmp_path, request)
    assert main(["feasibility", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["feasibility"] == "impossible_within_constraints"


def test_over_budget_abstention_has_distinct_exit_code(tmp_path, capsys):
    path = _json_file(tmp_path, _request())
    assert main(["feasibility", str(path), "--max-variables", "0"]) == 3
    report = json.loads(capsys.readouterr().out)
    assert report["feasibility"] == "indeterminate"
    assert report["proof"] is None


@pytest.mark.parametrize("content", [
    "{", "[]", '{"schema": 1, "schema": 2}',
    '{"a": {"x": 1, "x": 2}}', '{"value": NaN}', '{"value": Infinity}',
])
def test_invalid_json_has_no_analysis_on_stdout(tmp_path, capsys, content):
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    assert main(["feasibility", str(path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "error" in json.loads(output.err)


def test_invalid_contract_returns_json_error_without_traceback(tmp_path, capsys):
    request = _request()
    request["constraints"][0]["value"] = 1
    path = _json_file(tmp_path, request)
    assert main(["feasibility", str(path)]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "ValueError"


def test_missing_file_is_a_read_failure_not_an_empty_model(tmp_path, capsys):
    assert main(["feasibility", str(tmp_path / "missing.json")]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "FileNotFoundError"


@pytest.mark.parametrize("payload", [b"\xff", b" " * (MAX_INPUT_BYTES + 1)])
def test_input_encoding_and_byte_budget(tmp_path, capsys, payload):
    path = tmp_path / "bad.json"
    path.write_bytes(payload)
    assert main(["feasibility", str(path)]) == 2
    assert capsys.readouterr().out == ""


def test_syntax_failure_abstains_without_claiming_no_risk(tmp_path, capsys):
    path = tmp_path / "bad.py"
    path.write_text("if :", encoding="utf-8")
    assert main(["stability", str(path), "--source-id", "fixture", "--revision", "v1"]) == 3
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "indeterminate"


def test_inspecting_hostile_source_does_not_execute_it(tmp_path, capsys):
    marker = tmp_path / "must-not-exist"
    path = tmp_path / "hostile.py"
    path.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
        "def collect(items=[]):\n    return items\n",
        encoding="utf-8",
    )
    assert main(["stability", str(path), "--source-id", "fixture", "--revision", "v1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "risks_identified"
    assert {item["verdict"] for item in report["findings"]} == {"risk_indicator"}
    assert not marker.exists()


def test_module_entry_point_supports_ascii_only_windows_style_pipes(tmp_path):
    path = _json_file(tmp_path, _request())
    request = _request()
    request["task_id"] = "objectif-évalué"
    path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    environment = dict(os.environ, PYTHONIOENCODING="ascii")
    result = subprocess.run(
        [sys.executable, "-m", "tiberium_ai.diagnostics", "feasibility", str(path)],
        capture_output=True, env=environment, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.decode("ascii"))
    assert report["task_id"] == "objectif-évalué"
