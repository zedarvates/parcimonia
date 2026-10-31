"""Measure the candidates on real asks taken from a local corpus revision.

There is no outcome label for a real ask, so this lane measures what labels cannot
change: how often each mechanism answers at all, what it answers with, and where
the mechanisms agree or split. Agreement is a triage signal for pricing human
labelling, never a measure of truth.

The retrieval candidate is absent on purpose: it needs labelled examples, and that
is exactly what does not exist yet for real work.

Usage:
    python examples/real_asks_lane.py
    python examples/real_asks_lane.py --max-prompts 400 --out runs/signature-corpus/real-lane.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from tiberium_ai.real_asks import (
    LABELS_ABSENT,
    agreement_triage,
    measure_coverage,
    reachable_schema,
)
from tiberium_ai.signature_backends import VerbFrameSignatureBackend
from tiberium_ai.signature_taxonomy import classify_prompt
from tiberium_ai.task_signature import RuleBasedSignatureBackend


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", default="runs/signature-corpus/latest.json")
    parser.add_argument("--out", default=None)
    parser.add_argument("--max-prompts", type=int, default=0)
    return parser.parse_args(list(argv))


def load_asks(path: Path, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    revision = json.loads(path.read_text(encoding="utf-8"))
    asks = [
        prompt
        for prompt in revision["prompts"]
        if classify_prompt(str(prompt.get("text", "")))[0] == "ask"
    ]
    if limit > 0:
        asks = asks[:limit]
    if not asks:
        raise SystemExit("no ask-bearing prompt in " + str(path))
    return asks, {"revision_id": revision.get("revision_id"), "asks": len(asks)}


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(sys.argv[1:] if argv is None else argv)
    schema = reachable_schema()
    asks, meta = load_asks(Path(arguments.corpus), arguments.max_prompts)
    predictors = {
        "rule.keyword": RuleBasedSignatureBackend(schema),
        "frame.control": VerbFrameSignatureBackend(schema, interrogative_signal=False),
        "frame.interrogative": VerbFrameSignatureBackend(schema),
    }

    reports = measure_coverage(asks, predictors=predictors, schema=schema)
    triage = agreement_triage(asks, predictors=predictors, schema=schema)

    print("corpus", meta["revision_id"][:16], "| asks", meta["asks"])
    print()
    print(f"{'candidate':<22}{'cov(d)':>8}{'cov(v)':>8}{'answered':>10}")
    for report in reports:
        print(
            f"{report.predictor:<22}{report.coverage_distinct:>8.3f}"
            f"{report.coverage_volume:>8.3f}{report.answered_volume:>10}"
        )
    print()
    for report in reports:
        record = report.to_record()
        print(report.predictor, "actions:", json.dumps(record["actions"], sort_keys=True))
        print(
            "   bands:",
            json.dumps(record["by_band"], sort_keys=True),
        )
    print()
    print("triage:", json.dumps(triage["buckets"], sort_keys=True))
    print("unanimous share of volume:", triage["unanimous_share"])
    print("share needing one label:", triage["needs_a_label_share"])
    print("triage examples:", json.dumps(triage["example_ids"], sort_keys=True))
    print()
    print("reading:", LABELS_ABSENT)

    if arguments.out:
        out = Path(arguments.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "corpus": arguments.corpus,
                    "revision_id": meta["revision_id"],
                    "candidates": [report.to_record() for report in reports],
                    "triage": triage,
                    "reading": LABELS_ABSENT,
                },
                indent=1,
                sort_keys=True,
            )
            + chr(10),
            encoding="utf-8",
            newline=chr(10),
        )
        print("wrote:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
