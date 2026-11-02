"""Authored fixture: candidate retrieval, revision replacement and feed outage.

No actual user history, workstation, wiki, backend or synchronization is tested.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tiberium_ai.knowledge_crosswalk import (
    create_knowledge_index, find_knowledge_candidates, update_knowledge_index,
)


def build_demo() -> dict:
    records = []
    for name, channel, text in (
        ("cloud", "cloud", "Vérifier toiture escalier dimensions avant reconstruction."),
        ("workstation", "local", "La recette contrôle toiture escalier proportions."),
        ("wiki", "wiki", "Documenter toiture escalier mesures et références."),
        ("memory", "memory", "Ancienne idée toiture escalier à conserver en mémoire."),
    ):
        records.append({
            "id": "fixture:" + name, "version": "v1", "feed_id": name,
            "channel": channel, "project": "fixture-architecture",
            "uri": "fixture:" + name, "locator": "message:1",
            "timestamp": "2026-11-01", "state": "active", "text": text,
        })
    created = update_knowledge_index(
        create_knowledge_index("fixture:cloud-local"), upserts=records, removals=[],
        coverage=[{"id": record["feed_id"], "status": "complete"} for record in records],
        expected_head=create_knowledge_index("fixture:cloud-local")["index_hash"],
    )
    index = created["index"]
    before = find_knowledge_candidates(index, fragment_id="fixture:cloud")
    replaced = {**records[-1], "version": "v2", "state": "superseded"}
    updated = update_knowledge_index(
        index, upserts=[replaced], removals=[],
        coverage=[{"id": "workstation", "status": "unavailable"}],
        expected_head=index["index_hash"],
    )
    after = find_knowledge_candidates(updated["index"], fragment_id="fixture:cloud")
    assert len(before["matches"]) == 3
    assert [match["target"]["id"] for match in after["matches"]] == ["fixture:wiki"]
    assert after["coverage_incomplete"]
    assert len(updated["index"]["fragments"]) == 4
    return {"fixture_only": True, "initial_delta": created["delta"],
            "updated_delta": updated["delta"], "before": before, "after": after}


if __name__ == "__main__":
    print(json.dumps(build_demo(), ensure_ascii=True, sort_keys=True, indent=2))
