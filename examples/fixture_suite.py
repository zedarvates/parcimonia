"""Run a deterministic fixture suite through measurement, verification and observation.

Every case executes a real local callable twice: a baseline route and a cheaper
rule route. Each run is measured, its output is verified, and the pair is stored
as one attributed observation. These are fixture tasks: they exercise the
pipeline and prove provenance, not representative cost or savings.

Usage:
    python examples/fixture_suite.py --out runs/fixtures
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from tiberium_ai.capture import capture_run
from tiberium_ai.contracts import CandidateRoute, Task
from tiberium_ai.measurement import Environment, write_measurement
from tiberium_ai.observations import (
    compare_observation,
    record_observation,
    write_observation,
)
from tiberium_ai.verification import VerifierRegistry, exact_match_verifier

BASELINE_ESTIMATED_COST = 1.0
RULE_ESTIMATED_COST = 0.01
COST_UNIT = "synthetic-unit/task"
DATA_ORIGIN = "synthetic"


@dataclass(frozen=True)
class FixtureCase:
    task_id: str
    kind: str
    baseline: Callable[[], Any]
    rule: Callable[[], Any]
    verifier_id: str
    verifier_version: str
    verifier: Callable[[Any], bool]


def arithmetic_case(index: int) -> FixtureCase:
    size = 13 * index
    expected = {"total": size * (size - 1) // 2}

    def baseline(size=size):
        return {"total": sum(range(size))}

    def rule(size=size):
        return {"total": size * (size - 1) // 2}

    return FixtureCase(
        task_id=f"arithmetic-{index:03d}",
        kind="arithmetic",
        baseline=baseline,
        rule=rule,
        verifier_id="arithmetic/exact",
        verifier_version=f"size={size}",
        verifier=exact_match_verifier(expected),
    )


def text_case(index: int) -> FixtureCase:
    words = [f"w{position}" for position in range(index + 1)]
    expected = " | ".join(word.upper() for word in words)

    def baseline(words=words):
        parts = []
        for word in words:
            parts.append(word.upper())
        return " | ".join(parts)

    def rule(words=words):
        return " | ".join(word.upper() for word in words)

    return FixtureCase(
        task_id=f"text-{index:03d}",
        kind="formatting",
        baseline=baseline,
        rule=rule,
        verifier_id="text/exact",
        verifier_version=f"words={len(words)}",
        verifier=exact_match_verifier(expected),
    )


def json_case(index: int) -> FixtureCase:
    keys = [f"k{position}" for position in range(1, index + 1)]
    expected = {key: position * 3 for position, key in enumerate(keys, start=1)}

    def baseline(keys=keys):
        result = {}
        for position, key in enumerate(keys, start=1):
            result[key] = position * 3
        return result

    def rule(keys=keys):
        return {key: position * 3 for position, key in enumerate(keys, start=1)}

    return FixtureCase(
        task_id=f"json-{index:03d}",
        kind="transform",
        baseline=baseline,
        rule=rule,
        verifier_id="json/exact",
        verifier_version=f"fields={len(keys)}",
        verifier=exact_match_verifier(expected),
    )


def failure_case() -> FixtureCase:
    expected = {"total": 0}

    def baseline():
        return {"total": 0}

    def rule():
        raise ValueError("fixture: this route fails on purpose")

    return FixtureCase(
        task_id="failure-001",
        kind="arithmetic",
        baseline=baseline,
        rule=rule,
        verifier_id="arithmetic/exact",
        verifier_version="failure-001",
        verifier=exact_match_verifier(expected),
    )


def wrong_answer_case() -> FixtureCase:
    expected = {"total": sum(range(100))}

    def baseline():
        return {"total": sum(range(100))}

    def rule():
        return {"total": 5049}

    return FixtureCase(
        task_id="wrong-answer-001",
        kind="arithmetic",
        baseline=baseline,
        rule=rule,
        verifier_id="arithmetic/exact",
        verifier_version="wrong-answer-001",
        verifier=exact_match_verifier(expected),
    )


def build_suite() -> list[FixtureCase]:
    cases = [arithmetic_case(index) for index in range(1, 9)]
    cases += [text_case(index) for index in range(1, 7)]
    cases += [json_case(index) for index in range(1, 5)]
    cases.append(failure_case())
    cases.append(wrong_answer_case())
    return cases


def run_suite(out_dir: Path) -> dict[str, Any]:
    measurements_dir = out_dir / "measurements"
    observations_dir = out_dir / "observations"
    measurements_dir.mkdir(parents=True, exist_ok=True)
    observations_dir.mkdir(parents=True, exist_ok=True)

    environment = Environment(
        machine_id="fixture-runner",
        runtime_versions={"python": platform.python_version()},
    )
    registry = VerifierRegistry()
    statuses: dict[str, int] = {}
    measurements_ok = 0
    measurements_failed = 0

    for case in build_suite():
        registry.register(case.verifier_id, case.verifier_version, case.verifier)
        captured = {}
        for route_id, run in (("baseline", case.baseline), ("rule", case.rule)):
            captured[route_id] = capture_run(
                task_id=case.task_id,
                route_id=route_id,
                run=run,
                verifier_id=case.verifier_id,
                verifier_version=case.verifier_version,
                registry=registry,
                cost_unit=COST_UNIT,
                environment=environment,
                clock=perf_counter,
            )
            write_measurement(
                measurements_dir / f"{case.task_id}.{route_id}.json",
                captured[route_id].measurement,
            )
            if captured[route_id].measurement["outcome"]["ok"]:
                measurements_ok += 1
            else:
                measurements_failed += 1

        record = record_observation(
            Task(case.task_id, case.kind, {}),
            [
                CandidateRoute(
                    "baseline",
                    ["fixture:baseline"],
                    estimated_cost=BASELINE_ESTIMATED_COST,
                    confidence=0.99,
                ),
                CandidateRoute(
                    "rule",
                    ["fixture:rule"],
                    estimated_cost=RULE_ESTIMATED_COST,
                    confidence=0.95,
                ),
            ],
            baseline_route_id="baseline",
            cost_unit=COST_UNIT,
            data_origin=DATA_ORIGIN,
            baseline_evidence=captured["baseline"].evidence,
            proposal_evidence=captured["rule"].evidence,
        )
        write_observation(observations_dir / f"{case.task_id}.json", record)
        status = compare_observation(record)["status"]
        statuses[status] = statuses.get(status, 0) + 1

    summary = {
        "cases": len(build_suite()),
        "measurements": measurements_ok + measurements_failed,
        "measurements_ok": measurements_ok,
        "measurements_failed": measurements_failed,
        "statuses": dict(sorted(statuses.items())),
        "cost_unit": COST_UNIT,
        "data_origin": DATA_ORIGIN,
        "environment": {
            "machine_id": environment.machine_id,
            "runtime_versions": dict(environment.runtime_versions),
        },
        "out_dir": str(out_dir),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("runs/fixtures"))
    arguments = parser.parse_args(argv)
    try:
        summary = run_suite(arguments.out)
    except FileExistsError as exc:
        print(
            f"refusing to overwrite existing records in {arguments.out}: {exc}",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
