"""Readiness gate for comparing composed agent routes on identical tasks.

This is an experiment plan, not a benchmark result. Unknown models have no
placeholder score. Caller-supplied outcomes are advisory and can never by
themselves authorize a saving claim. Only the canonical benchmark measurement
and verifier records can later support such a claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .router import is_nonnegative_number

__all__ = [
    "ArmAvailability",
    "ExperimentArm",
    "ExperimentPlan",
    "PairedOutcome",
    "ReadinessReport",
    "assess_experiment",
]


class ArmAvailability(str, Enum):
    READY = "ready"
    UNAVAILABLE = "unavailable"
    NEEDS_AUTHORIZATION = "needs_authorization"


@dataclass(frozen=True)
class ExperimentArm:
    arm_id: str
    stages: tuple[str, ...]
    availability: ArmAvailability
    backend_id: str | None = None
    backend_version: str | None = None

    def __post_init__(self) -> None:
        if not self.arm_id or self.arm_id != self.arm_id.strip():
            raise ValueError("arm_id must be nonempty and trimmed.")
        if not self.stages or any(not stage or stage != stage.strip() for stage in self.stages):
            raise ValueError("stages must be nonempty and trimmed.")
        if not isinstance(self.availability, ArmAvailability):
            raise TypeError("availability must be an ArmAvailability.")
        if self.availability is ArmAvailability.READY and (
            not self.backend_id or not self.backend_version
        ):
            raise ValueError("a ready arm needs a backend id and version.")


@dataclass(frozen=True)
class ExperimentPlan:
    corpus_id: str
    task_ids: tuple[str, ...]
    baseline_arm_id: str
    arms: tuple[ExperimentArm, ...]

    def __post_init__(self) -> None:
        if not self.corpus_id or not self.corpus_id.strip():
            raise ValueError("corpus_id must be nonempty.")
        if not self.task_ids or len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("task_ids must be nonempty and unique.")
        if len(self.arms) < 2 or len({arm.arm_id for arm in self.arms}) != len(self.arms):
            raise ValueError("at least two unique arms are required.")
        if self.baseline_arm_id not in {arm.arm_id for arm in self.arms}:
            raise ValueError("baseline arm must be declared.")


@dataclass(frozen=True)
class PairedOutcome:
    task_id: str
    arm_id: str
    verified: bool
    elapsed_ms: float
    total_cost: float | None
    measured: bool
    origin: str
    verifier_id: str | None = None
    verifier_version: str | None = None

    def __post_init__(self) -> None:
        if not is_nonnegative_number(self.elapsed_ms):
            raise ValueError("elapsed_ms must be finite and nonnegative.")
        if self.total_cost is not None and not is_nonnegative_number(self.total_cost):
            raise ValueError("total_cost must be finite and nonnegative or null.")


@dataclass(frozen=True)
class ReadinessReport:
    comparable: bool
    claim_allowed: bool
    reason_codes: tuple[str, ...]
    measured_pairs: int
    required_pairs: int
    estimated_cost_improvement: bool | None = None


def assess_experiment(
    plan: ExperimentPlan,
    outcomes: Sequence[PairedOutcome] = (),
) -> ReadinessReport:
    arms = {arm.arm_id: arm for arm in plan.arms}
    expected = {(task_id, arm_id) for task_id in plan.task_ids for arm_id in arms}
    actual = [(outcome.task_id, outcome.arm_id) for outcome in outcomes]
    reasons: list[str] = []

    if any(arm.availability is not ArmAvailability.READY for arm in plan.arms):
        reasons.append("arm_unavailable")
    if len(actual) != len(set(actual)):
        reasons.append("duplicate_outcome")
    if set(actual) - expected:
        reasons.append("unexpected_outcome")
    if expected - set(actual):
        reasons.append("missing_paired_outcomes")
    if any(not outcome.measured or outcome.origin != "labelled_outcomes" for outcome in outcomes):
        reasons.append("unmeasured_or_fixture")
    if any(outcome.total_cost is None for outcome in outcomes):
        reasons.append("incomplete_cost")
    if any(not outcome.verified for outcome in outcomes):
        reasons.append("verification_failure")
    if any(
        not outcome.verifier_id or not outcome.verifier_version for outcome in outcomes
    ):
        reasons.append("unattributed_verification")
    if any(
        len({
            (outcome.verifier_id, outcome.verifier_version)
            for outcome in outcomes
            if outcome.task_id == task_id
        }) > 1
        for task_id in plan.task_ids
    ):
        reasons.append("verifier_mismatch")
    if any(
        (outcome.task_id, outcome.arm_id) in expected
        and arms[outcome.arm_id].availability is not ArmAvailability.READY
        for outcome in outcomes
    ):
        reasons.append("unavailable_arm_has_outcome")

    comparable = not reasons and bool(outcomes)
    estimated_cost_improvement: bool | None = None
    if comparable:
        by_key = {(item.task_id, item.arm_id): item for item in outcomes}
        baseline = plan.baseline_arm_id
        baseline_cost = sum(by_key[(task_id, baseline)].total_cost for task_id in plan.task_ids)
        candidate_improved = False
        for arm_id in arms:
            if arm_id == plan.baseline_arm_id:
                continue
            candidate_cost = sum(by_key[(task_id, arm_id)].total_cost for task_id in plan.task_ids)
            candidate_improved = candidate_improved or candidate_cost < baseline_cost
        estimated_cost_improvement = candidate_improved
        if not candidate_improved:
            reasons.append("no_total_cost_improvement")

    # PairedOutcome is a caller assertion. It does not carry a measurement/2
    # record or a verifier-bound input hash. Even a fully populated comparison
    # cannot turn these assertions into measured savings.
    reasons.append("caller_reported_only")

    return ReadinessReport(
        comparable=comparable,
        claim_allowed=False,
        reason_codes=tuple(dict.fromkeys(reasons)),
        measured_pairs=len(set(actual) & expected),
        required_pairs=len(expected),
        estimated_cost_improvement=estimated_cost_improvement,
    )
