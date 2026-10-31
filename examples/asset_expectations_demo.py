"""Authored reports illustrating all four advisory expectation outcomes."""

from __future__ import annotations

import argparse
import json

from examples.asset_catalog_demo import _png
from examples.ply_catalog_demo import cloud_fixture
from tiberium_ai.asset_expectations import EXPECTATIONS_SCHEMA, audit_asset_expectations
from tiberium_ai.asset_inspection import inspect_asset


def run_demo() -> dict:
    fixtures = [
        ("fixture:image", "image.png", _png()),
        ("fixture:cloud", "points.ply", cloud_fixture()),
        ("fixture:text", "note.txt", b"An authored note without a scene classifier."),
    ]
    reports = [inspect_asset(data, filename=name, source_id=identity, revision="v1")
               for identity, name, data in fixtures]
    expectations = {
        "schema": EXPECTATIONS_SCHEMA, "id": "fixture:delivery-requirements",
        "assets": [
            {"source": {"id": "fixture:image", "revision": "v1"}, "checks": [
                {"id": "format", "fact": "format.detected", "op": "eq", "value": "png"},
                {"id": "width", "fact": "metadata.width", "op": "gte", "value": 1},
            ]},
            {"source": {"id": "fixture:cloud", "revision": "v1"}, "checks": [
                {"id": "faces-required", "fact": "metadata.observed_face_count", "op": "gte", "value": 1},
            ]},
            {"source": {"id": "fixture:text", "revision": "v1"}, "checks": [
                {"id": "forest-proposal", "fact": "tag:topic:forest", "op": "eq", "value": True},
            ]},
            {"source": {"id": "fixture:sound", "revision": "v1"}, "checks": [
                {"id": "complete", "fact": "sample.complete", "op": "eq", "value": True},
            ]},
        ],
    }
    return {
        "data_origin": "authored_fixtures_not_a_personal_asset_inventory",
        "reports": reports, "expectations": expectations,
        "audit": audit_asset_expectations(reports, expectations),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true")
    options = parser.parse_args()
    demo = run_demo()
    output = demo if not options.summary else {
        "data_origin": demo["data_origin"], "summary": demo["audit"]["summary"],
        "assets": [{"source": row["source"], "status": row["status"]}
                   for row in demo["audit"]["results"]],
    }
    print(json.dumps(output, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
