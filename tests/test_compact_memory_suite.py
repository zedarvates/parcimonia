import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from tiberium_ai.verification import hash_input

SCRIPT = Path(__file__).resolve().parents[1] / "examples" / "compact_memory_suite.py"


def run_suite(out):
    return subprocess.run([sys.executable, str(SCRIPT), "--out", str(out)], capture_output=True, text=True)


def test_authored_suite_verifies_all_three_variants_and_preserves_negative_results(tmp_path):
    completed = run_suite(tmp_path)
    assert completed.returncode == 0, completed.stderr
    summary = json.loads((tmp_path / "context-summary.json").read_text())
    report = json.loads((tmp_path / "report.json").read_text())
    assert summary["cases"] == 14
    assert summary["production_saving_claim"]["status"] == "refused"
    for variant, metrics in summary["variants"].items():
        assert metrics["accepted"] == 14
        assert metrics["source_retrievals"] == 68
        assert report["routes"][variant]["heldout_median"]["tokens"] is None
    traces = summary["traces"]
    assert traces["short"]["compact"]["metrics"]["prepared_context_utf8_bytes"] > traces["short"]["full_history"]["metrics"]["prepared_context_utf8_bytes"]
    assert traces["long_history"]["compact"]["metrics"]["prepared_context_utf8_bytes"] < traces["long_history"]["full_history"]["metrics"]["prepared_context_utf8_bytes"]
    assert traces["jitter"]["compact_persistent"]["metrics"]["route_switches_including_abstentions"] < traces["jitter"]["compact"]["metrics"]["route_switches_including_abstentions"]
    for variants in traces.values():
        assert len({v["metrics"]["external_archive_utf8_bytes"] for v in variants.values()}) == 1
    for path in (tmp_path / "measurements").glob("*.json"):
        record = json.loads(path.read_text())
        output = traces[record["task_id"]][record["route_id"]]
        verification = summary["verifications"][record["task_id"]][record["route_id"]]
        assert record["cost"] is None
        assert verification["verdict"] is True
        assert verification["input_hash"] == hash_input(output)
    assert len(list((tmp_path / "measurements").glob("*.json"))) == 42


def test_independent_oracle_rejects_inexact_facts_and_ignored_critical_change():
    spec = importlib.util.spec_from_file_location("compact_memory_suite", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    scenario = next(s for s in module.scenarios() if s.name == "critical_change")
    output = module.run_scenario(scenario, "compact_persistent")
    verifier = module.scenario_verifier(scenario)
    assert verifier(output)
    broken = copy.deepcopy(output)
    broken["steps"][1]["selected_route"] = "a"
    assert not verifier(broken)
    broken = copy.deepcopy(output)
    broken["steps"][0]["facts"]["budget"] = 101
    assert not verifier(broken)


def test_authored_suite_refuses_to_overwrite_evidence(tmp_path):
    assert run_suite(tmp_path).returncode == 0
    before = (tmp_path / "context-summary.json").read_bytes()
    completed = run_suite(tmp_path)
    assert completed.returncode == 2
    assert "refusing to overwrite" in completed.stderr
    assert (tmp_path / "context-summary.json").read_bytes() == before
