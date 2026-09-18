import json
import subprocess
import sys
from pathlib import Path

import pytest

from tiberium_ai.benchmark import (
    BenchmarkCase,
    BenchmarkRoute,
    BenchmarkSplit,
    CaseResult,
    build_report,
    run_benchmark,
    split_cases,
)
from tiberium_ai.contracts import Task
from tiberium_ai.measurement import Environment
from tiberium_ai.resources import ResourceVector
from tiberium_ai.verification import exact_match_verifier

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "examples" / "benchmark_suite.py"


def case(index, *, candidate_fails=False):
    size = 10 * index
    expected = {"total": size * (size - 1) // 2}

    def candidate(size=size):
        if candidate_fails:
            raise ValueError("fixture failure")
        return {"total": size * (size - 1) // 2}

    return BenchmarkCase(
        task=Task(f"case-{index:03d}", "arithmetic", {}),
        routes=(
            BenchmarkRoute(
                "baseline",
                lambda size=size: {"total": sum(range(size))},
                estimated_cost=1.0,
                confidence=0.99,
            ),
            BenchmarkRoute("rule", candidate, estimated_cost=0.01, confidence=0.95),
        ),
        verifier_id="arithmetic/exact",
        verifier_version=f"size={size}",
        verifier=exact_match_verifier(expected),
        baseline_route_id="baseline",
    )


def result(
    task_id,
    split,
    *,
    candidate_verdict=True,
    baseline_verdict=True,
    candidate_latency=10.0,
    baseline_latency=100.0,
    status="verified_without_measurements",
):
    return CaseResult(
        task_id=task_id,
        split=split,
        status=status,
        verdicts={"baseline": baseline_verdict, "rule": candidate_verdict},
        vectors={
            "baseline": ResourceVector(latency_ms=baseline_latency),
            "rule": ResourceVector(latency_ms=candidate_latency),
        },
        ok={"baseline": True, "rule": candidate_verdict is not None},
    )


def report(results, *, split=BenchmarkSplit(("a",), ("b", "c"))):
    return build_report(
        results,
        seed=7,
        split=split,
        environment=Environment("test-machine", {"python": "3.14.0"}),
        corpus="fixture",
        baseline_route_id="baseline",
    )


def test_split_partitions_cases_deterministically():
    cases = [case(index) for index in range(1, 11)]
    first = split_cases(cases, seed=42, heldout_fraction=0.3)
    second = split_cases(list(reversed(cases)), seed=42, heldout_fraction=0.3)
    assert first == second
    assert first.development and first.heldout
    assert set(first.development) | set(first.heldout) == {c.task.task_id for c in cases}
    assert set(first.development) & set(first.heldout) == set()
    assert first.development == tuple(sorted(first.development))
    assert first.heldout == tuple(sorted(first.heldout))


@pytest.mark.parametrize("overrides", [
    {"seed": -1}, {"seed": True}, {"heldout_fraction": 0}, {"heldout_fraction": 1},
])
def test_split_validation(overrides):
    arguments = {"seed": 7, "heldout_fraction": 0.3}
    arguments.update(overrides)
    with pytest.raises(ValueError):
        split_cases([case(1), case(2)], **arguments)


def test_split_rejects_duplicate_task_ids():
    with pytest.raises(ValueError, match="duplicate"):
        split_cases([case(1), case(1)], seed=1)


def test_claim_is_allowed_when_verified_and_dominant():
    results = [result("a", "development"), result("b", "heldout"), result("c", "heldout")]
    claim = report(results)["claim"]
    assert claim["status"] == "allowed"
    assert claim["reason_code"] == "verified_dominance"
    assert claim["candidate"] == "rule"
    assert claim["baseline"] == "baseline"


def test_claim_is_refused_after_a_quality_regression():
    results = [
        result("b", "heldout", candidate_verdict=True),
        result("c", "heldout", candidate_verdict=False, status="verification_failed"),
    ]
    claim = report(results)["claim"]
    assert claim["status"] == "refused"
    assert claim["reason_code"] == "quality_regression"


def test_claim_is_refused_without_evidence():
    results = [
        result("b", "heldout", candidate_verdict=True),
        result("c", "heldout", candidate_verdict=None, status="insufficient_evidence"),
    ]
    claim = report(results)["claim"]
    assert claim["status"] == "refused"
    assert claim["reason_code"] == "insufficient_evidence"


def test_claim_is_refused_without_dominance():
    results = [
        result("b", "heldout", candidate_latency=200.0),
        result("c", "heldout", candidate_latency=300.0),
    ]
    claim = report(results)["claim"]
    assert claim["status"] == "refused"
    assert claim["reason_code"] == "no_dominance"


def test_claim_is_refused_when_no_held_out_case_exists():
    results = [result("a", "development")]
    claim = report(results, split=BenchmarkSplit(("a",), ("b",)))["claim"]
    assert claim["status"] == "refused"
    assert claim["reason_code"] == "insufficient_evidence"


def test_report_contains_every_case_environment_and_pareto_front():
    results = [result("a", "development"), result("b", "heldout")]
    built = report(results)
    assert [entry["task_id"] for entry in built["cases"]] == ["a", "b"]
    assert built["cases"][1]["split"] == "heldout"
    assert built["environment"] == {
        "machine_id": "test-machine",
        "runtime_versions": {"python": "3.14.0"},
    }
    assert built["corpus"] == "fixture"
    assert built["pareto"] == ["rule"]
    assert built["routes"]["rule"]["heldout_median_latency_ms"] == 10.0
    assert built["routes"]["baseline"]["runs"] == 2


def test_case_requires_exactly_two_routes_with_a_declared_baseline():
    with pytest.raises(ValueError, match="two routes"):
        BenchmarkCase(
            task=Task("t", "arithmetic", {}),
            routes=(BenchmarkRoute("baseline", lambda: None),),
            verifier_id="v",
            verifier_version="1",
            verifier=lambda value: True,
            baseline_route_id="baseline",
        )
    with pytest.raises(ValueError, match="baseline"):
        BenchmarkCase(
            task=Task("t", "arithmetic", {}),
            routes=(
                BenchmarkRoute("one", lambda: None),
                BenchmarkRoute("two", lambda: None),
            ),
            verifier_id="v",
            verifier_version="1",
            verifier=lambda value: True,
            baseline_route_id="absent",
        )


def test_harness_writes_records_and_reports_a_failing_route(tmp_path):
    cases = [case(index, candidate_fails=index == 4) for index in range(1, 7)]
    built = run_benchmark(
        cases,
        out_dir=tmp_path,
        seed=3,
        environment=Environment("bench-machine", {"python": "3.14.0"}),
        clock=__import__("time").perf_counter,
        cost_unit="synthetic-unit/task",
        corpus="fixture",
    )
    measurements = sorted((tmp_path / "measurements").glob("*.json"))
    observations = sorted((tmp_path / "observations").glob("*.json"))
    assert len(measurements) == 12
    assert len(observations) == 6
    assert (tmp_path / "report.json").is_file()
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["seed"] == 3
    statuses = {entry["status"] for entry in built["cases"]}
    assert "insufficient_evidence" in statuses
    assert built["claim"]["status"] in {"allowed", "refused"}
    assert built["routes"]["rule"]["failed"] == 1


def test_benchmark_suite_script_produces_a_report(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["corpus"] == "fixture"
    assert len(report["cases"]) == 20
    assert len(report["split"]["heldout"]) >= 1
    statuses = {entry["status"] for entry in report["cases"]}
    assert "verification_failed" in statuses
    assert "insufficient_evidence" in statuses
    assert report["claim"]["reason_code"] in {
        "quality_regression", "insufficient_evidence", "no_dominance", "verified_dominance",
    }
