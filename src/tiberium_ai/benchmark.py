"""Benchmark harness: split, run, report, and refuse unearned claims.

Every run is measured and verified through the normal path, so a report cites
measurement records instead of estimates. A resource claim is only allowed when
every held-out case was verified and the candidate dominates the baseline on the
median measured vector; a quality regression blocks the claim outright.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .capture import capture_run
from .contracts import CandidateRoute, Task
from .measurement import Environment, write_measurement
from .observations import compare_observation, record_observation, write_observation
from .resources import ResourceVector, pareto_front
from .router import ShadowRouter, is_nonnegative_number
from .verification import VerifierRegistry

__all__ = [
    "BenchmarkCase",
    "BenchmarkRoute",
    "BenchmarkSplit",
    "CaseResult",
    "build_report",
    "run_benchmark",
    "split_cases",
]

REPORT_SCHEMA_VERSION = 1
_CLAIM_SEVERITY = {
    "quality_regression": 0,
    "insufficient_evidence": 1,
    "no_dominance": 2,
}


def _is_trimmed_nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


@dataclass(frozen=True)
class BenchmarkRoute:
    route_id: str
    run: Callable[[], Any]
    estimated_cost: float | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not _is_trimmed_nonempty(self.route_id):
            raise ValueError("route_id must be a nonempty, trimmed string.")
        if not callable(self.run):
            raise TypeError("run must be callable.")
        if self.estimated_cost is not None and not is_nonnegative_number(
            self.estimated_cost
        ):
            raise ValueError("estimated_cost must be null or a finite nonnegative number.")
        if self.confidence is not None and (
            not is_nonnegative_number(self.confidence) or self.confidence > 1
        ):
            raise ValueError("confidence must be null or in [0, 1].")


@dataclass(frozen=True)
class BenchmarkCase:
    """One task compared between exactly two routes: baseline and candidate."""

    task: Task
    routes: tuple[BenchmarkRoute, ...]
    verifier_id: str
    verifier_version: str
    verifier: Callable[[Any], bool]
    baseline_route_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.task, Task):
            raise TypeError("task must be a Task instance.")
        if not isinstance(self.routes, tuple) or len(self.routes) != 2:
            raise ValueError("a benchmark case compares exactly two routes.")
        if not all(isinstance(route, BenchmarkRoute) for route in self.routes):
            raise TypeError("routes must contain BenchmarkRoute instances.")
        identifiers = [route.route_id for route in self.routes]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("route ids must be unique inside a case.")
        if self.baseline_route_id not in identifiers:
            raise ValueError("baseline_route_id must name one of the two routes.")
        if not _is_trimmed_nonempty(self.verifier_id) or not _is_trimmed_nonempty(
            self.verifier_version
        ):
            raise ValueError("verifier_id and verifier_version must be nonempty strings.")
        if not callable(self.verifier):
            raise TypeError("verifier must be callable.")

    @property
    def candidate_route_id(self) -> str:
        return next(
            route.route_id
            for route in self.routes
            if route.route_id != self.baseline_route_id
        )


@dataclass(frozen=True)
class BenchmarkSplit:
    development: tuple[str, ...]
    heldout: tuple[str, ...]


@dataclass(frozen=True)
class CaseResult:
    task_id: str
    split: str
    status: str
    verdicts: Mapping[str, bool | None]
    vectors: Mapping[str, ResourceVector]
    ok: Mapping[str, bool]


def split_cases(
    cases: Sequence[BenchmarkCase], *, seed: int, heldout_fraction: float = 0.3
) -> BenchmarkSplit:
    """Split task ids into development and held-out sets, reproducibly."""
    cases = list(cases)
    if not cases:
        raise ValueError("at least one case is required.")
    identifiers = [case.task.task_id for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate task ids are not allowed.")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer.")
    if not isinstance(heldout_fraction, (int, float)) or isinstance(
        heldout_fraction, bool
    ):
        raise ValueError("heldout_fraction must be a number strictly between 0 and 1.")
    if not 0 < heldout_fraction < 1:
        raise ValueError("heldout_fraction must be strictly between 0 and 1.")

    shuffled = sorted(identifiers)
    random.Random(seed).shuffle(shuffled)
    heldout_count = max(1, round(len(shuffled) * heldout_fraction))
    heldout_count = min(heldout_count, len(shuffled) - 1)
    return BenchmarkSplit(
        development=tuple(sorted(shuffled[heldout_count:])),
        heldout=tuple(sorted(shuffled[:heldout_count])),
    )


def build_report(
    results: Sequence[CaseResult],
    *,
    seed: int,
    split: BenchmarkSplit,
    environment: Environment,
    corpus: str,
    baseline_route_id: str,
) -> dict[str, Any]:
    """Summarise results and decide whether a saving claim is allowed."""
    results = list(results)
    if not results:
        raise ValueError("at least one case result is required.")
    if not isinstance(environment, Environment):
        raise TypeError("environment must be an Environment instance.")
    if not isinstance(split, BenchmarkSplit):
        raise TypeError("split must be a BenchmarkSplit instance.")
    if not _is_trimmed_nonempty(corpus):
        raise ValueError("corpus must be a nonempty, trimmed string.")

    route_ids = sorted({route for result in results for route in result.verdicts})
    if baseline_route_id not in route_ids:
        raise ValueError("baseline_route_id must appear in the results.")
    heldout = [result for result in results if result.split == "heldout"]
    vectors = {
        route_id: ResourceVector(
            latency_ms=_median(
                [
                    result.vectors[route_id].latency_ms
                    for result in heldout
                    if route_id in result.vectors
                    and result.vectors[route_id].latency_ms is not None
                ]
            )
        )
        for route_id in route_ids
    }
    routes = {
        route_id: {
            "runs": sum(1 for result in results if route_id in result.verdicts),
            "ok": sum(1 for result in results if result.ok.get(route_id) is True),
            "failed": sum(1 for result in results if result.ok.get(route_id) is False),
            "accepted": sum(1 for result in results if result.verdicts.get(route_id) is True),
            "rejected": sum(1 for result in results if result.verdicts.get(route_id) is False),
            "no_verdict": sum(
                1
                for result in results
                if route_id in result.verdicts and result.verdicts.get(route_id) is None
            ),
            "heldout_median_latency_ms": vectors[route_id].latency_ms,
        }
        for route_id in route_ids
    }
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "corpus": corpus,
        "seed": seed,
        "split": {
            "development": list(split.development),
            "heldout": list(split.heldout),
        },
        "environment": {
            "machine_id": environment.machine_id,
            "runtime_versions": dict(environment.runtime_versions),
        },
        "routes": routes,
        "pareto": list(pareto_front(vectors)),
        "cases": [
            {"task_id": result.task_id, "split": result.split, "status": result.status}
            for result in results
        ],
        "claim": _claim(results, vectors, baseline_route_id),
    }


def run_benchmark(
    cases: Sequence[BenchmarkCase],
    *,
    out_dir: str | Path,
    seed: int,
    environment: Environment,
    clock: Callable[[], float],
    cost_unit: str,
    corpus: str = "declared",
    heldout_fraction: float = 0.3,
    min_confidence: float = 0.9,
    now: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Execute every case on both routes, store the records and write a report."""
    cases = list(cases)
    split = split_cases(cases, seed=seed, heldout_fraction=heldout_fraction)
    baseline_ids = {case.baseline_route_id for case in cases}
    if len(baseline_ids) != 1:
        raise ValueError("every case must declare the same baseline_route_id.")
    baseline_route_id = baseline_ids.pop()
    by_id = {case.task.task_id: case for case in cases}

    registry = VerifierRegistry()
    for case in cases:
        registry.register(case.verifier_id, case.verifier_version, case.verifier)

    out_dir = Path(out_dir)
    measurements_dir = out_dir / "measurements"
    observations_dir = out_dir / "observations"
    measurements_dir.mkdir(parents=True, exist_ok=True)
    observations_dir.mkdir(parents=True, exist_ok=True)

    results: list[CaseResult] = []
    for case_id in [*split.development, *split.heldout]:
        case = by_id[case_id]
        captured = {}
        for route in case.routes:
            captured[route.route_id] = capture_run(
                task_id=case_id,
                route_id=route.route_id,
                run=route.run,
                verifier_id=case.verifier_id,
                verifier_version=case.verifier_version,
                registry=registry,
                cost_unit=cost_unit,
                environment=environment,
                clock=clock,
                now=now,
            )
            write_measurement(
                measurements_dir / f"{case_id}.{route.route_id}.json",
                captured[route.route_id].measurement,
            )

        candidates = [
            CandidateRoute(
                route.route_id,
                [f"capability:{route.route_id}"],
                route.estimated_cost,
                None,
                route.confidence,
            )
            for route in case.routes
        ]
        decision = ShadowRouter(min_confidence=min_confidence).propose(
            case.task, candidates
        )
        selected = None if decision.abstained else decision.selected_route_id
        record = record_observation(
            case.task,
            candidates,
            baseline_route_id=baseline_route_id,
            cost_unit=cost_unit,
            data_origin="synthetic",
            min_confidence=min_confidence,
            baseline_evidence=captured[baseline_route_id].evidence,
            proposal_evidence=(
                None if selected is None else captured[selected].evidence
            ),
        )
        write_observation(observations_dir / f"{case_id}.json", record)
        results.append(
            CaseResult(
                task_id=case_id,
                split="heldout" if case_id in split.heldout else "development",
                status=compare_observation(record)["status"],
                verdicts={
                    route.route_id: (
                        None
                        if captured[route.route_id].verification is None
                        else captured[route.route_id].verification.verdict
                    )
                    for route in case.routes
                },
                vectors={
                    route.route_id: ResourceVector.from_measurement(
                        captured[route.route_id].measurement
                    )
                    for route in case.routes
                },
                ok={
                    route.route_id: captured[route.route_id].measurement["outcome"]["ok"]
                    for route in case.routes
                },
            )
        )

    report = build_report(
        results,
        seed=seed,
        split=split,
        environment=environment,
        corpus=corpus,
        baseline_route_id=baseline_route_id,
    )
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _claim(
    results: Sequence[CaseResult],
    vectors: Mapping[str, ResourceVector],
    baseline_route_id: str,
) -> dict[str, Any]:
    heldout = [result for result in results if result.split == "heldout"]
    candidates = sorted(
        route_id for route_id in vectors if route_id != baseline_route_id
    )
    if not heldout:
        return {
            "status": "refused",
            "reason_code": "insufficient_evidence",
            "candidate": None,
            "baseline": baseline_route_id,
            "detail": "No held-out case was measured, so no claim can be made.",
        }

    refused: tuple[str, str] | None = None
    for candidate in candidates:
        reasons: set[str] = set()
        for result in heldout:
            if result.verdicts.get(candidate) is False:
                reasons.add("quality_regression")
            elif (
                result.verdicts.get(candidate) is not True
                or result.verdicts.get(baseline_route_id) is not True
            ):
                reasons.add("insufficient_evidence")
        if not reasons and not vectors[candidate].dominates(vectors[baseline_route_id]):
            reasons.add("no_dominance")
        if not reasons:
            return {
                "status": "allowed",
                "reason_code": "verified_dominance",
                "candidate": candidate,
                "baseline": baseline_route_id,
                "detail": (
                    f"{candidate} was verified on every held-out case and dominates "
                    f"{baseline_route_id} on the median measured vector."
                ),
            }
        reason = min(reasons, key=lambda item: _CLAIM_SEVERITY[item])
        if refused is None or _CLAIM_SEVERITY[reason] < _CLAIM_SEVERITY[refused[0]]:
            refused = (reason, candidate)

    if refused is None:
        return {
            "status": "refused",
            "reason_code": "no_candidate",
            "candidate": None,
            "baseline": baseline_route_id,
            "detail": "No candidate route was declared.",
        }
    reason, candidate = refused
    details = {
        "quality_regression": "a held-out case failed verification",
        "insufficient_evidence": "a held-out case carries no verdict",
        "no_dominance": "the median measured vector does not dominate the baseline",
    }
    return {
        "status": "refused",
        "reason_code": reason,
        "candidate": candidate,
        "baseline": baseline_route_id,
        "detail": f"Claim refused for {candidate}: {details[reason]}.",
    }


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2
