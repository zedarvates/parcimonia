"""Improve one caller-owned candidate, without adding an agent orchestrator.

The existing caller owns authorization, tools, model calls, resource locks and
artifact snapshots. This opt-in helper only bounds iterations and keeps the best
technically verified JSON descriptor. It never executes shell/model instructions.
Scores are advisory; they cannot override a rejected or unknown verifier.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable

from .capture import capture_run
from .measurement import Environment
from .router import is_nonnegative_number
from .verification import VerifierRegistry, hash_input


@dataclass(frozen=True)
class IterationBudget:
    max_iterations: int = 6
    patience: int = 2
    max_seconds: float = 1800.0
    target_score: float | None = None
    max_candidate_bytes: int = 262144

    def __post_init__(self) -> None:
        for name in ("max_iterations", "patience"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 64:
                raise ValueError(f"{name} must be an integer in [1, 64].")
        if not is_nonnegative_number(self.max_seconds) or self.max_seconds == 0:
            raise ValueError("max_seconds must be finite and positive.")
        if self.target_score is not None:
            _score(self.target_score)
        if type(self.max_candidate_bytes) is not int or not 1 <= self.max_candidate_bytes <= 16777216:
            raise ValueError("max_candidate_bytes must be an integer in [1, 16777216].")


def _score(value: object) -> float:
    if not is_nonnegative_number(value) or value > 1:
        raise ValueError("score must be finite and in [0, 1].")
    return float(value)


def _identity(value: object) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("identities must be nonempty, trimmed strings.")


def _json(value: Any, cap: int) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(text.encode("utf-8")) > cap:
        raise ValueError("candidate exceeds max_candidate_bytes.")
    return text


def _unchanged(value: Any, expected_hash: str) -> bool:
    try:
        return hash_input(value) == expected_hash
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class IterationResult:
    task_id: str
    route_id: str
    evaluator_id: str
    evaluator_version: str
    stop_reason: str
    best_iteration: int | None
    best_score: float | None
    _records_json: str = field(repr=False)
    elapsed_seconds: float
    error_type: str | None = None
    _best_json: str | None = field(default=None, repr=False)

    @property
    def records(self) -> tuple[dict[str, Any], ...]:
        return tuple(json.loads(self._records_json))

    @property
    def best_output(self) -> Any:
        return json.loads(self._best_json) if self._best_json is not None else None

    def to_record(self) -> dict[str, Any]:
        """Payload-free, attributed summary; unknown usage is never zero."""
        has_best = self.best_iteration is not None
        interrupted = self.stop_reason in {"producer_error", "evaluator_error", "checkpoint_error", "verifier_mutation", "verification_error"}
        if self.stop_reason == "running":
            status = "running"
        else:
            status = ("partial" if has_best else "blocked") if interrupted else (
                "ready_for_review" if has_best else "abstained"
            )
        return {
            "kind": "local_iteration",
            "schema_version": 1,
            "task_id": self.task_id,
            "route_id": self.route_id,
            "evaluator": {"id": self.evaluator_id, "version": self.evaluator_version},
            "status": status,
            "stop_reason": self.stop_reason,
            "best_iteration": self.best_iteration,
            "best_score": self.best_score,
            "best_input_hash": hash_input(self.best_output) if has_best else None,
            "iterations": json.loads(self._records_json),
            "elapsed_seconds": self.elapsed_seconds,
            "error_type": self.error_type,
            "usage": {"cloud_tokens": None, "local_tokens": None, "cost": None},
            "saving_claim": False,
        }


def improve_candidate(
    *,
    task_id: str,
    route_id: str,
    produce: Callable[[int, Any], Any],
    evaluate: Callable[[Any], float | None],
    registry: VerifierRegistry,
    verifier_id: str,
    verifier_version: str,
    evaluator_id: str,
    evaluator_version: str,
    environment: Environment,
    budget: IterationBudget = IterationBudget(),
    baseline: Any = None,
    clock: Callable[[], float] = perf_counter,
    now: Callable[[], str] | None = None,
    checkpoint: Callable[[IterationResult], None] | None = None,
) -> IterationResult:
    """Execute at most N producer calls for an already admitted task.

    Baseline is optional and, when supplied, verified and scored identically.
    A score of None abstains. Ties keep the earlier best. Returned payloads are
    JSON snapshots, not filesystem backups. A caller must snapshot actual files
    before returning descriptors, and may persist checkpoints in its journal.

    Time bounds are cooperative between callbacks, not process preemption.
    A callback that overruns is not retried; pending evaluation is skipped.
    KeyboardInterrupt propagates. A checkpoint error stops without replaying
    the producer or assuming whether a caller-owned write took effect.
    """
    for identity in (task_id, route_id, verifier_id, verifier_version, evaluator_id, evaluator_version):
        _identity(identity)
    if not isinstance(budget, IterationBudget):
        raise TypeError("budget must be IterationBudget.")
    if not isinstance(registry, VerifierRegistry) or not isinstance(environment, Environment):
        raise TypeError("registry and environment must use existing Parcimonia contracts.")
    if not callable(produce) or not callable(evaluate) or (checkpoint is not None and not callable(checkpoint)):
        raise TypeError("producer, evaluator and optional checkpoint must be callable.")
    previous_tick: float | None = None

    def tick() -> float:
        nonlocal previous_tick
        value = clock()
        if not is_nonnegative_number(value) or (previous_tick is not None and value < previous_tick):
            raise ValueError("clock must be finite, nonnegative and monotonic.")
        previous_tick = float(value)
        return previous_tick

    started = tick()
    records: list[dict[str, Any]] = []
    best_json: str | None = None
    best_index: int | None = None
    best_score: float | None = None
    stalls = 0

    def result(reason: str, error: str | None = None) -> IterationResult:
        return IterationResult(
            task_id, route_id, evaluator_id, evaluator_version, reason,
            best_index, best_score, json.dumps(records, allow_nan=False),
            tick() - started, error, best_json,
        )

    def score_candidate(text: str) -> float | None:
        # Scorers cannot mutate the retained candidate or its verified input.
        value = evaluate(json.loads(text))
        return None if value is None else _score(value)

    if not registry.is_registered(verifier_id, verifier_version):
        return result("unregistered_verifier")

    if baseline is not None:
        text = _json(baseline, budget.max_candidate_bytes)
        baseline_value = json.loads(text)
        try:
            verification = registry.verify(verifier_id, verifier_version, baseline_value)
        except (TypeError, ValueError) as exc:
            return result("verification_error", type(exc).__name__)
        row = {"iteration": 0, "measurement": None, "verification": verification.to_record(),
               "score": None, "accepted_as_best": False}
        records.append(row)
        if not _unchanged(baseline_value, verification.input_hash):
            return result("verifier_mutation")
        if tick() - started >= budget.max_seconds:
            return result("time_budget")
        if verification.verdict is True:
            try:
                value = score_candidate(text)
            except Exception as exc:
                return result("evaluator_error", type(exc).__name__)
            row["score"] = value
            if value is not None:
                best_json, best_index, best_score = text, 0, value
                row["accepted_as_best"] = True

    if best_score is not None and budget.target_score is not None and best_score >= budget.target_score:
        return result("target_reached")

    for index in range(1, budget.max_iterations + 1):
        if tick() - started >= budget.max_seconds:
            return result("time_budget")

        def generate() -> Any:
            value = produce(index, json.loads(best_json) if best_json is not None else None)
            return json.loads(_json(value, budget.max_candidate_bytes))

        try:
            captured = capture_run(
                task_id=task_id, route_id=route_id, run=generate,
                verifier_id=verifier_id, verifier_version=verifier_version,
                registry=registry, cost_unit="unknown/task", environment=environment,
                clock=tick, now=now,
            )
        except (TypeError, ValueError) as exc:
            # A producer can already have completed before verification fails.
            # Preserve that uncertainty and the earlier best; never replay it.
            records.append({"iteration": index, "measurement": None, "verification": None,
                            "score": None, "accepted_as_best": False,
                            "execution_state": "verification_not_completed"})
            return result("verification_error", type(exc).__name__)
        row = {"iteration": index, "measurement": captured.measurement,
               "verification": captured.verification.to_record() if captured.verification else None,
               "score": None, "accepted_as_best": False}
        records.append(row)
        if not captured.measurement["outcome"]["ok"]:
            return result("producer_error", captured.measurement["outcome"]["error_type"])
        if captured.verification is not None and not _unchanged(captured.output, captured.verification.input_hash):
            return result("verifier_mutation")
        if tick() - started >= budget.max_seconds:
            return result("time_budget")
        if captured.verification is not None and captured.verification.verdict is True:
            text = _json(captured.output, budget.max_candidate_bytes)
            try:
                value = score_candidate(text)
            except Exception as exc:
                return result("evaluator_error", type(exc).__name__)
            row["score"] = value
            if value is not None and (best_score is None or value > best_score):
                best_json, best_index, best_score = text, index, value
                row["accepted_as_best"] = True
        stalls = 0 if row["accepted_as_best"] else stalls + 1
        if tick() - started >= budget.max_seconds:
            return result("time_budget")
        if checkpoint is not None:
            try:
                checkpoint(result("running"))
            except Exception as exc:
                return result("checkpoint_error", type(exc).__name__)
        if tick() - started >= budget.max_seconds:
            return result("time_budget")
        if best_score is not None and budget.target_score is not None and best_score >= budget.target_score:
            return result("target_reached")
        if stalls >= budget.patience:
            return result("patience")
    return result("iteration_budget")
