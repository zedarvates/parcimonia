import importlib.util

import pytest

from tiberium_ai.reflex import InjectedReflexBackend, ReflexKind, ReflexQuestion


QUESTIONS = (
    ReflexQuestion("kind", ReflexKind.CHOICE, "type?", {"extract": "extraire", "verify": "verifier"}),
    ReflexQuestion("field.path", ReflexKind.NOUL, "chemin?"),
)


def cascade_type():
    assert importlib.util.find_spec("tiberium_ai.signature_cascade") is not None, "cascade implementation missing"
    from tiberium_ai.signature_cascade import SignatureCascadeBackend
    return SignatureCascadeBackend


def backend(p, path, choice="extract"):
    return InjectedReflexBackend({
        "kind": {"choice": choice, "probabilities": {"extract": p, "verify": 1-p}, "confidence": p},
        "field.path": {"noul": path, "probabilities": {"false": 1-path, "true": path}},
    }, latin_only=False)


def test_confident_baseline_preserves_its_complete_response():
    b = cascade_type()(backend(.95, .1), backend(.05, .9, "not-an-option"), threshold=.9)
    result = b.evaluate("input", QUESTIONS)
    assert result["kind"]["choice"] == "extract"
    assert result["field.path"]["noul"] == .1
    assert b.fallback_calls == 0
    assert b.last_route == "baseline"


def test_uncertain_baseline_replaced_by_complete_fallback_response():
    b = cascade_type()(backend(.6, .1), backend(.05, .9, "verify"), threshold=.9)
    result = b.evaluate("input", QUESTIONS)
    assert result["kind"]["choice"] == "verify"
    assert result["field.path"]["noul"] == .9
    assert b.fallback_calls == 1
    assert b.last_route == "fallback"
    assert len(b.last_stages) == 2


def test_fallback_budget_failure_never_returns_uncertain_baseline():
    b = cascade_type()(backend(.6, .1), backend(.95, .9), threshold=.9, max_fallback_calls=1)
    b.evaluate("first", QUESTIONS)
    with pytest.raises(ValueError, match="fallback_budget"):
        b.evaluate("second", QUESTIONS)
    assert b.last_route == "error"
    assert b.fallback_calls == 1
    assert b.calls == 2


def test_invalid_baseline_is_rejected_before_escalation():
    broken = backend(.6, .1)
    broken.answers["kind"]["probabilities"] = {"extract": .7, "verify": .7}
    b = cascade_type()(broken, backend(.95, .9), threshold=.9)
    with pytest.raises(ValueError):
        b.evaluate("input", QUESTIONS)
    assert b.fallback_calls == 0
    assert b.last_stages[0]["status"] == "error"


def test_failed_fallback_consumes_budget_and_does_not_mix_answers():
    b = cascade_type()(backend(.6, .1), backend(.95, .9, "unknown"), max_fallback_calls=1)
    with pytest.raises(ValueError):
        b.evaluate("input", QUESTIONS)
    assert b.fallback_calls == 1
    assert b.last_route == "error"
    assert b.last_stages[-1]["status"] == "error"


def test_total_call_budget_and_no_implicit_kind_question():
    b = cascade_type()(backend(.95, .1), backend(.95, .9), max_calls=1)
    b.evaluate("first", QUESTIONS)
    with pytest.raises(ValueError, match="call_budget"):
        b.evaluate("second", QUESTIONS)
    fresh = cascade_type()(backend(.95, .1), backend(.95, .9))
    with pytest.raises(ValueError, match="kind question"):
        fresh.evaluate("input", QUESTIONS[1:])
