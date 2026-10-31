"""Validate an actual source review and prepare a grouped comparison; no inference."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tiberium_ai.agent_recipes.source_review import apply_source_review, source_comparison_readiness

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    output.relative_to((ROOT / "runs").resolve())
    if output.exists():
        raise FileExistsError("choose a new finalization directory")
    packet = json.loads(args.packet.read_text(encoding="utf-8"))
    review = json.loads(args.review.read_text(encoding="utf-8"))
    result = apply_source_review(packet, review, require_complete=not args.allow_partial)
    readiness = source_comparison_readiness(result)
    output.mkdir(parents=True, exist_ok=False)
    for name, data in (("reviewed-packet.json", result), ("comparison-readiness.json", readiness)):
        with (output / name).open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(readiness, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
