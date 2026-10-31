"""Real CLI feature: structured constraints and strict precedence."""
import importlib.util
import json
from pathlib import Path

import pytest

from test_task_preparation import inventory


@pytest.fixture
def cli(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "examples/prepare_development_task.py"
    spec = importlib.util.spec_from_file_location("task_policy_cli", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    data = inventory(tmp_path)
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return module, path


def policy():
    return {"version": "test-policy/1", "required": {"domains": ["code"]},
            "allowed": {"effects": ["read"], "network": ["offline"]}, "require_verified": False}


def run(cli, tmp_path, value, *extra):
    module, source = cli
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "runs/result"
    module.main(["--goal", "profils outils", "--inventory", str(source),
                 "--policy", str(path), "--output-dir", str(output), *extra])
    return json.loads((output / "packet.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("dimension,tags", [("domains", ["research"]), ("effects", []), ("network", ["internet"])])
def test_policy_actually_filters_candidates(cli, tmp_path, dimension, tags):
    value = policy()
    value["required" if dimension == "domains" else "allowed"][dimension] = tags
    packet = run(cli, tmp_path, value)
    assert packet["capabilities"] == []
    assert packet["policy"] == value
    assert packet["auto_act_allowed"] is False


def test_policy_accepts_matching_candidate_and_is_recorded(cli, tmp_path):
    packet = run(cli, tmp_path, policy())
    assert [c["id"] for c in packet["capabilities"]] == ["mechanism:inspect"]
    assert packet["policy"] == policy()
    assert packet["assessment"]["policy"] == policy()


def test_strict_flag_cannot_be_downgraded_by_policy_file(cli, tmp_path):
    packet = run(cli, tmp_path, policy(), "--strict")
    assert packet["capabilities"] == []
    assert packet["policy"]["require_verified"] is True
    assert packet["policy"]["version"] == "test-policy/1+strict"


@pytest.mark.parametrize("change", [
    lambda p: p.update(require_verified="false"),
    lambda p: p.update(extra="ignored"),
    lambda p: p["allowed"].update(effects=["unknown-effect"]),
    lambda p: p.pop("required"),
])
def test_invalid_policy_is_not_repaired_or_masked_by_strict(cli, tmp_path, change):
    value = policy()
    change(value)
    with pytest.raises(ValueError):
        run(cli, tmp_path, value, "--strict")
    assert not (tmp_path / "runs/result").exists()


@pytest.mark.parametrize("raw", ['{"version":"one","version":"two"}', '{"value":NaN}', 'not json'])
def test_ambiguous_or_malformed_json_fails_before_output(cli, tmp_path, raw):
    module, source = cli
    path = tmp_path / "bad.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        module.main(["--goal", "profils", "--inventory", str(source), "--policy", str(path),
                     "--output-dir", str(tmp_path / "runs/result")])
    assert not (tmp_path / "runs/result").exists()


def test_development_case_finds_preparer_sources_after_inventory_review():
    """Regression on the reviewed development case, not a held-out benchmark."""
    from tiberium_ai.task_preparation import build_index, prepare_task

    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "examples/fixtures/development_capabilities.json").read_text(encoding="utf-8"))
    packet = prepare_task(
        "Ajouter une option --policy JSON a la CLI de preparation des taches pour filtrer les domaines effets et reseau ; conserver --strict prioritaire ; tester les politiques invalides",
        data, build_index(data, {"workspace": root}))
    paths = {row["source"]["path"] for row in packet["files"]}
    assert {"examples/prepare_development_task.py", "src/tiberium_ai/task_preparation.py",
            "tests/test_task_preparation.py"} <= paths
    assert packet["capabilities"][0]["id"] == "mechanism:preparation.policy"
    assert "mechanism:preparation.cli" not in {row["id"] for row in packet["capabilities"]}
