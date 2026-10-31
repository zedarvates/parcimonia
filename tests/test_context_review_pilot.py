import importlib.util
import json
from pathlib import Path

import pytest

from tiberium_ai.signature_ingest import CORPUS_KIND, revision_id


def module():
    script = Path(__file__).resolve().parents[1] / "examples/context_review_pilot.py"
    spec = importlib.util.spec_from_file_location("context_review_pilot", script)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_fixture_walkthrough_keeps_known_missing_and_unknown_separate():
    report = module().fixture_report()
    assert len(report["cases"]) == 7 and report["data_origin"] == "fixture"
    assert not report["claim_allowed"] and not report["model_inference_executed"]
    cases = {row["case_id"]: row["result"] for row in report["cases"]}
    assert cases["mentioned-only"]["context"]["provided_fields"] == []
    assert cases["mentioned-only"]["status"] == "missing_context"
    assert cases["uncaptured-context"]["status"] == "context_unknown"
    assert cases["verified-reference"]["context"]["provided_fields"] == []
    assert cases["verified-reference"]["context"]["available_context"] == ["document"]


def corpus(tmp_path):
    rows = [{"text": "Peux-tu extraire les colonnes du fichier joint et vérifier le résultat ?", "sources": ["sessions"]},
            {"text": "continuer", "sources": ["sessions"]},
            {"text": "Peux-tu vérifier ce document dont la capture est tronquée ?", "sources": ["sessions"], "truncated": True}]
    path = tmp_path / "revision.json"
    path.write_text(json.dumps({"kind": CORPUS_KIND, "revision_id": revision_id(rows), "prompts": rows}), encoding="utf-8")
    return path


def test_real_pack_preparation_preserves_unreviewed_state_and_excludes_truncation(tmp_path):
    pack = module().prepare_pack(corpus(tmp_path))
    assert pack["selected_count"] == 1 and pack["labelled_cases"] == 0
    assert pack["cases"][0]["context_snapshot"] is None
    assert pack["cases"][0]["language_review_required"]
    assert pack["quality_metrics"] is None and not pack["claim_allowed"]


def test_corrupted_revision_cannot_be_presented_as_a_fixed_pack(tmp_path):
    path = corpus(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["revision_id"] = "changed"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="content"):
        module().prepare_pack(path)


def test_real_text_cannot_be_written_outside_the_ignored_run_area(tmp_path):
    with pytest.raises(ValueError):
        module().main(["--corpus", str(corpus(tmp_path)), "--output", str(tmp_path / "public-pack.json")])
    assert not (tmp_path / "public-pack.json").exists()


def test_fixture_output_never_overwrites_an_existing_file(tmp_path):
    output = tmp_path / "fixture.json"
    output.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        module().main(["--output", str(output)])
    assert output.read_text(encoding="utf-8") == "keep"
