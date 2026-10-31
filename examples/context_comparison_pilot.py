"""Audit captured inputs and prepare an unscored, paired comparison gate."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from tiberium_ai.context_comparison import assess_context_comparison
from tiberium_ai.context_input_audit import audit_context_inputs, isolate_context_candidates
from tiberium_ai.context_review_ui import render_context_review
from tiberium_ai.route_experiment import ArmAvailability, ExperimentArm

ROOT = Path(__file__).resolve().parents[1]


def prepare(packet):
    audit = audit_context_inputs(packet)
    candidate_packet = isolate_context_candidates(packet, audit)
    arms = (ExperimentArm("frame.baseline", ("frame",), ArmAvailability.READY, "frame.verb-object", "1"),
            ExperimentArm("cascade.candidate", ("frame", "typed-fallback"), ArmAvailability.UNAVAILABLE))
    readiness = assess_context_comparison(candidate_packet, arms, baseline_arm_id="frame.baseline")
    quarantined = {row["case_id"] for row in audit["cases"] if row["disposition"] == "quarantine"}
    quarantine = {"schema_version": 1, "kind": "context_input_quarantine", "parent_pack_id": packet["pack_id"],
        "audit_version": audit["audit_version"], "cases": [case for case in packet["cases"] if case["case_id"] in quarantined],
        "decisions": [row for row in audit["cases"] if row["case_id"] in quarantined],
        "labels_created": 0, "auto_act_allowed": False}
    return audit, candidate_packet, quarantine, readiness


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    output.relative_to((ROOT / "runs").resolve())
    names = ("input-audit.json", "review-packet.json", "quarantine.json", "comparison-readiness.json", "review.html", "manifest.json")
    if any((output / name).exists() for name in names):
        raise FileExistsError("output exists; use a new audit directory")
    data = args.packet.read_bytes()
    packet = json.loads(data.decode("utf-8"))
    audit, candidates, quarantine, readiness = prepare(packet)
    output.mkdir(parents=True, exist_ok=True)
    for name, value in zip(names[:4], (audit, candidates, quarantine, readiness)):
        with (output / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with (output / "review.html").open("x", encoding="utf-8") as stream:
        stream.write(render_context_review(candidates))
    manifest = {"parent_file_sha256": sha256(data).hexdigest(), "parent_pack_id": packet["pack_id"],
        "files": {name: sha256((output / name).read_bytes()).hexdigest() for name in names[:-1]},
        "source_cases": len(packet["cases"]), "candidate_cases": len(candidates["cases"]),
        "quarantined_cases": len(quarantine["cases"]), "labels_created": 0,
        "quality_metrics": None, "model_inference_executed": False, "claim_allowed": False}
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
    print(json.dumps({"candidates": manifest["candidate_cases"], "quarantined": manifest["quarantined_cases"],
        "labels_created": 0, "kind_capture_ready": readiness["kind_capture_ready"], "reason_codes": readiness["reason_codes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
