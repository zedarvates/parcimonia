"""Explicit-file asset inspection and advisory catalogue search.

Exit 0 means a usable report was produced, 2 an input/read error,
3 indeterminate inspection or unavailable extraction, and 4 native extraction
failure. Reports contain proposed tags; no source file is changed.
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
from .asset_tag_journal import append_tag_decision, create_tag_journal, validate_tag_journal
from .asset_tag_review import project_tag_reviews, search_reviewed_assets
from .asset_text_extract import extract_asset_text
from .asset_text_enrichment import enrich_asset_with_text

MAX_JOURNAL_BYTES = 8 * 1024 * 1024


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


def _write_journal_new(path: str, journal: dict) -> dict:
    """Use the repository's exclusive-write pattern for a new review snapshot."""
    validate_tag_journal(journal)
    payload = json.dumps(journal, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if len(payload.encode("utf-8")) > MAX_JOURNAL_BYTES:
        raise ValueError("The serialized journal exceeds the CLI's 8 MiB read/write budget.")
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
    return {
        "schema": "parcimonia.asset-tag-write/v1", "output": str(Path(path)),
        "head_hash": journal["head_hash"], "event_count": len(journal["events"]),
        "write": "created",
    }


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
    init = commands.add_parser("review-init", help="create a new empty tag journal")
    init.add_argument("output")
    decision = commands.add_parser("review-tag", help="record one caller decision in a new journal snapshot")
    decision.add_argument("input", help="one exact inspection report")
    decision.add_argument("journal", help="existing journal snapshot")
    decision.add_argument("--tag", required=True, help="namespace:value of an existing proposal")
    decision.add_argument("--decision", required=True, choices=["accept", "reject", "reset"])
    decision.add_argument("--actor", required=True)
    decision.add_argument("--reason", required=True)
    decision.add_argument("--event-id", required=True)
    decision.add_argument("--expected-head", required=True, help="current journal head, or none for an empty journal")
    decision.add_argument("--out", required=True, help="new journal path; never overwritten")
    view = commands.add_parser("review-view", help="project journal decisions onto an explicit catalogue")
    view.add_argument("input", help="catalogue JSON array")
    view.add_argument("journal")
    reviewed = commands.add_parser("search-reviewed", help="search tags with explicit review-state filtering")
    reviewed.add_argument("input", help="catalogue JSON array")
    reviewed.add_argument("journal")
    reviewed.add_argument("--tag", action="append", default=[])
    reviewed.add_argument("--state", action="append", choices=["proposed", "accepted", "rejected"])
    reviewed.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    reviewed.add_argument("--limit", type=int, default=50)
    extract = commands.add_parser("extract-text", help="explicitly run one installed local OCR/PDF backend")
    extract.add_argument("input")
    extract.add_argument("--source-id", required=True)
    extract.add_argument("--revision", required=True)
    extract.add_argument("--backend", required=True, choices=["tesseract", "pdftotext"])
    extract.add_argument("--executable", help="optional explicit local executable path")
    extract.add_argument("--language", default="eng")
    extract.add_argument("--max-pages", type=int, default=3)
    extract.add_argument("--timeout", type=float, default=10.0)
    enrich = commands.add_parser("enrich-text", help="propose tags from an existing exact extraction record")
    enrich.add_argument("input", help="original deterministic inspection report")
    enrich.add_argument("extraction", help="completed text extraction record")
    enrich.add_argument("--topics", help="optional explicit JSON vocabulary")
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
        elif arguments.command == "search":
            reports = _read_json(arguments.input, 16 * 1024 * 1024)
            report = search_asset_reports(reports, tags=arguments.tag, bbox=arguments.bbox, limit=arguments.limit)
            code = 0
        elif arguments.command == "extract-text":
            data, _, complete = _read_regular(arguments.input, MAX_SAMPLE_BYTES)
            report = extract_asset_text(
                data, filename=Path(arguments.input).name,
                source_id=arguments.source_id, revision=arguments.revision,
                backend=arguments.backend, executable=arguments.executable,
                language=arguments.language, max_pages=arguments.max_pages,
                timeout_s=arguments.timeout, complete=complete,
            )
            code = 0 if report["status"] == "completed" else 4 if report["status"] == "failed" else 3
        elif arguments.command == "enrich-text":
            inspection = _read_json(arguments.input, 2 * 1024 * 1024)
            extraction = _read_json(arguments.extraction, 2 * 1024 * 1024)
            topics = _read_json(arguments.topics, 64 * 1024, max_nodes=4096) if arguments.topics else None
            report = enrich_asset_with_text(inspection, extraction, topic_terms=topics)
            code = 0
        elif arguments.command == "review-init":
            report = _write_journal_new(arguments.output, create_tag_journal())
            code = 0
        elif arguments.command == "review-tag":
            inspection = _read_json(arguments.input, 2 * 1024 * 1024)
            journal = _read_json(arguments.journal, MAX_JOURNAL_BYTES)
            namespace, separator, value = arguments.tag.partition(":")
            if not separator:
                raise ValueError("The reviewed tag must use namespace:value syntax.")
            updated = append_tag_decision(
                journal, inspection, namespace=namespace, value=value,
                action=arguments.decision, actor_id=arguments.actor,
                reason=arguments.reason, event_id=arguments.event_id,
                expected_head=None if arguments.expected_head == "none" else arguments.expected_head,
            )
            report = _write_journal_new(arguments.out, updated)
            report["event_created"] = len(updated["events"]) > len(journal["events"])
            code = 0
        else:
            reports = _read_json(arguments.input, 16 * 1024 * 1024)
            journal = _read_json(arguments.journal, MAX_JOURNAL_BYTES)
            if arguments.command == "review-view":
                report = project_tag_reviews(reports, journal)
            else:
                report = search_reviewed_assets(
                    reports, journal, tags=arguments.tag, bbox=arguments.bbox,
                    states=arguments.state, limit=arguments.limit,
                )
            code = 0
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
