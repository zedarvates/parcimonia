"""Demonstrate resource gates with injected fixture clocks and one local monotonic run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from tiberium_ai.cascade_resources import CascadeResourceControl, CostReceipt, StageEstimate
from tiberium_ai.decision_clock import DecisionBudget
from tiberium_ai.escalation import Budget
from tiberium_ai.measurement import Environment, write_measurement
from tiberium_ai.signature_cascade import SignatureCascadeBackend
from tiberium_ai.task_context import ContextContract, ContextField
from tiberium_ai.task_signature import DeclaredItem, SignatureSchema


class FixtureClock:
    def __init__(self): self.value = 0.0
    def __call__(self): return self.value


class FixturePredictor:
    latin_only = False
    def __init__(self, clock, probability=.95, duration_ms=4):
        self.clock, self.probability, self.duration_ms, self.calls = clock, probability, duration_ms, 0
    def evaluate(self, state, questions):
        self.calls += 1
        if isinstance(self.clock, FixtureClock):
            self.clock.value += self.duration_ms / 1000
        return {q.name: {"choice": "extract", "confidence": None,
            "probabilities": {"extract": self.probability, "verify": 1-self.probability}} for q in questions}


def run_suite():
    schema = SignatureSchema("resource-pilot", (DeclaredItem("extract"), DeclaredItem("verify")))
    contract = ContextContract("extract.fixture", "1", "extract", (ContextField("document", "Contents"),), ("document",))
    scenarios = [
        ("baseline-measured", {}, .95, 4, 4, "selected"),
        ("fallback-measured", {}, .6, 4, 4, "selected"),
        ("fallback-unpriced", {"fallback": StageEstimate(None, 5)}, .6, 4, 4, "abstained"),
        ("late-baseline", {"deadline": DecisionBudget(5)}, .95, 6, 4, "budget_exhausted"),
        ("fallback-estimate-too-slow", {"deadline": DecisionBudget(8)}, .6, 4, 4, "budget_exhausted"),
        ("late-fallback", {"deadline": DecisionBudget(10)}, .6, 4, 10, "budget_exhausted"),
        ("cost-unobserved", {"observe_cost": None}, .95, 4, 4, "abstained"),
        ("snapshot-age-unknown", {"deadline": DecisionBudget(100, max_state_age_ms=5)}, .95, 4, 4, "collect_context"),
    ]
    rows = []
    for case_id, overrides, probability, baseline_ms, fallback_ms, expected in scenarios:
        clock = FixtureClock()
        config = dict(budget=Budget(3, 1, 2, 100), deadline=DecisionBudget(100), baseline=StageEstimate(1, 5),
            fallback=StageEstimate(1, 5), cost_unit="fixture-unit", environment=Environment("injected-clock-fixture", {"clock": "synthetic"}),
            clock=clock, observe_cost=lambda role, backend: CostReceipt(1, "fixture-unit", "fixture-accounting"))
        resources = CascadeResourceControl(**{**config, **overrides})
        baseline, fallback = FixturePredictor(clock, probability, baseline_ms), FixturePredictor(clock, .95, fallback_ms)
        result = SignatureCascadeBackend(baseline, fallback).propose_signature("extraire le document", schema=schema, contract=contract,
            baseline_identity=("fixture.baseline", "1"), fallback_identity=("fixture.fallback", "1"),
            context_revision="fixture-snapshot", values={"document": "csv"}, resource_control=resources)
        if result.status != expected:
            raise ValueError("resource fixture did not match its declared expectation")
        rows.append({"case_id": case_id, "timing_source": "injected_synthetic_clock", "expected_status": expected,
                     "baseline_calls": baseline.calls, "fallback_calls": fallback.calls, "proposal": result.to_record()})
    # A real monotonic clock measures only a local fixture callback; no model is loaded.
    baseline, fallback = FixturePredictor(perf_counter), FixturePredictor(perf_counter)
    control = CascadeResourceControl(Budget(3, 1, 2, 1000), DecisionBudget(1000), StageEstimate(0, 10), StageEstimate(0, 10),
        "paid-provider-call-unit", Environment("local-fixture-runner", {"clock": "perf_counter"}), perf_counter,
        observe_cost=lambda role, backend: CostReceipt(0, "paid-provider-call-unit", "no-paid-provider-calls"))
    result = SignatureCascadeBackend(baseline, fallback).propose_signature("extraire le document", schema=schema, contract=contract,
        baseline_identity=("fixture.local", "1"), fallback_identity=("fixture.fallback", "1"), context_revision="local-fixture",
        values={"document": "csv"}, resource_control=control)
    rows.append({"case_id": "local-monotonic-callback", "timing_source": "real_perf_counter_fixture_only",
        "baseline_calls": baseline.calls, "fallback_calls": fallback.calls, "proposal": result.to_record()})
    return {"schema_version": 1, "kind": "resource_context_cascade_pilot", "data_origin": "fixture", "cases": rows,
        "model_inference_executed": False, "cost_savings": None, "quality_metrics": None, "claim_allowed": False,
        "clock_scope": "eight synthetic timing scenarios plus one local callback wall-clock measurement"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        raise FileExistsError("choose a new resource pilot directory")
    report = run_suite()
    args.output_dir.mkdir(parents=True)
    for row in report["cases"]:
        for i, measurement in enumerate(row["proposal"]["resource_trace"]["measurements"]):
            write_measurement(args.output_dir / f"{row['case_id']}-{i}.json", measurement)
    with (args.output_dir / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"cases": len(report["cases"]), "statuses": [row["proposal"]["status"] for row in report["cases"]],
        "measurements": sum(len(row["proposal"]["resource_trace"]["measurements"]) for row in report["cases"]),
        "model_inference_executed": False, "claim_allowed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
