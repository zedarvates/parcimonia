"""Authored GPX coordinates through inspection, saved-catalogue API and review.

All positions are invented for protocol verification. Links and extension
positions are deliberately untrusted inputs, without external resource access.
"""

from __future__ import annotations

import json

from tiberium_ai.asset_catalog import search_asset_reports
from tiberium_ai.asset_catalog_snapshot import create_asset_catalog, export_asset_reports, put_asset_report
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import append_tag_decision, create_tag_journal, validated_review_report_hash
from tiberium_ai.asset_tag_review import search_reviewed_assets


GPX_FIXTURE = b'''<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:x="urn:parcimonia:authored-fixture"
     version="1.1" creator="parcimonia-authored-fixture">
  <metadata>
    <name>Robot &amp; jardin</name>
    <link href="https://example.invalid/reference-never-fetched"/>
    <bounds minlat="-80" minlon="-100" maxlat="80" maxlon="100"/>
  </metadata>
  <wpt lat="2.0" lon="1.0"/>
  <rte>
    <rtept lat="2.2" lon="1.2"/>
    <rtept lat="2.4" lon="1.4"/>
  </rte>
  <trk>
    <trkseg>
      <trkpt lat="2.6" lon="1.6"/>
      <trkpt lat="2.8" lon="1.8"/>
    </trkseg>
    <trkseg><trkpt lat="3.0" lon="2.0"/></trkseg>
  </trk>
  <extensions><x:trkpt lat="80" lon="90"/></extensions>
</gpx>'''


def run_demo() -> dict:
    report = inspect_asset(GPX_FIXTURE, filename="fixture.gpx", source_id="fixture:gpx", revision="v1")
    empty = create_asset_catalog("fixture:gpx-catalog")
    catalog = put_asset_report(empty, report, expected_head=empty["snapshot_hash"], expected_report_hash=None)
    # Exercise JSON serialization without treating the hash as authentication.
    catalog = json.loads(json.dumps(catalog, ensure_ascii=False, allow_nan=False))
    reports = export_asset_reports(catalog)
    journal = create_tag_journal()
    query = {"tags": ["format:gpx"], "bbox": [0, 0, 4, 4]}
    before = search_reviewed_assets(reports, journal, **query)
    accepted = append_tag_decision(
        journal, report, namespace="format", value="gpx", action="accept",
        actor_id="fixture:reviewer", reason="Authored coordinate-profile fixture inspected.",
        event_id="fixture:gpx-review", expected_head=None,
    )
    after = search_reviewed_assets(reports, accepted, **query)
    invalid_data = GPX_FIXTURE.replace(b'lat="3.0"', b'lat="93.0"')
    invalid = inspect_asset(invalid_data, filename="fixture.gpx", source_id="fixture:gpx", revision="v2")
    changed = put_asset_report(
        catalog, invalid, expected_head=catalog["snapshot_hash"],
        expected_report_hash=validated_review_report_hash(report),
    )
    positions = next(item for item in report["evidence"] if item["id"] == "gpx:positions")
    return {
        "data_origin": "authored_fixture_not_observed_gps", "source_sha256": report["sample"]["sha256"],
        "analyser": report["analyser"], "format": report["format"], "spatial": report["spatial"],
        "point_paths": [item["path"] for item in positions["points"]],
        "reason_codes": report["reason_codes"],
        "proposed_search": search_asset_reports(reports, **query),
        "accepted_before_review": before["count"], "accepted_after_review": after["count"],
        "outside_bbox": search_reviewed_assets(reports, accepted, tags=["format:gpx"], bbox=[20, 20, 21, 21])["count"],
        "invalid_late_point_spatial": invalid["spatial"],
        "invalid_late_point_matches": search_asset_reports([invalid], bbox=[0, 0, 4, 4])["count"],
        "changed_report_accepted": search_reviewed_assets(export_asset_reports(changed), accepted, tags=["format:gpx"])["count"],
        "old_report_still_accepted": search_reviewed_assets(reports, accepted, **query)["count"],
        "catalog_ref": {"generation": catalog["generation"], "snapshot_hash": catalog["snapshot_hash"]},
        "model_calls": report["limits"]["model_calls"],
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=True, sort_keys=True, allow_nan=False))
