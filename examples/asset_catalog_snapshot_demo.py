"""Persist authored catalogue fixtures, reuse reviews and replace one revision.

Temporary files are removed after the demonstration. No personal asset is read,
no native extractor is invoked and no source asset or journal is rewritten.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from tiberium_ai.asset_catalog import search_asset_reports
from tiberium_ai.asset_catalog_snapshot import (
    create_asset_catalog, export_asset_reports, put_asset_report,
    remove_asset_report, validate_asset_catalog,
)
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import (
    append_tag_decision, create_tag_journal, validated_review_report_hash,
)
from tiberium_ai.asset_tag_review import search_reviewed_assets


def _persist(snapshot: dict, directory: Path) -> dict:
    path = directory / f"catalog-{snapshot['generation']}.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(snapshot, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    saved = json.loads(path.read_text(encoding="utf-8"))
    validate_asset_catalog(saved)
    return saved


def run_demo() -> dict:
    """Exercise actual temporary-file round trips on explicitly authored data."""
    vocabulary = {"robotique": ["robot"], "jardinage": ["jardin"]}
    notes = inspect_asset(
        b"Un robot pour le jardin.", filename="notes.txt",
        source_id="fixture:notes", revision="v1", topic_terms=vocabulary,
    )
    point = inspect_asset(
        b'{"type":"Point","coordinates":[2.3,47.6]}', filename="point.geojson",
        source_id="fixture:map", revision="v1",
    )
    revised = inspect_asset(
        b"Le robot du jardin a une nouvelle batterie.", filename="notes.txt",
        source_id="fixture:notes", revision="v2", topic_terms=vocabulary,
    )
    with tempfile.TemporaryDirectory(prefix="parcimonia-catalog-demo-") as temporary:
        directory = Path(temporary)
        snapshots = [_persist(create_asset_catalog("fixture:catalog"), directory)]
        for report in (point, notes):
            current = snapshots[-1]
            snapshots.append(_persist(put_asset_report(
                current, report, expected_head=current["snapshot_hash"], expected_report_hash=None,
            ), directory))
        original = snapshots[-1]
        original_bytes = (directory / "catalog-2.json").read_bytes()
        journal = create_tag_journal()
        for index, (report, namespace, value) in enumerate(((notes, "topic", "robotique"), (point, "modality", "geospatial"))):
            journal = append_tag_decision(
                journal, report, namespace=namespace, value=value, action="accept",
                actor_id="fixture:reviewer", reason="Authored demonstration decision.",
                event_id=f"fixture:review:{index}", expected_head=journal["head_hash"],
            )
        journal_path = directory / "reviews.json"
        with journal_path.open("x", encoding="utf-8") as stream:
            json.dump(journal, stream, ensure_ascii=False, allow_nan=False)
        journal_bytes = journal_path.read_bytes()
        journal = json.loads(journal_bytes)
        snapshots.append(_persist(put_asset_report(
            original, revised, expected_head=original["snapshot_hash"],
            expected_report_hash=validated_review_report_hash(notes),
        ), directory))
        changed = snapshots[-1]
        snapshots.append(_persist(remove_asset_report(
            changed, point["source"]["id"], expected_head=changed["snapshot_hash"],
            expected_report_hash=validated_review_report_hash(point),
        ), directory))
        removed = snapshots[-1]
        search = lambda snapshot, **query: search_reviewed_assets(export_asset_reports(snapshot), journal, **query)
        return {
            "data_origin": "authored_fixtures", "file_round_trips": len(snapshots),
            "snapshots": [{"generation": item["generation"], "snapshot_hash": item["snapshot_hash"], "parent_hash": item["parent_hash"], "report_count": len(item["reports"])} for item in snapshots],
            "accepted_original": search(original, tags=["topic:robotique"]),
            "accepted_changed_revision": search(changed, tags=["topic:robotique"]),
            "proposed_changed_revision": search(changed, tags=["topic:robotique"], states=["proposed"]),
            "unchanged_map_acceptance": search(changed, tags=["modality:geospatial"]),
            "spatial_before_removal": search_asset_reports(export_asset_reports(changed), bbox=[2, 47, 3, 48]),
            "spatial_after_removal": search_asset_reports(export_asset_reports(removed), bbox=[2, 47, 3, 48]),
            "old_snapshot_unchanged": original_bytes == (directory / "catalog-2.json").read_bytes(),
            "journal_unchanged": journal_bytes == journal_path.read_bytes(),
        }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=True, sort_keys=True, allow_nan=False))
