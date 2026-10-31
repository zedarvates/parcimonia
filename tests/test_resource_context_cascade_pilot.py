import importlib.util
from pathlib import Path

from tiberium_ai.measurement import read_measurement


def module():
    path = Path(__file__).resolve().parents[1] / "examples/resource_context_cascade_pilot.py"
    spec = importlib.util.spec_from_file_location("resource_context_cascade_pilot", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_pilot_keeps_synthetic_clocks_and_actual_local_callback_time_distinct():
    report = module().run_suite()
    assert len(report["cases"]) == 9
    assert all(row["proposal"]["status"] == row["expected_status"] for row in report["cases"] if "expected_status" in row)
    assert report["cases"][-1]["timing_source"] == "real_perf_counter_fixture_only"
    assert report["cost_savings"] is report["quality_metrics"] is None
    assert not report["model_inference_executed"] and not report["claim_allowed"]


def test_measurement_exports_use_the_existing_canonical_reader(tmp_path):
    directory = tmp_path / "new-pilot"
    assert module().main(["--output-dir", str(directory)]) == 0
    files = [path for path in directory.glob("*.json") if path.name != "report.json"]
    assert len(files) >= 8
    for path in files:
        record = read_measurement(path)
        assert record["schema_version"] == 2 and record["data_origin"] == "measured"
