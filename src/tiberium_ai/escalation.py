"""Deterministic escalation with budgets and hard stops.

The policy never executes anything. Given the outcome of one attempt and the
remaining budget, it decides whether to accept the result, retry, escalate to
another route, abstain, or stop hard. Every decision names the rule that fired.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .router import is_nonnegative_number

__all__ = ["Budget", "EscalationDecision", "EscalationPolicy", "EscalationState"]


class EscalationState(str, Enum):
    ACCEPT = "ACCEPT"
    RETRY = "RETRY"
    ESCALATE = "ESCALATE"
    ABSTAIN = "ABSTAIN"
    FAIL_HARD = "FAIL_HARD"


def _is_count(value: object, minimum: int) -> bool:
    return type(value) is int and value >= minimum


@dataclass(frozen=True)
class Budget:
    """Cumulative limits for one task, in the shared cost unit."""

    max_cost: float
    max_escalations: int
    max_attempts: int
    max_latency_ms: float | None = None

    def __post_init__(self) -> None:
        if not is_nonnegative_number(self.max_cost):
            raise ValueError("max_cost must be a finite nonnegative number.")
        if not _is_count(self.max_escalations, 0):
            raise ValueError("max_escalations must be a nonnegative integer.")
        if not _is_count(self.max_attempts, 1):
            raise ValueError("max_attempts must be an integer of at least 1.")
        if self.max_latency_ms is not None and not is_nonnegative_number(
            self.max_latency_ms
        ):
            raise ValueError("max_latency_ms must be null or a finite nonnegative number.")


@dataclass(frozen=True)
class EscalationDecision:
    state: EscalationState
    reason_code: str
    next_route_id: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.state, EscalationState):
            raise ValueError("state must be an EscalationState.")
        for name, value in (("reason_code", self.reason_code), ("detail", self.detail)):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be a nonempty, trimmed string.")
        if self.next_route_id is not None and (
            not isinstance(self.next_route_id, str)
            or not self.next_route_id
            or self.next_route_id != self.next_route_id.strip()
        ):
            raise ValueError("next_route_id must be null or a nonempty, trimmed string.")
        if self.state is EscalationState.ESCALATE and self.next_route_id is None:
            raise ValueError("An escalation requires next_route_id.")
        if self.state in (
            EscalationState.ACCEPT,
            EscalationState.ABSTAIN,
            EscalationState.FAIL_HARD,
        ) and self.next_route_id is not None:
            raise ValueError(f"{self.state.value} must not carry next_route_id.")


class EscalationPolicy:
    """Decide what to do after one attempt, inside a fixed budget."""

    def __init__(self, budget: Budget) -> None:
        if not isinstance(budget, Budget):
            raise TypeError("budget must be a Budget instance.")
        self._budget = budget

    @property
    def budget(self) -> Budget:
        return self._budget

    def decide(
        self,
        *,
        run_ok: bool,
        verdict: bool | None,
        attempts: int,
        escalations: int,
        spent_cost: float,
        spent_latency_ms: float,
        retry_safe: bool = False,
        next_route_id: str | None = None,
        next_estimated_cost: float | None = None,
        next_estimated_latency_ms: float | None = None,
        task_specified: bool = True,
    ) -> EscalationDecision:
        _validate_attempt(
            run_ok=run_ok,
            verdict=verdict,
            attempts=attempts,
            escalations=escalations,
            spent_cost=spent_cost,
            spent_latency_ms=spent_latency_ms,
            retry_safe=retry_safe,
            next_route_id=next_route_id,
            next_estimated_cost=next_estimated_cost,
            next_estimated_latency_ms=next_estimated_latency_ms,
            task_specified=task_specified,
        )

        if not task_specified:
            return self._fail(
                "ill_specified_task", "The task is not specified well enough to decide."
            )
        if run_ok and verdict is True:
            return EscalationDecision(
                EscalationState.ACCEPT,
                "verified_accept",
                detail="The attempt produced a verified result; accept it.",
            )
        if attempts >= self._budget.max_attempts:
            return self._fail(
                "attempt_budget_exhausted",
                "The attempt budget of "
                f"{self._budget.max_attempts} is exhausted; stop instead of looping.",
            )

        block = self._escalation_block(
            escalations=escalations,
            next_route_id=next_route_id,
            next_estimated_cost=next_estimated_cost,
            next_estimated_latency_ms=next_estimated_latency_ms,
            spent_cost=spent_cost,
            spent_latency_ms=spent_latency_ms,
        )

        if verdict is False:
            if block is None:
                return EscalationDecision(
                    EscalationState.ESCALATE,
                    "rejected_escalate",
                    next_route_id=next_route_id,
                    detail=f"The result was rejected; escalate to {next_route_id}.",
                )
            code, detail = block
            return self._fail(f"rejected_{code}", detail)

        if block is None:
            return EscalationDecision(
                EscalationState.ESCALATE,
                "route_failed_escalate" if not run_ok else "abstained_escalate",
                next_route_id=next_route_id,
                detail=(
                    f"The route failed; escalate to {next_route_id}."
                    if not run_ok
                    else f"No verdict was produced; escalate to {next_route_id}."
                ),
            )
        if retry_safe:
            return EscalationDecision(
                EscalationState.RETRY,
                "route_failed_retry" if not run_ok else "abstained_retry",
                detail=(
                    "The route failed; a caller-authorised retry is allowed."
                    if not run_ok
                    else "No verdict was produced; a caller-authorised retry is allowed."
                ),
            )
        return EscalationDecision(
            EscalationState.ABSTAIN,
            "route_failed_abstain" if not run_ok else "abstained_no_verdict",
            detail=(
                "The route failed and no escalation or retry is available."
                if not run_ok
                else "No verdict was produced and no escalation or retry is available."
            ),
        )

    def _escalation_block(
        self,
        *,
        escalations: int,
        next_route_id: str | None,
        next_estimated_cost: float | None,
        next_estimated_latency_ms: float | None,
        spent_cost: float,
        spent_latency_ms: float,
    ) -> tuple[str, str] | None:
        if next_route_id is None:
            return ("no_alternative", "No alternative route is available.")
        if escalations >= self._budget.max_escalations:
            return (
                "escalation_budget_exhausted",
                "The escalation budget of "
                f"{self._budget.max_escalations} is exhausted.",
            )
        if next_estimated_cost is None:
            return (
                "unknown_cost",
                "The next route has no known estimated cost.",
            )
        if spent_cost + next_estimated_cost > self._budget.max_cost:
            return (
                "cost_budget_exhausted",
                f"The next route would exceed the cost budget of {self._budget.max_cost:g}.",
            )
        if self._budget.max_latency_ms is not None:
            if next_estimated_latency_ms is None:
                return (
                    "unknown_latency",
                    "The next route has no known estimated latency.",
                )
            if spent_latency_ms + next_estimated_latency_ms > self._budget.max_latency_ms:
                return (
                    "latency_budget_exhausted",
                    "The next route would exceed the latency budget of "
                    f"{self._budget.max_latency_ms:g} ms.",
                )
        return None

    def _fail(self, reason_code: str, detail: str) -> EscalationDecision:
        return EscalationDecision(EscalationState.FAIL_HARD, reason_code, detail=detail)


def _validate_attempt(
    *,
    run_ok: object,
    verdict: object,
    attempts: object,
    escalations: object,
    spent_cost: object,
    spent_latency_ms: object,
    retry_safe: object,
    next_route_id: object,
    next_estimated_cost: object,
    next_estimated_latency_ms: object,
    task_specified: object,
) -> None:
    if not isinstance(run_ok, bool):
        raise ValueError("run_ok must be a boolean.")
    if verdict is not None and not isinstance(verdict, bool):
        raise ValueError("verdict must be a boolean or null.")
    if not run_ok and verdict is not None:
        raise ValueError("a failed run cannot carry a verdict.")
    if not _is_count(attempts, 1):
        raise ValueError("attempts must be an integer of at least 1.")
    if not _is_count(escalations, 0):
        raise ValueError("escalations must be a nonnegative integer.")
    if escalations >= attempts:
        raise ValueError("escalations cannot exceed the number of completed attempts minus one.")
    if not is_nonnegative_number(spent_cost):
        raise ValueError("spent_cost must be a finite nonnegative number.")
    if not is_nonnegative_number(spent_latency_ms):
        raise ValueError("spent_latency_ms must be a finite nonnegative number.")
    if not isinstance(retry_safe, bool):
        raise ValueError("retry_safe must be a boolean.")
    if not isinstance(task_specified, bool):
        raise ValueError("task_specified must be a boolean.")
    if next_route_id is not None and (
        not isinstance(next_route_id, str)
        or not next_route_id
        or next_route_id != next_route_id.strip()
    ):
        raise ValueError("next_route_id must be null or a nonempty, trimmed string.")
    for name, value in (
        ("next_estimated_cost", next_estimated_cost),
        ("next_estimated_latency_ms", next_estimated_latency_ms),
    ):
        if value is not None and not is_nonnegative_number(value):
            raise ValueError(f"{name} must be null or a finite nonnegative number.")
