import json
import subprocess
import sys
from pathlib import Path

from tiberium_ai.observations import read_observation, replay_observation

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "examples" / "fixture_suite.py"


def run_suite(out_dir):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out_dir)],
        capture_output=True,
        text=True,
    )


def test_fixture_suite_produces_measured_runs_and_replayable_observations(tmp_path):
    completed = run_suite(tmp_path)
    assert completed.returncode == 0, completed.stderr

    measurements = sorted((tmp_path / "measurements").glob("*.json"))
    observations = sorted((tmp_path / "observations").glob("*.json"))
    assert len(measurements) == 40
    assert len(observations) == 20

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["cases"] == 20
    assert summary["measurements_ok"] == 39
    assert summary["measurements_failed"] == 1
    assert summary["statuses"] == {
        "verified_without_measurements": 18,
        "verification_failed": 1,
        "insufficient_evidence": 1,
    }

    for path in measurements:
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["kind"] == "measurement"
        assert record["data_origin"] == "measured"
    for path in observations:
        record = read_observation(path)
        assert record["schema_version"] == 2
        assert replay_observation(record).mode == "shadow"


def test_fixture_suite_refuses_to_overwrite_existing_records(tmp_path):
    assert run_suite(tmp_path).returncode == 0
    second = run_suite(tmp_path)
    assert second.returncode == 2
    assert "refusing to overwrite" in second.stdout + second.stderr
