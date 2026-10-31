import importlib.util
import json
from pathlib import Path

import pytest

from tiberium_ai.agent_recipes import DecisionSession, assess_novelty, triage_attention
from tiberium_ai.reflex import InjectedReflexBackend


def pilot():
    path = Path(__file__).resolve().parents[1] / "examples" / "source_triage_pilot.py"
    spec = importlib.util.spec_from_file_location("source_triage_pilot", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pilot_compares_same_inputs_and_keeps_every_original():
    report = pilot().run_suite()
    assert report["counts"]["baseline_process"] == 12
    assert report["counts"]["process"] == 6
    assert report["counts"]["defer"] == 4
    assert report["counts"]["skip_candidate"] == 2
    assert report["counts"]["fixture_required_sources_proposed_skipped"] == 0
    assert report["counts"]["retained_originals"] == 12
    for row in report["cases"]:
        assert row["baseline_measurement"]["input_hash"] == row["candidate_measurement"]["input_hash"]
        assert row["baseline_measurement"]["verified"] and row["candidate_measurement"]["verified"]
        assert row["attention"]["data"]["recall"]["source"] == row["source"]
        assert row["novelty"]["data"]["recall"]["source"] == row["source"]
        assert row["comparison"]["reasons"] == ["unknown_cost"]
    assert report["quality_metrics"] is None and report["cost_savings"] is None
    assert report["claim_allowed"] is False and report["model_inference_executed"] is False


def test_unknown_context_cannot_be_bypassed_by_exact_duplicate():
    item = {"id": "incoming", "title": "Evidence", "text": "Same text", "reference": "fixture:incoming"}
    context = {"id": "project", "revision": "1", "objective": "Review evidence",
               "required_context": ["machine"], "values": {}}
    attention = triage_attention(item, context, DecisionSession())
    novelty = assess_novelty(item, [{**item, "id": "known"}], DecisionSession())
    assert novelty.data["decision"] == "duplicate"
    assert pilot().disposition(attention, novelty) == "defer"


@pytest.mark.parametrize("protected,limited,expected", [(True, False, "process"), (False, True, "defer")])
def test_duplicate_cannot_override_protection_or_limited_search(protected, limited, expected):
    item = {"id": "incoming", "title": "Evidence", "text": "Same text",
            "reference": "fixture:incoming", "protected": protected}
    context = {"id": "project", "revision": "1", "objective": "Review evidence"}
    answers = {key: {"noul": p, "probabilities": {"true": p, "false": 1 - p}}
               for key, p in (("relevant", .99), ("actionable", .99), ("needs_context", .01))}
    attention = triage_attention(item, context, DecisionSession(InjectedReflexBackend(answers, latin_only=False)))
    novelty = assess_novelty(item, [{**item, "id": "known"}], DecisionSession())
    assert pilot().disposition(attention, novelty, shortlist_limited=limited) == expected


def test_pilot_output_is_json_and_exclusive(tmp_path, capsys):
    module, path = pilot(), tmp_path / "report.json"
    assert module.main(["--output", str(path)]) == 0
    original = path.read_bytes()
    summary = json.loads(capsys.readouterr().out)
    assert summary["counts"]["retained_originals"] == 12
    with pytest.raises(FileExistsError):
        module.main(["--output", str(path)])
    assert path.read_bytes() == original
