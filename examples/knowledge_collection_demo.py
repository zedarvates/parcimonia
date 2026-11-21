"""Authored fixtures: selected local files, cloud projections and replay.

No real account, workstation, archive or wiki is accessed by this example.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tiberium_ai.knowledge_crosswalk import (
    create_knowledge_index, find_knowledge_candidates, update_knowledge_index,
)
from tiberium_ai.knowledge_import import prepare_knowledge_import, prepare_unavailable_import
from tiberium_ai.knowledge_local_export import export_local_documents


def build_demo() -> dict:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        raw = "Une recette locale mesure toiture escalier et proportions.\r\n".encode("utf-8")
        (root / "architecture.md").write_bytes(raw)
        exported = export_local_documents({
            "schema": "parcimonia.local-knowledge-catalog/v1", "documents": [{
                "id": "architecture", "file": "architecture.md", "sha256": hashlib.sha256(raw).hexdigest(),
                "version": "fixture-v1", "project": "fixture", "uri": "fixture:architecture",
                "timestamp": "not_provided", "state": "active",
            }],
        }, root=root)
    search = {"results": [{"id": 1, "kind": "task", "project": "fixture",
        "status": "completed", "title": "Toiture et escalier", "tags": "architecture",
        "url": None, "detail": "Vérifier toiture escalier dimensions avant la reconstruction."}]}
    inbox = {"items": [{"id": 2, "project": "fixture", "title": "Note de recette",
        "summary": "Une note explique toiture escalier et appuis.", "sourceKind": "thread",
        "sourceUrl": None, "status": "pending", "createdAt": "not_provided", "confidence": 55}],
        "syncStatus": "offline", "syncAgeSeconds": None}
    inputs = [("second_brain", "fixture-search", "cloud", search),
              ("knowledge_inbox", "fixture-inbox", "cloud", inbox),
              ("documents", "fixture-local", "local", exported["documents"])]
    index = create_knowledge_index("fixture:collection")
    manifests = []

    def apply(prepared):
        nonlocal index
        batch = prepared["batch"]
        index = update_knowledge_index(index, upserts=batch["upserts"], removals=batch["removals"],
            coverage=batch["coverage"], expected_head=prepared["manifest"]["expected_head"])["index"]

    for kind, feed, channel, response in inputs:
        prepared = prepare_knowledge_import(index, response, source_kind=kind, feed_id=feed,
            observed_at="2026-11-02", channel=channel)
        manifests.append(prepared["manifest"])
        apply(prepared)
    anchor = next(f for f in index["fragments"] if f["feed_id"] == "fixture-search" and ":detail:" in f["id"])
    candidates = find_knowledge_candidates(index, fragment_id=anchor["id"])
    assert {m["target"]["feed_id"] for m in candidates["matches"]} == {"fixture-inbox", "fixture-local"}
    before_replay = index["index_hash"]
    for kind, feed, channel, response in inputs:
        apply(prepare_knowledge_import(index, response, source_kind=kind, feed_id=feed,
              observed_at="2026-11-03", channel=channel))
    assert index["index_hash"] == before_replay
    before_failure = len(index["fragments"])
    apply(prepare_unavailable_import(index, feed_id="fixture-search", observed_at="2026-11-03",
                                    reason_code="read_failed"))
    assert len(index["fragments"]) == before_failure
    return {"schema": "parcimonia.knowledge-collection-demo/v1", "fixture_only": True,
        "records": sum(len(m["records"]) for m in manifests), "fragments": len(index["fragments"]),
        "candidates": candidates, "identical_replay_changed_index": False,
        "failed_read_deleted_fragments": False, "coverage_after_failure": index["coverage"],
        "local_export_manifest": exported["manifest"]}


if __name__ == "__main__":
    print(json.dumps(build_demo(), ensure_ascii=True, sort_keys=True, indent=2))
