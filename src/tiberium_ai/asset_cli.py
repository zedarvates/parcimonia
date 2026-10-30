"""Explicit-file asset inspection and advisory catalogue search.

Exit 0 means a report was produced, 2 an input/read error, 3 indeterminate
inspection. Reports contain proposed tags; no source file is changed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
from typing import Sequence

from .asset_catalog import search_asset_reports
from .asset_inspection import MAX_SAMPLE_BYTES, _json_value, inspect_asset


def _signature(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_regular(path: str, maximum: int) -> tuple[bytes, int, bool]:
    """Read one regular file or prefix, refusing changes observed during read."""
    source = Path(path)
    before = source.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Only explicit regular files are supported; links and devices are refused.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(source, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or _signature(opened) != _signature(before):
            raise ValueError("Source changed before the read.")
        payload = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    if _signature(after) != _signature(opened) or _signature(source.lstat()) != _signature(opened):
        raise ValueError("Source changed during the read.")
    if len(payload) < min(opened.st_size, maximum + 1):
        raise ValueError("The source could not be read completely within its observed size.")
    return payload[:maximum], opened.st_size, opened.st_size <= maximum


def _read_json(path: str, maximum: int, *, max_nodes: int = 200_000):
    data, _, complete = _read_regular(path, maximum)
    if not complete:
        raise ValueError("JSON input exceeds the read budget.")
    return _json_value(data.decode("utf-8"), max_nodes=max_nodes)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="inspect one file without modifying it")
    inspect.add_argument("input")
    inspect.add_argument("--source-id", required=True)
    inspect.add_argument("--revision", required=True)
    inspect.add_argument("--topics", help="optional explicit JSON mapping of labels to literal terms")
    search = commands.add_parser("search", help="search an explicit JSON array of inspection reports")
    search.add_argument("input")
    search.add_argument("--tag", action="append", default=[])
    search.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    search.add_argument("--limit", type=int, default=50)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "inspect":
            data, total, complete = _read_regular(arguments.input, MAX_SAMPLE_BYTES)
            topics = _read_json(arguments.topics, 64 * 1024, max_nodes=4096) if arguments.topics else None
            report = inspect_asset(
                data, filename=Path(arguments.input).name,
                source_id=arguments.source_id, revision=arguments.revision,
                complete=complete, total_bytes=total, topic_terms=topics,
            )
            code = 3 if report["status"] == "indeterminate" else 0
        else:
            reports = _read_json(arguments.input, 16 * 1024 * 1024)
            report = search_asset_reports(reports, tags=arguments.tag, bbox=arguments.bbox, limit=arguments.limit)
            code = 0
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
