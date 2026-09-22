"""Compare the three candidate signature backends on the authored bench.

The bench is authored, so every number below says what a mechanism does on
inputs written for it, never what a real task needed. Nothing here can authorize
anything: it ranks candidates and it exposes which failure each one has.

Usage:
    python examples/signature_bench.py
"""

from __future__ import annotations

import json
import sys
from typing import Any, Sequence

from tiberium_ai.signature_backends import (
    KnnSignatureBackend,
    VerbFrameSignatureBackend,
    memory_from_cases,
)
from tiberium_ai.signature_corpus import (
    aligned_cases,
    example_schema,
    paraphrase_cases,
)
from tiberium_ai.task_signature import (
    RuleBasedSignatureBackend,
    calibrate_signatures,
)


def measure(label: str, predictor: Any, cases: Sequence[Any], schema: Any) -> dict[str, Any]:
    report = calibrate_signatures(
        cases,
        schema=schema,
        predictor=predictor,
        predictor_id=label,
        predictor_version="1",
    )
    return {
        "predictor": label,
        "cases": report.cases,
        "abstained": report.abstained,
        "coverage": round(report.coverage, 3),
        "kind_agreement": (
            None if report.kind_agreement is None else round(report.kind_agreement, 3)
        ),
        "field_precision": (
            None if report.field_precision is None else round(report.field_precision, 3)
        ),
        "field_recall": (
            None if report.field_recall is None else round(report.field_recall, 3)
        ),
        "goal_agreement": (
            None if report.goal_agreement is None else round(report.goal_agreement, 3)
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    schema = example_schema()
    aligned = aligned_cases()
    paraphrased = paraphrase_cases()
    candidates: tuple[tuple[str, Any], ...] = (
        ("rule.keyword", RuleBasedSignatureBackend(schema)),
        ("frame.verb-object", VerbFrameSignatureBackend(schema)),
        # The retrieval memory is the aligned half, so this candidate has, by
        # construction, already seen every prompt it is scored on there.
        ("knn.memory=aligned", KnnSignatureBackend(memory_from_cases(aligned, schema))),
    )

    rows: list[dict[str, Any]] = []
    for label, predictor in candidates:
        for half, cases in (("aligned", aligned), ("paraphrase", paraphrased)):
            entry = measure(label, predictor, cases, schema)
            entry["half"] = half
            rows.append(entry)

    header = f"{'predictor':<22}{'half':<12}{'cov':>6}{'kind':>7}{'prec':>7}{'rec':>7}{'goal':>7}"
    print(header)
    for row in rows:
        def show(value: Any) -> str:
            return "-" if value is None else f"{value}"

        print(
            f"{row['predictor']:<22}{row['half']:<12}{row['coverage']:>6}"
            f"{show(row['kind_agreement']):>7}{show(row['field_precision']):>7}"
            f"{show(row['field_recall']):>7}{show(row['goal_agreement']):>7}"
        )

    by_key = {(row["predictor"], row["half"]): row for row in rows}
    frame_para = by_key[("frame.verb-object", "paraphrase")]
    rule_para = by_key[("rule.keyword", "paraphrase")]
    knn_aligned = by_key[("knn.memory=aligned", "aligned")]
    knn_para = by_key[("knn.memory=aligned", "paraphrase")]
    summary = {
        "kind": "signature_bench",
        "data_origin": "fixture",
        "model_called": False,
        "rows": rows,
        "readings": [
            (
                "structure triples coverage off distribution and earns a kind the "
                f"lexical rule cannot: {rule_para['coverage']} -> "
                f"{frame_para['coverage']} coverage, "
                f"{rule_para['kind_agreement']} -> {frame_para['kind_agreement']} agreement"
            ),
            (
                "structure does not buy the vocabulary: the frame keeps a field "
                f"recall of {frame_para['field_recall']} on the French paraphrases, "
                "because the declared hints are still English"
            ),
            (
                "span position removes the rule's invented field: precision "
                f"{rule_para['field_precision']} -> {frame_para['field_precision']}"
            ),
            (
                "the retrieval candidate is exact on its own memory and mute off "
                f"it: agreement {knn_aligned['kind_agreement']} at coverage "
                f"{knn_aligned['coverage']} on the half it memorised, coverage "
                f"{knn_para['coverage']} on the other"
            ),
            (
                "no number here can authorize a threshold: the situations and the "
                "labels come from the same authored hand"
            ),
        ],
    }
    print()
    for reading in summary["readings"]:
        print("-", reading)
    print()
    print(json.dumps({"rows": len(rows), "data_origin": "fixture"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
