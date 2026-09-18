"""Opt-in active mode: execute a route, inside declared limits, with a trail.

Nothing runs without a policy, cumulative budgets, a sandbox of pre-declared
routes and an explicit kill switch. A supervised risk class additionally needs a
single-use human authorization, an idempotency key is required for every
execution, and the escalation policy decides after each attempt whether to
accept, escalate, abstain or stop hard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .capture import capture_run
from .contracts import CandidateRoute, Task
from .escalation import Budget, EscalationPolicy, EscalationState
from .measurement import Environment
from .observations import record_observation
from .registry import RouteRegistry
from .router import ShadowRouter
from .verification import VerifierRegistry

__all__ = [
    "ActivePolicy",
    "ActiveRouter",
    "Authorization",
    "ExecutionResult",
    "KillSwitch",
    "Sandbox",
]


def _is_trimmed_nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


@dataclass(frozen=True)
class ActivePolicy:
    """What may run without a human, and inside which budget."""

    budget: Budget
    baseline_route_id: str
    auto_risk_classes: tuple[str, ...] = ("low",)

    def __post_init__(self) -> None:
        if not isinstance(self.budget, Budget):
            raise ValueError("budget must be a Budget instance.")
        if not _is_trimmed_nonempty(self.baseline_route_id):
            raise ValueError("baseline_route_id must be a nonempty, trimmed string.")
        if not isinstance(self.auto_risk_classes, tuple):
            raise ValueError(
                "auto_risk_classes must be a tuple; an empty tuple supervises every class."
            )
        for risk_class in self.auto_risk_classes:
            if not _is_trimmed_nonempty(risk_class):
                raise ValueError("auto_risk_classes entries must be nonempty strings.")


@dataclass(frozen=True)
class Authorization:
    """One human approval, scoped to one task and one route, single use."""

    authorization_id: str
    task_id: str
    route_id: str
    approved_by: str
    detail: str = ""

    def __post_init__(self) -> None:
        for name in ("authorization_id", "task_id", "route_id", "approved_by"):
            if not _is_trimmed_nonempty(getattr(self, name)):
                raise ValueError(f"{name} must be a nonempty, trimmed string.")
        if self.detail and self.detail != self.detail.strip():
            raise ValueError("detail must be empty or a trimmed string.")


class KillSwitch:
    """Global stop that no route, budget or policy can override."""

    def __init__(self, *, engaged: bool = False, reason: str = "") -> None:
        self._reason = ""
        if engaged:
            self.engage(reason or "engaged at construction")

    @property
    def engaged(self) -> bool:
        return bool(self._reason)

    @property
    def reason(self) -> str:
        return self._reason

    def engage(self, reason: str) -> None:
        if not _is_trimmed_nonempty(reason):
            raise ValueError("engaging the kill switch requires a reason.")
        self._reason = reason

    def release(self, reason: str) -> None:
        if not _is_trimmed_nonempty(reason):
            raise ValueError("releasing the kill switch requires a reason.")
        if not self.engaged:
            raise ValueError("the kill switch is not engaged.")
        self._reason = ""


@dataclass(frozen=True)
class Sandbox:
    """The only callables active mode is allowed to execute.

    The mapping is copied at construction, and a route that is not declared here
    cannot be executed, whatever the registry proposes.
    """

    routes: Mapping[str, Callable[[], Any]]

    def __post_init__(self) -> None:
        if not isinstance(self.routes, Mapping) or not self.routes:
            raise ValueError("a sandbox needs at least one declared route.")
        for route_id, run in self.routes.items():
            if not _is_trimmed_nonempty(route_id):
                raise ValueError("sandbox route ids must be nonempty, trimmed strings.")
            if not callable(run):
                raise TypeError(f"sandbox route {route_id!r} must be callable.")
        object.__setattr__(self, "routes", dict(self.routes))


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    reason_code: str
    route_id: str | None
    attempts: int
    escalations: int
    spent_cost: float
    authorization_id: str | None
    idempotency_key: str
    detail: str
    observation: dict[str, Any] | None
    measurements: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_audit_record(self) -> dict[str, Any]:
        """Audit trail linking the authorization, the attempts and the record."""
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "route_id": self.route_id,
            "attempts": self.attempts,
            "escalations": self.escalations,
            "spent_cost": self.spent_cost,
            "authorization_id": self.authorization_id,
            "idempotency_key": self.idempotency_key,
            "routes": [measurement["route_id"] for measurement in self.measurements],
            "detail": self.detail,
            "observation": self.observation,
        }


class ActiveRouter:
    """Execute sandboxed routes, one bounded attempt at a time."""

    def __init__(
        self,
        *,
        policy: ActivePolicy,
        sandbox: Sandbox,
        kill_switch: KillSwitch,
        registry: RouteRegistry,
        verifiers: VerifierRegistry,
        environment: Environment,
        clock: Callable[[], float],
        cost_unit: str,
        min_confidence: float = 0.9,
        now: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(policy, ActivePolicy):
            raise ValueError("policy must be an ActivePolicy instance.")
        if not isinstance(kill_switch, KillSwitch):
            raise ValueError("kill_switch must be a KillSwitch instance.")
        if not isinstance(sandbox, Sandbox):
            raise ValueError("sandbox must be a Sandbox instance.")
        if not isinstance(registry, RouteRegistry):
            raise ValueError("active mode requires a RouteRegistry.")
        if not isinstance(verifiers, VerifierRegistry):
            raise ValueError("active mode requires a VerifierRegistry.")
        if not isinstance(environment, Environment):
            raise ValueError("environment must be an Environment instance.")
        if not callable(clock):
            raise TypeError("clock must be callable.")
        if not _is_trimmed_nonempty(cost_unit):
            raise ValueError("cost_unit must be a nonempty, trimmed string.")

        self._policy = policy
        self._sandbox = sandbox
        self._kill_switch = kill_switch
        self._registry = registry
        self._verifiers = verifiers
        self._environment = environment
        self._clock = clock
        self._cost_unit = cost_unit
        self._min_confidence = min_confidence
        self._now = now
        self._used_authorizations: set[str] = set()
        self._used_keys: set[str] = set()
        self._cancel_reason: str | None = None

    @property
    def kill_switch(self) -> KillSwitch:
        return self._kill_switch

    @property
    def sandbox(self) -> Sandbox:
        return self._sandbox

    @property
    def cancelled(self) -> bool:
        return self._cancel_reason is not None

    def cancel(self, reason: str) -> None:
        if not _is_trimmed_nonempty(reason):
            raise ValueError("cancelling requires a reason.")
        self._cancel_reason = reason

    def execute(
        self,
        task: Task,
        *,
        idempotency_key: str,
        authorization: Authorization | None = None,
    ) -> ExecutionResult:
        if not _is_trimmed_nonempty(idempotency_key):
            raise ValueError("idempotency_key must be a nonempty, trimmed string.")
        if self._kill_switch.engaged:
            return self._stop("refused", "kill_switch_engaged", None, task, idempotency_key)
        if self.cancelled:
            return self._stop("refused", "cancelled", None, task, idempotency_key)
        if idempotency_key in self._used_keys:
            return self._stop("refused", "idempotency_key_reused", None, task, idempotency_key)

        supervised = task.risk_class not in self._policy.auto_risk_classes
        if supervised:
            if authorization is None:
                return self._stop(
                    "refused", "approval_required", None, task, idempotency_key
                )
            if authorization.authorization_id in self._used_authorizations:
                return self._stop(
                    "refused", "authorization_consumed", authorization, task, idempotency_key
                )
            if authorization.task_id != task.task_id:
                return self._stop(
                    "refused", "authorization_mismatch", authorization, task, idempotency_key
                )

        candidates = self._registry.candidates_for(task)
        if not candidates:
            return self._stop(
                "abstained", "no_eligible_route", authorization, task, idempotency_key
            )
        if self._policy.baseline_route_id not in {
            candidate.route_id for candidate in candidates
        }:
            return self._stop(
                "refused", "baseline_not_eligible", authorization, task, idempotency_key
            )
        decision = ShadowRouter(
            min_confidence=self._min_confidence, registry=self._registry
        ).propose(task, candidates)
        if decision.abstained or decision.selected_route_id is None:
            return self._stop(
                "abstained", "router_abstained", authorization, task, idempotency_key
            )

        self._used_keys.add(idempotency_key)
        if supervised and authorization is not None:
            self._used_authorizations.add(authorization.authorization_id)

        attempts = 0
        escalations = 0
        spent_cost = 0.0
        spent_latency_ms = 0.0
        tried: list[str] = []
        measurements: list[dict[str, Any]] = []
        evidence_by_route: dict[str, Any] = {}
        first_route = decision.selected_route_id
        current = first_route
        escalation_policy = EscalationPolicy(self._policy.budget)

        while True:
            if self._kill_switch.engaged:
                return self._finish(
                    "refused", "kill_switch_engaged", current, attempts, escalations,
                    spent_cost, authorization, task, idempotency_key, measurements,
                    evidence_by_route, first_route, candidates,
                )
            if self.cancelled:
                return self._finish(
                    "cancelled", "cancelled", current, attempts, escalations,
                    spent_cost, authorization, task, idempotency_key, measurements,
                    evidence_by_route, first_route, candidates,
                )
            if supervised and authorization is not None and current != authorization.route_id:
                return self._finish(
                    "refused", "authorization_route_mismatch", current, attempts,
                    escalations, spent_cost, authorization, task, idempotency_key,
                    measurements, evidence_by_route, first_route, candidates,
                )
            if current not in self._sandbox.routes:
                return self._finish(
                    "refused", "route_not_in_sandbox", current, attempts, escalations,
                    spent_cost, authorization, task, idempotency_key, measurements,
                    evidence_by_route, first_route, candidates,
                )

            verifier_id, verifier_version = self._registry.verifier_for(current)
            captured = capture_run(
                task_id=task.task_id,
                route_id=current,
                run=self._sandbox.routes[current],
                verifier_id=verifier_id,
                verifier_version=verifier_version,
                registry=self._verifiers,
                cost_unit=self._cost_unit,
                environment=self._environment,
                clock=self._clock,
                now=self._now,
            )
            measurements.append(captured.measurement)
            evidence_by_route[current] = captured.evidence
            route = self._registry.route(current)
            spent_cost += route.estimated_cost or 0.0
            spent_latency_ms += captured.measurement["latency_ms"]
            attempts += 1
            tried.append(current)

            following = self._next_candidate(candidates, tried)
            chosen = escalation_policy.decide(
                run_ok=captured.measurement["outcome"]["ok"],
                verdict=None if captured.verification is None else captured.verification.verdict,
                attempts=attempts,
                escalations=escalations,
                spent_cost=spent_cost,
                spent_latency_ms=spent_latency_ms,
                retry_safe=False,
                next_route_id=None if following is None else following.route_id,
                next_estimated_cost=None if following is None else following.estimated_cost,
                next_estimated_latency_ms=None if following is None else following.estimated_latency_ms,
            )
            if chosen.state is EscalationState.ACCEPT:
                return self._finish(
                    "executed", chosen.reason_code, current, attempts, escalations,
                    spent_cost, authorization, task, idempotency_key, measurements,
                    evidence_by_route, first_route, candidates,
                )
            if chosen.state is EscalationState.ESCALATE and chosen.next_route_id is not None:
                escalations += 1
                current = chosen.next_route_id
                continue
            status = "abstained" if chosen.state is EscalationState.ABSTAIN else "failed"
            return self._finish(
                status, chosen.reason_code, current, attempts, escalations, spent_cost,
                authorization, task, idempotency_key, measurements, evidence_by_route,
                first_route, candidates,
            )

    @staticmethod
    def _next_candidate(
        candidates: list[CandidateRoute], tried: list[str]
    ) -> CandidateRoute | None:
        remaining = [
            candidate for candidate in candidates if candidate.route_id not in tried
        ]
        remaining.sort(
            key=lambda candidate: (
                candidate.estimated_cost is None,
                candidate.estimated_cost if candidate.estimated_cost is not None else 0.0,
                candidate.route_id,
            )
        )
        return remaining[0] if remaining else None

    def _finish(
        self,
        status: str,
        reason_code: str,
        route_id: str | None,
        attempts: int,
        escalations: int,
        spent_cost: float,
        authorization: Authorization | None,
        task: Task,
        idempotency_key: str,
        measurements: list[dict[str, Any]],
        evidence_by_route: Mapping[str, Any],
        first_route: str,
        candidates: list[CandidateRoute],
    ) -> ExecutionResult:
        observation = None
        if measurements:
            observation = record_observation(
                task,
                candidates,
                baseline_route_id=self._policy.baseline_route_id,
                cost_unit=self._cost_unit,
                data_origin="synthetic",
                min_confidence=self._min_confidence,
                baseline_evidence=evidence_by_route.get(self._policy.baseline_route_id),
                proposal_evidence=evidence_by_route.get(first_route),
            )
        return ExecutionResult(
            status=status,
            reason_code=reason_code,
            route_id=route_id,
            attempts=attempts,
            escalations=escalations,
            spent_cost=spent_cost,
            authorization_id=None if authorization is None else authorization.authorization_id,
            idempotency_key=idempotency_key,
            detail=f"{status}: {reason_code}",
            observation=observation,
            measurements=tuple(measurements),
        )

    def _stop(
        self,
        status: str,
        reason_code: str,
        authorization: Authorization | None,
        task: Task,
        idempotency_key: str,
    ) -> ExecutionResult:
        return ExecutionResult(
            status=status,
            reason_code=reason_code,
            route_id=None,
            attempts=0,
            escalations=0,
            spent_cost=0.0,
            authorization_id=None if authorization is None else authorization.authorization_id,
            idempotency_key=idempotency_key,
            detail=f"{status}: {reason_code}",
            observation=None,
            measurements=(),
        )
