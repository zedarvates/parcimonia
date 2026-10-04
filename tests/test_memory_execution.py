"""Simulated caller-loop tests, never real homelab/provider evidence."""

import json
from dataclasses import replace

import pytest

from tiberium_ai.capture import capture_run
from tiberium_ai.measurement import Environment
from tiberium_ai.memory_capture import MemorySequenceCapture
from tiberium_ai.memory_execution import attach_memory_run
from tiberium_ai.memory_replay import VersionedFactArchive, build_memory_replay_cases, read_jsonl
from tiberium_ai.verification import VerifierRegistry, hash_input


def turn(index=0):
    return {"task": {"task_id": f"turn-{index}", "kind": "choose", "inputs": {
        "entity_id": "alpha", "source_version": "v1"}}, "required_keys": ["budget"],
        "routing_epoch": "fixture-v1", "candidates": [
        {"route_id": "existing-route", "capability_ids": ["solve"], "confidence": 0.95}]}


def capture(*, origin="authored", max_bytes=33554432):
    cap = MemorySequenceCapture(sequence_id="episode-a", origin=origin, source_ref="fixture-v1",
                                producer_id="fixture-author", max_capture_bytes=max_bytes)
    cap.append_turn(turn(), facts={"budget": 10}, missing=[])
    return cap


def existing_run(*, fail=False, unknown_verifier=False):
    calls = []
    registry = VerifierRegistry()
    if not unknown_verifier:
        registry.register("fixture-exact", "1", lambda value: value["answer"] == "PRIVATE-ANSWER-MARKER")
    def run():
        calls.append("called")
        if fail:
            raise OSError("PRIVATE-ERROR-MARKER")
        return {"answer": "PRIVATE-ANSWER-MARKER"}
    captured = capture_run(task_id="turn-0", route_id="existing-route", run=run,
        verifier_id="fixture-exact", verifier_version="1", registry=registry,
        environment=Environment("fixture-runner", {"python": "fixture"}),
        clock=iter([1.0, 1.25]).__next__, now=lambda: "2026-10-04T06:00:00+00:00",
        cost_unit="unmeasured-provider-unit")
    return captured, calls


REQUEST_HASH = hash_input({"request": "PRIVATE-REQUEST-MARKER"})


def usage(**extra):
    return {"receipt_id": "run-001", "origin": "provider_reported", "source_ref": "fixture-response",
            "variant": "current", "backend_id": "fixture-backend", "backend_version": "v1",
            "payload_hash": REQUEST_HASH, "input_tokens": 7, "output_tokens": 3,
            "latency_ms": 90, **extra}


def test_attach_existing_run_never_reexecutes_and_exports_no_raw_response(tmp_path):
    cap = capture()
    captured, calls = existing_run()
    attached = attach_memory_run(cap, captured, execution_id="run-001", request_hash=REQUEST_HASH,
                                 usage_receipt=usage())
    assert attached.execution_recorded and attached.usage_recorded
    assert attached.detail_code == "recorded" and calls == ["called"]
    cap.append_turn(turn(1), facts={"budget": 10}, missing=[])
    snapshot = cap.snapshot()
    execution, receipt = snapshot["executions"][0], snapshot["usage"][0]
    assert execution["sequence_hash"] == receipt["sequence_hash"] == hash_input(snapshot["sequence"])
    assert execution["origin"] == receipt["origin"] == "authored"
    assert execution["measurement"]["latency_ms"] == 250
    assert receipt["latency_ms"] == 90
    assert execution["measurement"]["cost"] is None
    assert execution["measurement"]["resources"]["tokens"] is None
    assert receipt["tokens_total"] == 10
    assert execution["verification"]["input_hash"] == hash_input(captured.output)
    cap.write(tmp_path / "capture")
    assert read_jsonl(tmp_path / "capture" / "executions.jsonl")[0] == execution
    for file in (tmp_path / "capture").iterdir():
        assert "PRIVATE-ANSWER-MARKER" not in file.read_text(encoding="utf-8")
        assert "PRIVATE-REQUEST-MARKER" not in file.read_text(encoding="utf-8")
    cases, provenance = build_memory_replay_cases([snapshot["sequence"]], VersionedFactArchive(snapshot["facts"]))
    assert cases[0].verifier is None
    assert provenance["label_status"]["episode-a"] == "missing_outcomes"
    duplicate = attach_memory_run(cap, captured, execution_id="run-001", request_hash=REQUEST_HASH)
    assert not duplicate.execution_recorded and calls == ["called"]
    assert len(cap.snapshot()["executions"]) == 1


def test_missing_usage_and_verifier_preserve_unknowns_without_inferred_success():
    cap = capture()
    captured, calls = existing_run(unknown_verifier=True)
    result = attach_memory_run(cap, captured, execution_id="run-001", request_hash=REQUEST_HASH)
    assert result.execution_recorded and not result.usage_recorded
    assert result.detail_code == "usage_not_supplied"
    snapshot = cap.snapshot()
    assert snapshot["usage"] == []
    assert snapshot["executions"][0]["verification"]["verdict"] is None
    assert snapshot["manifest"]["outcomes"] == "not_collected"
    assert snapshot["manifest"]["production_saving_claim"]["status"] == "refused"
    assert calls == ["called"]


def test_failed_call_keeps_failure_and_explicit_partial_usage_without_retry():
    cap = capture()
    captured, calls = existing_run(fail=True)
    result = attach_memory_run(cap, captured, execution_id="run-001", request_hash=REQUEST_HASH,
                              usage_receipt=usage(input_tokens=7, output_tokens=None, latency_ms=None))
    assert result.execution_recorded and result.usage_recorded and calls == ["called"]
    snapshot = cap.snapshot()
    assert snapshot["executions"][0]["measurement"]["outcome"] == {"ok": False, "error_type": "OSError"}
    assert snapshot["executions"][0]["verification"] is None
    assert snapshot["usage"][0]["tokens_total"] is None
    assert "PRIVATE-ERROR-MARKER" not in json.dumps(snapshot)


@pytest.mark.parametrize("extra", [{"receipt_id": "other-run"}, {"payload_hash": "0" * 64},
                                    {"variant": "compact"}, {"cost": 1}, {"tokens_saved": 10}])
def test_rejected_usage_preserves_the_actual_execution_and_never_retries(extra):
    cap = capture()
    captured, calls = existing_run()
    result = attach_memory_run(cap, captured, execution_id="run-001", request_hash=REQUEST_HASH,
                              usage_receipt=usage(**extra))
    assert result.execution_recorded and not result.usage_recorded
    assert result.detail_code == "usage_record_rejected"
    assert len(cap.snapshot()["executions"]) == 1 and cap.snapshot()["usage"] == []
    assert calls == ["called"]


@pytest.mark.parametrize("change", ["task", "route", "request_hash", "output"])
def test_scope_and_changed_output_are_rejected_before_recording(change):
    cap = capture()
    captured, calls = existing_run()
    request_hash = REQUEST_HASH
    if change == "task":
        captured.measurement["task_id"] = "other-task"
    elif change == "route":
        captured.measurement["route_id"] = "other-route"
    elif change == "request_hash":
        request_hash = "invalid"
    else:
        captured.output["answer"] = "changed"
    result = attach_memory_run(cap, captured, execution_id="run-001", request_hash=request_hash)
    assert not result.execution_recorded and result.detail_code == "execution_record_rejected"
    assert cap.snapshot()["executions"] == [] and calls == ["called"]


def test_unknown_provider_measurement_is_not_filled_from_local_measurement():
    cap = capture(origin="captured")  # Simulated attribution only.
    captured, _ = existing_run()
    result = attach_memory_run(cap, captured, execution_id="run-001", request_hash=REQUEST_HASH,
                              usage_receipt=usage(latency_ms=None, input_tokens=None, output_tokens=None))
    assert result.usage_recorded
    receipt = cap.snapshot()["usage"][0]
    assert receipt["origin"] == "provider_reported"
    assert receipt["latency_ms"] is None and receipt["tokens_total"] is None
    assert receipt["cost"] is None


def test_budget_failure_is_logging_failure_and_leaves_completed_run_available():
    cap = capture(max_bytes=1800)
    captured, calls = existing_run()
    before = cap.snapshot()
    result = attach_memory_run(cap, captured, execution_id="run-001", request_hash=REQUEST_HASH)
    assert not result.execution_recorded
    assert captured.measurement["outcome"]["ok"] is True
    assert cap.snapshot() == before and calls == ["called"]


def test_execution_without_successful_output_cannot_have_verification():
    cap = capture()
    failed, calls = existing_run(fail=True)
    successful, _ = existing_run()
    bad = replace(failed, verification=successful.verification, output=successful.output)
    result = attach_memory_run(cap, bad, execution_id="run-001", request_hash=REQUEST_HASH)
    assert not result.execution_recorded and calls == ["called"]


def test_earlier_usage_cannot_be_bound_to_a_different_execution():
    cap = capture()
    cap.record_usage("turn-0", usage(payload_hash="0" * 64))
    captured, calls = existing_run()
    before = cap.snapshot()
    result = attach_memory_run(cap, captured, execution_id="run-001", request_hash=REQUEST_HASH)
    assert not result.execution_recorded and cap.snapshot() == before and calls == ["called"]
