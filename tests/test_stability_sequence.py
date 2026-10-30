import hashlib
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "examples" / "stability_sequence.py"


def run_demo_script():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=True
    )
    return json.loads(completed.stdout)


def test_jitter_causes_observed_single_threshold_oscillation():
    report = run_demo_script()
    prefix = report["inputs"]["jitter_prefix_length"]
    single = report["outputs"]["single_threshold"][:prefix]
    hysteresis = report["outputs"]["hysteresis"][:prefix]

    assert len(set(single)) == 2
    assert all(before != after for before, after in zip(single, single[1:]))
    assert hysteresis == [False] * prefix
    assert report["counts"]["single_threshold_switches"] > report["counts"]["hysteresis_switches"]


def test_hysteresis_responds_to_clear_changes_and_retains_state_inside_band():
    report = run_demo_script()
    sequence = report["inputs"]["sequence"]
    outputs = report["outputs"]["hysteresis"]
    rise = sequence.index(0.60)
    fall = sequence.index(0.40)

    assert outputs[rise - 1] is False
    assert outputs[rise] is True
    assert sequence[rise + 1 : fall] == [0.50, 0.48]
    assert outputs[rise + 1 : fall] == [True, True]
    assert outputs[fall] is False
    for key, values in report["outputs"].items():
        assert report["counts"][key + "_switches"] == sum(
            previous != current for previous, current in zip(values, values[1:])
        )


def test_report_is_reproducible_and_bounds_its_claims():
    report = run_demo_script()
    assert run_demo_script() == report
    assert report["data_origin"] == "authored_fixture"
    canonical = json.dumps(
        report["inputs"], ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    assert report["input_hash"] == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert report["hardware_performance_not_measured"] is True
    assert report["no_general_stability_claim"] is True
    assert any("delay" in limitation for limitation in report["limitations"])
