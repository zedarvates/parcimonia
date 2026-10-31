"""Authored handoff fixtures qualify provenance, not ffprobe or codec quality.

No native executable is invoked or read. Native identities/call records below
are caller declarations for the pure enrichment protocol.
"""

from copy import deepcopy
import hashlib
import json
import struct

import pytest

from tiberium_ai.asset_catalog import search_asset_reports
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_media_enrichment import enrich_asset_with_media
from tiberium_ai.asset_tag_journal import (
    append_tag_decision, create_tag_journal, validated_review_report_hash,
)
from tiberium_ai.asset_tag_review import project_tag_reviews, search_reviewed_assets
from tiberium_ai.media_evidence import parse_ffprobe_json
from tiberium_ai.verification import hash_input


PROFILE = "parcimonia.ffprobe-stream-profile/v1"
VERSION = "ffprobe version 7.1.1 Copyright fixture"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def wav():
    fmt = struct.pack("<HHIIHH", 1, 1, 8, 16, 2, 16)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", 16) + b"\x00" * 16
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


SOURCES = {
    "wav": (wav(), "fixture.wav", "wav"),
    "flac": (b"fLaC", "fixture.flac", "flac"),
    "ogg": (b"OggS", "fixture.ogg", "ogg"),
    "iso_bmff": (struct.pack(">I", 16) + b"ftypisom\x00\x00\x00\x00", "fixture.mp4", "mov"),
}


def call(phase, stdout):
    return {
        "phase": phase, "status": "completed", "returncode": 0,
        "stdout_sha256": sha(stdout), "stderr_sha256": sha(b""),
        "stdout_complete": True, "stderr_complete": True,
        "elapsed_ms": 0.25, "started": True, "error": None,
    }


def raw_document(demuxer="mov", streams=None):
    if streams is None:
        streams = [{"index": 0, "codec_type": "audio", "codec_name": "aac"}]
    return {"format": {"format_name": demuxer, "duration": "1.25"}, "streams": streams}


def replace_native_payload(observation, raw):
    payload = json.dumps(raw, ensure_ascii=False, allow_nan=False).encode("utf-8")
    observation["raw_json"] = payload.decode("utf-8")
    observation["projection"] = parse_ffprobe_json(payload, expected_demuxer=observation["profile"]["demuxer"])
    observation["native_calls"][1]["stdout_sha256"] = sha(payload)


def fixture(source_format="iso_bmff", *, raw=None, complete=True):
    data, filename, demuxer = SOURCES[source_format]
    inspection = inspect_asset(
        data, filename=filename, source_id="fixture:media-protocol", revision="fixture-1",
        complete=complete, **({} if complete else {"total_bytes": len(data) + 1}),
    )
    observation = {
        "schema": "parcimonia.asset-media-observation/v1",
        "source": deepcopy(inspection["source"]),
        "input_hash": hash_input({"fixture": "authored-media-handoff", "demuxer": demuxer}),
        "sample_sha256": sha(data), "source_complete": True,
        "backend": {
            "id": "ffprobe", "version": VERSION,
            "executable": "/declared-fixture-only/ffprobe",
            "executable_sha256": sha(b"declared fixture identity, not executable bytes"),
        },
        "profile": {"id": PROFILE, "source_format": source_format, "demuxer": demuxer},
        "status": "completed", "raw_json": "", "projection": {}, "reason_codes": [],
        "native_calls": [call("version", VERSION.encode("utf-8")), call("probe", b"")],
        "elapsed_ms": 0.5,
        "limits": {"fixture": "authored_protocol_only"},
    }
    replace_native_payload(observation, raw_document(demuxer) if raw is None else raw)
    return inspection, observation


def tag_keys(report):
    return {(tag["namespace"], tag["value"]) for tag in report["tag_proposals"]}


def added_keys(original, enriched):
    return tag_keys(enriched) - tag_keys(original)


def metadata(report, name):
    return [item for item in report["metadata"] if item["name"] == name]


@pytest.mark.parametrize("source_format", ["wav", "flac", "ogg", "iso_bmff"])
def test_supported_sources_preserve_existing_inspection_and_add_proposed_stream_tags(source_format):
    original, observation = fixture(source_format)
    report = enrich_asset_with_media(original, observation)
    assert set(report) == set(original)
    assert report["schema"] == "parcimonia.asset-inspection/v1"
    assert report["analyser"] == {"id": "asset-media-enrichment", "version": "1"}
    for key in ("source", "sample", "format", "spatial"):
        assert report[key] == original[key]
    assert set(original["modalities"]) <= set(report["modalities"])
    assert tag_keys(original) <= tag_keys(report)
    assert all(item in report["metadata"] for item in original["metadata"])
    assert all(item in report["evidence"] for item in original["evidence"])
    assert all(tag["status"] == "proposed" for tag in report["tag_proposals"])
    assert ("stream_type", "audio") in tag_keys(report)
    assert ("codec", "aac") in tag_keys(report)
    assert "audio" in report["modalities"]
    assert report["mode"] == "shadow" and report["status"] == "partial"
    assert validated_review_report_hash(report) == hash_input(report)


@pytest.mark.parametrize("attached,expected,forbidden", [
    (False, {("modality", "video")}, {("modality", "image"), ("media_feature", "attached_picture")}),
    (True, {("modality", "image"), ("media_feature", "attached_picture")}, {("modality", "video")}),
    (None, set(), {("modality", "video"), ("modality", "image"), ("media_feature", "attached_picture")}),
])
def test_video_and_attached_picture_modalities_require_an_explicit_disposition(attached, expected, forbidden):
    stream = {"index": 3, "codec_type": "video", "codec_name": "mjpeg"}
    if attached is not None:
        stream["disposition"] = {"attached_pic": int(attached)}
    original, observation = fixture(raw=raw_document(streams=[stream]))
    report = enrich_asset_with_media(original, observation)
    keys = added_keys(original, report)
    assert expected <= keys
    assert not forbidden & keys
    assert ("stream_type", "video") in keys
    assert ("codec", "mjpeg") in keys
    if attached is None:
        assert report["modalities"] == original["modalities"]
    else:
        assert ("image" if attached else "video") in report["modalities"]


@pytest.mark.parametrize("kind,codec", [
    ("subtitle", "hdmv_pgs_subtitle"), ("data", "bin_data"),
    ("attachment", "ttf"), ("unknown", None),
])
def test_non_audio_video_streams_do_not_invent_modalities_or_quality(kind, codec):
    stream = {"index": 4, "codec_type": kind}
    if codec is not None:
        stream["codec_name"] = codec
    original, observation = fixture(raw=raw_document(streams=[stream]))
    report = enrich_asset_with_media(original, observation)
    assert ("stream_type", kind) in added_keys(original, report)
    assert report["modalities"] == original["modalities"]
    assert ("modality", "text") not in added_keys(original, report)
    assert not any(tag["namespace"] in {"quality", "absence", "topic"} for tag in report["tag_proposals"])
    if codec is None:
        assert not any(tag["namespace"] == "codec" for tag in report["tag_proposals"])
    else:
        assert ("codec", codec) in tag_keys(report)


def test_each_stream_has_distinct_indexed_evidence_and_all_references_resolve():
    original, observation = fixture(raw=raw_document(streams=[
        {"index": 7, "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
        {"index": 2, "codec_type": "video", "codec_name": "h264", "width": 320, "height": 180, "disposition": {"attached_pic": 0}},
    ]))
    report = enrich_asset_with_media(original, observation)
    evidence = {item["id"]: item for item in report["evidence"]}
    assert len(evidence) == len(report["evidence"])
    assert len(metadata(report, "media_stream")) == 2
    assert len({item["evidence_ref"] for item in metadata(report, "media_stream")}) == 2
    for item in metadata(report, "media_stream"):
        assert item["evidence_ref"] in evidence
    for tag in report["tag_proposals"]:
        assert set(tag["evidence_refs"]) <= set(evidence)
    assert {("stream_type", "audio"), ("stream_type", "video"), ("codec", "aac"), ("codec", "h264")} <= tag_keys(report)

    summary = next(item for item in report["evidence"] if item["kind"] == "native_media_observation")
    assert summary["observation_hash"] == hash_input(observation)
    assert summary["backend"] == observation["backend"]
    assert summary["profile"] == observation["profile"]
    assert summary["source_sha256"] == original["sample"]["sha256"]
    assert summary["raw_stdout_sha256"] == sha(observation["raw_json"].encode("utf-8"))
    streams = [item for item in report["evidence"] if item["kind"] == "native_media_stream"]
    assert {item["stream"]["index"] for item in streams} == {7, 2}
    assert all(item["observation_hash"] == hash_input(observation) for item in streams)
    assert {item["id"] for item in streams} == {
        f"media:{hash_input(observation)}:stream:7", f"media:{hash_input(observation)}:stream:2",
    }


def test_duration_is_retained_as_reported_metadata_without_decode_or_measurement_claim():
    original, observation = fixture(raw=raw_document(streams=[
        {"index": 0, "codec_type": "audio", "codec_name": "aac", "duration": "1.20"},
    ]))
    report = enrich_asset_with_media(original, observation)
    assert len(metadata(report, "media_format")) == 1
    assert len(metadata(report, "media_observation")) == 1
    assert len(metadata(report, "media_stream")) == 1
    encoded = json.dumps(report)
    assert "reported" in encoded
    assert "measured_duration" not in encoded
    assert "confidence" not in encoded
    assert "no_audio" not in encoded
    assert "no_video" not in encoded


def test_shared_codec_proposal_retains_evidence_from_each_distinct_stream():
    original, observation = fixture(raw=raw_document(streams=[
        {"index": 0, "codec_type": "audio", "codec_name": "aac"},
        {"index": 9, "codec_type": "audio", "codec_name": "aac"},
    ]))
    report = enrich_asset_with_media(original, observation)
    codecs = [tag for tag in report["tag_proposals"] if tag["namespace"] == "codec" and tag["value"] == "aac"]
    assert len(codecs) == 1
    evidence = {item["id"]: item for item in report["evidence"]}
    linked_streams = [evidence[ref] for ref in codecs[0]["evidence_refs"] if evidence[ref]["kind"] == "native_media_stream"]
    assert {item["stream"]["index"] for item in linked_streams} == {0, 9}


def test_empty_observed_streams_do_not_assert_absence_of_audio_or_video():
    original, observation = fixture(raw=raw_document(streams=[]))
    report = enrich_asset_with_media(original, observation)
    assert report["modalities"] == original["modalities"]
    assert not metadata(report, "media_stream")
    assert not any(key[0] in {"stream_type", "codec", "absence"} for key in added_keys(original, report))
    assert report["status"] == "partial"


def test_unrequested_private_native_fields_refuse_the_handoff_instead_of_being_copied():
    original, observation = fixture()
    raw = json.loads(observation["raw_json"])
    raw["streams"][0]["tags"] = {"comment": "private-stream-comment"}
    raw["format"].update(filename="/private/path/do-not-publish.mp4", tags={"title": "private-format-title"})
    payload = json.dumps(raw).encode("utf-8")
    observation["raw_json"] = payload.decode("utf-8")
    observation["native_calls"][1]["stdout_sha256"] = sha(payload)
    with pytest.raises(ValueError):
        enrich_asset_with_media(original, observation)


def test_enrichment_is_pure_and_does_not_invoke_a_native_process(monkeypatch):
    import subprocess
    import tiberium_ai.native_process as native

    original, observation = fixture()

    def forbidden(*args, **kwargs):
        raise AssertionError("pure enrichment attempted native execution")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(native, "run_bounded", forbidden)
    assert enrich_asset_with_media(original, observation)["analyser"]["id"] == "asset-media-enrichment"


def test_inputs_and_result_do_not_share_mutable_containers():
    original, observation = fixture()
    original_before, observation_before = deepcopy(original), deepcopy(observation)
    report = enrich_asset_with_media(original, observation)
    report_before = deepcopy(report)
    assert original == original_before and observation == observation_before
    original["source"]["filename"] = "changed.mp4"
    original["metadata"].clear()
    observation["backend"]["version"] = "changed"
    observation["projection"]["streams"].clear()
    observation["native_calls"][1]["elapsed_ms"] = 99
    observation["limits"]["fixture"] = "changed"
    assert report == report_before
    report["source"]["id"] = "changed"
    metadata(report, "media_stream")[0]["value"]["index"] = 99
    report["tag_proposals"][-1]["evidence_refs"].append("foreign")
    assert enrich_asset_with_media(original_before, observation_before) == report_before


def test_catalogue_and_review_use_exact_enriched_report_without_implicit_acceptance():
    original, observation = fixture()
    report = enrich_asset_with_media(original, observation)
    assert search_asset_reports([report], tags=["codec:aac"])["count"] == 1
    journal = create_tag_journal()
    assert search_reviewed_assets([report], journal, tags=["codec:aac"])["count"] == 0
    assert search_reviewed_assets([report], journal, tags=["codec:aac"], states=["proposed"])["count"] == 1


def test_input_hash_binds_the_whole_original_inspection_not_only_its_source_digest():
    original, observation = fixture()
    first = enrich_asset_with_media(original, observation)
    changed = deepcopy(original)
    changed["reason_codes"].append("declared_additional_inspection_limit")
    second = enrich_asset_with_media(changed, observation)
    assert first["source"] == second["source"]
    assert first["sample"] == second["sample"]
    assert first["input_hash"] != second["input_hash"]
    assert "declared_additional_inspection_limit" in second["reason_codes"]


def test_matching_new_source_revision_does_not_inherit_reviewed_tags():
    original, observation = fixture()
    previous = enrich_asset_with_media(original, observation)
    journal = append_tag_decision(
        create_tag_journal(), previous, namespace="codec", value="aac", action="accept",
        actor_id="fixture-reviewer", reason="Previous declared revision reviewed",
        event_id="revision-review-1", expected_head=None,
    )
    original["source"]["revision"] = "fixture-2"
    observation["source"]["revision"] = "fixture-2"
    current = enrich_asset_with_media(original, observation)
    assert current["input_hash"] != previous["input_hash"]
    review = project_tag_reviews([current], journal)
    assert review["unapplied_events"][0]["reason"] == "source_revision_changed"
    assert search_reviewed_assets([current], journal, tags=["codec:aac"])["count"] == 0


@pytest.mark.parametrize("change", ["observation_hash", "elapsed", "call_elapsed", "backend", "limits", "raw"])
def test_changed_handoff_evidence_or_configuration_invalidates_the_old_review(change):
    original, observation = fixture()
    old = enrich_asset_with_media(original, observation)
    journal = append_tag_decision(
        create_tag_journal(), old, namespace="codec", value="aac", action="accept",
        actor_id="fixture-reviewer", reason="Authored media protocol fixture reviewed",
        event_id="media-review-1", expected_head=None,
    )
    assert search_reviewed_assets([old], journal, tags=["codec:aac"])["count"] == 1
    if change == "observation_hash":
        observation["input_hash"] = sha(b"different declared native configuration")
    elif change == "elapsed":
        observation["elapsed_ms"] += 1
    elif change == "call_elapsed":
        observation["native_calls"][1]["elapsed_ms"] += 1
    elif change == "backend":
        observation["backend"]["version"] += "-changed"
    elif change == "limits":
        observation["limits"]["configuration"] = "changed bounded setting"
    else:
        raw = json.loads(observation["raw_json"])
        raw["format"]["duration"] = "2.25"
        replace_native_payload(observation, raw)
    current = enrich_asset_with_media(original, observation)
    assert ("codec", "aac") in tag_keys(current)
    assert current["input_hash"] != old["input_hash"]
    assert hash_input(current) != hash_input(old)
    projected = project_tag_reviews([current], journal)
    assert projected["unapplied_events"][0]["reason"] == "report_changed"
    assert search_reviewed_assets([current], journal, tags=["codec:aac"])["count"] == 0


@pytest.mark.parametrize("field,value", [("id", "other"), ("revision", "fixture-2"), ("filename", "renamed.mp4")])
def test_all_source_identity_components_must_match_exactly(field, value):
    original, observation = fixture()
    observation["source"][field] = value
    with pytest.raises(ValueError):
        enrich_asset_with_media(original, observation)


@pytest.mark.parametrize("field,value", [
    ("sample_sha256", "f" * 64), ("sample_sha256", "A" * 64),
    ("source_complete", False), ("source_complete", 1),
    ("status", "failed"), ("status", "indeterminate"), ("status", {}),
    ("schema", []), ("elapsed_ms", True), ("elapsed_ms", -1),
    ("elapsed_ms", float("nan")), ("elapsed_ms", float("inf")),
])
def test_nonmatching_incomplete_or_malformed_observations_are_rejected(field, value):
    original, observation = fixture()
    observation[field] = value
    with pytest.raises(ValueError):
        enrich_asset_with_media(original, observation)


def test_matching_sample_digest_does_not_make_a_prefix_complete():
    original, observation = fixture(complete=False)
    assert original["sample"]["sha256"] == observation["sample_sha256"]
    with pytest.raises(ValueError):
        enrich_asset_with_media(original, observation)


@pytest.mark.parametrize("change", ["source_format", "demuxer", "profile_id", "extra_profile", "raw_demuxer"])
def test_source_profile_and_demuxer_must_remain_bound_to_the_inspection(change):
    original, observation = fixture()
    if change == "source_format":
        observation["profile"]["source_format"] = "wav"
    elif change == "demuxer":
        observation["profile"]["demuxer"] = "wav"
    elif change == "profile_id":
        observation["profile"]["id"] = "parcimonia.ffprobe-stream-profile/v2"
    elif change == "extra_profile":
        observation["profile"]["allowed_protocols"] = ["http"]
    else:
        raw = json.loads(observation["raw_json"])
        raw["format"]["format_name"] = "wav"
        payload = json.dumps(raw).encode("utf-8")
        observation["raw_json"] = payload.decode("utf-8")
        observation["native_calls"][1]["stdout_sha256"] = sha(payload)
    with pytest.raises(ValueError):
        enrich_asset_with_media(original, observation)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("field,value", [
    ("status", "timeout"), ("status", []), ("returncode", 1), ("returncode", False),
    ("started", False), ("started", 1), ("stdout_complete", False), ("stdout_complete", 1),
    ("stderr_complete", False), ("error", "declared-error"),
    ("elapsed_ms", True), ("elapsed_ms", float("inf")),
])
def test_both_native_calls_must_be_successful_complete_and_strictly_typed(index, field, value):
    original, observation = fixture()
    observation["native_calls"][index][field] = value
    with pytest.raises(ValueError):
        enrich_asset_with_media(original, observation)


@pytest.mark.parametrize("change", ["missing", "duplicate", "reordered", "probe_digest", "extra_call_field"])
def test_native_call_sequence_and_raw_payload_digest_are_validated(change):
    original, observation = fixture()
    if change == "missing":
        observation["native_calls"].pop()
    elif change == "duplicate":
        observation["native_calls"].append(deepcopy(observation["native_calls"][1]))
    elif change == "reordered":
        observation["native_calls"].reverse()
    elif change == "probe_digest":
        observation["native_calls"][1]["stdout_sha256"] = "f" * 64
    else:
        observation["native_calls"][1]["approved"] = True
    with pytest.raises(ValueError):
        enrich_asset_with_media(original, observation)


@pytest.mark.parametrize("change", ["projection", "boolean_index", "raw_text", "duplicate_json", "nonfinite_json"])
def test_projection_must_reproduce_the_exact_strict_raw_native_json(change):
    original, observation = fixture()
    if change == "projection":
        observation["projection"]["streams"][0]["codec"] = "flac"
    elif change == "boolean_index":
        observation["projection"]["streams"][0]["index"] = False
    elif change == "raw_text":
        observation["raw_json"] = observation["raw_json"].replace("aac", "flac")
    else:
        raw = '{"format":{"format_name":"mov"},"streams":[],"streams":[]}' if change == "duplicate_json" else '{"format":{"format_name":"mov","duration":NaN},"streams":[]}'
        observation["raw_json"] = raw
        observation["native_calls"][1]["stdout_sha256"] = sha(raw.encode("utf-8"))
    with pytest.raises(ValueError):
        enrich_asset_with_media(original, observation)


@pytest.mark.parametrize("where", ["observation", "source", "backend", "profile"])
def test_closed_handoff_schemas_do_not_silently_ignore_extra_fields(where):
    original, observation = fixture()
    target = observation if where == "observation" else observation[where]
    target["unsupported"] = "must not be ignored"
    with pytest.raises(ValueError):
        enrich_asset_with_media(original, observation)


@pytest.mark.parametrize("field,value", [
    ("backend", []), ("profile", []), ("native_calls", {}), ("projection", []),
    ("reason_codes", [{}]), ("limits", {"nonfinite": float("inf")}),
    ("limits", {"not_json": (1, 2)}),
])
def test_pure_json_contract_rejects_unhashable_shapes_and_nonfinite_values(field, value):
    original, observation = fixture()
    observation[field] = value
    with pytest.raises(ValueError):
        enrich_asset_with_media(original, observation)


@pytest.mark.parametrize("section,field,value", [
    ("backend", "id", {}), ("backend", "version", None),
    ("backend", "executable", 7), ("backend", "executable_sha256", "not-a-hash"),
    ("profile", "source_format", {}), ("profile", "demuxer", []),
])
def test_nested_identity_fields_are_validated_before_comparison(section, field, value):
    original, observation = fixture()
    observation[section][field] = value
    with pytest.raises(ValueError):
        enrich_asset_with_media(original, observation)


def test_enrichment_cannot_be_chained_or_attached_to_an_unsupported_format():
    original, observation = fixture()
    enriched = enrich_asset_with_media(original, observation)
    with pytest.raises(ValueError):
        enrich_asset_with_media(enriched, observation)
    text = inspect_asset(b"not media", filename="fixture.txt", source_id="fixture:media-protocol", revision="fixture-1")
    observation["source"] = deepcopy(text["source"])
    observation["sample_sha256"] = text["sample"]["sha256"]
    with pytest.raises(ValueError):
        enrich_asset_with_media(text, observation)


def test_avif_image_brand_cannot_be_promoted_to_video_by_an_authored_native_claim():
    _, observation = fixture()
    data = struct.pack(">I", 16) + b"ftypavif\x00\x00\x00\x00"
    image = inspect_asset(data, filename="fixture.avif", source_id="fixture:media-protocol", revision="fixture-1")
    observation["source"] = deepcopy(image["source"])
    observation["sample_sha256"] = image["sample"]["sha256"]
    assert image["format"]["detected"] == "iso_bmff"
    with pytest.raises(ValueError):
        enrich_asset_with_media(image, observation)
