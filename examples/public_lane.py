"""Measure the candidates on well-formed public instructions with external labels.

Fetches a slice of Dolly-15k (CC-BY-SA-3.0) from the Hugging Face datasets
server, maps its human categories to declared kinds, and measures the keyword
rule, the verb frame and a retrieval backend on a set disjoint from the memory.

Requires network access, so it is deliberately absent from the offline test
suite. The dataset labels are not ours, which is the whole point: an authored
bench cannot settle a disagreement about its own labels.

Usage:
    python examples/public_lane.py
    python examples/public_lane.py --rows 400 --memory 100
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any, Sequence

from tiberium_ai.public_corpus import cases_from_rows, public_schema, public_split
from tiberium_ai.signature_backends import (
    KnnSignatureBackend,
    LayeredSignatureBackend,
    VerbFrameSignatureBackend,
    memory_from_cases,
)
from tiberium_ai.task_signature import (
    RuleBasedSignatureBackend,
    calibrate_signatures,
)

ENDPOINT = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=databricks%2Fdatabricks-dolly-15k&config=default&split=train"
)
PAGE = 100


def fetch(rows: int, *, offset: int = 0) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for start in range(0, rows, PAGE):
        length = min(PAGE, rows - start)
        with urllib.request.urlopen(  # noqa: S310 - a fixed public endpoint
            f"{ENDPOINT}&offset={offset + start}&length={length}", timeout=60
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        for entry in payload.get("rows", []):
            raw = entry.get("row", {})
            collected.append(
                {
                    "category": str(raw.get("category", "")),
                    "instruction": str(raw.get("instruction", "")),
                    "context_present": bool(str(raw.get("context", "")).strip()),
                }
            )
    return collected


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
        "kind_agreement": None if report.kind_agreement is None else round(report.kind_agreement, 3),
        "field_precision": None if report.field_precision is None else round(report.field_precision, 3),
        "field_recall": None if report.field_recall is None else round(report.field_recall, 3),
        "per_kind": {},
        "confusions": {},
    }, report


def seed_curve(arguments: Any) -> int:
    """How much labelled memory does the retrieval candidate need?

    The sizes are nested subsets of one region, so the curve isolates the size
    and nothing else, and the evaluation slice is one the protocol has never
    read. Reading a curve is not choosing from it: any default taken here would
    need a later unread slice to be validated.
    """
    schema = public_schema()
    sizes = [int(part) for part in str(arguments.memory_sizes).split(",") if part.strip()]
    if sorted(sizes) != sizes or len(set(sizes)) != len(sizes):
        raise SystemExit("--memory-sizes must be increasing and distinct")
    largest = max(sizes)
    memory_rows = fetch(largest, offset=arguments.memory_offset)
    evaluated = cases_from_rows(
        fetch(arguments.rows, offset=arguments.eval_offset),
        schema=schema,
        id_prefix="eval",
    )

    reference = (
        ("reference.rule", RuleBasedSignatureBackend(schema)),
        ("reference.frame", VerbFrameSignatureBackend(schema)),
    )
    rows_out: list[dict[str, Any]] = []
    for label, predictor in reference:
        entry, _ = measure(label, predictor, evaluated, schema)
        entry["memory_size"] = 0
        rows_out.append(entry)
    for size in sizes:
        memory = cases_from_rows(
            memory_rows[:size], schema=schema, id_prefix=f"mem{size}"
        )
        entry, _ = measure(
            f"knn.memory={size}",
            KnnSignatureBackend(memory_from_cases(memory, schema)),
            evaluated,
            schema,
        )
        entry["memory_size"] = size
        rows_out.append(entry)

    print(f"{'candidate':<20}{'mem':>5}{'cov':>7}{'kind':>7}{'prec':>7}{'rec':>7}")
    for entry in rows_out:
        show = lambda value: "-" if value is None else f"{value}"  # noqa: E731
        print(
            f"{entry['predictor']:<20}{entry['memory_size']:>5}{entry['coverage']:>7}"
            f"{show(entry['kind_agreement']):>7}{show(entry['field_precision']):>7}"
            f"{show(entry['field_recall']):>7}"
        )
    print()
    print(json.dumps(
        {
            "evaluated": len(evaluated),
            "eval_offset": arguments.eval_offset,
            "memory_offset": arguments.memory_offset,
            "memory_sizes": sizes,
            "data_origin": "fixture",
            "note": "public corpus cannot authorize",
        },
        sort_keys=True,
    ))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=400)
    parser.add_argument("--memory", type=int, default=100)
    parser.add_argument("--memory-offset", type=int, default=0)
    parser.add_argument("--eval-offset", type=int, default=400)
    parser.add_argument(
        "--seed-curve",
        action="store_true",
        help="measure one retrieval candidate against nested memory sizes",
    )
    parser.add_argument("--memory-sizes", default="25,50,100,200")
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    if arguments.seed_curve:
        return seed_curve(arguments)

    schema = public_schema()
    # The evaluation slice is deliberately one this protocol has never read, and
    # the control arm differs from the treatment by one signal only.
    memory = cases_from_rows(
        fetch(arguments.memory, offset=arguments.memory_offset),
        schema=schema,
        id_prefix="mem",
    )
    evaluated = cases_from_rows(
        fetch(arguments.rows, offset=arguments.eval_offset),
        schema=schema,
        id_prefix="eval",
    )

    candidates = (
        ("rule.keyword", RuleBasedSignatureBackend(schema)),
        (
            "frame.control",
            VerbFrameSignatureBackend(
                schema, interrogative_signal=False, specificity_tie_break=False
            ),
        ),
        (
            "frame.084-signal",
            VerbFrameSignatureBackend(schema, specificity_tie_break=False),
        ),
        (
            "frame.086-specificity",
            VerbFrameSignatureBackend(schema, specificity_tie_break=True),
        ),
        ("knn.memory=seed", KnnSignatureBackend(memory_from_cases(memory, schema))),
        (
            "knn+rule.layered",
            LayeredSignatureBackend(
                primary=KnnSignatureBackend(memory_from_cases(memory, schema)),
                fallback=RuleBasedSignatureBackend(schema),
            ),
        ),
    )

    rows_out = []
    for label, predictor in candidates:
        entry, report = measure(label, predictor, evaluated, schema)
        scored = [o for o in report.observations if not o["abstained"]]
        for kind in sorted({o["expected_kind"] for o in report.observations}):
            total = [o for o in report.observations if o["expected_kind"] == kind]
            right = [o for o in scored if o["expected_kind"] == kind and o["kind"] == kind]
            entry["per_kind"][kind] = {
                "cases": len(total),
                "answered": len([o for o in scored if o["expected_kind"] == kind]),
                "right": len(right),
            }
        for observation in scored:
            if observation["kind"] != observation["expected_kind"]:
                key = f"{observation['expected_kind']}->{observation['kind']}"
                entry["confusions"][key] = entry["confusions"].get(key, 0) + 1
        rows_out.append(entry)

    print(f"{'predictor':<20}{'cov':>6}{'kind':>7}{'prec':>7}{'rec':>7}")
    for entry in rows_out:
        show = lambda value: "-" if value is None else f"{value}"  # noqa: E731
        print(
            f"{entry['predictor']:<20}{entry['coverage']:>6}"
            f"{show(entry['kind_agreement']):>7}{show(entry['field_precision']):>7}"
            f"{show(entry['field_recall']):>7}"
        )
    print()
    for entry in rows_out:
        print(entry["predictor"], "per kind:",
              json.dumps(entry["per_kind"], sort_keys=True))
        if entry["confusions"]:
            print(entry["predictor"], "confusions:",
                  json.dumps(entry["confusions"], sort_keys=True))
    print()
    print(json.dumps(
        {"evaluated": len(evaluated), "memory": len(memory),
         "memory_offset": arguments.memory_offset, "eval_offset": arguments.eval_offset,
         "data_origin": "fixture", "note": "public corpus cannot authorize"},
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
