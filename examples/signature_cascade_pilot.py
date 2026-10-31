"""Execute a frame/captured-model cascade on exactly paired fixture cases."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from local_decision_pilot import FRENCH_IDS, run_arm
from tiberium_ai.signature_backends import VerbFrameSignatureBackend
from tiberium_ai.signature_cascade import SignatureCascadeBackend
from tiberium_ai.signature_corpus import aligned_cases, example_schema, paraphrase_cases


class CapturedBackend:
    latin_only = False

    def __init__(self, traces):
        self.traces = {}
        for trace in traces:
            key = trace["state_sha256"]
            if key in self.traces or trace["status"] != "ok":
                raise ValueError("duplicate or unsuccessful captured trace")
            self.traces[key] = trace

    def evaluate(self, state_text, questions):
        key = sha256(state_text.encode()).hexdigest()
        trace = self.traces[key]
        if json.loads(json.dumps([asdict(q) for q in questions])) != trace["questions"]:
            raise ValueError("captured questions do not match")
        return trace["answers"]


def run_capture(report, model_arm):
    schema = example_schema()
    cases = tuple(c for c in paraphrase_cases() if c.case_id in FRENCH_IDS)
    evaluation = json.loads(json.dumps([asdict(c) for c in cases]))
    digest = sha256(json.dumps(evaluation, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if (report.get("data_origin") != "fixture"
            or report.get("claim_allowed") is not False
            or report.get("auto_act_allowed") is not False
            or report.get("evaluation_cases") != evaluation
            or report.get("corpus_sha256") != digest
            or report.get("schema") != schema.to_record()
            or report.get("training_case_ids") != [c.case_id for c in aligned_cases()]):
        raise ValueError("capture does not match the current fixture protocol")
    arms = [a for a in report["arms"] if a["arm"] == model_arm]
    if len(arms) != 1 or arms[0]["status"] != "ok":
        raise ValueError("captured model arm must be unique and successful")
    backend = CapturedBackend(arms[0]["traces"])
    if set(backend.traces) != {sha256(c.prompt.encode()).hexdigest() for c in cases}:
        raise ValueError("capture must cover exactly the evaluation cases")
    cascade = SignatureCascadeBackend(
        VerbFrameSignatureBackend(schema), backend,
        threshold=schema.min_kind_confidence,
        max_calls=len(cases), max_fallback_calls=len(cases),
    )
    row = run_arm("cascade.frame-captured-model", cascade, cases, schema, "1")
    baseline = run_arm("frame.verb-object", VerbFrameSignatureBackend(schema), cases, schema, "1")
    comparison = compare_rows(cases, baseline, row, schema.min_kind_confidence)
    fields = compare_fields(cases, baseline, row, schema.min_field_confidence)
    return {
        "kind": "signature_cascade_pilot", "data_origin": "fixture",
        "corpus_sha256": digest, "claim_allowed": False, "auto_act_allowed": False,
        "fallback_arm": model_arm, "model_inference_executed": False,
        "latency_scope": "local frame, validation and captured-response replay only",
        "calls": cascade.calls, "fallback_calls": cascade.fallback_calls,
        "result": row,
        "baseline": baseline,
        "paired_comparison": comparison,
        "paired_fields": fields,
    }


def compare_fields(cases, baseline, cascade, threshold):
    """Compare field heads on all cases, including those with an abstained kind.

    These are descriptor scores against authored labels, not extracted values.
    Including abstentions keeps fallback field errors visible.
    """
    compare_rows(cases, baseline, cascade, 0.9)
    rows = []
    totals = {name: {"true_positive": 0, "false_positive": 0, "false_negative": 0}
              for name in ("baseline", "cascade")}
    for case, before, after in zip(cases, baseline["traces"], cascade["traces"]):
        expected = set(case.fields)
        row = {"case_id": case.case_id, "expected": sorted(expected)}
        for name, trace in (("baseline", before), ("cascade", after)):
            predicted = {key.removeprefix("field.") for key, value in trace["answers"].items()
                         if key.startswith("field.") and value["noul"] >= threshold}
            values = {"predicted": sorted(predicted), "missing": sorted(expected - predicted),
                      "extra": sorted(predicted - expected)}
            row[name] = values
            totals[name]["true_positive"] += len(expected & predicted)
            totals[name]["false_positive"] += len(predicted - expected)
            totals[name]["false_negative"] += len(expected - predicted)
        rows.append(row)
    return {"scope": "all_case_field_heads_against_authored_labels",
            "threshold": threshold, "counts": totals, "cases": rows}


def compare_rows(cases, baseline, cascade, threshold):
    """Count actual accepted errors separately from abstentions on paired traces."""
    rows = []
    for arm in (baseline, cascade):
        if arm.get("status") != "ok" or len(arm["traces"]) != len(cases):
            raise ValueError("paired comparison requires complete successful traces")
    for case, before, after in zip(cases, baseline["traces"], cascade["traces"]):
        if before["state_sha256"] != after["state_sha256"] or before["questions"] != after["questions"]:
            raise ValueError("paired traces differ in state or questions")
        if before["state_sha256"] != sha256(case.prompt.encode()).hexdigest():
            raise ValueError("paired trace does not match its labelled case")
        outcomes = []
        for trace in (before, after):
            answer = trace["answers"]["kind"]
            covered = answer["probabilities"][answer["choice"]] >= threshold
            outcomes.append("abstained" if not covered else
                            "correct" if answer["choice"] == case.kind else "incorrect")
        rows.append({"case_id": case.case_id, "baseline": outcomes[0], "cascade": outcomes[1],
                     "route": after.get("cascade", {}).get("route")})
    return {
        "cases": rows,
        "improved": sum(r["baseline"] != "correct" and r["cascade"] == "correct" for r in rows),
        "regressed": sum(r["baseline"] == "correct" and r["cascade"] != "correct" for r in rows),
        "new_accepted_errors": sum(r["baseline"] != "incorrect" and r["cascade"] == "incorrect" for r in rows),
        "baseline_counts": {o: sum(r["baseline"] == o for r in rows) for o in ("correct", "incorrect", "abstained")},
        "cascade_counts": {o: sum(r["cascade"] == o for r in rows) for o in ("correct", "incorrect", "abstained")},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--arm", default="laya.sdk.multilingual@1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    capture_bytes = args.capture.read_bytes()
    result = run_capture(json.loads(capture_bytes.decode("utf-8")), args.arm)
    result["source_capture"] = {
        "path": str(args.capture),
        "sha256": sha256(capture_bytes).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": result["result"]["status"],
                      "calls": result["calls"], "fallback_calls": result["fallback_calls"],
                      "correct_and_covered": result["result"].get("kind_correct_and_covered")}))
    return 0 if result["result"]["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
