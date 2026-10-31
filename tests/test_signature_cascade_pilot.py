import importlib.util
import sys
from pathlib import Path

import pytest

from tiberium_ai.reflex import ReflexKind, ReflexQuestion


def pilot():
    root = Path(__file__).resolve().parents[1] / "examples"
    sys.path.insert(0, str(root))
    try:
        spec = importlib.util.spec_from_file_location("cascade_pilot_test", root / "signature_cascade_pilot.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_replay_rejects_a_different_question_contract():
    from hashlib import sha256
    module = pilot()
    backend = module.CapturedBackend([{
        "state_sha256": sha256(b"input").hexdigest(), "status": "ok",
        "questions": [], "answers": {},
    }])
    question = ReflexQuestion("kind", ReflexKind.CHOICE, "type?", {"a": "A", "b": "B"})
    with pytest.raises(ValueError, match="questions"):
        backend.evaluate("input", [question])


def test_replay_rejects_duplicate_states():
    module = pilot()
    trace = {"state_sha256": "same", "status": "ok"}
    with pytest.raises(ValueError, match="duplicate"):
        module.CapturedBackend([trace, trace])


def test_pilot_rejects_unpaired_report_before_execution():
    with pytest.raises(ValueError, match="protocol"):
        pilot().run_capture({}, "model")


def test_paired_comparison_distinguishes_error_from_abstention():
    from hashlib import sha256
    from types import SimpleNamespace
    case = SimpleNamespace(case_id="one", prompt="input", kind="a")
    def row(probability, choice):
        return {"status": "ok", "traces": [{
            "state_sha256": sha256(b"input").hexdigest(), "questions": [],
            "answers": {"kind": {"choice": choice, "probabilities": {
                "a": probability, "b": 1 - probability}}},
        }]}
    result = pilot().compare_rows([case], row(.6, "a"), row(.05, "b"), .9)
    assert result["baseline_counts"]["abstained"] == 1
    assert result["cascade_counts"]["incorrect"] == 1
    assert result["new_accepted_errors"] == 1
    assert result["improved"] == 0


def test_field_comparison_keeps_errors_on_abstained_kind_visible():
    from hashlib import sha256
    from types import SimpleNamespace
    case = SimpleNamespace(case_id="one", prompt="input", kind="a", fields=("path",))
    def arm(fields):
        return {"status": "ok", "traces": [{
            "state_sha256": sha256(b"input").hexdigest(), "questions": [],
            "answers": {"kind": {"choice": "a", "probabilities": {"a": .6, "b": .4}},
                        **{f"field.{name}": {"noul": score} for name, score in fields.items()}},
        }]}
    result = pilot().compare_fields([case], arm({"path": .1}), arm({"language": .8}), .5)
    assert result["counts"]["cascade"] == {
        "true_positive": 0, "false_positive": 1, "false_negative": 1}
    assert result["cases"][0]["cascade"]["extra"] == ["language"]
