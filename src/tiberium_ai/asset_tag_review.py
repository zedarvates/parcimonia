"""Project declared tag decisions onto exact reports and search their states.

An accepted tag is a recorded review, not authenticated source truth. Decisions
never transfer through a content/prefix hash or an assumed latest revision.
"""

from __future__ import annotations

from typing import Any

from .asset_catalog import MAX_REPORTS, search_asset_reports
from .asset_tag_journal import (
    MAX_TAG_PROPOSALS,
    validate_tag_journal,
    validated_review_report_hash,
)
from .verification import hash_input

__all__ = ["project_tag_reviews", "search_reviewed_assets"]

_STATUSES = {"accept": "accepted", "reject": "rejected", "reset": "proposed"}


def _catalogue(reports: Any) -> dict[tuple[str, str], dict[str, Any]]:
    if type(reports) is not list or len(reports) > MAX_REPORTS:
        raise ValueError(f"reports must contain at most {MAX_REPORTS} inspection reports.")
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for report in reports:
        if type(report) is dict and type(report.get("tag_proposals")) is list:
            if len(report["tag_proposals"]) > MAX_TAG_PROPOSALS:
                raise ValueError("Each report may contain at most 256 tag proposals.")
        report_hash = validated_review_report_hash(report)
        source = report["source"]
        identity = (source["id"], source["revision"])
        if identity in indexed:
            raise ValueError("Duplicate source identity and revision are ambiguous.")
        tags: dict[tuple[str, str], dict[str, Any]] = {}
        for proposal in report["tag_proposals"]:
            key = (proposal["namespace"], proposal["value"])
            if key not in tags:
                tags[key] = {
                    "namespace": key[0], "value": key[1], "status": "proposed",
                    "evidence_refs": set(), "decision": None,
                }
            tags[key]["evidence_refs"].update(proposal["evidence_refs"])
        indexed[identity] = {"report": report, "report_hash": report_hash, "tags": tags}
    return indexed


def project_tag_reviews(reports: list[dict[str, Any]], journal: dict[str, Any]) -> dict[str, Any]:
    """Apply only decisions bound to a supplied report's exact identity/hash.

    A newer or differently inspected report starts with proposed tags. Historical
    decisions remain in the journal and are listed as unapplied when stale or
    outside this catalogue. Multiple supplied revisions remain distinct assets.
    """
    validate_tag_journal(journal)
    indexed = _catalogue(reports)
    source_ids = {identifier for identifier, _ in indexed}
    unapplied = []
    for event in journal["events"]:
        source = event["source"]
        identity = (source["id"], source["revision"])
        current = indexed.get(identity)
        if current is None:
            reason = "source_revision_changed" if source["id"] in source_ids else "source_not_in_catalogue"
        elif event["report_hash"] != current["report_hash"]:
            reason = "report_changed"
        else:
            key = (event["tag"]["namespace"], event["tag"]["value"])
            if key not in current["tags"]:
                raise ValueError("A decision bound to this report references an unknown tag.")
            tag = current["tags"][key]
            tag["status"] = _STATUSES[event["action"]]
            tag["decision"] = {
                field: event[field]
                for field in ("event_id", "event_hash", "sequence", "actor_id", "reason")
            }
            continue
        unapplied.append({"event_id": event["event_id"], "source": dict(source), "reason": reason})

    assets = []
    for identity, current in sorted(indexed.items()):
        report = current["report"]
        tags = []
        for key, tag in sorted(current["tags"].items()):
            tags.append({
                "namespace": key[0], "value": key[1], "status": tag["status"],
                "evidence_refs": sorted(tag["evidence_refs"]),
                "decision": dict(tag["decision"]) if tag["decision"] is not None else None,
            })
        assets.append({
            "source": dict(report["source"]),
            "report_hash": current["report_hash"],
            "input_hash": report["input_hash"],
            "sample_sha256": report["sample"]["sha256"],
            "tags": tags,
        })
    return {
        "schema": "parcimonia.asset-tag-review/v1",
        "input_hash": hash_input({"reports": reports, "journal": journal}),
        "journal_head": journal["head_hash"],
        "assets": assets,
        "unapplied_events": unapplied,
        "limits": {
            "sources": "caller_supplied_unverified",
            "actors": "caller_declared_unauthenticated",
            "acceptance": "recorded_review_not_source_truth",
            "revision_selection": "explicit_no_latest_revision_inference",
        },
    }


def _states(states: Any) -> list[str]:
    if states is None:
        return ["accepted"]
    if type(states) is not list or not 1 <= len(states) <= 256:
        raise ValueError("states must be a nonempty array of at most 256 review states.")
    if any(type(state) is not str or state not in {"proposed", "accepted", "rejected"} for state in states):
        raise ValueError("Review states must be proposed, accepted or rejected.")
    return sorted(set(states))


def search_reviewed_assets(
    reports: list[dict[str, Any]], journal: dict[str, Any], *,
    tags: list[str] | None = None, bbox: list[float] | None = None,
    states: list[str] | None = None, limit: int = 50,
) -> dict[str, Any]:
    """Search exact tag states, using the existing catalogue for AND/bbox rules.

    Accepted-only is the default for tag matching. Without a tag filter, listing
    and spatial search cover the supplied catalogue and do not imply approval.
    Rejected tags are searchable only when explicitly requested.
    """
    requested_states = _states(states)
    review = project_tag_reviews(reports, journal)
    assets = {
        (asset["source"]["id"], asset["source"]["revision"]): asset
        for asset in review["assets"]
    }
    projected_reports = []
    for report in reports:
        identity = (report["source"]["id"], report["source"]["revision"])
        asset = assets[identity]
        allowed = {
            (tag["namespace"], tag["value"])
            for tag in asset["tags"] if tag["status"] in requested_states
        }
        # This is an internal, read-only query projection. The original report
        # and its proposal schema remain unchanged; only this new API exposes
        # the review-state policy and corresponding decision provenance.
        projected_reports.append(dict(
            report,
            tag_proposals=[
                proposal for proposal in report["tag_proposals"]
                if (proposal["namespace"], proposal["value"]) in allowed
            ],
        ))
    candidates = search_asset_reports(projected_reports, tags=tags, bbox=bbox, limit=limit)
    query = dict(candidates["query"], states=requested_states)
    matches = []
    for candidate in candidates["matches"]:
        identity = (candidate["source"]["id"], candidate["source"]["revision"])
        asset = assets[identity]
        tag_states = {f"{tag['namespace']}:{tag['value']}": tag for tag in asset["tags"]}
        provenance = []
        for key in candidate["matched_tags"]:
            tag = tag_states[key]
            decision = tag["decision"]
            provenance.append({
                "tag": key, "status": tag["status"],
                "decision_event_id": decision["event_id"] if decision else None,
                "decision_event_hash": decision["event_hash"] if decision else None,
            })
        matches.append(dict(candidate, report_hash=asset["report_hash"], tag_states=provenance))
    return {
        "schema": "parcimonia.asset-reviewed-search/v1",
        "input_hash": hash_input({"reports": reports, "journal": journal, "query": query}),
        "query": query,
        "journal_head": journal["head_hash"],
        "matches": matches,
        "count": candidates["count"],
        "truncated": candidates["truncated"],
        "limits": {
            "sources": "caller_supplied_unverified",
            "actors": "caller_declared_unauthenticated",
            "acceptance": "recorded_review_not_source_truth",
            "state_filter": "tag_matching_only",
            "listing_without_tag_filter": "does_not_imply_approval",
            "spatial": "envelope_only_no_geometry_verification",
        },
    }
