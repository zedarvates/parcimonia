"""Measured pipeline phases and conservative paired comparisons."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from time import perf_counter
from typing import Any, Callable, Mapping

from .core import fingerprint


@dataclass(frozen=True)
class PhaseResult:
    value: Any
    cost: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


def measure_pipeline(case_id: str, arm: str, input_value: Any,
                     phases: Mapping[str, Callable[[Any], PhaseResult]],
                     verifier: Callable[[Any], bool], *, currency: str = "USD",
                     clock: Callable[[], float] = perf_counter) -> dict[str, Any]:
    if not case_id or not arm or not phases:
        raise ValueError("case, arm and phases required")
    value, records, error = input_value, [], None
    start = clock()
    for name, operation in phases.items():
        before = clock()
        try:
            result = operation(value)
            if not isinstance(result, PhaseResult):
                raise TypeError("phase must return PhaseResult")
            if result.cost is not None and (isinstance(result.cost, bool) or
                    not math.isfinite(result.cost) or result.cost < 0):
                raise ValueError("invalid measured cost")
            for count in (result.input_tokens, result.output_tokens):
                if count is not None and (type(count) is not int or count < 0):
                    raise ValueError("invalid token count")
            value = result.value
            records.append({"phase": name, "latency_ms": (clock() - before) * 1000,
                            "cost": result.cost, "input_tokens": result.input_tokens,
                            "output_tokens": result.output_tokens})
        except Exception:
            error = "phase_failed:" + name
            records.append({"phase": name, "latency_ms": (clock() - before) * 1000,
                            "cost": None, "input_tokens": None, "output_tokens": None})
            break
    before_verify = clock()
    try:
        verified = error is None and verifier(value) is True
    except Exception:
        verified = False
    verification_ms = (clock() - before_verify) * 1000
    costs = [r["cost"] for r in records]
    return {"schema": "agent_pipeline/1", "case_id": case_id, "arm": arm,
            "input_hash": fingerprint(input_value), "origin": "measured",
            "currency": currency, "phases": records, "verified": verified,
            "verification_ms": verification_ms, "error": error,
            "latency_ms": (clock() - start) * 1000,
            "total_cost": sum(costs) if all(c is not None for c in costs) else None,
            "monetary_scope": "reported_phase_costs_excludes_unreported_verification_and_human_cost"}


def compare_pipelines(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    reasons = []
    if any(baseline.get(k) != candidate.get(k) for k in ("case_id", "input_hash", "currency")):
        reasons.append("unpaired_inputs")
    if not baseline.get("verified") or not candidate.get("verified"):
        reasons.append("unverified_outcome")
    if baseline.get("total_cost") is None or candidate.get("total_cost") is None:
        reasons.append("unknown_cost")
    # These local measurements inform a pilot. Only the existing canonical benchmark
    # chain can certify a project-wide saving; arbitrary dictionaries cannot open it.
    return {"comparable": not reasons, "reasons": reasons, "claim_allowed": False,
            "claim_reason": "pilot_only_use_canonical_benchmark",
            "reported_cost_delta": None if reasons else baseline["total_cost"] - candidate["total_cost"],
            "latency_delta_ms": None if reasons else baseline["latency_ms"] - candidate["latency_ms"]}
