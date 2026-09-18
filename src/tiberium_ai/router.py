from __future__ import annotations
from math import isfinite

from .contracts import Task, CandidateRoute, Decision


def is_nonnegative_number(value: object) -> bool:
    # bool is an int subclass, but is not a confidence or cost estimate.
    return (
        type(value) in (int, float)
        and value >= 0
        and (isinstance(value, int) or isfinite(value))
    )


class ShadowRouter:
    """Propose routes without executing them or replacing the baseline.

    Costs must share one unit and estimation basis within a proposal.
    Declared confidence is a filtering signal, not verified quality.
    """

    def __init__(self, min_confidence: float = 0.9) -> None:
        if not is_nonnegative_number(min_confidence) or min_confidence > 1:
            raise ValueError("min_confidence must be a finite number in [0, 1].")
        self._min_confidence = min_confidence

    def propose(self, task: Task, candidates: list[CandidateRoute]) -> Decision:
        # CandidateRoute has no evidence or locality guarantees yet. Do not
        # silently interpret these requirements as satisfied by confidence.
        if (task.risk_class, task.evidence_level, task.locality) != (
            "low", "normal", "any"
        ):
            return Decision(
                task_id=task.task_id,
                selected_route_id=None,
                rationale=(
                    "Unsupported task requirements; this prototype only proposes "
                    "for risk_class=low, evidence_level=normal, locality=any."
                ),
                abstained=True,
            )

        route_ids = [c.route_id for c in candidates]
        if (
            any(not isinstance(r, str) or not r or r != r.strip() for r in route_ids)
            or len(set(route_ids)) != len(route_ids)
        ):
            return Decision(
                task_id=task.task_id,
                selected_route_id=None,
                rationale="Route IDs must be unique, nonempty strings without surrounding whitespace.",
                abstained=True,
            )

        usable = [
            c for c in candidates
            if is_nonnegative_number(c.confidence)
            and self._min_confidence <= c.confidence <= 1
            and (c.estimated_cost is None or is_nonnegative_number(c.estimated_cost))
        ]
        if not usable:
            return Decision(
                task_id=task.task_id,
                selected_route_id=None,
                rationale="No candidate meets the confidence and cost validity checks.",
                abstained=True,
            )

        priced = [c for c in usable if c.estimated_cost is not None]
        if priced:
            chosen = min(
                priced,
                key=lambda c: (c.estimated_cost, -c.confidence, c.route_id),
            )
            rationale = (
                "Shadow proposal only; lowest known estimated cost at or above the "
                f"confidence threshold {self._min_confidence:g}. "
                "Ties use higher confidence, then lexical route ID."
            )
        else:
            chosen = min(usable, key=lambda c: (-c.confidence, c.route_id))
            rationale = (
                "Shadow proposal only; all eligible costs are unknown. "
                "Highest declared confidence, then lexical route ID; "
                "no cost comparison is possible."
            )
        return Decision(
            task_id=task.task_id,
            selected_route_id=chosen.route_id,
            rationale=rationale,
        )
