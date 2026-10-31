"""Functional relations preserve direction, exact revisions and declared evidence."""

from copy import deepcopy
import hashlib
import json

import pytest

from tiberium_ai.asset_catalog_snapshot import (
    create_asset_catalog, put_asset_report, remove_asset_report,
)
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_relations import (
    MAX_RELATIONS, MAX_RELATIONS_BYTES, RELATIONS_SCHEMA, SEARCH_SCHEMA,
    bind_asset_relation, bind_asset_relations, create_asset_relations,
    search_asset_relations, validate_asset_relations,
)
from tiberium_ai.asset_tag_journal import validated_review_report_hash


def digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def rehash(document):
    document["relations_hash"] = digest({key: value for key, value in document.items() if key != "relations_hash"})
    return document


def report(source, revision="v1", payload=None):
    return inspect_asset(
        (payload or ("fixture " + source).encode()), filename=source + ".txt",
        source_id=source, revision=revision,
    )


def put(catalog, item):
    old = next((r for r in catalog["reports"] if r["source"]["id"] == item["source"]["id"]), None)
    return put_asset_report(
        catalog, item, expected_head=catalog["snapshot_hash"],
        expected_report_hash=validated_review_report_hash(old) if old else None,
    )


def catalogue(*ids):
    value = create_asset_catalog("architecture-fixture")
    for identifier in ids or ("house", "house-alt", "roof", "stairs"):
        value = put(value, report(identifier))
    return value


def evidence(reference="fixture:recipe", revision="recipe-v1", locator="/components/roof"):
    return [{"reference": reference, "revision": revision, "locator": locator}]


def relation(catalog, *, identity="roof-link", source="house", target="roof", kind="complements", proof=None):
    return bind_asset_relation(
        catalog, relation_id=identity, source_id=source, target_id=target,
        kind=kind, evidence=proof if proof is not None else evidence(),
    )


def sidecar(catalog, *relations):
    return create_asset_relations(catalog, list(relations), relations_id="fixture:relations")


def targets(result):
    return [item["target"]["id"] for item in result["matches"]]


def test_sidecar_is_closed_and_canonical_without_mutating_inputs():
    catalog = catalogue()
    proof = evidence("fixture:recette-é")
    edge = relation(catalog, proof=proof)
    before = deepcopy((catalog, edge, proof))
    document = sidecar(catalog, edge)
    assert set(document) == {"schema", "id", "catalog_id", "relations", "relations_hash"}
    assert document["schema"] == RELATIONS_SCHEMA
    assert document["relations_hash"] == digest({key: value for key, value in document.items() if key != "relations_hash"})
    assert edge["source"] == {
        "id": "house", "revision": "v1", "report_hash": digest(next(r for r in catalog["reports"] if r["source"]["id"] == "house")),
    }
    assert validate_asset_relations(json.loads(json.dumps(document))) is None
    assert (catalog, edge, proof) == before
    document["relations"][0]["evidence"][0]["reference"] = "changed"
    proof[0]["reference"] = "changed too"
    assert edge["evidence"][0]["reference"] == "fixture:recette-é"


def test_query_separates_similarity_and_complementarity_and_preserves_evidence():
    catalog = catalogue()
    similar = relation(catalog, identity="variant", target="house-alt", kind="similar_to")
    complement = relation(catalog, identity="roof")
    document = sidecar(catalog, similar, complement)
    result = search_asset_relations(catalog, document, source_id="house", intent="complementary")
    assert result["schema"] == SEARCH_SCHEMA
    assert targets(result) == ["roof"]
    assert result["matches"][0]["relations"] == [complement]
    assert result["matches"][0]["status"] == "caller_declared"
    assert result["limits"]["compatibility"] == "not_certified_no_geometry_or_constraint_execution"
    assert targets(search_asset_relations(catalog, document, source_id="house", intent="similar")) == ["house-alt"]
    result["matches"][0]["relations"][0]["evidence"].clear()
    assert document["relations"][0]["evidence"] == evidence()


@pytest.mark.parametrize("kind", ["complements", "requires", "used_with", "compatible_with", "tested_by", "fixed_by"])
def test_functional_kinds_remain_declared_candidates(kind):
    catalog = catalogue()
    document = sidecar(catalog, relation(catalog, kind=kind))
    result = search_asset_relations(catalog, document, source_id="house")
    assert targets(result) == ["roof"]
    assert result["matches"][0]["relations"][0]["kind"] == kind
    assert search_asset_relations(catalog, document, source_id="house", intent="similar")["matches"] == []


def test_no_reverse_transitive_or_dissimilarity_inference():
    catalog = catalogue()
    document = sidecar(catalog, relation(catalog), relation(catalog, identity="roof-stairs", source="roof", target="stairs"))
    assert targets(search_asset_relations(catalog, document, source_id="house")) == ["roof"]
    assert targets(search_asset_relations(catalog, document, source_id="stairs")) == []
    assert targets(search_asset_relations(catalog, sidecar(catalog), source_id="house")) == []


@pytest.mark.parametrize("blocker_id", ["a-blocker", "z-blocker"])
def test_directed_incompatibility_blocks_functional_candidates_in_any_order(blocker_id):
    catalog = catalogue()
    candidate = relation(catalog)
    blocker = relation(catalog, identity=blocker_id, kind="incompatible_with", proof=evidence(locator="/clearance/failure"))
    document = sidecar(catalog, candidate, blocker)
    result = search_asset_relations(catalog, document, source_id="house")
    assert result["matches"] == [] and result["count"] == 0
    assert result["blocked_candidates"] == [{
        "target": candidate["target"], "reason": "declared_incompatibility",
        "relations": [candidate], "blockers": [blocker],
    }]


def test_incompatibility_is_not_implicitly_symmetric_and_does_not_remove_similarity():
    catalog = catalogue()
    candidate = relation(catalog)
    reverse = relation(catalog, identity="reverse", source="roof", target="house", kind="incompatible_with")
    similar = relation(catalog, identity="similar", kind="similar_to")
    direct = relation(catalog, identity="direct", kind="incompatible_with")
    assert targets(search_asset_relations(catalog, sidecar(catalog, candidate, reverse), source_id="house")) == ["roof"]
    assert targets(search_asset_relations(catalog, sidecar(catalog, similar, direct), source_id="house", intent="similar")) == ["roof"]


@pytest.mark.parametrize("endpoint", ["house", "roof"])
@pytest.mark.parametrize("change,reason", [
    ("revision", "source_revision_changed"), ("report", "report_changed"), ("remove", "source_not_in_catalogue"),
])
def test_stale_endpoint_is_excluded_with_exact_reason(endpoint, change, reason):
    catalog = catalogue()
    document = sidecar(catalog, relation(catalog))
    if change == "remove":
        old = next(r for r in catalog["reports"] if r["source"]["id"] == endpoint)
        changed = remove_asset_report(catalog, endpoint, expected_head=catalog["snapshot_hash"], expected_report_hash=digest(old))
    else:
        changed = put(catalog, report(endpoint, revision="v2" if change == "revision" else "v1", payload=b"different exact evidence"))
    if endpoint == "house" and change == "remove":
        with pytest.raises(ValueError, match="Query source_id"):
            search_asset_relations(changed, document, source_id="house")
        query_source = "roof"
    else:
        query_source = "house"
    result = search_asset_relations(changed, document, source_id=query_source)
    assert result["matches"] == []
    assert result["unapplied_relations"][0]["reasons"] == [{
        "endpoint": "source" if endpoint == "house" else "target", "reason": reason,
    }]
    assert targets(search_asset_relations(catalog, document, source_id="house")) == ["roof"]


def test_stale_blocker_does_not_become_a_current_claim_and_new_claim_is_explicit():
    old = catalogue()
    blocker = relation(old, identity="old-blocker", kind="incompatible_with")
    changed = put(old, report("roof", revision="v2"))
    new_claim = relation(changed, identity="new-claim")
    # A mixed historical/current sidecar may be loaded independently, but the
    # creation helper refuses to call this stale declaration current.
    with pytest.raises(ValueError, match="exact current"):
        sidecar(changed, blocker, new_claim)
    mixed = sidecar(old, blocker)
    mixed["relations"].append(new_claim)
    mixed["relations"].sort(key=lambda edge: edge["id"])
    rehash(mixed)
    result = search_asset_relations(changed, mixed, source_id="house")
    assert targets(result) == ["roof"]
    assert result["blocked_candidates"] == []
    assert [item["id"] for item in result["unapplied_relations"]] == ["old-blocker"]


def test_unrelated_catalogue_updates_preserve_exact_relations_but_change_query_identity():
    catalog = catalogue()
    document = sidecar(catalog, relation(catalog))
    first = search_asset_relations(catalog, document, source_id="house")
    changed = put(catalog, report("unrelated"))
    second = search_asset_relations(changed, document, source_id="house")
    assert first["matches"] == second["matches"]
    assert first["input_hash"] != second["input_hash"]


def test_grouping_order_limit_and_truncation_count_candidates_not_assertions():
    catalog = catalogue()
    document = sidecar(catalog,
        relation(catalog, identity="z"), relation(catalog, identity="a", kind="used_with"),
        relation(catalog, identity="stairs", target="stairs"),
    )
    result = search_asset_relations(catalog, document, source_id="house", limit=1)
    assert targets(result) == ["roof"] and result["count"] == 1 and result["truncated"] is True
    assert [item["id"] for item in result["matches"][0]["relations"]] == ["a", "z"]
    complete = search_asset_relations(catalog, document, source_id="house", limit=2)
    assert targets(complete) == ["roof", "stairs"] and complete["truncated"] is False


def test_batch_binding_is_equivalent_and_closed():
    catalog = catalogue()
    declaration = {"id": "roof-link", "source_id": "house", "target_id": "roof", "kind": "complements", "evidence": evidence()}
    assert bind_asset_relations(catalog, [declaration], relations_id="fixture:relations") == sidecar(catalog, relation(catalog))
    assert bind_asset_relations(catalog, [], relations_id="empty")["relations"] == []
    with pytest.raises(ValueError, match="exactly"):
        bind_asset_relations(catalog, [dict(declaration, status="verified")], relations_id="x")


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(extra=True),
    lambda d: d.update(schema="parcimonia.asset-relations/v2"),
    lambda d: d.update(relations_hash="a" * 64),
    lambda d: d["relations"][0].update(status="verified"),
    lambda d: d["relations"][0].update(kind="causes"),
    lambda d: d["relations"][0]["source"].update(extra=True),
    lambda d: d["relations"][0]["target"].update(report_hash="A" * 64),
    lambda d: d["relations"][0]["evidence"][0].update(extra=True),
    lambda d: d["relations"][0]["evidence"][0].update(locator=""),
    lambda d: d["relations"][0].update(evidence=[]),
    lambda d: d["relations"][0].update(evidence=evidence() * 2),
    lambda d: d["relations"][0].update(target=d["relations"][0]["source"]),
])
def test_invalid_sidecars_are_rejected_even_if_a_caller_recomputes_the_hash(mutation):
    catalog = catalogue()
    document = sidecar(catalog, relation(catalog))
    mutation(document)
    # A pure hash mismatch is checked as supplied; all structural attacks are
    # rehashed to ensure hashing alone is not being mistaken for validation.
    if document["relations_hash"] != "a" * 64:
        rehash(document)
    with pytest.raises(ValueError):
        validate_asset_relations(document)


@pytest.mark.parametrize("limit", [True, False, 0, -1, 257, 1.0, "1", None])
def test_limit_requires_a_bounded_exact_integer(limit):
    catalog = catalogue()
    with pytest.raises(ValueError, match="limit"):
        search_asset_relations(catalog, sidecar(catalog), source_id="house", limit=limit)


@pytest.mark.parametrize("intent", ["duplicate", "all", "", None, True])
def test_intent_is_explicit(intent):
    catalog = catalogue()
    with pytest.raises(ValueError, match="intent"):
        search_asset_relations(catalog, sidecar(catalog), source_id="house", intent=intent)


def test_foreign_catalogue_identity_is_not_equivalent_to_matching_report_bytes():
    catalog = catalogue()
    document = sidecar(catalog, relation(catalog))
    foreign = deepcopy(catalog)
    foreign["catalog_id"] = "other"
    foreign["snapshot_hash"] = digest({key: value for key, value in foreign.items() if key != "snapshot_hash"})
    with pytest.raises(ValueError, match="another catalogue"):
        search_asset_relations(foreign, document, source_id="house")


def test_creation_rejects_duplicate_ids_missing_endpoints_and_stale_reports():
    catalog = catalogue()
    edge = relation(catalog)
    with pytest.raises(ValueError, match="unique"):
        sidecar(catalog, edge, edge)
    with pytest.raises(ValueError, match="endpoints"):
        relation(catalog, target="missing")
    changed = put(catalog, report("roof", revision="v2"))
    with pytest.raises(ValueError, match="exact current"):
        sidecar(changed, edge)


def test_relations_are_sorted_and_input_order_cannot_reorder_results():
    catalog = catalogue()
    first = relation(catalog, identity="z", target="stairs")
    second = relation(catalog, identity="a")
    assert sidecar(catalog, first, second) == sidecar(catalog, second, first)
    document = sidecar(catalog, first, second)
    document["relations"].reverse()
    with pytest.raises(ValueError, match="sorted"):
        validate_asset_relations(rehash(document))


def test_exact_json_boundary_rejects_cycles_subclasses_and_nonfinite_values():
    catalog = catalogue()
    edge = relation(catalog)
    class Text(str):
        pass
    class Array(list):
        pass
    bad = [edge]
    bad.append(bad)
    for relations in (bad, (edge,), Array([edge]), [dict(edge, id=Text("subclass"))], [dict(edge, evidence=float("nan"))]):
        with pytest.raises(ValueError):
            create_asset_relations(catalog, relations, relations_id="fixture")
    with pytest.raises(ValueError):
        relation(catalog, proof=evidence(reference="\ud800"))


def test_relation_count_boundary_and_total_byte_budget():
    catalog = catalogue()
    edge = relation(catalog)
    maximum = [dict(edge, id=f"link-{i:03}") for i in range(MAX_RELATIONS)]
    document = create_asset_relations(catalog, maximum, relations_id="maximum")
    assert len(document["relations"]) == MAX_RELATIONS
    with pytest.raises(ValueError, match="at most"):
        create_asset_relations(catalog, maximum + [dict(edge, id="overflow")], relations_id="overflow")
    huge_evidence = [
        {"reference": "r" * 4095 + str(i), "revision": "v" * 4096, "locator": "l" * 4096}
        for i in range(8)
    ]
    large_edge = relation(catalog, proof=huge_evidence)
    too_large = [dict(large_edge, id=f"large-{i:03}") for i in range(12)]
    assert len(json.dumps(too_large).encode()) > MAX_RELATIONS_BYTES
    with pytest.raises(ValueError, match="exceeds"):
        create_asset_relations(catalog, too_large, relations_id="large")
