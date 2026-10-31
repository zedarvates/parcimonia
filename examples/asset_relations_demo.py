"""Authored architecture candidates; no real model, geometry or compatibility test.

The example reuses actual catalogue reports and exact revision invalidation.
Evidence references below identify authored declarations, not external proofs.
"""

from __future__ import annotations

import json

from tiberium_ai.asset_catalog_snapshot import create_asset_catalog, put_asset_report
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_relations import bind_asset_relations, search_asset_relations
from tiberium_ai.asset_tag_journal import validated_review_report_hash


def _report(name: str, text: str, revision: str = "v1") -> dict:
    return inspect_asset(
        text.encode("utf-8"), filename=f"{name}.txt",
        source_id=f"fixture:{name}", revision=revision,
    )


def build_demo_inputs() -> tuple[dict, list[dict]]:
    """Return portable catalogue and declarations for the two CLI commands."""
    reports = [
        _report("house", "Maison de démonstration, recette déclarée A."),
        _report("house-variant", "Une autre maison de démonstration."),
        _report("roof", "Toit proposé par la recette A pour cette maison."),
        _report("stairs", "Escalier proposé, mais déclaré incompatible dans la recette A."),
    ]
    catalog = create_asset_catalog("fixture:uo-architecture")
    for report in reports:
        catalog = put_asset_report(
            catalog, report, expected_head=catalog["snapshot_hash"], expected_report_hash=None,
        )
    declarations = []
    for relation_id, target, kind in (
        ("variant", "house-variant", "similar_to"),
        ("roof", "roof", "complements"),
        ("stairs-proposal", "stairs", "requires"),
        ("stairs-conflict", "stairs", "incompatible_with"),
    ):
        declarations.append({
            "id": f"fixture:{relation_id}", "source_id": "fixture:house",
            "target_id": f"fixture:{target}", "kind": kind,
            "evidence": [{
                "reference": "fixture:architecture-recipe", "revision": "r1",
                "locator": f"/declarations/{relation_id}",
            }],
        })
    return catalog, declarations


def run_demo() -> dict:
    catalog, declarations = build_demo_inputs()
    document = bind_asset_relations(catalog, declarations, relations_id="fixture:architecture-links")
    # Exercise the actual portable representation before searching it.
    document = json.loads(json.dumps(document, ensure_ascii=False, allow_nan=False))
    similar = search_asset_relations(catalog, document, source_id="fixture:house", intent="similar")
    complementary = search_asset_relations(catalog, document, source_id="fixture:house", intent="complementary")
    roof = next(value for value in catalog["reports"] if value["source"]["id"] == "fixture:roof")
    changed = put_asset_report(
        catalog, _report("roof", "Toit modifié : ancienne relation à réexaminer.", "v2"),
        expected_head=catalog["snapshot_hash"], expected_report_hash=validated_review_report_hash(roof),
    )
    after_change = search_asset_relations(changed, document, source_id="fixture:house", intent="complementary")
    reverse = search_asset_relations(catalog, document, source_id="fixture:roof", intent="complementary")
    return {
        "data_origin": "authored_fixtures", "real_geometry_checked": False,
        "similar": similar, "complementary": complementary,
        "after_roof_revision": after_change, "reverse_query": reverse,
        "catalogue_unchanged": catalog["snapshot_hash"] == complementary["catalog"]["snapshot_hash"],
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=True, sort_keys=True, allow_nan=False))
