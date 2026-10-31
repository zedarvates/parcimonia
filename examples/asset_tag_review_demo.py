"""Authored tag-review walkthrough; no files, models or services are used."""

from __future__ import annotations

import json

from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import append_tag_decision, create_tag_journal
from tiberium_ai.asset_tag_review import project_tag_reviews, search_reviewed_assets


def run_demo() -> dict:
    vocabulary = {"robotique": ["robot"]}
    first = inspect_asset(b"A robot prepares a tool.", filename="notes.txt", source_id="fixture:positive", revision="v1", topic_terms=vocabulary)
    second = inspect_asset(b"This text says it is not a robot.", filename="negation.txt", source_id="fixture:negative", revision="v1", topic_terms=vocabulary)
    catalogue = [first, second]
    journal = create_tag_journal()
    accepted = append_tag_decision(
        journal, first, namespace="topic", value="robotique", action="accept",
        actor_id="fixture:reviewer", reason="Authored positive fixture.", event_id="fixture:accept-positive",
        expected_head=journal["head_hash"],
    )
    reviewed = append_tag_decision(
        accepted, second, namespace="topic", value="robotique", action="reject",
        actor_id="fixture:reviewer", reason="Authored example of a lexical false positive.", event_id="fixture:reject-negative",
        expected_head=accepted["head_hash"],
    )
    # Persistence-compatible JSON round trip; the CLI also writes fresh files.
    restored = json.loads(json.dumps(reviewed, ensure_ascii=True, allow_nan=False))
    changed = inspect_asset(b"A robot prepares a different tool.", filename="notes.txt", source_id="fixture:positive", revision="v2", topic_terms=vocabulary)
    reset = append_tag_decision(
        restored, first, namespace="topic", value="robotique", action="reset",
        actor_id="fixture:reviewer", reason="Return the proposal to pending review.", event_id="fixture:reset-positive",
        expected_head=restored["head_hash"],
    )
    return {
        "data_origin": "authored_fixture",
        "before_review": search_reviewed_assets(catalogue, journal, tags=["topic:robotique"]),
        "after_review": search_reviewed_assets(catalogue, restored, tags=["topic:robotique"]),
        "rejected_tags": search_reviewed_assets(catalogue, restored, tags=["topic:robotique"], states=["rejected"]),
        "after_reset": search_reviewed_assets(catalogue, reset, tags=["topic:robotique"]),
        "changed_revision": project_tag_reviews([changed, second], restored),
        "history_preserved": len(reset["events"]) == 3,
        "limitations": ["Actor identities are declarations, not signatures.", "Accepted tags are recorded judgments, not verified semantic truth."],
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=True, sort_keys=True, allow_nan=False))
