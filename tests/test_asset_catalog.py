"""Pure catalogue search respects proposal, identity and CRS boundaries."""

from copy import deepcopy
import json

import pytest

from tiberium_ai.asset_catalog import search_asset_reports


def _tag(namespace="modality", value="image"):
    return {"namespace": namespace, "value": value, "status": "proposed", "basis": "fixture", "evidence_refs": ["fixture:evidence"]}


def _report(identifier="asset-a", revision="v1", tags=None, spatial=None):
    return {
        "schema": "parcimonia.asset-inspection/v1",
        "source": {"id": identifier, "revision": revision, "filename": "fixture.png"},
        "input_hash": "1" * 64,
        "sample": {"sha256": "0" * 64, "bytes": 3, "complete": True, "total_bytes": 3, "content_sha256": "0" * 64},
        "analyser": {"id": "asset-inspection", "version": "1"},
        "mode": "shadow", "status": "inspected",
        "format": {"detected": "png", "media_type": "image/png", "basis": "signature", "extension_hint": "png", "extension_conflict": False},
        "modalities": ["image"], "metadata": [],
        "tag_proposals": [_tag()] if tags is None else tags,
        "evidence": [{"id": "fixture:evidence", "kind": "fixture"}],
        "spatial": spatial, "reason_codes": [], "limits": {},
    }


def _spatial(bbox=None, **updates):
    result = {"crs": "OGC:CRS84", "axis_order": ["longitude", "latitude"], "units": "degrees", "position_count": 1, "bbox": [2, 48, 2, 48] if bbox is None else bbox}
    result.update(updates)
    return result


def test_default_listing_is_sorted_and_explicitly_unverified():
    reports = [_report("z"), _report("a", "v2"), _report("a", "v1")]
    result = search_asset_reports(reports)
    assert result["schema"] == "parcimonia.asset-search/v1"
    assert [(item["source"]["id"], item["source"]["revision"]) for item in result["matches"]] == [("a", "v1"), ("a", "v2"), ("z", "v1")]
    assert result["count"] == 3 and result["truncated"] is False
    assert all(item["matched_tags"] == [] and item["spatial_match"] is None for item in result["matches"])
    assert result["limits"]["tags"] == "proposals_only"
    assert result["limits"]["inputs"] == "caller_supplied_unverified"


def test_exact_tags_use_and_not_or_or_substrings():
    first = _report("both", tags=[_tag("modality", "image"), _tag("topic", "tree")])
    second = _report("one", tags=[_tag("modality", "image")])
    third = _report("substring", tags=[_tag("modality", "image"), _tag("topic", "trees")])
    result = search_asset_reports([first, second, third], tags=["topic:tree", "modality:image"])
    assert [item["source"]["id"] for item in result["matches"]] == ["both"]
    assert result["matches"][0]["matched_tags"] == ["modality:image", "topic:tree"]


@pytest.mark.parametrize("query", [["Modality:image"], ["modality:Image"]])
def test_tag_matching_is_case_sensitive(query):
    assert search_asset_reports([_report()], tags=query)["count"] == 0


def test_first_colon_separates_namespace_from_value():
    report = _report(tags=[_tag("crs", "OGC:CRS84")])
    assert search_asset_reports([report], tags=["crs:OGC:CRS84"])["count"] == 1


def test_duplicate_query_filters_are_normalized_without_changing_and_semantics():
    result = search_asset_reports([_report()], tags=["modality:image", "modality:image"])
    assert result["query"]["tags"] == ["modality:image"]
    assert result["matches"][0]["matched_tags"] == ["modality:image"]


def test_same_content_different_asset_identities_remain_separate():
    result = search_asset_reports([_report("one"), _report("two")])
    assert result["count"] == 2
    assert result["matches"][0]["sample_sha256"] == result["matches"][1]["sample_sha256"]


def test_duplicate_source_identity_and_revision_is_rejected_even_with_different_hash():
    other = _report()
    other["input_hash"] = "2" * 64
    with pytest.raises(ValueError, match="Duplicate source"):
        search_asset_reports([_report(), other])


def test_limit_truncates_after_stable_sort_and_count_is_returned_count():
    result = search_asset_reports([_report("z"), _report("b"), _report("a")], limit=2)
    assert [item["source"]["id"] for item in result["matches"]] == ["a", "b"]
    assert result["count"] == 2
    assert result["truncated"] is True
    assert search_asset_reports([_report()], limit=1)["truncated"] is False


def test_bbox_overlap_is_an_envelope_candidate_and_combines_with_tags():
    result = search_asset_reports([_report(spatial=_spatial())], tags=["modality:image"], bbox=[1, 47, 3, 49])
    assert result["count"] == 1
    assert result["matches"][0]["spatial_match"] == "envelope_overlap_candidate"
    assert result["limits"]["spatial"] == "envelope_only_no_geometry_verification"
    assert search_asset_reports([_report(spatial=_spatial())], tags=["topic:absent"], bbox=[1, 47, 3, 49])["count"] == 0


def test_touching_boundary_matches_but_nonoverlap_does_not():
    report = _report(spatial=_spatial())
    assert search_asset_reports([report], bbox=[2, 48, 4, 50])["count"] == 1
    assert search_asset_reports([report], bbox=[3, 48, 4, 50])["count"] == 0


def test_missing_or_unknown_crs_does_not_match_and_no_reprojection_is_attempted():
    unknown = _report("unknown", spatial=_spatial([500000, 5000000, 500100, 5000100], crs="EPSG:32631", units="metres", axis_order=["easting", "northing"]))
    missing = _report("missing")
    no_bbox = _report("no-bbox", spatial=_spatial(bbox=None, position_count=0))
    no_bbox["spatial"]["bbox"] = None
    assert search_asset_reports([unknown, missing, no_bbox], tags=["modality:image"])["count"] == 3
    assert search_asset_reports([unknown, missing, no_bbox], bbox=[-180, -90, 180, 90])["count"] == 0


@pytest.mark.parametrize("bbox", [
    [True, 0, 1, 1], [0, False, 1, 1], [0, 0, float("nan"), 1],
    [0, 0, 1, float("inf")], [-181, 0, 0, 1], [0, -91, 1, 0],
    [0, 0, 181, 1], [0, 0, 1, 91], [170, 0, -170, 1],
    [0, 2, 1, 1], [0, 0, 1], (0, 0, 1, 1),
])
def test_query_bbox_rejects_invalid_numbers_bounds_axes_and_wrap(bbox):
    with pytest.raises(ValueError):
        search_asset_reports([_report()], bbox=bbox)


@pytest.mark.parametrize("bbox", [[0, True, 1, 2], [0, float("nan"), 1, 2], [0, -91, 1, 2]])
def test_invalid_report_coordinates_are_rejected_even_without_spatial_filter(bbox):
    with pytest.raises(ValueError):
        search_asset_reports([_report(spatial=_spatial(bbox))])


@pytest.mark.parametrize("updates", [
    {"axis_order": ["latitude", "longitude"]}, {"units": "radians"},
    {"position_count": True}, {"position_count": -1}, {"crs": None},
])
def test_invalid_spatial_declarations_do_not_silently_become_unlocated(updates):
    with pytest.raises(ValueError):
        search_asset_reports([_report(spatial=_spatial(**updates))])


@pytest.mark.parametrize("count,bounds", [(0, [2, 48, 2, 48]), (1, None)])
def test_crs84_count_and_bbox_cannot_disagree(count, bounds):
    spatial = _spatial(position_count=count)
    spatial["bbox"] = bounds
    with pytest.raises(ValueError, match="position_count and bbox"):
        search_asset_reports([_report(spatial=spatial)], bbox=[1, 47, 3, 49])


@pytest.mark.parametrize("status", ["validated", "rejected", "unknown", True])
def test_only_proposed_tag_state_is_supported(status):
    report = _report()
    report["tag_proposals"][0]["status"] = status
    with pytest.raises(ValueError):
        search_asset_reports([report])


@pytest.mark.parametrize("value", ["0" * 63, "A" * 64, "g" * 64, None, 1])
@pytest.mark.parametrize("field", ["input_hash", "sample_sha256"])
def test_hashes_must_be_present_lowercase_sha256(field, value):
    report = _report()
    if field == "input_hash":
        report["input_hash"] = value
    else:
        report["sample"]["sha256"] = value
    with pytest.raises(ValueError):
        search_asset_reports([report])


@pytest.mark.parametrize("field", ["source", "input_hash", "sample", "tag_proposals", "spatial"])
def test_missing_required_report_fields_fail_closed(field):
    report = _report()
    del report[field]
    with pytest.raises(ValueError):
        search_asset_reports([report])


def test_prefix_and_full_content_provenance_are_not_interchangeable():
    prefix = _report()
    prefix["sample"].update(complete=False, total_bytes=10, content_sha256=None)
    assert search_asset_reports([prefix])["count"] == 1
    prefix["sample"]["total_bytes"] = None
    assert search_asset_reports([prefix])["count"] == 1
    prefix["sample"]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        search_asset_reports([prefix])
    complete = _report()
    complete["sample"]["total_bytes"] = 10
    with pytest.raises(ValueError):
        search_asset_reports([complete])


@pytest.mark.parametrize("update", [
    {"bytes": True}, {"bytes": -1}, {"total_bytes": True},
    {"complete": 1}, {"complete": False, "content_sha256": None, "total_bytes": 3},
    {"content_sha256": "2" * 64},
])
def test_sample_provenance_validation(update):
    report = _report()
    report["sample"].update(update)
    with pytest.raises(ValueError):
        search_asset_reports([report])


@pytest.mark.parametrize("size,total,complete", [
    (1024 * 1024 + 1, 1024 * 1024 + 1, True),
    (3, 2**63, False),
])
def test_sample_size_and_total_respect_the_named_producer_bounds(size, total, complete):
    report = _report()
    report["sample"].update(bytes=size, total_bytes=total, complete=complete, content_sha256=report["sample"]["sha256"] if complete else None)
    with pytest.raises(ValueError):
        search_asset_reports([report])


def test_producer_sample_size_and_total_boundaries_are_accepted():
    report = _report()
    report["sample"].update(bytes=1024 * 1024, total_bytes=1024 * 1024)
    assert search_asset_reports([report])["count"] == 1
    report["sample"].update(complete=False, total_bytes=2**63 - 1, content_sha256=None)
    assert search_asset_reports([report])["count"] == 1


@pytest.mark.parametrize("refs", [[], ["missing"], [1], "fixture:evidence"])
def test_tag_evidence_references_must_point_to_known_ids(refs):
    report = _report()
    report["tag_proposals"][0]["evidence_refs"] = refs
    with pytest.raises(ValueError):
        search_asset_reports([report])


def test_duplicate_evidence_ids_are_ambiguous():
    report = _report()
    report["evidence"].append(deepcopy(report["evidence"][0]))
    with pytest.raises(ValueError, match="Evidence IDs"):
        search_asset_reports([report])


def test_malformed_nonmatching_report_is_not_skipped_after_limit():
    bad = _report("z")
    bad["tag_proposals"][0]["status"] = "validated"
    with pytest.raises(ValueError):
        search_asset_reports([_report("a"), bad], tags=["topic:absent"], limit=1)


def test_result_and_inputs_do_not_share_mutable_aliases():
    report = _report(spatial=_spatial())
    original = deepcopy(report)
    query_tags, query_bbox = ["modality:image"], [1, 47, 3, 49]
    result = search_asset_reports([report], tags=query_tags, bbox=query_bbox)
    result["matches"][0]["source"]["id"] = "changed-output"
    result["matches"][0]["matched_tags"].append("topic:new")
    result["query"]["bbox"][0] = -180
    assert report == original
    assert query_tags == ["modality:image"] and query_bbox == [1, 47, 3, 49]


def test_input_hash_changes_when_source_report_changes():
    report = _report()
    first = search_asset_reports([report])["input_hash"]
    report["source"]["revision"] = "v2"
    assert search_asset_reports([report])["input_hash"] != first


@pytest.mark.parametrize("tags", ["modality:image", ["image"], [":image"], ["modality:"], [" modality:image"], ["modality: image"], [True]])
def test_query_tag_syntax_is_explicit(tags):
    with pytest.raises(ValueError):
        search_asset_reports([_report()], tags=tags)


@pytest.mark.parametrize("limit", [True, 0, 257, 1.5, "1"])
def test_invalid_limits_are_not_coerced(limit):
    with pytest.raises(ValueError):
        search_asset_reports([], limit=limit)


def test_report_batch_bound_and_empty_batch():
    assert search_asset_reports([])["matches"] == []
    assert search_asset_reports([])["truncated"] is False
    with pytest.raises(ValueError):
        search_asset_reports([_report(str(i)) for i in range(257)])
    with pytest.raises(ValueError):
        search_asset_reports(())


def test_real_inspector_report_is_compatible():
    from tiberium_ai.asset_inspection import inspect_asset
    report = inspect_asset(b"Hello World", filename="readme.txt", source_id="real-api-fixture", revision="v1")
    result = search_asset_reports([report], tags=["format:text"])
    assert result["count"] == 1
    assert result["matches"][0]["sample_sha256"] == report["sample"]["content_sha256"]


def test_real_geojson_inspection_matches_only_as_an_envelope_candidate():
    from tiberium_ai.asset_inspection import inspect_asset
    payload = json.dumps({"type": "Feature", "geometry": {"type": "Point", "coordinates": [2, 48]}, "properties": {}}).encode("utf-8")
    report = inspect_asset(payload, filename="map.geojson", source_id="real-api-geo", revision="v1")
    result = search_asset_reports([report], tags=["format:geojson"], bbox=[1, 47, 3, 49])
    assert result["count"] == 1
    assert result["matches"][0]["spatial_match"] == "envelope_overlap_candidate"
