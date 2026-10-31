"""Read-only runtime and caller-machine diagnostic; no inference or repair.

Run on Eurekaï to inspect Eurekaï hardware. From another LAN machine, only
endpoint reachability is remote; hardware inventory still describes the caller.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tiberium_ai.local_probe import diagnose_local, write_diagnostic


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:1234")
    parser.add_argument("--allow-lan", action="store_true", help="Allow an explicit RFC1918/ULA IP.")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--disk-path", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True, help="New JSON file in an existing directory.")
    args = parser.parse_args(argv)
    if args.out.exists() or args.out.is_symlink():
        print("refusing to overwrite diagnostic", file=sys.stderr)
        return 2
    try:
        report = diagnose_local(
            args.base_url, allow_lan=args.allow_lan, timeout=args.timeout,
            disk_path=args.disk_path,
        )
        write_diagnostic(args.out, report)
    except (OSError, ValueError, TypeError):
        # Do not echo supplied URLs, credentials, paths, or subprocess errors.
        print("diagnostic configuration or output failed", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": report["endpoint"]["status"], "inference_ready": None,
        "inference_attempted": False, "saving_claim": False,
    }))
    return 0 if report["endpoint"]["status"] == "reachable" else 2


if __name__ == "__main__":
    raise SystemExit(main())
