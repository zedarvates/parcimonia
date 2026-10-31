import importlib.util
from pathlib import Path


def test_fixture_pilot_records_real_injected_predictor_counts_without_a_saving_claim():
    path = Path(__file__).resolve().parents[1] / "examples/context_signature_cascade_pilot.py"
    spec = importlib.util.spec_from_file_location("context_signature_cascade_pilot", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.run_suite()
    assert len(report["cases"]) == 8
    assert sum(row["result"]["backend_calls"] == 0 for row in report["cases"]) == 3
    assert all(row["result"]["status"] == row["expected_status"] for row in report["cases"])
    assert report["monetary_saving"] is None and not report["claim_allowed"]
    assert not report["model_inference_executed"]
