"""Explicit private-file knowledge snapshots and lexical candidates.

Inputs contain untrusted data, including any remembered instructions. No remote
source, model, wiki sync or execution route is activated. Exit 0 means a scoped
report was produced, not that coverage or a proposed relationship was verified.
Exit 2 means invalid input, unavailable input or a refused write.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Sequence

from .asset_inspection import _json_value
from .knowledge_crosswalk import (
    MAX_INDEX_BYTES, UPDATE_SCHEMA, create_knowledge_index,
    find_knowledge_candidates, update_knowledge_index,
)


def _signature(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_json(path: str) -> Any:
    source = Path(path)
    before = source.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_INDEX_BYTES:
        raise ValueError("Input must be a regular non-link file within 2 MiB.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(source, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or _signature(opened) != _signature(before):
            raise ValueError("Input changed before read.")
        data = stream.read(MAX_INDEX_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (
        len(data) > MAX_INDEX_BYTES or len(data) != opened.st_size
        or _signature(after) != _signature(opened)
        or _signature(source.lstat()) != _signature(opened)
    ):
        raise ValueError("Input changed during read or exceeds the read budget.")
    return _json_value(data.decode("utf-8"), max_nodes=200_000)


def _encoded(value: Any) -> bytes:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(payload) > MAX_INDEX_BYTES:
        raise ValueError("Serialized output exceeds 2 MiB.")
    return payload


def _write_new(path: str, value: Any) -> None:
    payload = _encoded(value)
    # Windows O_EXCL can follow a dangling symlink. lstat observes the link
    # itself and refuses every existing final directory entry before opening.
    # Keep O_EXCL too; these checks do not sandbox a hostile directory owner.
    try:
        Path(path).lstat()
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError("Output path already exists, including a dangling link.")
    # Mode 0600 is advisory on Windows; the caller owns the directory/ACL.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    created = None
    try:
        created = os.fstat(descriptor)
        stream = os.fdopen(descriptor, "wb")
        descriptor = None  # the stream now owns the descriptor
        with stream:
            if stream.write(payload) != len(payload):
                raise OSError("Incomplete output write.")
    except BaseException:
        # Close before removal for Windows. Do not remove another file or link
        # observed at this path after a concurrent replacement. The caller owns
        # the directory; this observation is not a hostile-directory sandbox.
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if created is not None:
            try:
                current = Path(path).lstat()
                if (stat.S_ISREG(current.st_mode)
                        and (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino)):
                    Path(path).unlink()
            except OSError:
                pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Create an empty index value")
    create.add_argument("index_id")
    create.add_argument("--out")
    update = commands.add_parser("update", help="Apply a versioned explicit fragment batch")
    update.add_argument("index")
    update.add_argument("batch")
    update.add_argument("--expected-head", required=True)
    update.add_argument("--out", required=True)
    candidates = commands.add_parser("candidates", help="Read lexical candidates across feeds/projects")
    candidates.add_argument("index")
    candidates.add_argument("--fragment-id", required=True)
    candidates.add_argument("--limit", type=int, default=5)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "create":
            report = create_knowledge_index(arguments.index_id)
            if arguments.out:
                _write_new(arguments.out, report)
                report = {"index_hash": report["index_hash"], "write": "created", "output": arguments.out}
        elif arguments.command == "update":
            snapshot = _read_json(arguments.index)
            batch = _read_json(arguments.batch)
            if (
                type(batch) is not dict
                or set(batch) != {"schema", "upserts", "removals", "coverage"}
                or type(batch["schema"]) is not str or batch["schema"] != UPDATE_SCHEMA
            ):
                raise ValueError("Unsupported or malformed knowledge-update batch.")
            result = update_knowledge_index(
                snapshot, upserts=batch["upserts"], removals=batch["removals"],
                coverage=batch["coverage"], expected_head=arguments.expected_head,
            )
            _write_new(arguments.out, result["index"])
            report = {"index_hash": result["index"]["index_hash"], "delta": result["delta"], "write": "created", "output": arguments.out}
        else:
            report = find_knowledge_candidates(
                _read_json(arguments.index), fragment_id=arguments.fragment_id,
                limit=arguments.limit,
            )
        # ASCII output is intentional for historical Windows console defaults;
        # cap that actual form as well as the canonical UTF-8 representation.
        output = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(output.encode("ascii")) > MAX_INDEX_BYTES:
            raise ValueError("Console output exceeds 2 MiB.")
        print(output)
        return 0
    except (OSError, ValueError, UnicodeError, TypeError, RecursionError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
