import json

import pytest

from tiberium_ai.capture import capture_run
from tiberium_ai.measurement import Environment
from tiberium_ai.verification import VerifierRegistry, shape_verifier


def environment():
    return Environment("fixture-runner", {"python": "3.14.0"})


def clock_from(*ticks):
    return iter(ticks).__next__


def registry():
    verifier_registry = VerifierRegistry()
    verifier_registry.register("shape/answer", "1", shape_verifier({"answer": "str"}))
    return verifier_registry


def capture(**overrides):
    arguments = dict(
        task_id="task-1",
        route_id="rule",
        run=lambda: {"answer": "ok"},
        verifier_id="shape/answer",
        verifier_version="1",
        registry=registry(),
        cost_unit="unit/task",
        environment=environment(),
        clock=clock_from(10.0, 10.25),
        now=lambda: "2026-09-18T06:00:00+00:00",
    )
    arguments.update(overrides)
    return capture_run(**arguments)


def test_successful_capture_returns_a_measurement_and_attributed_evidence():
    captured = capture()
    assert captured.measurement["kind"] == "measurement"
    assert captured.measurement["data_origin"] == "measured"
    assert captured.measurement["latency_ms"] == 250.0
    assert captured.measurement["outcome"] == {"ok": True, "error_type": None}
    assert captured.evidence is not None
    assert captured.evidence.verification.verdict is True
    assert captured.evidence.measured_latency_ms == 250.0
    assert captured.evidence.measured_cost is None


def test_the_output_is_verified_but_never_stored_in_a_record():
    captured = capture(run=lambda: {"answer": "PRIVATE_OUTPUT"})
    assert captured.output == {"answer": "PRIVATE_OUTPUT"}
    assert "PRIVATE_OUTPUT" not in json.dumps(captured.measurement)
    assert "PRIVATE_OUTPUT" not in json.dumps(captured.evidence.verification.to_record())
    assert len(captured.evidence.verification.input_hash) == 64


def test_a_wrong_output_is_rejected_by_the_verifier():
    captured = capture(run=lambda: {"answer": 1})
    assert captured.evidence.verification.verdict is False
    assert captured.evidence.verifier_ok is False


def test_a_failed_run_records_the_error_and_produces_no_evidence():
    def failing():
        raise ValueError("PRIVATE_REASON")

    captured = capture(run=failing)
    assert captured.measurement["outcome"] == {"ok": False, "error_type": "ValueError"}
    assert captured.measurement["latency_ms"] == 250.0
    assert captured.evidence is None
    assert captured.verification is None
    assert captured.output is None
    assert "PRIVATE_REASON" not in json.dumps(captured.measurement)


def test_an_unregistered_verifier_abstains_but_still_explains_itself():
    captured = capture(verifier_id="absent")
    assert captured.evidence is not None
    assert captured.evidence.verifier_ok is False
    assert captured.evidence.verification.verdict is None
    assert captured.evidence.verification.detail_code == "unregistered_verifier"


def test_a_non_serialisable_output_is_refused():
    with pytest.raises(ValueError, match="JSON"):
        capture(run=lambda: object())


def test_keyboard_interrupt_is_not_swallowed():
    def interrupted():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        capture(run=interrupted)
