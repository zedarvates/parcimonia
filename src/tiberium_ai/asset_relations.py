"""Declared directed relations between exact catalogue inspections.

The sidecar preserves supplied evidence references, not their truth. Relations
never follow a source revision or imply symmetry, transitivity, tag acceptance,
execution authority, or geometric compatibility. No model, network or I/O runs.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .asset_catalog_snapshot import _canonical_size, validate_asset_catalog
from .asset_tag_journal import _hash, _object, _text, _validate_report_json
from .verification import hash_input

__all__ = [
    "RELATIONS_SCHEMA", "SEARCH_SCHEMA", "RELATION_KINDS", "MAX_RELATIONS",
    "MAX_RELATIONS_BYTES", "MAX_SEARCH_BYTES", "bind_asset_relation", "bind_asset_relations",
    "create_asset_relations", "validate_asset_relations", "search_asset_relations",
]

RELATIONS_SCHEMA = "parcimonia.asset-relations/v1"
SEARCH_SCHEMA = "parcimonia.asset-relation-search/v1"
MAX_RELATIONS = 256
MAX_RELATIONS_BYTES = 1024 * 1024
MAX_SEARCH_BYTES = 4 * 1024 * 1024
RELATION_KINDS = frozenset({
    "similar_to", "complements", "requires", "used_with", "compatible_with",
    "incompatible_with", "tested_by", "fixed_by",
})
_COMPLEMENTARY_KINDS = RELATION_KINDS - {"similar_to", "incompatible_with"}
_FIELDS = {"schema", "id", "catalog_id", "relations", "relations_hash"}
_EDGE_FIELDS = {"id", "source", "target", "kind", "evidence", "status"}
_ENDPOINT_FIELDS = {"id", "revision", "report_hash"}


def _endpoint(value: Any, label: str) -> None:
    _object(value, _ENDPOINT_FIELDS, label)
    _text(value["id"], label + ".id")
    _text(value["revision"], label + ".revision")
    _hash(value["report_hash"], label + ".report_hash")


def _edge(value: Any) -> None:
    _object(value, _EDGE_FIELDS, "relation")
    _text(value["id"], "relation.id", 128)
    _endpoint(value["source"], "relation.source")
    _endpoint(value["target"], "relation.target")
    if value["source"]["id"] == value["target"]["id"]:
        raise ValueError("A relation must connect two distinct source IDs.")
    if type(value["kind"]) is not str or value["kind"] not in RELATION_KINDS:
        raise ValueError("Unsupported relation kind.")
    if type(value["status"]) is not str or value["status"] != "caller_declared":
        raise ValueError("Relation status must remain caller_declared.")
    evidence = value["evidence"]
    if type(evidence) is not list or not 1 <= len(evidence) <= 8:
        raise ValueError("Each relation needs 1..8 evidence references.")
    seen: set[tuple[str, str, str]] = set()
    for item in evidence:
        _object(item, {"reference", "revision", "locator"}, "relation evidence")
        for field in ("reference", "revision", "locator"):
            _text(item[field], "evidence." + field)
        identity = (item["reference"], item["revision"], item["locator"])
        if identity in seen:
            raise ValueError("Evidence references must be unique within a relation.")
        seen.add(identity)


def _payload(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "relations_hash"}


def _validate_relations(document: Any, *, check_hash: bool = True) -> None:
    # The existing strict boundary rejects non-JSON types, cycles, excessive
    # depth and node counts before hashing or copying any caller structure.
    _validate_report_json(document)
    _canonical_size(document, MAX_RELATIONS_BYTES, "Relations")
    _object(document, _FIELDS, "relations document")
    if type(document["schema"]) is not str or document["schema"] != RELATIONS_SCHEMA:
        raise ValueError("Unsupported relations schema.")
    _text(document["id"], "relations.id", 128)
    _text(document["catalog_id"], "relations.catalog_id")
    _hash(document["relations_hash"], "relations_hash")
    relations = document["relations"]
    if type(relations) is not list or len(relations) > MAX_RELATIONS:
        raise ValueError(f"relations must contain at most {MAX_RELATIONS} entries.")
    previous = None
    for relation in relations:
        _edge(relation)
        if previous is not None and relation["id"] <= previous:
            raise ValueError("Relations must be sorted by unique relation.id values.")
        previous = relation["id"]
    if check_hash and document["relations_hash"] != hash_input(_payload(document)):
        raise ValueError("relations_hash does not match the relations payload.")


def validate_asset_relations(document: Any) -> None:
    """Validate a sidecar's shape/hash, without authenticating its evidence."""
    _validate_relations(document)


def _catalogue(catalog: Any) -> dict[str, dict[str, Any]]:
    validate_asset_catalog(catalog)
    return {
        report["source"]["id"]: {
            "id": report["source"]["id"],
            "revision": report["source"]["revision"],
            "report_hash": hash_input(report),
        }
        for report in catalog["reports"]
    }


def _unapplied(relation: dict[str, Any], indexed: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    reasons = []
    for field in ("source", "target"):
        endpoint = relation[field]
        current = indexed.get(endpoint["id"])
        if current is None:
            reason = "source_not_in_catalogue"
        elif endpoint["revision"] != current["revision"]:
            reason = "source_revision_changed"
        elif endpoint["report_hash"] != current["report_hash"]:
            reason = "report_changed"
        else:
            continue
        reasons.append({"endpoint": field, "reason": reason})
    return reasons


def bind_asset_relation(
    catalog: dict[str, Any], *, relation_id: str, source_id: str,
    target_id: str, kind: str, evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bind an explicit declaration to the exact currently supplied reports.

    Call only for an intentional new declaration/review; rebinding an old claim
    after a source changes is not automatic revalidation of that claim.
    """
    return _bind(
        _catalogue(catalog), relation_id=relation_id, source_id=source_id,
        target_id=target_id, kind=kind, evidence=evidence,
    )


def _bind(
    indexed: dict[str, dict[str, Any]], *, relation_id: str, source_id: str,
    target_id: str, kind: str, evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    _text(source_id, "source_id")
    _text(target_id, "target_id")
    if source_id not in indexed or target_id not in indexed:
        raise ValueError("Both relation endpoints must be selected in the catalogue.")
    relation = {
        "id": relation_id, "source": indexed[source_id], "target": indexed[target_id],
        "kind": kind, "evidence": evidence, "status": "caller_declared",
    }
    _validate_report_json(relation)
    _canonical_size(relation, MAX_RELATIONS_BYTES, "Relation")
    _edge(relation)
    return deepcopy(relation)


def create_asset_relations(
    catalog: dict[str, Any], relations: list[dict[str, Any]], *, relations_id: str,
) -> dict[str, Any]:
    """Seal a new sidecar of explicit, current declarations, without I/O.

    Inputs are copied; IDs are sorted, not ranked. Existing sidecars are passed
    to search unchanged so stale declarations remain visible as unapplied.
    """
    return _create(catalog, _catalogue(catalog), relations, relations_id=relations_id)


def _create(
    catalog: dict[str, Any], indexed: dict[str, dict[str, Any]],
    relations: list[dict[str, Any]], *, relations_id: str,
) -> dict[str, Any]:
    _validate_report_json(relations)
    _canonical_size(relations, MAX_RELATIONS_BYTES, "Relations")
    if type(relations) is not list or len(relations) > MAX_RELATIONS:
        raise ValueError(f"relations must contain at most {MAX_RELATIONS} entries.")
    for relation in relations:
        _edge(relation)
        if _unapplied(relation, indexed):
            raise ValueError("A new relations document requires exact current endpoint reports.")
    document = {
        "schema": RELATIONS_SCHEMA, "id": relations_id, "catalog_id": catalog["catalog_id"],
        "relations": sorted(relations, key=lambda item: item["id"]),
        "relations_hash": "0" * 64,
    }
    _validate_relations(document, check_hash=False)
    document["relations_hash"] = hash_input(_payload(document))
    return deepcopy(document)


def bind_asset_relations(
    catalog: dict[str, Any], declarations: list[dict[str, Any]], *, relations_id: str,
) -> dict[str, Any]:
    """Bind and seal a bounded explicit declaration batch with one catalogue read.

    Raw declaration fields are id, source_id, target_id, kind and evidence.
    This is explicit rebinding, never a stale-sidecar refresh operation.
    """
    indexed = _catalogue(catalog)
    _validate_report_json(declarations)
    _canonical_size(declarations, MAX_RELATIONS_BYTES, "Relation declarations")
    if type(declarations) is not list or len(declarations) > MAX_RELATIONS:
        raise ValueError(f"declarations must contain at most {MAX_RELATIONS} entries.")
    relations = []
    for declaration in declarations:
        _object(declaration, {"id", "source_id", "target_id", "kind", "evidence"}, "relation declaration")
        relations.append(_bind(
            indexed, relation_id=declaration["id"], source_id=declaration["source_id"],
            target_id=declaration["target_id"], kind=declaration["kind"], evidence=declaration["evidence"],
        ))
    return _create(catalog, indexed, relations, relations_id=relations_id)


def search_asset_relations(
    catalog: dict[str, Any], document: dict[str, Any], *, source_id: str,
    intent: str = "complementary", limit: int = 50,
) -> dict[str, Any]:
    """Return direct outgoing caller-declared candidates from exact reports.

    Similar queries select only similar_to. Complementary queries select all
    positive functional kinds; current incompatible_with declarations for the
    same directed pair block those candidates, regardless of relation order.
    No relation certifies compatibility, no score is learned, and references
    are preserved without reading them. count counts returned matches only.
    """
    indexed = _catalogue(catalog)
    validate_asset_relations(document)
    if document["catalog_id"] != catalog["catalog_id"]:
        raise ValueError("Relations belong to another catalogue identity.")
    _text(source_id, "source_id")
    if source_id not in indexed:
        raise ValueError("Query source_id is not selected in the catalogue.")
    if type(intent) is not str or intent not in {"similar", "complementary"}:
        raise ValueError("intent must be similar or complementary.")
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError("limit must be an integer from 1 to 256.")
    kinds = {"similar_to"} if intent == "similar" else _COMPLEMENTARY_KINDS
    valid = []
    unapplied = []
    for relation in document["relations"]:
        reasons = _unapplied(relation, indexed)
        if reasons:
            unapplied.append({
                "id": relation["id"], "source": relation["source"],
                "target": relation["target"], "reasons": reasons,
            })
        elif relation["source"]["id"] == source_id:
            valid.append(relation)
    by_target: dict[str, list[dict[str, Any]]] = {}
    blockers: dict[str, list[dict[str, Any]]] = {}
    for relation in valid:
        target = relation["target"]["id"]
        if relation["kind"] in kinds:
            by_target.setdefault(target, []).append(relation)
        elif intent == "complementary" and relation["kind"] == "incompatible_with":
            blockers.setdefault(target, []).append(relation)
    matches = []
    blocked = []
    for target, relations in sorted(by_target.items()):
        candidate = {
            "target": indexed[target], "status": "caller_declared", "relations": relations,
        }
        if target in blockers:
            blocked.append({
                "target": indexed[target], "reason": "declared_incompatibility",
                "relations": relations, "blockers": blockers[target],
            })
        else:
            matches.append(candidate)
    query = {"source_id": source_id, "intent": intent, "limit": limit}
    catalogue_ref = {
        "id": catalog["catalog_id"], "generation": catalog["generation"],
        "snapshot_hash": catalog["snapshot_hash"],
    }
    relation_ref = {"id": document["id"], "relations_hash": document["relations_hash"]}
    result = {
        "schema": SEARCH_SCHEMA,
        "input_hash": hash_input({"catalog": catalogue_ref, "relations": relation_ref, "query": query}),
        "catalog": catalogue_ref, "relations": relation_ref, "query": query,
        "source": indexed[source_id], "matches": matches[:limit],
        "count": len(matches[:limit]), "truncated": len(matches) > limit,
        "blocked_candidates": blocked, "unapplied_relations": unapplied,
        "limits": {
            "relations": "caller_declared_not_verified",
            "evidence": "references_preserved_not_read_or_authenticated",
            "compatibility": "not_certified_no_geometry_or_constraint_execution",
            "navigation": "direct_outgoing_only_no_symmetry_or_transitivity",
            "ranking": "source_id_order_no_quality_score",
            "tag_acceptance": "does_not_approve_relations",
            "freshness": "exact_endpoint_reports_only_external_evidence_not_assessed",
        },
    }
    _canonical_size(result, MAX_SEARCH_BYTES, "Relation search")
    return deepcopy(result)
