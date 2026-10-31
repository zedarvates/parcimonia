"""Sensitivity analysis for disputed authored labels.

This module proposes no authoritative correction. It reports what each
predeclared interpretation would do to a candidate's kind agreement.
The caller still decides which intent the authored case represents.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from .task_signature import SignatureCase, SignatureSchema, calibrate_signatures

__all__ = ["LabelOption", "LabelReview", "review_label_options"]


@dataclass(frozen=True)
class LabelOption:
    case_id: str
    proposed_kind: str
    rationale: str


@dataclass(frozen=True)
class LabelReview:
    baseline_kind_agreement: float | None
    option_agreements: Mapping[str, float | None]
    data_origin: str = "fixture"
    decision_owner: str = "human"


def review_label_options(
    cases: Sequence[SignatureCase],
    options: Sequence[LabelOption],
    *,
    schema: SignatureSchema,
    predictor: Any,
    predictor_id: str,
    predictor_version: str,
) -> LabelReview:
    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("case ids must be unique.")
    known = {item.name for item in schema.kinds}
    for option in options:
        if option.case_id not in by_id:
            raise ValueError(f"unknown case {option.case_id!r}.")
        if option.proposed_kind not in known:
            raise ValueError(f"unknown kind {option.proposed_kind!r}.")
    baseline = calibrate_signatures(
        cases,
        schema=schema,
        predictor=predictor,
        predictor_id=predictor_id,
        predictor_version=predictor_version,
    )
    results: dict[str, float | None] = {}
    for option in options:
        modified = tuple(
            replace(case, kind=option.proposed_kind)
            if case.case_id == option.case_id else case
            for case in cases
        )
        report = calibrate_signatures(
            modified,
            schema=schema,
            predictor=predictor,
            predictor_id=predictor_id,
            predictor_version=predictor_version,
        )
        results[f"{option.case_id}:{option.proposed_kind}"] = report.kind_agreement
    return LabelReview(baseline.kind_agreement, results)
