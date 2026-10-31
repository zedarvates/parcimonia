"""Bounded option-order diagnostic over authored Tev1 cases, not calibration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .reflex import ReflexKind, ReflexQuestion
from .tev1_cases import Tev1Case, agrees, corpus_revision, rule_baseline, tev1_cases
from .verification import hash_input

BASE_CORPUS = "base"
CHOICE_ORDER_CORPUS = "choice-order"
CORPUS_KINDS = (BASE_CORPUS, CHOICE_ORDER_CORPUS)


@dataclass(frozen=True)
class OrderedTev1Case(Tev1Case):
    source_case_id: str
    order_id: str
    ordered_keys: tuple[str, ...]

    @property
    def question(self) -> ReflexQuestion:
        original = super().question
        if original.kind != ReflexKind.CHOICE:
            return original
        return replace(
            original,
            criteria={key: original.criteria[key] for key in self.ordered_keys},
        )


def choice_order_cases() -> tuple[OrderedTev1Case, ...]:
    """Use each cyclic rotation and a distinct reversal; keep ordinal controls."""
    result = []
    for case in tev1_cases():
        keys = case.question.option_keys
        orders = [("control", keys)]
        if case.question.kind == ReflexKind.CHOICE:
            orders = [
                (f"rotate-{index}", keys[index:] + keys[:index])
                for index in range(len(keys))
            ]
            reverse = tuple(reversed(keys))
            if reverse not in [order for _, order in orders]:
                orders.append(("reverse", reverse))
        for order_id, order in orders:
            result.append(
                OrderedTev1Case(
                    f"{case.case_id}-{order_id}",
                    case.family,
                    case.state,
                    case.expected,
                    case.case_id,
                    order_id,
                    order,
                )
            )
    return tuple(result)


def cases_for(corpus_kind: str = BASE_CORPUS) -> tuple[Tev1Case, ...]:
    if corpus_kind == BASE_CORPUS:
        return tev1_cases()
    if corpus_kind == CHOICE_ORDER_CORPUS:
        return choice_order_cases()
    raise ValueError("unknown_corpus_kind")


def revision_for(corpus_kind: str = BASE_CORPUS) -> str:
    if corpus_kind == BASE_CORPUS:
        return corpus_revision()
    cases = cases_for(corpus_kind)
    return hash_input(
        {
            "protocol": "tev1-choice-order/v1",
            "base_corpus_revision": corpus_revision(),
            "cases": [
                {
                    **order_metadata(case),
                    "state": case.state,
                    "expected": case.expected,
                    "question": {
                        "name": case.question.name,
                        "kind": case.question.kind.value,
                        "instructions": case.question.instructions,
                        "criteria": case.question.criteria,
                    },
                }
                for case in cases
            ],
        }
    )


def order_metadata(case: OrderedTev1Case) -> dict[str, Any]:
    # The explicit list survives canonical JSON hashing, which sorts mapping keys.
    return {
        "case_id": case.case_id,
        "source_case_id": case.source_case_id,
        "order_id": case.order_id,
        "option_order": list(case.ordered_keys),
    }


def choice_order_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize revalidated rows; missing orders cannot establish invariance."""
    cases = choice_order_cases()
    if len(rows) != len(cases) or any(
        row.get("case_id") != case.case_id for case, row in zip(cases, rows)
    ):
        raise ValueError("order_cases_mismatch")
    grouped = {}
    for case, row in zip(cases, rows):
        grouped.setdefault(case.source_case_id, []).append((case, row))
    choices, by_family = [], {}
    source_correct = source_complete = rules_correct = 0
    for source in tev1_cases():
        variants = grouped[source.case_id]
        usable = [row for _, row in variants if row["status"] == "ok"]
        complete = len(usable) == len(variants)
        all_correct = complete and all(
            agrees(case, row["model"]) for case, row in variants
        )
        source_complete += complete
        source_correct += all_correct
        rules_agree = agrees(source, rule_baseline(source))
        rules_correct += rules_agree
        family = by_family.setdefault(
            source.family,
            {
                "source_case_count": 0,
                "fully_answered": 0,
                "all_variants_correct": 0,
                "rules_correct": 0,
            },
        )
        family["source_case_count"] += 1
        family["fully_answered"] += complete
        family["all_variants_correct"] += all_correct
        family["rules_correct"] += rules_agree
        if source.question.kind != ReflexKind.CHOICE:
            continue
        original = variants[0][1]
        reference = original if original["status"] == "ok" else None
        paired = [row for row in usable if row["case_id"] != original["case_id"]]
        deltas = (
            [
                max(row["probabilities"][key] for row in usable)
                - min(row["probabilities"][key] for row in usable)
                for key in source.question.option_keys
            ]
            if len(usable) > 1
            else []
        )
        diagnostics = []
        for case, row in variants:
            probabilities = row["probabilities"]
            values = (
                sorted(probabilities.values(), reverse=True) if probabilities else []
            )
            diagnostics.append(
                {
                    **order_metadata(case),
                    "status": row["status"],
                    "choice": row["model"],
                    "margin_top_two": values[0] - values[1] if values else None,
                    "max_tie_options": sorted(
                        key
                        for key, value in probabilities.items()
                        if value == values[0]
                    )
                    if values
                    else None,
                }
            )
        choices.append(
            {
                "source_case_id": source.case_id,
                "family": source.family,
                "expected": source.expected,
                "variant_count": len(variants),
                "usable_variants": len(usable),
                "complete": complete,
                "reference_choice": reference["model"] if reference else None,
                "reference_correct": agrees(source, reference["model"])
                if reference
                else None,
                "choice_invariant": len({row["model"] for row in usable}) == 1
                if complete
                else None,
                "compared_to_original": len(paired) if reference else 0,
                "winner_changes_from_original": sum(
                    row["model"] != reference["model"] for row in paired
                )
                if reference and paired
                else None,
                "max_pairwise_probability_delta": max(deltas) if deltas else None,
                "all_variants_correct_and_usable": all_correct,
                "variants": diagnostics,
            }
        )
    return {
        "source_case_count": len(grouped),
        "fully_answered_source_cases": source_complete,
        "all_variants_correct_source_cases": source_correct,
        "source_coverage": source_complete / len(grouped),
        "source_agreement_all_cases": source_correct / len(grouped),
        "rules_correct_source_cases": rules_correct,
        "rules_source_agreement_all_cases": rules_correct / len(grouped),
        "choice_source_count": len(choices),
        "complete_choice_sources": sum(row["complete"] for row in choices),
        "incomplete_choice_sources": sum(not row["complete"] for row in choices),
        "invariant_choice_sources": sum(
            row["choice_invariant"] is True for row in choices
        ),
        "changed_choice_sources": sum(
            row["choice_invariant"] is False for row in choices
        ),
        "stable_but_wrong_sources": sum(
            row["choice_invariant"] is True
            and not row["all_variants_correct_and_usable"]
            for row in choices
        ),
        "by_family": by_family,
        "choices": choices,
        "independent_sample_count": None,
        "auto_act_allowed": False,
        "saving_claim": False,
    }
