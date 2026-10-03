"""Replay explicit local sequence/archive/outcome JSONL files in shadow mode.

No automatic trace discovery or model call. Source and outcome declarations are
preserved; missing or dependent outcomes produce no quality verdict.

python examples/memory_replay.py --sequences /path/sequences.jsonl \
    --archive /path/facts.jsonl --outcomes /path/outcomes.jsonl --out runs/memory-replay
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from time import perf_counter

from tiberium_ai.benchmark import run_benchmark
from tiberium_ai.measurement import Environment
from tiberium_ai.memory_replay import VARIANTS, VersionedFactArchive, build_memory_replay_cases, read_jsonl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequences", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--outcomes", type=Path)
    parser.add_argument("--out", type=Path, default=Path("runs/memory-replay"))
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--cost-margin", type=float, default=0.0)
    parser.add_argument("--max-holds", type=int, default=3)
    args = parser.parse_args(argv)
    outputs = {}
    try:
        archive = VersionedFactArchive(read_jsonl(args.archive, allow_empty=True))
        cases, provenance = build_memory_replay_cases(
            read_jsonl(args.sequences), archive,
            outcomes=() if args.outcomes is None else read_jsonl(args.outcomes),
            relative_cost_margin=args.cost_margin, max_holds=args.max_holds, outputs=outputs,
        )
        report = run_benchmark(cases, out_dir=args.out, seed=args.seed,
                               environment=Environment("offline-memory-replay", {"python": platform.python_version()}),
                               clock=perf_counter, cost_unit="unmeasured-provider-unit",
                               corpus="memory-sequences:" + provenance["sequence_revision"])
    except FileExistsError:
        print("refusing to overwrite existing replay evidence.", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Do not expose source contents, task payloads or local paths.
        detail = str(exc) if isinstance(exc, (ValueError, TypeError)) else type(exc).__name__
        print("cannot import/replay declared files: " + detail, file=sys.stderr)
        return 2
    modules = ("benchmark", "memory_replay", "compact_memory", "context_router", "verification")
    provenance["files_sha256"] = {
        "tiberium_ai." + name: hashlib.sha256(Path(sys.modules["tiberium_ai." + name].__file__).read_bytes()).hexdigest()
        for name in modules
    }
    provenance["files_sha256"]["memory_replay_cli"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    totals = {}
    for variant in VARIANTS:
        metrics = [v[variant]["metrics"] for v in outputs.values() if variant in v]
        complete = len(metrics) == len(cases)
        totals[variant] = {
            "completed_sequences": len(metrics), "requested_sequences": len(cases),
            "prepared_context_utf8_bytes": sum(m["prepared_context_utf8_bytes"] for m in metrics) if complete else None,
            "route_switches_including_abstentions": sum(m["route_switches_including_abstentions"] for m in metrics) if complete else None,
            "tokens": None, "provider_cost": None,
        }
    report.update(memory_replay=provenance, context_totals=totals)
    (args.out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"sequences": len(cases), "variants": {
        v: {"accepted": report["routes"][v]["accepted"], "no_verdict": report["routes"][v]["no_verdict"],
            "failed": report["routes"][v]["failed"], **totals[v]} for v in VARIANTS
    }, "production_saving_claim": provenance["production_saving_claim"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
