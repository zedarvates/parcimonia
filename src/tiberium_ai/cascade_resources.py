"""Measured predictor stages and existing cost/deadline policies, without authority."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from math import isfinite
from typing import Any, Callable

from .decision_clock import DecisionBudget, DecisionTiming, assess_decision_timing
from .escalation import Budget, EscalationPolicy, EscalationState
from .measurement import Environment, run_baseline
from .router import is_nonnegative_number


@dataclass(frozen=True)
class StageEstimate:
    cost: float | None = None
    latency_ms: float | None = None

    def __post_init__(self) -> None:
        for value in (self.cost, self.latency_ms):
            if value is not None and not is_nonnegative_number(value):
                raise ValueError("stage estimates must be finite, nonnegative or null")


@dataclass(frozen=True)
class CostReceipt:
    amount: float | None
    unit: str
    method: str

    def __post_init__(self) -> None:
        if self.amount is not None and not is_nonnegative_number(self.amount):
            raise ValueError("observed cost must be finite, nonnegative or null")
        for value in (self.unit, self.method):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError("cost unit and observation method must be named")


class StageMeasurementError(Exception):
    """Safe error code; never preserve a provider or observer exception message."""


@dataclass(frozen=True)
class CascadeResourceControl:
    budget: Budget
    deadline: DecisionBudget
    baseline: StageEstimate
    fallback: StageEstimate
    cost_unit: str
    environment: Environment
    clock: Callable[[], float]
    observe_cost: Callable[[str, Any], CostReceipt] | None = None
    now: Callable[[], str] | None = None
    state_age_ms: float | None = None
    spent_cost_before: float | None = 0.0
    spent_latency_ms_before: float = 0.0
    attempts_before: int = 0
    escalations_before: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.budget, Budget) or not isinstance(self.deadline, DecisionBudget):
            raise TypeError("existing cost and decision budgets are required")
        if not isinstance(self.baseline, StageEstimate) or not isinstance(self.fallback, StageEstimate):
            raise TypeError("stage estimates are required")
        if not isinstance(self.environment, Environment) or not callable(self.clock):
            raise TypeError("environment and injected clock are required")
        if not isinstance(self.cost_unit, str) or not self.cost_unit.strip() or self.cost_unit != self.cost_unit.strip():
            raise ValueError("cost_unit must be named")
        if self.observe_cost is not None and not callable(self.observe_cost):
            raise TypeError("observe_cost must be callable or null")
        if self.now is not None and not callable(self.now):
            raise TypeError("now must be callable or null")
        for value in (self.spent_cost_before, self.state_age_ms):
            if value is not None and not is_nonnegative_number(value):
                raise ValueError("previous cost and snapshot age must be finite or null")
        if not is_nonnegative_number(self.spent_latency_ms_before):
            raise ValueError("previous latency must be finite and nonnegative")
        if type(self.attempts_before) is not int or self.attempts_before < 0 or type(self.escalations_before) is not int or not 0 <= self.escalations_before <= max(0, self.attempts_before - 1):
            raise ValueError("previous attempt/escalation counts are inconsistent")

    def to_policy_record(self):
        return {"version": "cascade-resources/1", "budget": asdict(self.budget), "deadline": asdict(self.deadline),
            "estimates": {"baseline": asdict(self.baseline), "fallback": asdict(self.fallback)},
            "cost_unit": self.cost_unit, "environment": asdict(self.environment), "state_age_ms": self.state_age_ms,
            "spent_cost_before": self.spent_cost_before, "spent_latency_ms_before": self.spent_latency_ms_before,
            "attempts_before": self.attempts_before, "escalations_before": self.escalations_before,
            "cost_observer_declared": self.observe_cost is not None}

    def start(self):
        return _ResourceSession(self)


class _ResourceSession:
    def __init__(self, control):
        self.control = control
        self.policy_record = control.to_policy_record()
        self.environment = Environment(control.environment.machine_id, dict(control.environment.runtime_versions))
        self.started = self._clock()
        self.last_tick = self.started
        self.elapsed_current_ms = 0.0
        self.spent_cost = control.spent_cost_before
        self.current_cost = 0.0
        self.attempts, self.escalations = control.attempts_before, control.escalations_before
        self.measurements, self.receipts, self.decisions = [], [], []
        self.timing = None
        self.last_run_ok = False
        self.measurement_pending = False

    def _clock(self):
        try:
            tick = self.control.clock()
        except Exception:
            raise StageMeasurementError("clock_unavailable") from None
        if type(tick) not in (int, float) or not isfinite(tick):
            raise StageMeasurementError("invalid_clock")
        if hasattr(self, "last_tick") and tick < self.last_tick:
            raise StageMeasurementError("clock_went_backwards")
        self.last_tick = tick
        return tick

    def _timing_block(self):
        self.timing = None
        tick = self._clock()
        self.elapsed_current_ms = (tick - self.started) * 1000
        age = None if self.control.state_age_ms is None else self.control.state_age_ms + self.elapsed_current_ms
        elapsed = self.control.spent_latency_ms_before + self.elapsed_current_ms
        self.timing = assess_decision_timing(self.control.deadline, DecisionTiming(elapsed, age))
        if not self.timing.usable:
            return self.timing.reason_code
        maximum = self.control.budget.max_latency_ms
        if maximum is not None and elapsed > maximum:
            return "latency_budget_exhausted"
        return None

    def before(self, route, next_route_id):
        block = self._timing_block()
        if block:
            return block
        if self.spent_cost is None:
            return "unknown_spent_cost"
        if self.attempts >= self.control.budget.max_attempts:
            return "attempt_budget_exhausted"
        estimate = self.control.baseline if route == "baseline" else self.control.fallback
        elapsed = self.control.spent_latency_ms_before + self.elapsed_current_ms
        if route == "fallback":
            decision = EscalationPolicy(self.control.budget).decide(run_ok=self.last_run_ok, verdict=None,
                attempts=self.attempts, escalations=self.escalations, spent_cost=self.spent_cost,
                spent_latency_ms=elapsed, next_route_id=next_route_id,
                next_estimated_cost=estimate.cost, next_estimated_latency_ms=estimate.latency_ms)
            self.decisions.append({"state": decision.state.value, "reason_code": decision.reason_code,
                                   "next_route_id": decision.next_route_id, "detail": decision.detail})
            if decision.state is not EscalationState.ESCALATE:
                return decision.reason_code
        if estimate.cost is None:
            return "unknown_cost"
        if self.spent_cost + estimate.cost > self.control.budget.max_cost:
            return "cost_budget_exhausted"
        if estimate.latency_ms is None:
            return "unknown_latency"
        if elapsed + estimate.latency_ms > self.control.deadline.budget_ms:
            return "latency_budget_exhausted"
        if self.control.budget.max_latency_ms is not None and elapsed + estimate.latency_ms > self.control.budget.max_latency_ms:
            return "latency_budget_exhausted"
        return None

    def skipped(self):
        # A rejected route preflight is an attempt, but has no predictor measurement.
        self.attempts += 1
        self.last_run_ok = False

    def execute(self, route, backend, identity, request_hash, run):
        box = {"called": False}
        def capture():
            box["called"] = True
            box["value"] = run()
        self.measurement_pending = True
        self.attempts += 1
        if route == "fallback":
            self.escalations += 1
        try:
            measurement = run_baseline(request_hash, identity[0], capture, environment=self.environment,
                cost_unit=self.control.cost_unit, clock=self._clock, now=self.control.now)
            record = measurement.to_record()
        except Exception:
            if box["called"]:
                self.current_cost = self.spent_cost = None
            raise StageMeasurementError("stage_measurement_failed") from None
        self.measurements.append(record)
        self.last_run_ok = measurement.ok
        try:
            receipt = self.control.observe_cost(route, backend) if self.control.observe_cost else CostReceipt(None, self.control.cost_unit, "unobserved")
            if not isinstance(receipt, CostReceipt) or receipt.unit != self.control.cost_unit:
                raise ValueError("invalid cost receipt")
        except Exception:
            self.current_cost = self.spent_cost = None
            raise StageMeasurementError("cost_observation_failed") from None
        self.measurements[-1] = replace(measurement, cost=receipt.amount).to_record()
        self.receipts.append({"route": route, **asdict(receipt)})
        self.current_cost = None if self.current_cost is None or receipt.amount is None else self.current_cost + receipt.amount
        self.spent_cost = None if self.spent_cost is None or receipt.amount is None else self.spent_cost + receipt.amount
        if not measurement.ok:
            raise StageMeasurementError("predictor_run_failed")
        return box["value"]

    def after(self):
        block = self._timing_block()
        self.measurement_pending = False
        if block:
            return block
        if self.spent_cost is None:
            return "unknown_observed_cost"
        if self.spent_cost > self.control.budget.max_cost:
            return "cost_budget_exhausted"
        return None

    def to_record(self):
        return {"policy": deepcopy(self.policy_record), "measurements": list(self.measurements),
            "cost_observations": list(self.receipts), "escalation_decisions": list(self.decisions),
            "timing": self.timing.to_record() if self.timing is not None and not self.measurement_pending else None,
            "elapsed_current_ms": self.elapsed_current_ms if self.timing is not None and not self.measurement_pending else None, "cost_current": self.current_cost,
            "spent_cost_total": self.spent_cost, "attempts_total": self.attempts,
            "escalations_total": self.escalations}
