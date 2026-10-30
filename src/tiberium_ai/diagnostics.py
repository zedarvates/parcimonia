"""Explicit-file, offline entry point for consultative diagnostics.

Exit 0 means an analysis was produced, not that the project is correct or
feasible. Exit 2 means invalid input; exit 3 means analysis abstained.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .feasibility import diagnose
from .reduced_feasibility import diagnose_via_2sat
from .reductions import reduce_to_2cnf
from .stability import inspect_python_stability

MAX_INPUT_BYTES = 256 * 1024


def _read_input(path: str) -> str:
    # Read one caller-selected file only; never discover or import project code.
    with Path(path).open("rb") as stream:
        payload = stream.read(MAX_INPUT_BYTES + 1)
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError("input exceeds the 256 KiB limit")
    return payload.decode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    feasibility = commands.add_parser("feasibility", help="analyse a Boolean contract")
    feasibility.add_argument("input", help="explicit UTF-8 JSON request file")
    feasibility.add_argument("--max-variables", type=int, default=12)
    reduction = commands.add_parser("reduce", help="translate a Boolean contract into 2-CNF")
    reduction.add_argument("input", help="explicit UTF-8 JSON request file")
    reduction.add_argument("--with-observations", action="store_true")
    solve = commands.add_parser("solve", help="check a Boolean contract through 2-SAT")
    solve.add_argument("input", help="explicit UTF-8 JSON request file")
    stability = commands.add_parser("stability", help="inspect Python patterns without execution")
    stability.add_argument("input", help="explicit UTF-8 Python source file")
    stability.add_argument("--source-id", required=True)
    stability.add_argument("--revision", required=True)
    arguments = parser.parse_args(argv)
    try:
        source = _read_input(arguments.input)
        if arguments.command in {"feasibility", "reduce", "solve"}:
            request = json.loads(
                source, object_pairs_hook=_unique_object, parse_constant=_reject_constant
            )
            if arguments.command == "feasibility":
                report = diagnose(request, max_variables=arguments.max_variables)
                indeterminate = report["feasibility"] == "indeterminate"
            elif arguments.command == "reduce":
                report = reduce_to_2cnf(
                    request, include_observations=arguments.with_observations
                )
                indeterminate = report["status"] == "indeterminate"
            else:
                report = diagnose_via_2sat(request)
                indeterminate = report["feasibility"] == "indeterminate"
        else:
            report = inspect_python_stability(
                source, source_id=arguments.source_id, revision=arguments.revision
            )
            indeterminate = report["status"] == "indeterminate"
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
        # ASCII output also works with default Windows pipes.
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, ensure_ascii=True, allow_nan=False))
    return 3 if indeterminate else 0


if __name__ == "__main__":
    raise SystemExit(main())
