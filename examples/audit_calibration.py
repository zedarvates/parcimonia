"""Run the authored static-audit corpus and write the calibration snapshot.

The snapshot records what the audit did on 31 labelled files, per rule and per
role, together with the fact that it may not authorize anything. It is evidence
about the analyser on authored examples, not about real code, so the boundary
travels inside the file instead of being remembered by whoever reads it later.

Usage:
    python examples/audit_calibration.py --out runs/audit-calibration
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from tiberium_ai.audit_calibrate import calibrate_static_audit


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="runs/audit-calibration", help="output directory")
    return parser.parse_args(list(argv))


def rate(value: float | None) -> str:
    """Render a rate that may be undefined because its denominator was zero."""
    return "n/a" if value is None else f"{value:.4f}"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    snapshot_path = out / "calibration.json"
    cases_path = out / "cases.jsonl"
    for target in (snapshot_path, cases_path):
        if target.exists():
            raise SystemExit(f"{target} already exists; use another --out directory")

    report = calibrate_static_audit()
    snapshot = report.to_record()
    snapshot_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with cases_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in report.case_records():
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    print("cases:", report.n_cases, "| origin:", report.data_origin)
    print("role agreement:", rate(report.role_agreement))
    print("band agreement:", rate(report.band_agreement))
    print("rule agreement:", rate(report.rule_agreement))
    for score in report.per_rule:
        print(f"  {score.rule_id:26} precision {rate(score.precision)} recall {rate(score.recall)}")
    print("disagreements:", [item.case_id for item in report.disagreements])
    print("threshold authorized:", report.authorizes_threshold())
    print("reason:", snapshot["threshold_authorized_reason"])
    print("snapshot:", snapshot_path, "| cases:", cases_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
