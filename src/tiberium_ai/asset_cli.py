"""Explicit-file asset inspection and advisory catalogue search.

Exit 0 means a usable report was produced, 2 an input/read error,
3 indeterminate inspection or unavailable extraction, and 4 native extraction
failure. Reports contain proposed tags; no source file is changed.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import stat
import sys
from typing import Sequence

from .asset_catalog import search_asset_reports
from .asset_expectations import MAX_AUDIT_BYTES, MAX_EXPECTATIONS_BYTES, audit_asset_expectations
from .asset_expectation_constraints import MAX_CONSISTENCY_BYTES, check_asset_expectations
from .asset_catalog_snapshot import (
    MAX_REPORT_BYTES, MAX_SNAPSHOT_BYTES, MAX_SNAPSHOT_NODES, create_asset_catalog,
    export_asset_reports, put_asset_report, remove_asset_report,
    validate_asset_catalog,
)
from .asset_inspection import MAX_SAMPLE_BYTES, _json_value, inspect_asset
from .asset_tag_journal import append_tag_decision, create_tag_journal, validate_tag_journal
from .asset_tag_review import project_tag_reviews, search_reviewed_assets
from .asset_text_extract import extract_asset_text
from .asset_text_enrichment import enrich_asset_with_text
from .asset_media_probe import probe_asset_media
from .asset_media_enrichment import enrich_asset_with_media
from .asset_relations import (
    MAX_RELATIONS_BYTES, MAX_SEARCH_BYTES, bind_asset_relations,
    search_asset_relations, validate_asset_relations,
)
from .verification import hash_input

MAX_JOURNAL_BYTES = 8 * 1024 * 1024


def _new_output(path: str):
    """Refuse every existing directory entry, including a dangling symlink.

    Windows CRT exclusive-open may follow dangling links; check the entry itself
    before the exclusive open. Do not resolve the output path to its target.
    """
    output = Path(path)
    try:
        output.lstat()
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(output))
    return output.open("x", encoding="utf-8", newline="\n")


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
    with _new_output(path) as stream:
        stream.write(payload)
    return {
        "schema": "parcimonia.asset-tag-write/v1", "output": str(Path(path)),
        "head_hash": journal["head_hash"], "event_count": len(journal["events"]),
        "write": "created",
    }


def _write_catalog_new(path: str, snapshot: dict) -> dict:
    """Create a new compact snapshot within the same budget as its reader."""
    validate_asset_catalog(snapshot)
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(payload.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ValueError("The serialized catalogue exceeds the 16 MiB read/write budget.")
    with _new_output(path) as stream:
        stream.write(payload)
    return {
        "schema": "parcimonia.asset-catalog-write/v1", "output": str(Path(path)),
        "catalog_id": snapshot["catalog_id"], "generation": snapshot["generation"],
        "snapshot_hash": snapshot["snapshot_hash"], "report_count": len(snapshot["reports"]),
        "write": "created",
    }


def _read_catalog(path: str) -> dict:
    snapshot = _read_json(path, MAX_SNAPSHOT_BYTES, max_nodes=MAX_SNAPSHOT_NODES)
    validate_asset_catalog(snapshot)
    return snapshot


def _write_relations_new(path: str, document: dict) -> dict:
    validate_asset_relations(document)
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(payload.encode("utf-8")) > MAX_RELATIONS_BYTES:
        raise ValueError("The serialized relation document exceeds its read/write budget.")
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
    return {
        "schema": "parcimonia.asset-relations-write/v1", "output": str(Path(path)),
        "relations_id": document["id"], "relations_hash": document["relations_hash"],
        "relation_count": len(document["relations"]), "write": "created",
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
    audit = commands.add_parser("audit-expectations", help="compare explicit expectations with supplied reports")
    audit.add_argument("input", help="JSON report array, or catalogue snapshot with --catalog")
    audit.add_argument("expectations", help="explicit versioned expectations JSON")
    audit.add_argument("--catalog", action="store_true", help="read the input as a saved catalogue snapshot")
    consistency = commands.add_parser("check-expectations", help="find contradictions within the explicit expectation contract")
    consistency.add_argument("input", help="expectations JSON; no asset or inspection report is read")
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
    media_probe = commands.add_parser("probe-media", help="explicitly observe installed ffprobe stream metadata")
    media_probe.add_argument("input")
    media_probe.add_argument("--source-id", required=True)
    media_probe.add_argument("--revision", required=True)
    media_probe.add_argument("--executable", help="optional explicit local ffprobe executable")
    media_probe.add_argument("--timeout", type=float, default=10.0)
    media_enrich = commands.add_parser("enrich-media", help="propose tags from one exact saved media observation")
    media_enrich.add_argument("input", help="original deterministic inspection")
    media_enrich.add_argument("observation", help="completed ffprobe observation record")
    catalog_init = commands.add_parser("catalog-init", help="create a new empty catalogue snapshot")
    catalog_init.add_argument("output")
    catalog_init.add_argument("--catalog-id", required=True)
    catalog_put = commands.add_parser("catalog-put", help="select one exact report in a new catalogue snapshot")
    catalog_put.add_argument("input", help="current snapshot")
    catalog_put.add_argument("report", help="inspection or enriched report JSON")
    catalog_put.add_argument("--expected-head", required=True, help="exact current snapshot hash")
    catalog_put.add_argument("--expected-report-hash", required=True, help="current report hash, or none for a new source")
    catalog_put.add_argument("--out", required=True, help="new snapshot path; never overwritten")
    catalog_remove = commands.add_parser("catalog-remove", help="omit one report from a new snapshot, keeping source files")
    catalog_remove.add_argument("input", help="current snapshot")
    catalog_remove.add_argument("--source-id", required=True)
    catalog_remove.add_argument("--expected-head", required=True)
    catalog_remove.add_argument("--expected-report-hash", required=True)
    catalog_remove.add_argument("--out", required=True)
    catalog_export = commands.add_parser("catalog-export", help="print reports for existing catalogue/review commands")
    catalog_export.add_argument("input")
    catalog_export.add_argument("--out", help="new compact UTF-8 report array file; never overwritten")
    catalog_search = commands.add_parser("catalog-search", help="search one snapshot using an explicit tag journal")
    catalog_search.add_argument("input")
    catalog_search.add_argument("journal")
    catalog_search.add_argument("--tag", action="append", default=[])
    catalog_search.add_argument("--state", action="append", choices=["proposed", "accepted", "rejected"])
    catalog_search.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    catalog_search.add_argument("--limit", type=int, default=50)
    relations_build = commands.add_parser("relations-build", help="bind caller-declared directed relations to exact catalogue reports")
    relations_build.add_argument("input", help="existing catalogue snapshot")
    relations_build.add_argument("declarations", help="explicit JSON array of relation declarations")
    relations_build.add_argument("--relations-id", required=True)
    relations_build.add_argument("--expected-head", required=True, help="exact catalogue hash used when authoring the declarations")
    relations_build.add_argument("--out", required=True, help="new relation document; never overwritten")
    relations_search = commands.add_parser("relations-search", help="find declared similar or complementary candidates with source references")
    relations_search.add_argument("input", help="current catalogue snapshot")
    relations_search.add_argument("relations", help="saved relation document")
    relations_search.add_argument("--source-id", required=True)
    relations_search.add_argument("--intent", required=True, choices=["similar", "complementary"])
    relations_search.add_argument("--limit", type=int, default=50)
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
        elif arguments.command == "check-expectations":
            expectations = _read_json(arguments.input, MAX_EXPECTATIONS_BYTES, max_nodes=20_000)
            report = check_asset_expectations(expectations)
            code = 0
        elif arguments.command == "audit-expectations":
            if arguments.catalog:
                snapshot = _read_catalog(arguments.input)
                reports = export_asset_reports(snapshot)
            else:
                reports = _read_json(arguments.input, MAX_SNAPSHOT_BYTES, max_nodes=MAX_SNAPSHOT_NODES)
            expectations = _read_json(arguments.expectations, MAX_EXPECTATIONS_BYTES, max_nodes=20_000)
            report = audit_asset_expectations(reports, expectations)
            if arguments.catalog:
                reference = {
                    "id": snapshot["catalog_id"], "generation": snapshot["generation"],
                    "snapshot_hash": snapshot["snapshot_hash"],
                }
                report = {
                    "schema": "parcimonia.asset-catalog-expectation-audit/v1", "catalog": reference,
                    "input_hash": hash_input({"catalog": reference, "audit_input_hash": report["input_hash"]}),
                    "result": report,
                }
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
        elif arguments.command == "probe-media":
            data, _, complete = _read_regular(arguments.input, MAX_SAMPLE_BYTES)
            report = probe_asset_media(
                data, filename=Path(arguments.input).name, source_id=arguments.source_id,
                revision=arguments.revision, executable=arguments.executable,
                timeout_s=arguments.timeout, complete=complete,
            )
            code = 0 if report["status"] == "completed" else 4 if report["status"] == "failed" else 3
        elif arguments.command == "enrich-media":
            inspection = _read_json(arguments.input, 2 * 1024 * 1024)
            observation = _read_json(arguments.observation, 2 * 1024 * 1024)
            report = enrich_asset_with_media(inspection, observation)
            code = 0
        elif arguments.command == "relations-build":
            snapshot = _read_catalog(arguments.input)
            if arguments.expected_head != snapshot["snapshot_hash"]:
                raise ValueError("expected_head does not match the supplied catalogue snapshot.")
            declarations = _read_json(arguments.declarations, MAX_RELATIONS_BYTES, max_nodes=20_000)
            document = bind_asset_relations(snapshot, declarations, relations_id=arguments.relations_id)
            report = _write_relations_new(arguments.out, document)
            code = 0
        elif arguments.command == "relations-search":
            snapshot = _read_catalog(arguments.input)
            document = _read_json(arguments.relations, MAX_RELATIONS_BYTES, max_nodes=20_000)
            report = search_asset_relations(
                snapshot, document, source_id=arguments.source_id,
                intent=arguments.intent, limit=arguments.limit,
            )
            code = 0
        elif arguments.command == "catalog-init":
            report = _write_catalog_new(arguments.output, create_asset_catalog(arguments.catalog_id))
            code = 0
        elif arguments.command == "catalog-put":
            snapshot = _read_catalog(arguments.input)
            inspection = _read_json(arguments.report, MAX_REPORT_BYTES)
            updated = put_asset_report(
                snapshot, inspection, expected_head=arguments.expected_head,
                expected_report_hash=None if arguments.expected_report_hash == "none" else arguments.expected_report_hash,
            )
            report = _write_catalog_new(arguments.out, updated)
            report["snapshot_changed"] = updated["snapshot_hash"] != snapshot["snapshot_hash"]
            code = 0
        elif arguments.command == "catalog-remove":
            snapshot = _read_catalog(arguments.input)
            updated = remove_asset_report(
                snapshot, arguments.source_id, expected_head=arguments.expected_head,
                expected_report_hash=arguments.expected_report_hash,
            )
            report = _write_catalog_new(arguments.out, updated)
            report["snapshot_changed"] = True
            code = 0
        elif arguments.command == "catalog-export":
            snapshot = _read_catalog(arguments.input)
            report = export_asset_reports(snapshot)
            if arguments.out:
                payload = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                if len(payload.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
                    raise ValueError("The exported array exceeds the 16 MiB read/write budget.")
                with _new_output(arguments.out) as stream:
                    stream.write(payload)
                report = {
                    "schema": "parcimonia.asset-catalog-export-write/v1",
                    "output": str(Path(arguments.out)), "write": "created",
                    "catalog_id": snapshot["catalog_id"], "generation": snapshot["generation"],
                    "snapshot_hash": snapshot["snapshot_hash"], "report_count": len(snapshot["reports"]),
                }
            code = 0
        elif arguments.command == "catalog-search":
            snapshot = _read_catalog(arguments.input)
            journal = _read_json(arguments.journal, MAX_JOURNAL_BYTES)
            result = search_reviewed_assets(
                export_asset_reports(snapshot), journal, tags=arguments.tag,
                states=arguments.state, bbox=arguments.bbox, limit=arguments.limit,
            )
            reference = {"id": snapshot["catalog_id"], "generation": snapshot["generation"], "snapshot_hash": snapshot["snapshot_hash"]}
            report = {
                "schema": "parcimonia.asset-catalog-reviewed-search/v1",
                "catalog": reference,
                "input_hash": hash_input({"catalog": reference, "search_input_hash": result["input_hash"]}),
                "result": result,
            }
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
        output = json.dumps(report, ensure_ascii=True, sort_keys=True, allow_nan=False)
        if arguments.command == "check-expectations" and len(output.encode("ascii")) + 1 > MAX_CONSISTENCY_BYTES:
            raise ValueError("The ASCII consistency output exceeds 256 KiB.")
        if arguments.command == "audit-expectations" and len(output.encode("ascii")) + 1 > MAX_AUDIT_BYTES:
            raise ValueError("The ASCII audit output exceeds 16 MiB.")
        if arguments.command == "catalog-export" and not arguments.out and len(output.encode("ascii")) + 1 > MAX_SNAPSHOT_BYTES:
            raise ValueError("The ASCII stdout export exceeds 16 MiB; use --out for compact UTF-8 export.")
        if arguments.command == "relations-search" and len(output.encode("ascii")) + 1 > MAX_SEARCH_BYTES:
            raise ValueError("The ASCII relation-search output exceeds 4 MiB.")
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    print(output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
