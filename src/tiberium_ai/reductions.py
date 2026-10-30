"""A polynomial, assignment-preserving reduction of Boolean contracts to 2-CNF.

The source decision question is explicit: either the hard constraints alone,
or those constraints conjoined with all known observations. Unknown values are
never converted to false. Reduction does not solve either decision problem.
"""

from __future__ import annotations

from typing import Any

from .feasibility import MAX_VARIABLES, _validate
from .verification import VerifierRegistry, hash_input

REPORT_SCHEMA = "parcimonia.boolean-reduction/v1"
TARGET_SCHEMA = "parcimonia.2cnf/v1"
REDUCTION_ID = "boolean-contract-to-2cnf"
REDUCTION_VERSION = "1"
CONSTRAINTS_QUESTION = "constraints_satisfiable"
OBSERVATIONS_QUESTION = "constraints_and_known_observations_satisfiable"

__all__ = [
    "REPORT_SCHEMA", "TARGET_SCHEMA", "REDUCTION_ID", "REDUCTION_VERSION",
    "CONSTRAINTS_QUESTION", "OBSERVATIONS_QUESTION", "reduce_to_2cnf",
    "register_reduction_verifier",
]


def reduce_to_2cnf(
    request: dict[str, Any], *, include_observations: bool = False
) -> dict[str, Any]:
    """Translate a supported source request without enumerating assignments.

    Variables are numbered from one in lexical name order. A positive integer
    denotes the corresponding variable and a negative integer its negation.
    ``require(L)`` becomes ``[L]``; ``implies(A, B)`` becomes ``[-A, B]``.
    Each resulting clause retains its source reference and a zero-based index.

    The shared source validator accepts at most 128 variables and 256 source
    constraints. Its ``MAX_VARIABLES`` argument validates the old exhaustive
    solver's parameter only; this function never calls that solver. Unknown
    constraint kinds abstain for the whole translation instead of being dropped.
    """
    if type(include_observations) is not bool:
        raise ValueError("include_observations must be a boolean.")
    unsupported = _validate(request, MAX_VARIABLES)
    variables = sorted(request["variables"])
    observations = sorted(
        request.get("observations", []), key=lambda item: item["variable"]
    )
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "task_id": request["task_id"],
        "scope_id": request["scope_id"],
        "revision": request["revision"],
        "input_hash": hash_input(request),
        "mode": "shadow",
        "reduction": {
            "id": REDUCTION_ID,
            "version": REDUCTION_VERSION,
            "kind": "karp",
        },
        "source_question": (
            OBSERVATIONS_QUESTION if include_observations else CONSTRAINTS_QUESTION
        ),
        "status": "indeterminate" if unsupported else "reduced",
        "target": None,
        "target_hash": None,
        "clause_origins": [],
        "unknown_observations": [
            item["variable"] for item in observations if item["value"] is None
        ],
        "reason_codes": ["unsupported_constraint_kind"] if unsupported else [],
        "unsupported_constraint_ids": sorted(item["id"] for item in unsupported),
        "limits": {
            "max_variables": 128,
            "max_source_constraints": 256,
            "max_target_clauses": 384,
            "sources": "caller_supplied_unverified",
            "world_feasibility": "not_established",
            "criteria": "not_part_of_source_question",
            "costs": "not_measured",
        },
    }
    if unsupported:
        return report

    numbers = {name: index + 1 for index, name in enumerate(variables)}
    clauses: list[list[int]] = []
    origins: list[dict[str, Any]] = []

    def encode(literal: dict[str, Any]) -> int:
        number = numbers[literal["variable"]]
        return number if literal["value"] else -number

    for constraint in sorted(request["constraints"], key=lambda item: item["id"]):
        if constraint["kind"] == "require":
            clause = [encode(constraint)]
        else:
            clause = [-encode(constraint["if"]), encode(constraint["then"])]
        origins.append({
            "clause_index": len(clauses),
            "kind": "constraint",
            "id": constraint["id"],
            "source": constraint["source"],
        })
        clauses.append(clause)

    if include_observations:
        for observation in observations:
            if observation["value"] is None:
                continue
            origins.append({
                "clause_index": len(clauses),
                "kind": "observation",
                "variable": observation["variable"],
                "source": observation["source"],
            })
            clauses.append([encode(observation)])

    target = {"schema": TARGET_SCHEMA, "variables": variables, "clauses": clauses}
    report["target"] = target
    report["target_hash"] = hash_input(target)
    report["clause_origins"] = origins
    return report


def register_reduction_verifier(registry: VerifierRegistry) -> None:
    """Register exact replay of ``{request, report}``, not source truth.

    The recorded question determines whether known observations were included.
    Replaying a reduction establishes its computation and attribution, not
    satisfiability, authenticated sources, or correctness of the source model.
    """
    def verify(value: Any) -> bool:
        try:
            if type(value) is not dict or set(value) != {"request", "report"}:
                return False
            report = value["report"]
            if type(report) is not dict:
                return False
            question = report.get("source_question")
            if question == CONSTRAINTS_QUESTION:
                include_observations = False
            elif question == OBSERVATIONS_QUESTION:
                include_observations = True
            else:
                return False
            recomputed = reduce_to_2cnf(
                value["request"], include_observations=include_observations
            )
            return hash_input(report) == hash_input(recomputed)
        except (TypeError, ValueError, KeyError):
            return False

    registry.register(REDUCTION_ID, REDUCTION_VERSION, verify)
