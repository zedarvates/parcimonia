"""Optional installed-tool checks on authored silence and a solid RGB frame.

No media, binary or model is downloaded. These checks qualify the metadata
path for these fixtures; they do not measure perceptual or semantic quality.
Only unavailable fixture-generation capabilities can skip an installed probe.
"""

from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import wave

import pytest

from examples import native_media_demo as demo
from tiberium_ai.asset_catalog import search_asset_reports
from tiberium_ai.asset_catalog_snapshot import (
    create_asset_catalog, export_asset_reports, put_asset_report, validate_asset_catalog,
)
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_media_enrichment import enrich_asset_with_media
from tiberium_ai.asset_media_probe import probe_asset_media
from tiberium_ai.asset_tag_journal import (
    append_tag_decision, create_tag_journal, validated_review_report_hash,
)
from tiberium_ai.asset_tag_review import search_reviewed_assets
from tiberium_ai.verification import hash_input


def _installed(name):
    selected = shutil.which(name)
    if selected is None:
        pytest.skip(f"Optional native media integration requires installed {name}.")
    return str(Path(selected).resolve())


def _generation_available(generation):
    if generation["status"] == "completed":
        return
    reason = generation["reason_codes"]
    if reason == ["ffmpeg_not_found"]:
        pytest.skip("Optional MP4 fixture requires installed ffmpeg; WAV remains independent.")
    diagnostic = (generation["diagnostic"] or "").lower()
    missing_capability = (
        "unknown encoder", "encoder not found", "unrecognized option", "option not found",
        "requested output format", "encoder (codec", "not available in this build",
    )
    if reason == ["ffmpeg_generation_exit_nonzero"] and any(marker in diagnostic for marker in missing_capability):
        pytest.skip(f"Installed ffmpeg cannot generate the optional fixture: {generation['diagnostic']}")
    pytest.fail(f"Authored fixture generation failed: {generation}")


def _tags(report):
    return {(tag["namespace"], tag["value"]) for tag in report["tag_proposals"]}


@pytest.fixture(scope="module", params=demo.KINDS)
def native_case(request):
    executable = _installed("ffprobe")
    kind = request.param
    if kind == "wav":
        data, generation = demo.wav_fixture(), None
    else:
        data, generation = demo.generate_mp4_fixture(kind)
        _generation_available(generation)
    assert data is not None and 0 < len(data) <= demo.MAX_FIXTURE_BYTES
    identity = {
        "filename": "authored.wav" if kind == "wav" else "authored.mp4",
        "source_id": f"fixture:native-media:{kind}", "revision": "authored-v1",
    }
    inspection = inspect_asset(data, **identity)
    observation = probe_asset_media(data, **identity, executable=executable, timeout_s=10.0)
    # An installed probe failing on successfully generated media is a failure,
    # never a missing-encoder skip or a fabricated empty successful result.
    assert observation["status"] == "completed", observation
    enriched = enrich_asset_with_media(inspection, observation)
    return {
        "kind": kind, "data": data, "generation": generation,
        "inspection": inspection, "observation": observation,
        "enriched": enriched, "executable": executable,
    }


def test_stdlib_wav_fixture_is_authored_pcm_silence():
    data = demo.wav_fixture()
    with wave.open(io.BytesIO(data), "rb") as source:
        assert source.getnchannels() == 1
        assert source.getsampwidth() == 2
        assert source.getframerate() == 8000
        assert source.getnframes() == 1600
        assert source.readframes(source.getnframes()) == b"\x00\x00" * 1600


def test_native_observation_binds_exact_complete_source_and_observed_backend(native_case):
    case, observation = native_case, native_case["observation"]
    assert observation["schema"] == "parcimonia.asset-media-observation/v1"
    assert observation["source"] == case["inspection"]["source"]
    assert observation["sample_sha256"] == hashlib.sha256(case["data"]).hexdigest()
    assert observation["source_complete"] is True
    assert observation["backend"]["id"] == "ffprobe"
    assert observation["backend"]["executable"] == case["executable"]
    assert observation["backend"]["version"].startswith("ffprobe version ")
    assert len(observation["backend"]["executable_sha256"]) == 64
    assert [call["phase"] for call in observation["native_calls"]] == ["version", "probe"]
    for call in observation["native_calls"]:
        assert call["status"] == "completed" and call["returncode"] == 0
        assert call["started"] is True and call["error"] is None
        assert call["stdout_complete"] is True and call["stderr_complete"] is True
        assert call["elapsed_ms"] >= 0
    assert observation["elapsed_ms"] >= 0
    assert observation["projection"]["coverage"] == {"streams": "reported_only", "full_decode": "not_established"}
    assert observation["limits"]["model_calls"] == 0
    assert observation["limits"]["native_inference"] == "none"


def test_real_streams_keep_known_fixture_codec_type_dimensions_and_duration(native_case):
    kind, observation = native_case["kind"], native_case["observation"]
    streams = observation["projection"]["streams"]
    assert len(streams) == 1
    stream = streams[0]
    expected_type = "video" if kind == "video-mp4" else "audio"
    expected_codec = {"wav": "pcm_s16le", "audio-mp4": "aac", "video-mp4": "mpeg4"}[kind]
    assert stream["type"] == expected_type and stream["codec"] == expected_codec
    assert stream["index"] == 0 and stream["attached_picture"] is False
    assert stream["duration_seconds"] is not None and stream["duration_seconds"] >= 0
    assert observation["projection"]["format"]["duration_seconds"] is not None
    assert observation["projection"]["format"]["duration_seconds"] >= 0
    raw = json.loads(observation["raw_json"])
    assert raw["streams"][0]["codec_name"] == expected_codec
    assert raw["streams"][0]["codec_type"] == expected_type
    if expected_type == "video":
        assert (stream["width"], stream["height"]) == (16, 16)
        assert stream["sample_rate"] is None and stream["channels"] is None
    else:
        assert stream["sample_rate"] == 8000 and stream["channels"] == 1
        assert stream["width"] is None and stream["height"] is None
    assert observation["profile"]["source_format"] == ("wav" if kind == "wav" else "iso_bmff")
    assert observation["profile"]["demuxer"] == ("wav" if kind == "wav" else "mov")


def test_real_native_stream_enrichment_preserves_source_and_searchable_proposals(native_case):
    original, enriched = native_case["inspection"], native_case["enriched"]
    modality = "video" if native_case["kind"] == "video-mp4" else "audio"
    assert enriched["analyser"] == {"id": "asset-media-enrichment", "version": "1"}
    assert enriched["source"] == original["source"] and enriched["sample"] == original["sample"]
    assert enriched["format"] == original["format"]
    assert modality in enriched["modalities"] and ("modality", modality) in _tags(enriched)
    assert all(tag["status"] == "proposed" for tag in enriched["tag_proposals"])
    evidence = {item["id"]: item for item in enriched["evidence"]}
    assert all(set(tag["evidence_refs"]) <= evidence.keys() for tag in enriched["tag_proposals"])
    observation = native_case["observation"]
    summary = next(item for item in evidence.values() if item["kind"] == "native_media_observation")
    assert summary["observation_hash"] == hash_input(observation)
    assert summary["source_sha256"] == original["sample"]["sha256"]
    assert summary["raw_stdout_sha256"] == hashlib.sha256(observation["raw_json"].encode("utf-8")).hexdigest()
    assert summary["backend"] == observation["backend"]
    stream = observation["projection"]["streams"][0]
    codec = next(tag for tag in enriched["tag_proposals"] if tag["namespace"] == "codec" and tag["value"] == stream["codec"])
    assert codec["basis"] == "native_stream_observation"
    linked = [evidence[ref] for ref in codec["evidence_refs"]]
    assert summary in linked
    assert next(item for item in linked if item["kind"] == "native_media_stream")["stream"] == stream
    assert enriched["limits"]["model_calls"] == 0
    assert not any(tag["namespace"] in {"object", "scene", "transcript", "speech"} for tag in enriched["tag_proposals"])
    assert validated_review_report_hash(enriched) == hash_input(enriched)
    found = search_asset_reports([enriched], tags=[f"modality:{modality}", f"codec:{stream['codec']}"])
    assert found["count"] == 1 and found["matches"][0]["source"] == enriched["source"]
    if native_case["kind"] == "audio-mp4":
        assert native_case["inspection"]["format"]["detected"] == "iso_bmff"
        assert "video" not in enriched["modalities"]
        assert ("modality", "video") not in _tags(enriched)
        assert search_asset_reports([enriched], tags=["modality:video"])["count"] == 0
    if native_case["kind"] == "video-mp4":
        assert "audio" not in enriched["modalities"]
        assert ("modality", "audio") not in _tags(enriched)


def test_real_native_media_report_survives_catalogue_review_and_json_reload(native_case, tmp_path):
    report = native_case["enriched"]
    before = deepcopy(report)
    modality = "video" if native_case["kind"] == "video-mp4" else "audio"
    empty = create_asset_catalog("fixture:native-media")
    snapshot = put_asset_report(empty, report, expected_head=empty["snapshot_hash"], expected_report_hash=None)
    journal = append_tag_decision(
        create_tag_journal(), report, namespace="modality", value=modality, action="accept",
        actor_id="fixture:reviewer", reason="Authored native stream fixture reviewed",
        event_id="native-media-review", expected_head=None,
    )
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert validate_asset_catalog(reloaded) is None
    reports = export_asset_reports(reloaded)
    assert search_reviewed_assets(reports, create_tag_journal(), tags=[f"modality:{modality}"])["count"] == 0
    accepted = search_reviewed_assets(reports, journal, tags=[f"modality:{modality}"])
    assert accepted["count"] == 1
    assert accepted["matches"][0]["report_hash"] == hash_input(report)
    assert accepted["matches"][0]["tag_states"][0]["status"] == "accepted"
    assert report == before


@pytest.mark.parametrize("kind", demo.KINDS)
def test_demo_runs_the_authored_fixture_through_observation_and_search(kind):
    _installed("ffprobe")
    result = demo.run_demo(kind)
    assert set(result) == {"data_origin", "generation", "observation", "enriched", "search"}
    assert result["data_origin"] == "authored_fixture"
    if kind == "wav":
        assert result["generation"] is None
    else:
        _generation_available(result["generation"])
        assert result["generation"]["fixture_bytes"] <= demo.MAX_FIXTURE_BYTES
    assert result["observation"]["status"] == "completed", result["observation"]
    assert result["enriched"]["source"]["id"] == f"fixture:media:{kind}"
    assert result["search"]["count"] == 1
    assert result["search"]["matches"][0]["matched_tags"] == ["modality:video" if kind == "video-mp4" else "modality:audio"]
    json.dumps(result, allow_nan=False)


def test_real_ffmpeg_fixture_generation_is_bounded_private_and_cleans_its_paths(monkeypatch):
    _installed("ffmpeg")
    native = demo.run_bounded
    calls = []
    def record(argv, **options):
        directory = Path(options["cwd"])
        assert directory.is_dir()
        assert (directory / "authored.rgb").read_bytes() == b"\x18\x60\xa0" * (16 * 16)
        assert len(argv) <= 32 and "-an" in argv
        assert options["max_stdout_bytes"] == 4096 and options["max_stderr_bytes"] == 16384
        assert 0 < options["deadline"] - time.monotonic() <= 5.0
        assert options["env"]["LC_ALL"] == "C"
        calls.append((directory, list(argv)))
        return native(argv, **options)
    monkeypatch.setattr(demo, "run_bounded", record)
    data, generation = demo.generate_mp4_fixture("video-mp4")
    _generation_available(generation)
    assert data is not None and len(data) <= demo.MAX_FIXTURE_BYTES
    assert len(calls) == 1
    assert all(not directory.exists() for directory, _ in calls)
    assert generation["fixture_sha256"] == hashlib.sha256(data).hexdigest()
    call = generation["native_calls"][0]
    assert call["status"] == "completed" and call["returncode"] == 0
    assert call["stdout_complete"] is True and call["stderr_complete"] is True


def test_wav_demo_does_not_require_fixture_generation(monkeypatch):
    _installed("ffprobe")
    def forbidden(*args, **kwargs):
        pytest.fail("WAV silence must not require ffmpeg.")
    monkeypatch.setattr(demo, "generate_mp4_fixture", forbidden)
    result = demo.run_demo("wav")
    assert result["generation"] is None and result["observation"]["status"] == "completed"


def test_failed_fixture_generation_never_becomes_an_empty_media_observation(monkeypatch):
    monkeypatch.setattr(demo.shutil, "which", lambda name: None)
    result = demo.run_demo("audio-mp4")
    assert result["generation"]["status"] == "unavailable"
    assert result["generation"]["reason_codes"] == ["ffmpeg_not_found"]
    assert result["generation"]["native_calls"] == []
    assert result["observation"] is None and result["enriched"] is None and result["search"] is None


def test_demo_cli_emits_ascii_json_for_the_stdlib_wav_fixture():
    _installed("ffprobe")
    result = subprocess.run(
        [sys.executable, "examples/native_media_demo.py", "--kind", "wav"],
        env=dict(os.environ, PYTHONIOENCODING="ascii"), capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.decode("ascii"))
    assert report["observation"]["status"] == "completed"
    assert report["generation"] is None and report["search"]["count"] == 1
