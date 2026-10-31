import json

import pytest

from tiberium_ai.local_iteration import IterationBudget, improve_candidate
from tiberium_ai.measurement import Environment
from tiberium_ai.verification import VerifierRegistry, hash_input


def run(candidates=(), **overrides):
    registry = VerifierRegistry()
    registry.register("technical", "1", lambda x: x.get("valid") is True)
    values = iter(candidates)
    options = dict(
        task_id="fixture-goal", route_id="fixture-tool", registry=registry,
        verifier_id="technical", verifier_version="1", evaluator_id="fixture-score",
        evaluator_version="1", environment=Environment("fixture", {"python": "3.12"}),
        produce=lambda index, best: next(values), evaluate=lambda x: x["score"],
        clock=lambda: 100.0, now=lambda: "2026-10-30T00:00:00+00:00",
    )
    options.update(overrides)
    return improve_candidate(**options)


def candidate(score, valid=True, **extra):
    return {"score": score, "valid": valid, **extra}


def test_technically_invalid_visual_winner_cannot_replace_baseline():
    baseline = candidate(0.4)
    result = run([candidate(1.0, False), candidate(0.8)], baseline=baseline,
                 budget=IterationBudget(max_iterations=2))
    assert result.best_iteration == 2
    assert result.best_score == 0.8
    assert result.records[1]["score"] is None
    assert result.records[1]["verification"]["verdict"] is False
    assert result.to_record()["best_input_hash"] == hash_input(candidate(0.8))
    assert result.to_record()["saving_claim"] is False
    assert result.records[2]["measurement"]["resources"]["tokens"] is None


def test_ties_and_regressions_keep_earlier_best_and_stop_at_patience():
    calls = []
    def produce(index, best):
        calls.append(index)
        return candidate(0.5 if index < 3 else 0.1)
    result = run(produce=produce, baseline=candidate(0.5))
    assert calls == [1, 2]
    assert result.best_iteration == 0
    assert result.stop_reason == "patience"


def test_target_baseline_requires_no_producer_call():
    result = run(baseline=candidate(0.9), budget=IterationBudget(target_score=0.8))
    assert result.stop_reason == "target_reached"
    assert len(result.records) == 1


def test_target_new_candidate_stops_without_extra_calls():
    result = run([candidate(0.9)], budget=IterationBudget(target_score=0.8))
    assert result.best_iteration == 1
    assert result.stop_reason == "target_reached"


def test_iteration_cap_and_partial_scores():
    result = run([candidate(0.1), candidate(0.2), candidate(0.3)],
                 budget=IterationBudget(max_iterations=3))
    assert result.stop_reason == "iteration_budget"
    assert result.best_score == 0.3
    assert result.to_record()["status"] == "ready_for_review"


def test_unknown_verifier_does_not_invoke_tools_or_model():
    result = run(verifier_version="unknown", produce=lambda *_: pytest.fail("called"))
    assert result.stop_reason == "unregistered_verifier"
    assert result.best_output is None
    assert result.to_record()["status"] == "abstained"


def test_rejected_baseline_cannot_seed_producer():
    seen = []
    def produce(index, best):
        seen.append(best)
        return candidate(0.6)
    result = run(produce=produce, baseline=candidate(1.0, False),
                 budget=IterationBudget(max_iterations=1))
    assert seen == [None]
    assert result.best_iteration == 1


def test_unknown_score_abstains_and_remains_unranked():
    result = run([candidate(0.1), candidate(0.2)], evaluate=lambda _: None)
    assert result.best_iteration is None
    assert result.stop_reason == "patience"
    assert all(x["score"] is None for x in result.records)


@pytest.mark.parametrize("score", [True, -1, 1.01, float("nan"), float("inf"), "1"])
def test_invalid_scores_stop_and_preserve_prior_best(score):
    result = run([candidate(0.7)], baseline=candidate(0.5),
                 evaluate=lambda x: 0.5 if x["score"] == 0.5 else score)
    assert result.stop_reason == "evaluator_error"
    assert result.best_score == 0.5
    assert result.to_record()["status"] == "partial"


def test_producer_exception_is_not_retried_and_does_not_leak_message():
    calls = []
    def fail(index, best):
        calls.append(index)
        raise RuntimeError("PRIVATE_SECRET")
    result = run(produce=fail, baseline=candidate(0.5))
    assert calls == [1]
    assert result.best_iteration == 0
    assert result.stop_reason == "producer_error"
    assert "PRIVATE_SECRET" not in json.dumps(result.to_record())
    assert result.to_record()["error_type"] == "RuntimeError"


def test_evaluator_does_not_receive_rejected_candidates():
    result = run([candidate(0.9, False), candidate(0.8, False)],
                 evaluate=lambda _: pytest.fail("must not evaluate"))
    assert result.best_score is None


def test_mutating_producer_evaluator_checkpoint_cannot_change_retained_snapshots():
    original = candidate(0.7, payload={"secret": "PRIVATE_PAYLOAD"})
    def evaluate(value):
        score = value["score"]
        value["payload"] = "changed"
        return score
    def produce(index, best):
        if best is not None:
            best["payload"] = "changed"
        return original
    checkpoints = []
    def checkpoint(value):
        checkpoints.append(value.to_record())
        value.best_output["score"] = 0
    result = run(produce=produce, evaluate=evaluate, checkpoint=checkpoint,
                 budget=IterationBudget(max_iterations=2))
    original["score"] = 0
    assert result.best_score == 0.7
    assert result.best_output["score"] == 0.7
    assert result.best_output["payload"]["secret"] == "PRIVATE_PAYLOAD"
    assert "PRIVATE_PAYLOAD" not in json.dumps(result.to_record())
    assert all(x["status"] == "running" for x in checkpoints)


def test_checkpoint_failure_does_not_repeat_the_producer():
    calls = []
    def produce(index, best):
        calls.append(index)
        return candidate(0.7)
    def checkpoint(_):
        raise OSError("PRIVATE_PATH")
    result = run(produce=produce, checkpoint=checkpoint)
    assert calls == [1]
    assert result.best_score == 0.7
    assert result.stop_reason == "checkpoint_error"
    assert "PRIVATE_PATH" not in json.dumps(result.to_record())


def test_deadline_prevents_next_callback_without_claiming_preemption():
    current = [0.0]
    scored = []
    def produce(index, best):
        current[0] = 11.0
        return candidate(0.9)
    result = run(produce=produce, evaluate=lambda x: scored.append(x) or 1.0,
                 clock=lambda: current[0], budget=IterationBudget(max_seconds=10))
    assert result.stop_reason == "time_budget"
    assert len(result.records) == 1
    assert scored == []
    assert result.best_iteration is None


def test_slow_evaluator_does_not_start_checkpoint_or_another_producer():
    current = [0.0]
    def evaluate(_):
        current[0] = 11.0
        return 0.5
    result = run([candidate(0.5)], evaluate=evaluate, clock=lambda: current[0],
                 checkpoint=lambda _: pytest.fail("deadline"), budget=IterationBudget(max_seconds=10))
    assert result.stop_reason == "time_budget"
    assert result.best_score == 0.5


@pytest.mark.parametrize("baseline", [False, True])
def test_verifier_mutation_is_detected(baseline):
    registry = VerifierRegistry()
    def verifier(value):
        value["valid"] = True
        return True
    registry.register("technical", "1", verifier)
    value = candidate(1.0, False)
    result = run([value], baseline=value if baseline else None, registry=registry)
    assert result.stop_reason == "verifier_mutation"
    assert result.best_iteration is None


def test_oversized_output_fails_without_evaluation_or_retry():
    result = run([candidate(0.1, text="x" * 100)],
                 budget=IterationBudget(max_candidate_bytes=10))
    assert result.stop_reason == "producer_error"
    assert len(result.records) == 1


def test_keyboard_interrupt_is_not_swallowed():
    def produce(*_):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        run(produce=produce)


@pytest.mark.parametrize("kwargs", [
    {"max_iterations": True}, {"max_iterations": 65}, {"patience": 0},
    {"max_seconds": float("nan")}, {"max_seconds": 0}, {"max_seconds": True},
    {"target_score": 2}, {"max_candidate_bytes": False},
])
def test_invalid_budgets_are_rejected(kwargs):
    with pytest.raises(ValueError):
        IterationBudget(**kwargs)


def test_decreasing_clock_is_rejected():
    ticks = iter([10, 9])
    with pytest.raises(ValueError, match="clock"):
        run(clock=lambda: next(ticks))


def test_result_properties_and_serialized_records_are_defensive_copies():
    result = run([candidate(0.7)], budget=IterationBudget(max_iterations=1))
    expected = result.to_record()
    result.best_output["valid"] = False
    result.records[0]["verification"]["input_hash"] = "0" * 64
    result.to_record()["iterations"][0]["score"] = 1
    assert result.to_record() == expected
    assert result.to_record()["best_input_hash"] == result.records[0]["verification"]["input_hash"]


def test_non_json_verifier_mutation_keeps_prior_best():
    registry = VerifierRegistry()
    def verify(value):
        if value["score"] > 0.5:
            value["bad"] = set()
        return True
    registry.register("technical", "1", verify)
    result = run([candidate(0.9)], baseline=candidate(0.5), registry=registry)
    assert result.stop_reason == "verifier_mutation"
    assert result.best_score == 0.5
    assert result.to_record()["status"] == "partial"


def test_invalid_verifier_return_keeps_prior_best_and_does_not_retry():
    registry = VerifierRegistry()
    registry.register("technical", "1", lambda x: True if x["score"] == 0.5 else "yes")
    calls = []
    def produce(index, best):
        calls.append(index)
        return candidate(0.9)
    result = run(produce=produce, baseline=candidate(0.5), registry=registry)
    assert result.stop_reason == "verification_error"
    assert result.best_score == 0.5
    assert calls == [1]
    assert result.records[1]["measurement"] is None
