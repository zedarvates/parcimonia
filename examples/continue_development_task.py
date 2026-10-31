"""Record file usefulness and prepare the next stage without executing it."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from tiberium_ai.decision_json import canonical_json
from tiberium_ai.execution_profiles import ExecutionCatalog, content_digest
from tiberium_ai.registry import _reject_constant, _reject_duplicate_keys
from tiberium_ai.task_followup import continue_task, record_file_review, render_followup
from tiberium_ai.task_preparation import build_index, preparation_policy

ROOT = Path(__file__).resolve().parents[1]


def read_json(path, limit=16777216):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("JSON exceeds read budget")
    return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant,
                      object_pairs_hook=_reject_duplicate_keys)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-packet", type=Path, required=True)
    review_input = parser.add_mutually_exclusive_group(required=True)
    review_input.add_argument("--feedback", type=Path, help="New explicit file-use observations")
    review_input.add_argument("--review", type=Path, help="Previously saved, source-bound file review")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--stage-id", required=True)
    parser.add_argument("--constraint", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--previous-index", type=Path)
    parser.add_argument("--engineering-skills-root", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    output.relative_to((ROOT / "runs").resolve())
    if output.exists():
        raise FileExistsError("use a new output directory")
    policy = preparation_policy(read_json(args.policy, 65536) if args.policy else None, strict=args.strict)
    roots = {"workspace": ROOT}
    if args.engineering_skills_root is not None:
        roots["engineering"] = args.engineering_skills_root
    packet = read_json(args.previous_packet)
    if args.review:
        review = read_json(args.review, 1048576)
    else:
        feedback = read_json(args.feedback, 131072)
        review = record_file_review(packet, feedback, roots=roots, at=datetime.now(timezone.utc).isoformat())
    inventory = read_json(args.inventory or ROOT / "examples/fixtures/development_capabilities.json", 262144)
    index = build_index(inventory, roots, previous=read_json(args.previous_index) if args.previous_index else None)
    continuation = continue_task(args.goal, inventory, index, previous_packet=packet, review=review,
        roots=roots, task_id=review["task_id"], stage_id=args.stage_id, policy=policy, constraints=args.constraint)
    catalog = ExecutionCatalog(inventory["revision"], [e["profile"] for e in inventory["entries"]])
    artifacts = {"file-review.json": canonical_json(review), "index.json": canonical_json(index),
                 "packet.json": canonical_json(continuation), "packet.md": render_followup(continuation),
                 "catalog.json": canonical_json(catalog.to_record())}
    output.mkdir(parents=True, exist_ok=False)
    for name, text in artifacts.items():
        (output / name).write_text(text, encoding="utf-8")
    manifest = {"schema_version": 1, "status": "complete", "auto_act_allowed": False,
        "artifacts": {name: content_digest((output / name).read_bytes()) for name in artifacts}}
    (output / "manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
    metrics = continuation["continuity"]["metrics"]
    print(f"unchanged={metrics['unchanged_useful_references']} changed={metrics['changed_useful_references']} unavailable={metrics['unavailable_useful_references']}")
    print(f"missing_existing={review['metrics']['pre_existing_useful_files_missing']} created={review['metrics']['useful_files_created_during_task']} auto_act_allowed=false")


if __name__ == "__main__":
    main()
