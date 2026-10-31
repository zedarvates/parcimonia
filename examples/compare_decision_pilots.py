"""Compare captured pilot reports only when corpus, schema and questions match."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path


def compare(laya, jeff):
    for report in (laya, jeff):
        if report.get("data_origin") != "fixture" or report.get("claim_allowed") is not False or report.get("auto_act_allowed") is not False:
            raise ValueError("this comparison requires fixture shadow reports")
        corpus = json.dumps(report["evaluation_cases"], ensure_ascii=False, sort_keys=True).encode()
        if sha256(corpus).hexdigest() != report["corpus_sha256"]:
            raise ValueError("corpus hash mismatch")
    for key in ("corpus_sha256", "evaluation_cases", "schema", "training_case_ids"):
        if laya[key] != jeff[key]:
            raise ValueError("reports are not paired: " + key)
    def arm(report, name):
        rows = [a for a in report["arms"] if a["arm"] == name]
        if len(rows) != 1 or rows[0]["status"] != "ok":
            raise ValueError("required arm missing or unsuccessful: " + name)
        row = rows[0]
        if len(row["traces"]) != len(report["evaluation_cases"]) or any(t["status"] != "ok" for t in row["traces"]):
            raise ValueError("incomplete traces")
        return row
    frame = arm(jeff, "frame.verb-object")
    selected = [arm(jeff, "rule.keyword"), frame, arm(jeff, "knn.aligned"),
                arm(laya, "laya.sdk.multilingual@1"), arm(jeff, "jeff.sdk.qwen-0.8b@1")]
    reference = [(t["state_sha256"], t["questions"]) for t in frame["traces"]]
    for row in selected:
        if [(t["state_sha256"], t["questions"]) for t in row["traces"]] != reference:
            raise ValueError("question or state mismatch")
    summaries = [{k: a[k] for k in ("arm", "version", "kind_raw_correct", "kind_correct_and_covered",
                                   "kind_errors_or_abstentions", "kind_brier", "latency_ms", "metrics")}
                 for a in selected]
    # Reuse the captured choices only. This does not execute a composed route
    # and does not measure its latency, cost, fields or real-task outcome.
    threshold = jeff["schema"]["thresholds"]["kind"]
    cascade = []
    neural = selected[-1]
    for case, local, remote in zip(jeff["evaluation_cases"], frame["traces"], neural["traces"]):
        picked = local["answers"]["kind"]
        source = "frame.verb-object"
        if picked["probabilities"][picked["choice"]] < threshold:
            picked = remote["answers"]["kind"]
            source = neural["arm"]
        covered = picked["probabilities"][picked["choice"]] >= threshold
        cascade.append({"case_id": case["case_id"], "source": source,
                        "covered": covered, "correct_and_covered": covered and picked["choice"] == case["kind"]})
    return {"kind": "paired_decision_pilots", "data_origin": "fixture", "claim_allowed": False,
            "corpus_sha256": jeff["corpus_sha256"], "rows": summaries,
            "type_only_cascade_replay": {"executed": False, "latency_ms": None,
                                         "correct_and_covered": sum(r["correct_and_covered"] for r in cascade),
                                         "cases": cascade}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("laya", type=Path)
    parser.add_argument("jeff", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = compare(json.loads(args.laya.read_text(encoding="utf-8")),
                     json.loads(args.jeff.read_text(encoding="utf-8")))
    result["source_reports"] = [str(args.laya), str(args.jeff)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"paired": True, "output": str(args.output),
                      "cascade_replayed_correct_and_covered": result["type_only_cascade_replay"]["correct_and_covered"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
