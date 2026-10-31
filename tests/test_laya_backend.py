import pytest

from tiberium_ai.laya_backend import LayaBackend
from tiberium_ai.reflex import ReflexEngine, ReflexKind, ReflexQuestion


SHA = "a" * 40
QUESTIONS = (
    ReflexQuestion("kind", ReflexKind.CHOICE, "Choisir", {"a": "extraire", "b": "verifier"}),
    ReflexQuestion("browser", ReflexKind.NOUL, "Navigateur necessaire ?"),
    ReflexQuestion("effort", ReflexKind.SCORE, "Effort", ["faible", "fort"]),
)


def payload():
    return {"answers": {
        "kind": {"type": "choice", "choice": "a", "confidence": .9,
                 "probabilities": {"a": .9, "b": .1}},
        "browser": {"type": "noul", "noul": .2},
        "effort": {"type": "score", "score": .3, "probabilities": {"0": .7, "1": .3}},
    }, "usage": {"input_tokens": 20, "output_tokens": 0, "truncated": False}}


def backend(predict=None, max_calls=2):
    return LayaBackend(revision=SHA, predict=predict or (lambda *a, **k: payload()),
                       runtime_version="test", max_calls=max_calls)


def test_normalizes_all_types_without_authorizing():
    seen = []
    def predict(state, questions, **kwargs):
        seen.append((state, questions, kwargs))
        return payload()
    b = backend(predict)
    batch = ReflexEngine(b).evaluate("recupere ce fichier", QUESTIONS)
    assert batch.get("browser").probabilities == {"false": .8, "true": .2}
    assert batch.get("effort").probabilities == {"faible": .7, "fort": .3}
    assert all(not a.auto_act_allowed for a in batch.answers)
    assert batch.uncalibrated
    assert seen[0][2] == {"max_len": 8192}
    assert b.last_usage["input_tokens"] == 20


@pytest.mark.parametrize("mutation", [
    lambda p: p["answers"].pop("kind"),
    lambda p: p["answers"].update(extra={}),
    lambda p: p["answers"]["kind"].update(choice="unknown"),
    lambda p: p["answers"]["kind"].update(probabilities={"a": .9, "b": .9}),
    lambda p: p["answers"]["browser"].update(noul=float("nan")),
    lambda p: p["answers"]["browser"].update(noul=True),
    lambda p: p["answers"]["effort"].update(probabilities={"0": 1}),
    lambda p: p["answers"]["kind"].update(type="noul"),
    lambda p: p["usage"].update(truncated=True),
    lambda p: p["usage"].update(options={"kind": {"distinct": 1}}),
])
def test_malformed_or_truncated_response_rejected(mutation):
    def predict(*a, **k):
        p = payload()
        mutation(p)
        return p
    with pytest.raises((ValueError, KeyError)):
        backend(predict).evaluate("test", QUESTIONS)


def test_failed_call_consumes_budget_and_clears_usage():
    def predict(*a, **k):
        raise OSError("offline")
    b = backend(predict, max_calls=1)
    with pytest.raises(OSError):
        b.evaluate("test", QUESTIONS)
    with pytest.raises(ValueError, match="call_budget"):
        b.evaluate("test", QUESTIONS)
    assert b.calls == 1
    assert b.last_usage == {}


def test_four_decimal_rounding_preserves_original_evidence():
    def predict(*a, **k):
        p = payload()
        p["answers"]["kind"]["probabilities"] = {"a": .9000, "b": .0999}
        return p
    b = backend(predict)
    result = b.evaluate("test", QUESTIONS)
    assert sum(result["kind"]["probabilities"].values()) == pytest.approx(1)
    assert b.last_raw_answers["kind"]["probabilities"] == {"a": .9, "b": .0999}


def test_load_requires_opt_in_and_immutable_revision():
    with pytest.raises(ValueError, match="immutable"):
        LayaBackend.load(revision="main", allow_download=True)
    with pytest.raises(ValueError, match="opt-in"):
        LayaBackend.load(revision=SHA)


def test_sdk_load_is_pinned_and_detects_identity_mismatch(monkeypatch):
    import sys
    from types import SimpleNamespace
    seen = []
    agent = SimpleNamespace(revision=SHA, predict=lambda *a, **k: payload(), device="cpu")
    def load(*args, **kwargs):
        seen.append((args, kwargs))
        return agent
    monkeypatch.setitem(sys.modules, "laya", SimpleNamespace(load=load, __version__="test"))
    b = LayaBackend.load(revision=SHA, allow_download=True)
    assert b.device == "cpu"
    assert seen[0][1]["revision"] == SHA
    assert seen[0][1]["subfolder"] == "multilingual"
    assert seen[0][1]["compile"] is False
    agent.revision = "b" * 40
    with pytest.raises(ValueError, match="revision"):
        LayaBackend.load(revision=SHA, allow_download=True)


def test_pilot_baselines_use_french_holdout(tmp_path):
    import importlib.util
    from pathlib import Path
    import json
    spec = importlib.util.spec_from_file_location("pilot", Path(__file__).parents[1] / "examples/local_decision_pilot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "report.json"
    assert module.main(["--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert len(report["evaluation_cases"]) == 6
    assert not set(report["training_case_ids"]) & {c["case_id"] for c in report["evaluation_cases"]}
    assert not report["claim_allowed"] and not report["auto_act_allowed"]
    assert report["arms"][-1]["status"] == "not_requested"
    assert all(len(a["traces"]) == 6 for a in report["arms"][:-1])
