"""Export explicitly supplied observed turns for offline sequence replay.

Raw inputs are written only to the fresh caller-chosen directory. Source rows
are never printed. No route/model call, chat discovery or outcome generation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tiberium_ai.memory_capture import capture_rows
from tiberium_ai.memory_replay import read_jsonl


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", required=True, type=Path)
    parser.add_argument("--sequence-id", required=True)
    parser.add_argument("--origin", required=True, choices=("authored", "captured", "public"))
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--producer-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        capture = capture_rows(read_jsonl(args.turns), sequence_id=args.sequence_id, origin=args.origin,
                               source_ref=args.source_ref, producer_id=args.producer_id)
        manifest = capture.write(args.out)
    except FileExistsError:
        print("refusing to overwrite existing capture.", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError):
        print("cannot capture declared input; check its schema, versions and limits.", file=sys.stderr)
        return 2
    print(json.dumps({k: manifest[k] for k in ("turns", "facts", "usage_receipts", "outcomes",
                                               "production_saving_claim")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
