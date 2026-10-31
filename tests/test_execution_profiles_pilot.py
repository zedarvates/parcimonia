import importlib.util
import json
from pathlib import Path
import sys


def test_offline_pilot_produces_reloadable_snapshot_and_no_execution(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("execution_profiles_pilot", root / "examples/execution_profiles_pilot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Keep inputs in the real repository but output in the temporary workspace.
    original_build = module.build
    catalog, observed, policy = original_build()
    monkeypatch.setattr(module, "build", lambda: (catalog, observed, policy))
    monkeypatch.setattr(module, "ROOT", tmp_path)
    destination = tmp_path / "runs" / "pilot"
    monkeypatch.setattr(sys, "argv", ["pilot", "--output-dir", str(destination)])
    module.main()
    report = json.loads((destination / "report.json").read_text(encoding="utf-8"))
    assert report["replay_matches"] is True
    assert report["declared_assessment"]["eligible_ids"] == ["skill:fixture-review"]
    assert report["strict_assessment"]["eligible_ids"] == []
    assert report["skill_proposal"]["data"] == "fixture-review"
    assert report["execution"] == "not_run" and report["auto_act_allowed"] is False
    import pytest
    with pytest.raises(FileExistsError):
        module.main()
