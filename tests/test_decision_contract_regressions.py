"""Offline regressions for calibration scope, structured state and wire rounding."""
import json
from dataclasses import replace

import pytest

from tiberium_ai.agent_recipes.providers import TypeSafeBackend
from tiberium_ai.reflex import (
    CalibrationSnapshot, InjectedReflexBackend, ReflexEngine, ReflexKind, ReflexQuestion,
)
from tiberium_ai.decision_json import STATE_ENCODING_VERSION
from tiberium_ai.laya_backend import LayaBackend
from tiberium_ai.reflex_calibrate import LabelledCase, evaluate_calibration
from tiberium_ai.decision_adapter import DecisionRequest, DecisionRecord, replay_decision


Q = ReflexQuestion("kind", ReflexKind.CHOICE, "Select a kind", {"a": "A", "b": "B"})
RAW = {"kind": {"choice": "a", "probabilities": {"a": .95, "b": .05}, "confidence": .95}}


def test_unrelated_measured_calibration_cannot_accept_a_question():
    snapshot = CalibrationSnapshot("unrelated.question", True, n_labelled=100,
        coverage_at_threshold=.9, accuracy_at_threshold=.99, data_origin="labelled_outcomes")
    batch = ReflexEngine(InjectedReflexBackend(RAW)).evaluate("state", [Q], snapshot)
    assert batch.get("kind").auto_act_allowed is False
    assert batch.uncalibrated is True


def test_mapping_preserves_keys_types_and_canonical_order():
    class Recorder:
        latin_only = False
        def __init__(self):
            self.states = []
        def evaluate(self, text, questions):
            self.states.append(text)
            return RAW
    recorder = Recorder()
    engine = ReflexEngine(recorder)
    first = {"amount": 100, "limit": 200, "meta": {"approved": False, "tags": ["é", None]}}
    second = {"limit": 100, "amount": 200, "meta": first["meta"]}
    engine.evaluate(first, [Q])
    engine.evaluate(second, [Q])
    engine.evaluate(dict(reversed(list(first.items()))), [Q])
    assert recorder.states[0] != recorder.states[1]
    assert json.loads(recorder.states[0]) == first
    assert recorder.states[0] == recorder.states[2]


def test_typesafe_accepts_only_the_declared_four_decimal_rounding():
    q = ReflexQuestion("kind", ReflexKind.CHOICE, "Select a kind", {"a": "A", "b": "B", "c": "C"})
    payload = {"model": "pinned-synthetic", "usage": {"input_tokens": 12, "output_tokens": 0},
        "answers": {"kind": {"type": "choice", "choice": "a", "confidence": .3333,
            "probabilities": {"a": .3333, "b": .3333, "c": .3333}}}}
    backend = TypeSafeBackend(api_key="unused", model=payload["model"], post=lambda *_: payload)
    answer = ReflexEngine(backend).evaluate("state", [q]).get("kind")
    assert abs(sum(answer.probabilities.values()) - 1) < 1e-12
    assert payload["answers"]["kind"]["probabilities"]["a"] == .3333
    assert backend.last_raw_answers == payload["answers"]


def bound_engine(version="v1"):
    return ReflexEngine(InjectedReflexBackend(RAW), backend_id="test.fixed", backend_version=version)


def snapshot(engine, question=Q, questions=None):
    return CalibrationSnapshot(f"parcimonia.{question.name}", True, n_labelled=100,
        coverage_at_threshold=.9, accuracy_at_threshold=.99, data_origin="labelled_outcomes",
        binding=engine.calibration_binding(question, questions=questions))


def test_matching_calibration_has_statistical_eligibility_without_execution():
    engine = bound_engine()
    calibrated = snapshot(engine)
    answer = engine.evaluate("state", [Q], calibrated).get("kind")
    assert answer.auto_act_allowed is True
    assert calibrated.permits_auto_act(.95) is False  # Current identity is required.


@pytest.mark.parametrize("attribute,value", [
    ("backend_id", "other"), ("backend_version", "v2"),
    ("question_hash", "0" * 64), ("schema_hash", "0" * 64),
    ("state_encoding", "reflex-state/1"), ("confidence_metric", "margin/1"),
])
def test_mismatched_binding_cannot_calibrate(attribute, value):
    engine = bound_engine()
    old = snapshot(engine)
    invalid = replace(old, binding=replace(old.binding, **{attribute: value}))
    batch = engine.evaluate("state", [Q], invalid)
    assert batch.uncalibrated and not batch.get("kind").auto_act_allowed


def test_question_semantics_option_order_and_full_schema_are_bound():
    engine = bound_engine()
    calibrated = snapshot(engine)
    for changed in (replace(Q, instructions="Another decision"),
                    replace(Q, criteria={"a": "Changed meaning", "b": "B"}),
                    replace(Q, criteria={"b": "B", "a": "A"})):
        assert not engine.evaluate("state", [changed], calibrated).get("kind").auto_act_allowed
    q2 = ReflexQuestion("other", ReflexKind.NOUL, "Other question")
    assert engine.calibration_binding(Q, questions=[Q, q2]) != calibrated.binding
    assert engine.calibration_binding(Q, questions=[q2, Q]) != engine.calibration_binding(Q, questions=[Q, q2])


def test_calibrations_are_applied_per_question_and_partial_batch_stays_uncalibrated():
    q2 = ReflexQuestion("other", ReflexKind.NOUL, "Other question")
    engine = ReflexEngine(InjectedReflexBackend({**RAW, "other": {
        "noul": .95, "probabilities": {"false": .05, "true": .95}, "confidence": .95}}),
        backend_id="test.fixed", backend_version="v1")
    questions = [Q, q2]
    first, second = snapshot(engine, Q, questions), snapshot(engine, q2, questions)
    partial = engine.evaluate("state", questions, {"kind": first})
    assert partial.uncalibrated
    assert partial.get("kind").auto_act_allowed
    assert not partial.get("other").auto_act_allowed
    complete = engine.evaluate("state", questions, {"kind": first, "other": second})
    assert not complete.uncalibrated
    assert all(a.auto_act_allowed for a in complete.answers)
    unbound = engine.evaluate("state", [Q], replace(first, binding=None))
    assert unbound.uncalibrated and not unbound.get("kind").auto_act_allowed


def test_statistics_without_backend_identity_remain_ineligible():
    identified = bound_engine()
    calibrated = snapshot(identified)
    anonymous = ReflexEngine(InjectedReflexBackend(RAW))
    assert anonymous.calibration_binding(Q) is None
    assert not anonymous.evaluate("state", [Q], calibrated).get("kind").auto_act_allowed


def test_backend_identity_override_is_not_allowed_to_disagree():
    class Provider(InjectedReflexBackend):
        backend_id = "known"
        backend_version = "v1"
    with pytest.raises(ValueError, match="does not match"):
        ReflexEngine(Provider(RAW), backend_id="other", backend_version="v1")


@pytest.mark.parametrize("bad_state", [{"x": float("nan")}, {"nested": {1: "ambiguous"}}, {1: 2}])
def test_invalid_json_is_rejected_before_a_backend_call(bad_state):
    class Never:
        def evaluate(self, *_):
            pytest.fail("invalid state must not reach the backend")
    with pytest.raises((ValueError, TypeError)):
        ReflexEngine(Never()).evaluate(bad_state, [Q])


def test_text_inputs_remain_byte_for_byte_unchanged():
    class Recorder:
        def evaluate(self, text, questions):
            assert text == '  Unicode é and {"amount":100}\n'
            return RAW
    ReflexEngine(Recorder()).evaluate('  Unicode é and {"amount":100}\n', [Q])


@pytest.mark.parametrize("calibration", [{"unknown": object()}, {"kind": object()}, "wrong type"])
def test_invalid_calibration_is_rejected_before_a_backend_call(calibration):
    class Never:
        def evaluate(self, *_):
            pytest.fail("invalid calibration must not reach the backend")
    with pytest.raises((ValueError, TypeError)):
        ReflexEngine(Never()).evaluate("state", [Q], calibration)


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -1, 1.1])
def test_invalid_confidence_does_not_pass_a_bound_snapshot(bad):
    calibrated = snapshot(bound_engine())
    assert not calibrated.permits_auto_act(bad, binding=calibrated.binding)


@pytest.mark.parametrize("provider", ["typesafe", "laya"])
@pytest.mark.parametrize("probs", [
    {"a": .8, "b": .1}, {"a": 0, "b": 0}, {"a": True, "b": 0},
    {"a": float("nan"), "b": 1}, {"a": .9, "unknown": .1},
])
def test_providers_share_strict_rejection_of_invalid_distributions(provider, probs):
    payload = {"model": "pinned", "usage": {"input_tokens": 12, "output_tokens": 0},
        "answers": {"kind": {"type": "choice", "choice": "a", "probabilities": probs}}}
    if provider == "typesafe":
        backend = TypeSafeBackend(api_key="unused", model="pinned", post=lambda *_: payload)
    else:
        backend = LayaBackend(revision="a" * 40, runtime_version="test", predict=lambda *_, **kw: payload)
    with pytest.raises(ValueError):
        backend.evaluate("state", [Q])
    assert backend.calls == 1


def test_provider_rounding_is_not_relaxed_in_the_reflex_core():
    q = ReflexQuestion("kind", ReflexKind.CHOICE, "Select", {"a": "A", "b": "B", "c": "C"})
    raw = {"kind": {"type": "choice", "choice": "a", "probabilities": dict.fromkeys(q.option_keys, .3333)}}
    with pytest.raises(ValueError, match="sum to 1"):
        ReflexEngine(InjectedReflexBackend(raw)).evaluate("state", [q])


@pytest.mark.parametrize("usage", [{"truncated": True}, {"state_tokens_dropped": 1}, {"options": {"collapsed": True}}])
def test_typesafe_refuses_reported_truncation_without_retry(usage):
    payload = {"model": "pinned", "usage": usage, "answers": RAW}
    backend = TypeSafeBackend(api_key="unused", model="pinned", post=lambda *_: payload)
    with pytest.raises(ValueError, match="truncated"):
        backend.evaluate("state", [Q])
    assert backend.calls == 1


def test_calibration_harness_binds_full_schema_and_the_runtime_confidence_metric():
    q2 = ReflexQuestion("other", ReflexKind.NOUL, "Other question")
    class Provider:
        backend_id, backend_version = "test.fixed", "v1"
        def __init__(self):
            self.seen = []
        def evaluate(self, state, questions):
            self.seen.append([q.name for q in questions])
            return {**RAW, "other": {"noul": .9, "probabilities": {"false": .1, "true": .9}, "confidence": .95}}
    provider = Provider()
    engine = ReflexEngine(provider)
    questions = [Q, q2]
    cases = [LabelledCase("c1", "first", {"kind": "a", "other": True}),
             LabelledCase("c2", "second", {"other": True})]
    report = evaluate_calibration(engine, questions, cases, data_origin="labelled_outcomes", min_labelled=1)
    first = report.for_question("parcimonia.kind")
    second = report.for_question("parcimonia.other")
    assert provider.seen == [["kind", "other"], ["kind", "other"]]
    assert second.coverage_at_threshold == 1  # Provider .95, not a recomputed margin .8.
    assert first.binding.schema_hash == second.binding.schema_hash
    assert first.binding.state_encoding == STATE_ENCODING_VERSION
    assert report.to_record()["schema_version"] == 2
    assert report.to_record()["snapshots"][0]["binding"]["backend_version"] == "v1"
    assert report.authorizes_auto_act() is False
    batch = engine.evaluate("third", questions, {"kind": first, "other": second})
    assert all(answer.auto_act_allowed for answer in batch.answers)


def test_recorded_backend_identity_is_preserved_by_calibrated_replay():
    engine = bound_engine()
    calibrated = snapshot(engine)
    request = DecisionRequest("replay-contract", "state", (Q,),
                              backend_id="test.fixed", backend_version="v1")
    record = DecisionRecord("test.fixed", "v1", request.fingerprint(), RAW)
    replay = replay_decision(record, request, calibration=calibrated)
    assert replay.status == "ok"
    assert not replay.batch.uncalibrated
    assert replay.batch.get("kind").auto_act_allowed
    wrong = replace(calibrated, binding=replace(calibrated.binding, backend_version="v2"))
    replay = replay_decision(record, request, calibration=wrong)
    assert replay.batch.uncalibrated and not replay.batch.get("kind").auto_act_allowed


@pytest.mark.parametrize("provider", ["typesafe", "laya"])
def test_score_rounding_preserves_rubric_labels_and_raw_trace(provider):
    q = ReflexQuestion("effort", ReflexKind.SCORE, "Effort", ("low", "medium", "high"))
    payload = {"model": "pinned", "usage": {"input_tokens": 12, "output_tokens": 0},
        "answers": {"effort": {"type": "score", "score": 1,
            "probabilities": {"0": .3333, "1": .3333, "2": .3333}, "confidence": .3333}}}
    if provider == "typesafe":
        backend = TypeSafeBackend(api_key="unused", model="pinned", post=lambda *_: payload)
    else:
        backend = LayaBackend(revision="a" * 40, runtime_version="test", predict=lambda *_, **kw: payload)
    answer = ReflexEngine(backend).evaluate("state", [q]).get("effort")
    assert answer.probabilities == {key: 1 / 3 for key in q.option_keys}
    assert backend.last_raw_answers == payload["answers"]
