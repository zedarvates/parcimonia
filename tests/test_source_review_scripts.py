import importlib.util
import json
from pathlib import Path

import pytest

from test_source_review import completed_review, packet, saved_manifest


def example(name):
    path = Path(__file__).resolve().parents[1] / "examples" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prepare_rechecks_saved_bytes_and_refuses_overwrite(tmp_path, monkeypatch):
    module = example("prepare_source_review")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    manifest, _, snapshot = saved_manifest(tmp_path)
    output = tmp_path / "runs" / "review"
    original = snapshot.read_bytes()
    result = module.prepare(manifest, output)
    assert result["cases"] == 1 and result["human_reviewed_cases"] == 0
    assert not result["model_inference_executed"]
    for filename in result["files"]:
        assert (output / filename).exists()
    template = json.loads((output / "review-template.json").read_text(encoding="utf-8"))
    assert not any(annotation["complete"] for annotation in template["annotations"].values())
    before = (output / "review-packet.json").read_bytes()
    with pytest.raises(FileExistsError):
        module.prepare(manifest, output)
    assert snapshot.read_bytes() == original and (output / "review-packet.json").read_bytes() == before


def test_prepare_output_must_stay_in_local_runs(tmp_path, monkeypatch):
    module = example("prepare_source_review")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    manifest, _, _ = saved_manifest(tmp_path)
    output = tmp_path / "outside"
    with pytest.raises(ValueError):
        module.prepare(manifest, output)
    assert not output.exists()


def test_finalizer_refuses_blank_review_before_creating_output(tmp_path, monkeypatch):
    module = example("finalize_source_review")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    data = packet()
    from tiberium_ai.agent_recipes.source_review import source_review_template
    data_path, review_path = tmp_path / "packet.json", tmp_path / "review.json"
    data_path.write_text(json.dumps(data), encoding="utf-8")
    review_path.write_text(json.dumps(source_review_template(data)), encoding="utf-8")
    output = tmp_path / "runs" / "final"
    with pytest.raises(ValueError, match="incomplete"):
        module.main(["--packet", str(data_path), "--review", str(review_path), "--output-dir", str(output)])
    assert not output.exists()


def test_finalizer_keeps_measures_unknown_after_fixture_review(tmp_path, monkeypatch, capsys):
    module = example("finalize_source_review")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    data = packet()
    data_path, review_path = tmp_path / "packet.json", tmp_path / "review.json"
    data_path.write_text(json.dumps(data), encoding="utf-8")
    review_path.write_text(json.dumps(completed_review(data)), encoding="utf-8")
    output = tmp_path / "runs" / "final"
    args = ["--packet", str(data_path), "--review", str(review_path), "--output-dir", str(output)]
    assert module.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["human_reviewed_cases"] == 4 and result["quality_metrics"] is None
    assert result["cost_savings"] is None and not result["independence_certified"]
    with pytest.raises(FileExistsError):
        module.main(args)
