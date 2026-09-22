"""Show, in one command, what Parcimonia decides and what it refuses to decide.

Six fragments of one ordinary development day are submitted to the shadow
router. For each fragment it either proposes the least expensive mechanism that
still clears the declared confidence threshold, or abstains with a stated
reason. Nothing is executed, no route replaces a baseline, and every cost is a
caller-supplied estimate rather than a measurement.

What this proves:
    the decision rule is explicit, deterministic, and refuses to trade
    confidence for cost. A free option is rejected when it is not confident
    enough to be worth anything.

What this does not prove:
    that a proposal is correct, cheaper in practice, or representative.
    Estimates come from the caller; no saving is measured by this script.

Usage:
    python examples/flagship.py
    python examples/flagship.py --json
"""

from __future__ import annotations

import argparse
import json
import textwrap
from dataclasses import dataclass

from tiberium_ai.contracts import CandidateRoute, Task
from tiberium_ai.router import ShadowRouter

COST_UNIT = "synthetic-unit/fragment"
MIN_CONFIDENCE = 0.9
RULE = "-" * 78


@dataclass(frozen=True)
class Ask:
    """One fragment of work, with the options its caller declared for it."""

    task: Task
    candidates: tuple[CandidateRoute, ...]


def build_asks() -> tuple[Ask, ...]:
    """Six fragments, in the order a working day tends to bring them."""
    return (
        Ask(
            Task("normalise-date", "format", {"intent": "normalise a date typed into a form"}),
            (
                CandidateRoute("rule:date-parse", ("rule:format",), estimated_cost=0.0, confidence=0.99),
                CandidateRoute("micro-nn:date", ("nn:format",), estimated_cost=0.02, confidence=0.97),
                CandidateRoute("small-llm:fr", ("model:local",), estimated_cost=1.0, confidence=0.99),
            ),
        ),
        Ask(
            Task("summarise-ticket", "summarise", {"intent": "summarise a support ticket in three lines"}),
            (
                CandidateRoute("rule:template", ("rule:text",), estimated_cost=0.01, confidence=0.62),
                CandidateRoute("micro-llm:fr", ("model:local",), estimated_cost=0.15, confidence=0.93),
                CandidateRoute("large-llm", ("model:remote",), estimated_cost=4.0, confidence=0.99),
            ),
        ),
        Ask(
            Task("extract-invoice-total", "extract", {"intent": "read the gross total off an invoice"}),
            (
                CandidateRoute("rule:regex", ("rule:extract",), estimated_cost=0.0, confidence=0.88),
                CandidateRoute("knn:invoice", ("nn:extract",), estimated_cost=0.03, confidence=0.94),
            ),
        ),
        Ask(
            Task("review-contract-clause", "review", {"intent": "review a contractual clause"}, risk_class="high"),
            (
                CandidateRoute("small-llm:fr", ("model:local",), estimated_cost=1.0, confidence=0.95),
            ),
        ),
        Ask(
            Task("diagnose-regression", "diagnose", {"intent": "explain an intermittent production regression"}, evidence_level="high"),
            (
                CandidateRoute("large-llm", ("model:remote",), estimated_cost=4.0, confidence=0.99),
            ),
        ),
        Ask(
            Task("classify-tone", "classify", {"intent": "classify the tone of a customer message"}),
            (
                CandidateRoute("uncalibrated:rules", ("rule:text",), estimated_cost=0.01, confidence=None),
                CandidateRoute("uncalibrated:model", ("model:local",), estimated_cost=0.5, confidence=None),
            ),
        ),
    )


def format_cost(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.4f}"


def format_confidence(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.2f}"


def render(asks: tuple[Ask, ...], decisions: list[object]) -> str:
    lines = [
        RULE,
        " PARCIMONIA - one command, six fragments, shadow mode",
        f" confidence bar: {MIN_CONFIDENCE:g}     cost unit: {COST_UNIT}",
        RULE,
        "",
    ]
    proposed = 0
    for index, (ask, decision) in enumerate(zip(asks, decisions), start=1):
        task = ask.task
        lines.append(f"[{index}/{len(asks)}] {task.task_id}")
        lines.append(f'      intent: "{task.inputs.get("intent", "")}"')
        lines.append(
            f"      requirements: risk={task.risk_class} evidence={task.evidence_level} locality={task.locality}"
        )
        lines.append("      declared options:")
        for candidate in ask.candidates:
            lines.append(
                "        {0:<20} cost={1:<9} confidence={2}".format(
                    candidate.route_id,
                    format_cost(candidate.estimated_cost),
                    format_confidence(candidate.confidence),
                )
            )
        if decision.abstained:
            lines.append("      -> ABSTAINED")
            for wrapped in textwrap.wrap(decision.rationale, width=74):
                lines.append(f"         {wrapped}")
        else:
            proposed += 1
            lines.append(f"      -> PROPOSED  {decision.selected_route_id}")
            for wrapped in textwrap.wrap(decision.rationale, width=74):
                lines.append(f"         {wrapped}")
        lines.append("")
    lines.append(RULE)
    lines.append(
        f" {len(asks)} fragments: {proposed} proposed, {len(asks) - proposed} abstained"
    )
    for ask, decision in zip(asks, decisions):
        if decision.abstained:
            lines.append(f"   ABSTAINED  {ask.task.task_id}")
        else:
            lines.append(f"   PROPOSED   {ask.task.task_id} -> {decision.selected_route_id}")
    lines.append(RULE)
    lines.extend(
        [
            " Shadow mode only: nothing was executed and no baseline route was",
            " replaced. Every cost is a caller-supplied estimate in one shared",
            f" synthetic unit ({COST_UNIT}), not a measurement.",
            " This script measures no saving and claims none.",
        ]
    )
    lines.append(RULE)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit the decisions as JSON")
    args = parser.parse_args(argv)

    asks = build_asks()
    router = ShadowRouter(min_confidence=MIN_CONFIDENCE)
    decisions = [router.propose(ask.task, list(ask.candidates)) for ask in asks]

    if args.json:
        payload = {
            "policy_version": router.policy_version,
            "mode": "shadow",
            "cost_unit": COST_UNIT,
            "min_confidence": MIN_CONFIDENCE,
            "decisions": [
                {
                    "task_id": ask.task.task_id,
                    "selected_route_id": decision.selected_route_id,
                    "abstained": decision.abstained,
                    "rationale": decision.rationale,
                }
                for ask, decision in zip(asks, decisions)
            ],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(render(asks, decisions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

