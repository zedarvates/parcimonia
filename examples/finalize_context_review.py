"""Validate an exported human review and freeze its grouped split when complete."""
import argparse
import json
from pathlib import Path

from tiberium_ai.context_annotations import apply_context_review

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.relative_to((ROOT / "runs").resolve())
    packet = json.loads(args.packet.read_text(encoding="utf-8"))
    review = json.loads(args.review.read_text(encoding="utf-8"))
    result = apply_context_review(packet, review, require_complete=not args.draft)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({k: result[k] for k in ("reviewed_cases", "pending_cases", "labelled_cases", "split_status", "claim_allowed")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
