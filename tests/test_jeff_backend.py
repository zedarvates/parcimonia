import json
import sys
from types import SimpleNamespace

import pytest

from tiberium_ai.jeff_backend import JeffBackend
from tiberium_ai.reflex import ReflexEngine, ReflexKind, ReflexQuestion


SHA = "a" * 40
RUNTIME = "b" * 40


def test_injected_jeff_is_distinct_and_shadow_only():
    b = JeffBackend(revision=SHA, runtime_version="test", predict=lambda *a, **k: {
        "answers": {"kind": {"type": "choice", "choice": "extract",
                              "probabilities": {"extract": .95, "verify": .05}, "confidence": .9}},
        "usage": {"input_tokens": 30, "output_tokens": 0}})
    batch = ReflexEngine(b).evaluate("extraire les champs", [
        ReflexQuestion("kind", ReflexKind.CHOICE, "choisir", {"extract": "extraire", "verify": "verifier"})])
    assert "Jeff-Qwen3.5-0.8B@" in b.model
    assert b.backend_id != "laya.sdk.multilingual@1"
    assert not batch.answers[0].auto_act_allowed


def test_load_refuses_before_loading_runtime():
    with pytest.raises(ValueError, match="immutable"):
        JeffBackend.load(revision="main", runtime_revision=RUNTIME, allow_load=True)
    with pytest.raises(ValueError, match="opt-in"):
        JeffBackend.load(revision=SHA, runtime_revision=RUNTIME)
    with pytest.raises(ValueError, match="CPU"):
        JeffBackend.load(revision=SHA, runtime_revision=RUNTIME, allow_load=True, device="cuda")


def test_sdk_provenance_checked_before_import(monkeypatch):
    import tiberium_ai.jeff_backend as bridge
    monkeypatch.setattr(bridge, "distribution", lambda *a: SimpleNamespace(
        read_text=lambda *a: json.dumps({"vcs_info": {"commit_id": "c" * 40}})))
    with pytest.raises(ValueError, match="SDK"):
        JeffBackend.load(revision=SHA, runtime_revision=RUNTIME, allow_load=True)


def test_offline_pin_and_preparation_limit(monkeypatch, tmp_path):
    import tiberium_ai.jeff_backend as bridge
    from contextlib import nullcontext
    seen = []
    monkeypatch.setattr(bridge, "distribution", lambda *a: SimpleNamespace(
        read_text=lambda *a: json.dumps({"vcs_info": {"commit_id": RUNTIME}})))
    monkeypatch.setattr(bridge, "version", lambda *a: "test")
    def snapshot(*args, **kwargs):
        seen.append(kwargs)
        return str(tmp_path / SHA)
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    class Values:
        def __truediv__(self, other):
            return self
        def softmax(self, *args):
            return self
        def cpu(self):
            return self
        def tolist(self):
            return [[.1, .9]]
    class Model:
        temperature = 1
        device_name = "cpu"
        def eval(self):
            pass
        def prepare(self, rows, *, max_length):
            assert len(rows) == 1
            seen.append({"max_length": max_length})
            return SimpleNamespace(counts=[2], input_tokens=10)
        def __call__(self, batch):
            return Values()
    monkeypatch.setitem(sys.modules, "jeff", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "jeff.models", SimpleNamespace(load_decision_model=lambda **k: Model()))
    monkeypatch.setitem(sys.modules, "jeff.model", SimpleNamespace(answer=lambda q, p: {"type": "noul", "noul": p[1]}))
    b = JeffBackend.load(revision=SHA, runtime_revision=RUNTIME, allow_load=True)
    result = b.evaluate("test", [ReflexQuestion("browser", ReflexKind.NOUL, "browser?")])
    assert result["browser"]["noul"] == .9
    assert seen[0]["local_files_only"] is True and seen[0]["revision"] == SHA
    assert "model.safetensors" in seen[0]["allow_patterns"]
    assert seen[1]["max_length"] == 8192
    assert b.last_usage["question_batch_size"] == 1
    assert b.runtime_revision == RUNTIME


def test_neural_arms_must_run_in_separate_processes():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("pilot", Path(__file__).parents[1] / "examples/local_decision_pilot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(SystemExit) as error:
        module.main(["--laya", "--revision", SHA, "--jeff", "--jeff-revision", SHA,
                     "--jeff-runtime-revision", RUNTIME])
    assert error.value.code == 2


def test_comparison_rejects_unpaired_questions_or_labels(tmp_path):
    import importlib.util
    from pathlib import Path
    from copy import deepcopy
    def module(name, filename):
        spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "examples" / filename)
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result
    pilot = module("pilot", "local_decision_pilot.py")
    compare = module("compare", "compare_decision_pilots.py").compare
    path = tmp_path / "report.json"
    pilot.main(["--output", str(path)])
    report = json.loads(path.read_text(encoding="utf-8"))
    neural = deepcopy(report["arms"][1])
    neural["arm"] = "laya.sdk.multilingual@1"
    report["arms"][-1] = neural
    other = deepcopy(report)
    neural = deepcopy(other["arms"][1])
    neural["arm"] = "jeff.sdk.qwen-0.8b@1"
    other["arms"].append(neural)
    result = compare(report, other)
    assert result["claim_allowed"] is False
    assert result["type_only_cascade_replay"]["executed"] is False
    wrong = deepcopy(other)
    wrong["evaluation_cases"][0]["kind"] = "verify"
    with pytest.raises(ValueError, match="hash"):
        compare(report, wrong)
    wrong = deepcopy(other)
    wrong["arms"][-1]["traces"][0]["questions"][0]["instructions"] = "different"
    with pytest.raises(ValueError, match="question"):
        compare(report, wrong)
    wrong = deepcopy(other)
    wrong["auto_act_allowed"] = True
    with pytest.raises(ValueError, match="shadow"):
        compare(report, wrong)
