"""Capture and resume explicit discussion records, and exchange bounded JSON files.

The SQLite database is durable local state. Exchange files are carried by the
caller; this command starts no network service and discovers no conversations.
Output files are always new. Exit 2 reports invalid input or an operation/output
failure; inspect operation_completed before retrying a completed mutation.
Exit 3 means an identity-conflict receipt was produced without ingesting its batch.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import stat
import sys
from typing import Any, Sequence

from .inception import InceptionStore
from .knowledge_cli import _encoded, _read_json, _write_new
from .knowledge_crosswalk import MAX_INDEX_BYTES


def _output_available(path: str, database: str) -> None:
    """Catch existing destinations before a durable operation, without reserving.

    The final exclusive writer still handles a concurrent creation. This check
    is neither a lock nor a transaction joining SQLite with the output file.
    """
    target = Path(path)
    try:
        target.lstat()
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError("Output path already exists, including a dangling link.")
    if target.resolve() == Path(database).resolve():
        raise ValueError("The output file must differ from the SQLite database.")
    if not stat.S_ISDIR(target.parent.stat().st_mode):
        raise ValueError("Output parent must be an existing directory.")


def _console(value: Any) -> str:
    # Check the actual ASCII console representation for older Windows consoles,
    # as well as the shared canonical UTF-8 file budget.
    _encoded(value)
    result = json.dumps(value, ensure_ascii=True, sort_keys=True,
                        separators=(",", ":"), allow_nan=False)
    if len(result.encode("ascii")) > MAX_INDEX_BYTES:
        raise ValueError("Console output exceeds 2 MiB.")
    return result


def _common(parser: argparse.ArgumentParser, *, project: bool = False,
            required_output: bool = False) -> None:
    parser.add_argument("--db", required=True, help="Explicit local SQLite database")
    if project:
        parser.add_argument("--project", required=True)
    parser.add_argument("--out", required=required_output,
                        help="Also write the JSON result to a new private file")


def _append_arguments(parser: argparse.ArgumentParser, *, checkpoint: bool) -> None:
    _common(parser, project=True)
    if not checkpoint:
        parser.add_argument("--kind", required=True,
                            choices=("checkpoint", "decision", "outcome", "lesson", "link"))
    parser.add_argument("--record", default="main" if checkpoint else None,
                        required=not checkpoint, help="Stable record key within this project and kind")
    parser.add_argument("--input", required=True, help="JSON payload matching the chosen kind")
    parser.add_argument("--sources", help="JSON list of declared source references")
    parser.add_argument("--expected-heads", required=True,
                        help="Path to a JSON file of event IDs returned by heads; a file containing [] for a new record")
    parser.add_argument("--event-id", help="Stable event ID for an identical retry after an output failure")
    parser.add_argument("--scope", choices=("local", "shared"), default="local")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("init", help="Create a new private local database")
    _common(create)
    create.add_argument("--node", required=True, help="Stable identity of this database replica")

    projects = commands.add_parser("projects", help="List projects in an existing database")
    _common(projects)

    resume = commands.add_parser("resume", help="Prepare bounded context for a fresh discussion")
    _common(resume)
    resume.add_argument("--project", help="Omit to list the known projects")
    resume.add_argument("--record", default="main", help="Checkpoint record key")

    status = commands.add_parser("status", help="Inspect project and optional peer exchange state")
    _common(status, project=True)
    status.add_argument("--peer")

    heads = commands.add_parser("heads", help="Read exact event IDs for a record before appending")
    _common(heads, project=True)
    heads.add_argument("--kind", required=True,
                       choices=("checkpoint", "decision", "outcome", "lesson", "link"))
    heads.add_argument("--record", required=True)

    append = commands.add_parser("append", help="Persist a typed event with an explicit head precondition")
    _append_arguments(append, checkpoint=False)
    checkpoint = commands.add_parser("checkpoint", help="Append a checkpoint, using record main by default")
    _append_arguments(checkpoint, checkpoint=True)

    links = commands.add_parser("links", help="Read declared links and sourced lexical candidates")
    _common(links, project=True)
    links.add_argument("--event-id", required=True)
    links.add_argument("--limit", type=int, default=5)

    sync = commands.add_parser("sync", help="Exchange explicit files with one named peer")
    exchange = sync.add_subparsers(dest="sync_command", required=True)
    export = exchange.add_parser("export", help="Persist and export a replayable batch for a peer")
    _common(export, project=True, required_output=True)
    export.add_argument("--peer", required=True)
    export.add_argument("--limit", type=int, default=128)
    receive = exchange.add_parser("receive", help="Receive a carried batch and emit its receipt")
    _common(receive, required_output=True)
    receive.add_argument("--input", required=True, help="Batch JSON for this database replica")
    ack = exchange.add_parser("ack", help="Apply a carried receipt to its outstanding batch")
    _common(ack)
    ack.add_argument("--input", required=True, help="Receipt JSON for an outstanding export")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    operation_completed = False
    try:
        if arguments.out:
            _output_available(arguments.out, arguments.db)
        # Read and validate JSON syntax/bounds before opening or mutating a DB.
        payload = _read_json(arguments.input) if hasattr(arguments, "input") else None
        sources = _read_json(arguments.sources) if getattr(arguments, "sources", None) else None
        expected_heads = (_read_json(arguments.expected_heads)
                          if hasattr(arguments, "expected_heads") else None)

        if arguments.command == "init":
            InceptionStore.create(arguments.db, arguments.node)
            result = {"schema": "parcimonia.inception-cli-init/v1", "db": arguments.db,
                      "node_id": arguments.node, "write": "created"}
        else:
            store = InceptionStore(arguments.db)
            if arguments.command == "projects":
                result = store.projects()
            elif arguments.command == "resume":
                result = (store.resume(arguments.project, record_key=arguments.record)
                          if arguments.project else store.projects())
            elif arguments.command == "status":
                result = store.status(arguments.project, peer_id=arguments.peer)
            elif arguments.command == "heads":
                result = store.heads(arguments.project, arguments.kind, arguments.record)
            elif arguments.command in {"append", "checkpoint"}:
                result = store.append(
                    arguments.project,
                    "checkpoint" if arguments.command == "checkpoint" else arguments.kind,
                    arguments.record, payload, expected_heads=expected_heads,
                    sources=sources, event_id=arguments.event_id, scope=arguments.scope,
                )
            elif arguments.command == "links":
                result = store.links(arguments.project, arguments.event_id, limit=arguments.limit)
            elif arguments.sync_command == "export":
                result = store.export_batch(arguments.project, arguments.peer, limit=arguments.limit)
            elif arguments.sync_command == "receive":
                result = store.receive(payload)
            else:
                result = store.acknowledge(payload)
        operation_completed = True
        output = _console(result)
        if arguments.out:
            _write_new(arguments.out, result)
        print(output)
        return (3 if arguments.command == "sync" and arguments.sync_command == "receive"
                and result.get("status") == "conflict" else 0)
    except (OSError, ValueError, UnicodeError, TypeError, RecursionError, sqlite3.Error) as exc:
        error = {"error": type(exc).__name__, "detail": str(exc)[:2000],
                 "operation_completed": operation_completed}
        print(json.dumps(error, ensure_ascii=True, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
