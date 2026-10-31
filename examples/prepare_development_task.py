"""Prepare a local observation-only work packet from pinned development sources."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tiberium_ai.decision_json import canonical_json
from tiberium_ai.execution_profiles import ExecutionCatalog, content_digest
from tiberium_ai.registry import _reject_constant, _reject_duplicate_keys
from tiberium_ai.task_preparation import build_index, preparation_policy, prepare_task, render_packet

ROOT = Path(__file__).resolve().parents[1]


def read_json(path, limit=16777216):
    with Path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("JSON input exceeds read budget")
    return json.loads(data.decode("utf-8"), parse_constant=_reject_constant,
                      object_pairs_hook=_reject_duplicate_keys)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--constraint", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--engineering-skills-root", type=Path)
    parser.add_argument("--previous-index", type=Path)
    parser.add_argument("--policy", type=Path, help="Structured execution-profile policy JSON; --strict always strengthens it")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    output.relative_to((ROOT / "runs").resolve())
    if output.exists():
        raise FileExistsError("use a new output directory")
    policy = preparation_policy(read_json(args.policy, limit=65536) if args.policy else None,
                                strict=args.strict)
    inventory = read_json(args.inventory or ROOT / "examples/fixtures/development_capabilities.json", limit=262144)
    roots = {"workspace": ROOT}
    if args.engineering_skills_root is not None:
        roots["engineering"] = args.engineering_skills_root
    previous = read_json(args.previous_index) if args.previous_index else None
    index = build_index(inventory, roots, previous=previous)
    packet = prepare_task(args.goal, inventory, index, policy=policy, top_k=args.top_k, constraints=args.constraint)
    catalog = ExecutionCatalog(inventory["revision"], [e["profile"] for e in inventory["entries"]])
    artifacts = {"index.json": canonical_json(index), "packet.json": canonical_json(packet),
                 "catalog.json": canonical_json(catalog.to_record()), "packet.md": render_packet(packet)}
    output.mkdir(parents=True, exist_ok=False)
    for name, value in artifacts.items():
        (output / name).write_text(value, encoding="utf-8")
    manifest = {"schema_version": 1, "status": "complete", "auto_act_allowed": False,
                "artifacts": {name: content_digest((output / name).read_bytes()) for name in artifacts}}
    (output / "manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
    print(f"capabilities={len(packet['capabilities'])} review={len(packet['review_queue'])} files={len(packet['files'])} model_calls=0")
    print(f"index_built={index['metrics']['derived_built']} reused={index['metrics']['derived_reused']} status={packet['status']}")


if __name__ == "__main__":
    main()
