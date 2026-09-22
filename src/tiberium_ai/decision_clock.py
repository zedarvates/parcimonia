"""The decision clock: a late answer is not a slow answer, it is no answer.

A route that returns after its deadline has produced nothing the consumer can
use, because the consumer already acted. A route that answers from a snapshot
the consumer has since replaced is not late: it describes a state that no
longer exists. Public real-time evaluations of reasoning agents report those
two failures next to decision quality, so they carry their own reason codes
here instead of being folded into a single latency figure.

The clock is never read in this module. Elapsed time and state age arrive as
inputs, so a verdict is reproducible and testable, and reading a wall clock
stays the caller's decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .router import is_nonnegative_number

__all__ = [
    "DecisionBudget",
    "DecisionTiming",
    "TimingStatus",
    "TimingVerdict",
    "assess_decision_timing",
]

#: Stable reason codes, so a report groups by cause instead of parsing prose.
WITHIN_BUDGET = "within_budget"
ELAPSED_EXCEEDS_BUDGET = "elapsed_exceeds_budget"
STATE_AGE_EXCEEDS_BOUND = "state_age_exceeds_bound"
STATE_AGE_UNKNOWN = "state_age_unknown"


class TimingStatus(str, Enum):
    """Where one decision landed against its budget."""

    WITHIN_BUDGET = "within_budget"
    DEADLINE_MISSED = "deadline_missed"
    STATE_STALE = "state_stale"


@dataclass(frozen=True)
class DecisionBudget:
    """Hard bounds on one decision: when it must land and how old the state may be.

    ``fallback_route_id`` names the mechanism the consumer must use when this
    budget cannot be met. It is declared up front on purpose: a fallback chosen
    after the deadline has already been missed is chosen by the thing that
    failed to meet it.
    """

    budget_ms: float
    max_state_age_ms: float | None = None
    fallback_route_id: str | None = None

    def __post_init__(self) -> None:
        if not is_nonnegative_number(self.budget_ms):
            raise ValueError("budget_ms must be a finite nonnegative number.")
        if self.max_state_age_ms is not None and not is_nonnegative_number(
            self.max_state_age_ms
        ):
            raise ValueError(
                "max_state_age_ms must be null or a finite nonnegative number."
            )
        if self.fallback_route_id is not None and (
            not isinstance(self.fallback_route_id, str)
            or not self.fallback_route_id
            or self.fallback_route_id != self.fallback_route_id.strip()
        ):
            raise ValueError(
                "fallback_route_id must be null or a nonempty, trimmed string."
            )


@dataclass(frozen=True)
class DecisionTiming:
    """Measured time for one decision. `None` means the age was not observed."""

    elapsed_ms: float
    state_age_ms: float | None = None

    def __post_init__(self) -> None:
        if not is_nonnegative_number(self.elapsed_ms):
            raise ValueError("elapsed_ms must be a finite nonnegative number.")
        if self.state_age_ms is not None and not is_nonnegative_number(
            self.state_age_ms
        ):
            raise ValueError(
                "state_age_ms must be null or a finite nonnegative number."
            )


@dataclass(frozen=True)
class TimingVerdict:
    """Outcome of one decision against its budget, with the rule that fired.

    ``remaining_ms`` is signed: it goes negative on a miss, so a report cannot
    mistake a small overrun for a comfortable margin.
    """

    status: TimingStatus
    reason_code: str
    elapsed_ms: float
    remaining_ms: float
    state_age_ms: float | None
    fallback_route_id: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, TimingStatus):
            raise TypeError("status must be a TimingStatus enum.")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise ValueError("reason_code must be a nonempty string.")
        if self.status is TimingStatus.WITHIN_BUDGET and self.reason_code != WITHIN_BUDGET:
            raise ValueError("a within-budget verdict must carry the within-budget code.")

    @property
    def usable(self) -> bool:
        """Return whether the consumer may use this decision as it stands."""
        return self.status is TimingStatus.WITHIN_BUDGET

    @property
    def fallback_required(self) -> bool:
        """Return whether the pre-committed fallback must be taken instead."""
        return not self.usable

    def to_record(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "elapsed_ms": self.elapsed_ms,
            "remaining_ms": self.remaining_ms,
            "state_age_ms": self.state_age_ms,
            "fallback_route_id": self.fallback_route_id,
        }


def assess_decision_timing(
    budget: DecisionBudget, timing: DecisionTiming
) -> TimingVerdict:
    """Judge one decision against its budget, staleness first.

    Staleness is checked before the deadline because a fast answer about a
    replaced state is wrong, not quick. A declared staleness bound with an
    unobserved age fails closed, exactly as an unknown cost is never treated as
    zero.
    """
    if not isinstance(budget, DecisionBudget):
        raise TypeError("budget must be a DecisionBudget instance.")
    if not isinstance(timing, DecisionTiming):
        raise TypeError("timing must be a DecisionTiming instance.")

    remaining_ms = budget.budget_ms - timing.elapsed_ms

    def verdict(status: TimingStatus, reason_code: str) -> TimingVerdict:
        return TimingVerdict(
            status=status,
            reason_code=reason_code,
            elapsed_ms=timing.elapsed_ms,
            remaining_ms=remaining_ms,
            state_age_ms=timing.state_age_ms,
            fallback_route_id=budget.fallback_route_id,
        )

    if budget.max_state_age_ms is not None:
        if timing.state_age_ms is None:
            return verdict(TimingStatus.STATE_STALE, STATE_AGE_UNKNOWN)
        if timing.state_age_ms > budget.max_state_age_ms:
            return verdict(TimingStatus.STATE_STALE, STATE_AGE_EXCEEDS_BOUND)
    if timing.elapsed_ms > budget.budget_ms:
        return verdict(TimingStatus.DEADLINE_MISSED, ELAPSED_EXCEEDS_BUDGET)
    return verdict(TimingStatus.WITHIN_BUDGET, WITHIN_BUDGET)
