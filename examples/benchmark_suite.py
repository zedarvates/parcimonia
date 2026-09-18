"""Run the fixture corpus through the benchmark harness and write a report.

Usage:
    python examples/benchmark_suite.py --out runs/benchmark
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from time import perf_counter

from fixture_suite import build_suite
from tiberium_ai.benchmark import BenchmarkCase, BenchmarkRoute, run_benchmark
from tiberium_ai.contracts import Task
from tiberium_ai.measurement import Environment

BASELINE_ESTIMATED_COST = 1.0
CANDIDATE_ESTIMATED_COST = 0.01
COST_UNIT = "synthetic-unit/task"


def build_cases() -> list[BenchmarkCase]:
    return [
        BenchmarkCase(
            task=Task(fixture.task_id, fixture.kind, {}),
            routes=(
                BenchmarkRoute(
                    "baseline",
                    fixture.baseline,
                    estimated_cost=BASELINE_ESTIMATED_COST,
                    confidence=0.99,
                ),
                BenchmarkRoute(
                    "rule",
                    fixture.rule,
                    estimated_cost=CANDIDATE_ESTIMATED_COST,
                    confidence=0.95,
                ),
            ),
            verifier_id=fixture.verifier_id,
            verifier_version=fixture.verifier_version,
            verifier=fixture.verifier,
            baseline_route_id="baseline",
        )
        for fixture in build_suite()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("runs/benchmark"))
    parser.add_argument("--seed", type=int, default=20260918)
    arguments = parser.parse_args(argv)
    try:
        report = run_benchmark(
            build_cases(),
            out_dir=arguments.out,
            seed=arguments.seed,
            environment=Environment(
                "fixture-runner", {"python": platform.python_version()}
            ),
            clock=perf_counter,
            cost_unit=COST_UNIT,
            corpus="fixture",
        )
    except FileExistsError as exc:
        print(
            f"refusing to overwrite existing records in {arguments.out}: {exc}",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
