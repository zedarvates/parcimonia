"""Opt-in feasibility through a verified reduction and a 2-SAT solver.

The existing exhaustive diagnostic stays unchanged. This separate report
answers only two satisfiability questions and does not infer completeness.
"""

from __future__ import annotations

from typing import Any

from .reductions import reduce_to_2cnf
from .two_sat import solve_2cnf, verify_2sat_result
from .verification import VerifierRegistry, hash_input

__all__ = ["diagnose_via_2sat", "register_reduced_feasibility_verifier"]


def _solve(reduction: dict[str, Any]) -> dict[str, Any]:
    target = reduction["target"]
    solution = solve_2cnf(target)
    if not verify_2sat_result(target, solution):
        raise RuntimeError("2-SAT solver produced an invalid certificate.")
    return {"reduction": reduction, "solution": solution}


def diagnose_via_2sat(request: dict[str, Any]) -> dict[str, Any]:
    """Separate contradictory requirements from an incompatible current state.

    Sources are caller declarations. A satisfying assignment proves only that
    the declared Boolean model is consistent, not world feasibility or quality.
    """
    reduced = reduce_to_2cnf(request)
    report: dict[str, Any] = {
        "schema": "parcimonia.reduced-feasibility-report/v1",
        "task_id": request["task_id"],
        "scope_id": request["scope_id"],
        "revision": request["revision"],
        "input_hash": hash_input(request),
        "engine": {"id": "reduced-boolean-feasibility", "version": "1"},
        "mode": "shadow",
        "feasibility": "indeterminate",
        "requirements": {"reduction": reduced, "solution": None},
        "current_state": None,
        "next_checks": [],
        "limits": {
            "sources": "caller_supplied_unverified",
            "world_feasibility": "not_established",
            "quality": "not_assessed",
            "completeness": "not_assessed",
            "savings": "not_measured",
        },
    }
    if reduced["status"] != "reduced":
        report["next_checks"] = ["use_a_verifier_for_unsupported_constraints"]
        return report
    requirements = _solve(reduced)
    report["requirements"] = requirements
    if requirements["solution"]["status"] == "unsatisfiable":
        report["feasibility"] = "impossible_within_constraints"
        report["next_checks"] = ["review_the_declared_constraints"]
        return report
    current_state = _solve(reduce_to_2cnf(request, include_observations=True))
    report["current_state"] = current_state
    if current_state["solution"]["status"] == "unsatisfiable":
        report["feasibility"] = "blocked_current_state"
        report["next_checks"] = ["review_observations_and_constraints"]
    else:
        report["feasibility"] = "consistent_within_constraints"
        report["next_checks"] = ["verify_the_model_and_unobserved_conditions"]
    return report


def register_reduced_feasibility_verifier(registry: VerifierRegistry) -> None:
    """Register exact report replay; accepting a report is not project success."""
    def verify(value: Any) -> bool:
        if type(value) is not dict or set(value) != {"request", "report"}:
            return False
        try:
            return hash_input(value["report"]) == hash_input(
                diagnose_via_2sat(value["request"])
            )
        except (ValueError, TypeError, KeyError, RecursionError):
            return False

    registry.register("reduced-boolean-feasibility-report", "1", verify)
