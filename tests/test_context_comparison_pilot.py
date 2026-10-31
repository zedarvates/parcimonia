import importlib.util
import json
from pathlib import Path

import pytest

from tiberium_ai.context_review import build_context_review_pack


def module():
    path = Path(__file__).resolve().parents[1] / "examples/context_comparison_pilot.py"
    spec = importlib.util.spec_from_file_location("context_comparison_pilot", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_pipeline_keeps_quarantine_original_texts_and_never_scores_missing_labels():
    packet = build_context_review_pack([{"text": "extraire les colonnes du document", "sources": []},
        {"text": '<send_user_message_question_reply>[{"reply":"oui"}]</send_user_message_question_reply>', "sources": []}], corpus_revision="fixture")
    audit, candidates, quarantine, readiness = module().prepare(packet)
    assert audit["counts"] == {"candidate": 1, "quarantine": 1}
    assert candidates["cases"][0]["text"] == "extraire les colonnes du document"
    assert "send_user_message_question_reply" in quarantine["cases"][0]["text"]
    assert readiness["quality_metrics"] is None and not readiness["kind_capture_ready"]


def test_comparison_output_does_not_overwrite_or_escape_private_run_area(tmp_path):
    loaded = module()
    packet = build_context_review_pack([{"text": "extraire les colonnes du document", "sources": []}], corpus_revision="fixture")
    source = tmp_path / "packet.json"
    source.write_text(json.dumps(packet), encoding="utf-8")
    with pytest.raises(ValueError):
        loaded.main(["--packet", str(source), "--output-dir", str(tmp_path / "public")])
    assert not (tmp_path / "public").exists()
