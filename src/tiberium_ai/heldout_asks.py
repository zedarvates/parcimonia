"""Compare signature coverage only on prompts absent from a fixed revision.

This reports coverage, not correctness. The split is content based and keeps
the private prompt text outside the returned aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .real_asks import CandidateReport, measure_coverage, reachable_schema
from .signature_backends import VerbFrameSignatureBackend
from .signature_taxonomy import classify_prompt
from .task_signature import RuleBasedSignatureBackend

__all__ = ["HeldoutCoverage", "measure_new_ask_coverage"]


@dataclass(frozen=True)
class HeldoutCoverage:
    reference_revision_id: str
    current_revision_id: str
    new_distinct: int
    new_volume: int
    ask_distinct: int
    ask_volume: int
    reports: tuple[CandidateReport, ...]
    verdict: str

    def to_record(self) -> dict[str, Any]:
        return {
            "reference_revision_id": self.reference_revision_id,
            "current_revision_id": self.current_revision_id,
            "new_distinct": self.new_distinct,
            "new_volume": self.new_volume,
            "ask_distinct": self.ask_distinct,
            "ask_volume": self.ask_volume,
            "reports": [report.to_record() for report in self.reports],
            "verdict": self.verdict,
            "data_origin": "unlabelled_real_prompts",
            "claim": "coverage_only",
        }


def measure_new_ask_coverage(
    reference: Mapping[str, Any],
    current: Mapping[str, Any],
) -> HeldoutCoverage:
    for name, revision in (("reference", reference), ("current", current)):
        if not isinstance(revision, Mapping):
            raise TypeError(f"{name} revision must be a mapping.")
        if not isinstance(revision.get("prompts"), list):
            raise ValueError(f"{name} revision must contain prompts.")
        if not isinstance(revision.get("revision_id"), str) or not revision["revision_id"]:
            raise ValueError(f"{name} revision must have an id.")

    reference_texts = {
        entry["text"] for entry in reference["prompts"] if isinstance(entry, Mapping)
    }
    new_entries = [
        entry
        for entry in current["prompts"]
        if isinstance(entry, Mapping) and entry.get("text") not in reference_texts
    ]
    asks = [
        entry for entry in new_entries
        if classify_prompt(str(entry.get("text", "")))[0] == "ask"
    ]
    reports: tuple[CandidateReport, ...] = ()
    if asks:
        schema = reachable_schema()
        reports = measure_coverage(
            asks,
            schema=schema,
            predictors={
                "rule.keyword": RuleBasedSignatureBackend(schema),
                "frame.control": VerbFrameSignatureBackend(
                    schema, interrogative_signal=False
                ),
                "frame.interrogative": VerbFrameSignatureBackend(schema),
            },
        )
    frame = next((item for item in reports if item.predictor == "frame.interrogative"), None)
    if not asks:
        verdict = "empty_heldout"
    elif frame is not None and frame.coverage_volume >= 0.50:
        verdict = "coverage_threshold_met"
    else:
        verdict = "coverage_threshold_missed"
    return HeldoutCoverage(
        reference_revision_id=reference["revision_id"],
        current_revision_id=current["revision_id"],
        new_distinct=len(new_entries),
        new_volume=sum(int(entry.get("count", 1)) for entry in new_entries),
        ask_distinct=len(asks),
        ask_volume=sum(int(entry.get("count", 1)) for entry in asks),
        reports=reports,
        verdict=verdict,
    )
