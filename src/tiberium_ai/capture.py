"""Run one route, measure it, and verify its output.

The output stays in memory: it is reduced to a verdict and to the hash of its
canonical form, and it never enters a measurement or an observation record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .contracts import Evidence, Verification
from .measurement import Environment, run_baseline
from .verification import VerifierRegistry, attributed_evidence

__all__ = ["CapturedRun", "capture_run"]


@dataclass(frozen=True)
class CapturedRun:
    """One measured and verified execution of a caller-supplied callable."""

    measurement: dict[str, Any]
    verification: Verification | None
    evidence: Evidence | None
    output: Any = field(default=None, repr=False)


def capture_run(
    *,
    task_id: str,
    route_id: str,
    run: Callable[[], Any],
    verifier_id: str,
    verifier_version: str,
    registry: VerifierRegistry,
    cost_unit: str,
    environment: Environment,
    clock: Callable[[], float],
    now: Callable[[], str] | None = None,
    cost: float | None = None,
    resources: "ResourceVector | None" = None,
) -> CapturedRun:
    """Execute `run` once, measure it, then verify what it returned.

    A failing run is measured with its exception type and produces no evidence,
    because there is no output to verify. An unregistered verifier abstains and
    still produces evidence, so the abstention is recorded instead of hidden.
    """
    captured: dict[str, Any] = {}

    def capturing_run() -> Any:
        value = run()
        captured["value"] = value
        return value

    measured = run_baseline(
        task_id,
        route_id,
        capturing_run,
        cost_unit=cost_unit,
        environment=environment,
        clock=clock,
        now=now,
        cost=cost,
        resources=resources,
    )
    measurement = measured.to_record()
    if not measured.ok:
        return CapturedRun(measurement=measurement, verification=None, evidence=None)

    verification = registry.verify(verifier_id, verifier_version, captured["value"])
    evidence = attributed_evidence(
        verification,
        task_id=task_id,
        route_id=route_id,
        measured_latency_ms=measured.latency_ms,
        measured_cost=measured.cost,
    )
    return CapturedRun(
        measurement=measurement,
        verification=verification,
        evidence=evidence,
        output=captured["value"],
    )
