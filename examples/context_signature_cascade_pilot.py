"""Exercise context-before-inference and bounded fallback on authored fixtures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tiberium_ai.reflex import ReflexKind
from tiberium_ai.signature_cascade import SignatureCascadeBackend
from tiberium_ai.task_context import ContextContract, ContextField
from tiberium_ai.task_signature import DeclaredItem, SignatureSchema


class FixturePredictor:
    latin_only = False

    def __init__(self, kind="extract", probability=.95):
        self.kind, self.probability, self.calls = kind, probability, 0

    def evaluate(self, text, questions):
        self.calls += 1
        return {q.name: {"choice": self.kind, "confidence": None,
                    "probabilities": {key: self.probability if key == self.kind else 1-self.probability for key in q.option_keys}}
                if q.kind == ReflexKind.CHOICE else {"noul": .1, "probabilities": {"false": .9, "true": .1}}
                for q in questions}


def run_suite():
    schema = SignatureSchema("context-cascade-fixture", (DeclaredItem("extract"), DeclaredItem("verify")),
                             fields=(DeclaredItem("path"),))
    contract = ContextContract("extract.csv-columns", "1", "extract",
                              (ContextField("document", "Concrete CSV contents"),), ("document",))
    configurations = [
        ("missing-document", "extract", .95, "extract", .95, {"values": {}, "context_complete": True}, 1, "collect_context", 0),
        ("unobserved-document", "extract", .95, "extract", .95, {}, 1, "collect_context", 0),
        ("invalid-document", "extract", .95, "extract", .95, {"values": {"document": None}}, 1, "repair_context", 0),
        ("baseline-ready", "extract", .95, "extract", .95, {"values": {"document": "a,b\n1,2"}}, 1, "selected", 1),
        ("uncertain-baseline", "extract", .6, "extract", .95, {"values": {"document": "a,b\n1,2"}}, 1, "selected", 2),
        ("kind-mismatch", "verify", .95, "extract", .95, {"values": {"document": "a,b\n1,2"}}, 1, "selected", 2),
        ("uncertain-fallback", "extract", .6, "extract", .7, {"values": {"document": "a,b\n1,2"}}, 1, "abstained", 2),
        ("no-fallback-budget", "extract", .6, "extract", .95, {"values": {"document": "a,b\n1,2"}}, 0, "budget_exhausted", 1),
    ]
    rows = []
    for case_id, kind, probability, fallback_kind, fallback_probability, inputs, cap, expected, expected_calls in configurations:
        baseline, fallback = FixturePredictor(kind, probability), FixturePredictor(fallback_kind, fallback_probability)
        cascade = SignatureCascadeBackend(baseline, fallback, max_calls=1, max_fallback_calls=cap)
        result = cascade.propose_signature("récupère les colonnes de ce document", schema=schema, contract=contract,
            baseline_identity=("fixture.baseline", "1"), fallback_identity=("fixture.fallback", "1"),
            context_revision="fixture-snapshot-1", **inputs)
        if result.status != expected or result.backend_calls != expected_calls or baseline.calls + fallback.calls != expected_calls:
            raise ValueError("context cascade fixture did not match its declared expectation")
        rows.append({"case_id": case_id, "expected_status": expected, "baseline_calls": baseline.calls,
                     "fallback_calls": fallback.calls, "result": result.to_record()})
    return {"schema_version": 1, "kind": "context_signature_cascade_pilot", "data_origin": "fixture",
            "cases": rows, "claim_allowed": False, "model_inference_executed": False,
            "monetary_saving": None, "latency_scope": "not measured", "auto_act_allowed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_suite()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"cases": len(report["cases"]), "zero_backend_call_cases": sum(row["result"]["backend_calls"] == 0 for row in report["cases"]),
        "statuses": [row["result"]["status"] for row in report["cases"]], "claim_allowed": False,
        "model_inference_executed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
