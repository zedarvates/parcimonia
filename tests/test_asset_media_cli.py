"""Exercise the media CLI protocol without running a native executable.

WAV silence is authored with the standard library. The ffprobe JSON, backend
identity and call records are explicit synthetic declarations: their hashes
qualify handoff consistency, not an installed executable or codec quality.
"""

from copy import deepcopy
import hashlib
import io
import json
import wave

import pytest

import tiberium_ai.asset_cli as cli
import tiberium_ai.asset_media_probe as media_adapter
from tiberium_ai.asset_inspection import MAX_SAMPLE_BYTES, inspect_asset
from tiberium_ai.media_evidence import parse_ffprobe_json
from tiberium_ai.verification import hash_input


SOURCE_ID = "fixture:média-cli"
REVISION = "rév-1"
FILENAME = "séquence.wav"
VERSION = b"ffprobe version 7.1.5 Copyright authored CLI fixture"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _wav(data_bytes=3200):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00" * data_bytes)
    return buffer.getvalue()


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return path


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _observation(inspection):
    raw = json.dumps({
        "format": {"format_name": "wav", "duration": "0.200000"},
        "streams": [{
            "index": 0, "codec_type": "audio", "codec_name": "pcm_s16le",
            "sample_rate": "8000", "channels": 1, "duration": "0.200000",
        }],
    }, ensure_ascii=False, allow_nan=False).encode("utf-8")

    def call(phase, stdout):
        return {
            "phase": phase, "status": "completed", "returncode": 0,
            "stdout_sha256": _sha(stdout), "stderr_sha256": _sha(b""),
            "stdout_complete": True, "stderr_complete": True,
            "elapsed_ms": 0.25, "started": True, "error": None,
        }

    return {
        "schema": "parcimonia.asset-media-observation/v1",
        "source": deepcopy(inspection["source"]),
        "input_hash": hash_input({
            "data_origin": "authored_fixture", "source": inspection["source"],
            "sample_sha256": inspection["sample"]["sha256"],
        }),
        "sample_sha256": inspection["sample"]["sha256"], "source_complete": True,
        "backend": {
            "id": "ffprobe", "version": VERSION.decode("ascii"),
            "executable": "/declared-fixture-only/ffprobe",
            "executable_sha256": _sha(b"authored identity, not executable bytes"),
        },
        "profile": {
            "id": "parcimonia.ffprobe-stream-profile/v1",
            "source_format": "wav", "demuxer": "wav",
        },
        "status": "completed", "raw_json": raw.decode("utf-8"),
        "projection": parse_ffprobe_json(raw, expected_demuxer="wav"),
        "reason_codes": ["authored_protocol_fixture"],
        "native_calls": [call("version", VERSION), call("probe", raw)],
        "elapsed_ms": 0.5,
        "limits": {"data_origin": "authored_fixture", "qualification": "protocol_only"},
    }


def _setup(tmp_path):
    source = tmp_path / FILENAME
    source.write_bytes(_wav())
    inspection = inspect_asset(
        source.read_bytes(), filename=source.name, source_id=SOURCE_ID, revision=REVISION,
    )
    report = _write_json(tmp_path / "inspection.json", inspection)
    observation = _write_json(tmp_path / "observation.json", _observation(inspection))
    return source, report, observation


def _probe_args(path, *extra):
    return [
        "probe-media", str(path), "--source-id", SOURCE_ID,
        "--revision", REVISION, *extra,
    ]


def _ok(capsys, *arguments):
    assert cli.main([str(item) for item in arguments]) == 0
    output = capsys.readouterr()
    assert output.err == "" and output.out.isascii()
    return json.loads(output.out)


def _bad(capsys, *arguments):
    assert cli.main([str(item) for item in arguments]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.isascii()
    error = json.loads(output.err)
    assert error["error"] and error["detail"]
    return error


def _forbid_native(*args, **kwargs):
    pytest.fail("CLI protocol tests must not execute ffprobe or another native backend.")


@pytest.fixture(autouse=True)
def forbid_native_execution(monkeypatch):
    monkeypatch.setattr(media_adapter, "run_bounded", _forbid_native)


@pytest.mark.parametrize("status,expected_code", [
    ("completed", 0), ("indeterminate", 3), ("unavailable", 3), ("failed", 4),
])
def test_probe_forwards_explicit_options_and_serializes_status_without_changing_source(
    tmp_path, capsys, monkeypatch, status, expected_code,
):
    source, report_path, _ = _setup(tmp_path)
    response = _observation(_read_json(report_path))
    response["status"] = status
    if status != "completed":
        response.update(raw_json=None, projection=None, native_calls=[], reason_codes=["fixture_failure"])
    calls = []

    def probe(data, **options):
        calls.append((data, options))
        return response

    monkeypatch.setattr(cli, "probe_asset_media", probe)
    before = source.read_bytes()
    assert cli.main(_probe_args(source, "--executable", "/explicit/ffprobe", "--timeout", "1.5")) == expected_code
    output = capsys.readouterr()
    assert output.err == "" and output.out.isascii()
    assert json.loads(output.out) == response
    assert calls == [(before, {
        "filename": FILENAME, "source_id": SOURCE_ID, "revision": REVISION,
        "executable": "/explicit/ffprobe", "timeout_s": 1.5, "complete": True,
    })]
    assert source.read_bytes() == before


@pytest.mark.parametrize("extra,complete,reason", [
    (0, True, "executable_unavailable"), (37, False, "complete_source_required"),
])
def test_probe_read_budget_distinguishes_an_exact_complete_file_from_a_prefix(
    tmp_path, capsys, extra, complete, reason,
):
    source = tmp_path / "large.wav"
    payload = _wav(MAX_SAMPLE_BYTES + extra - 44)
    assert len(payload) == MAX_SAMPLE_BYTES + extra
    source.write_bytes(payload)
    assert cli.main(_probe_args(source, "--executable", str(tmp_path / "absent-tool"))) == 3
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert output.err == ""
    assert report["source_complete"] is complete
    assert report["sample_sha256"] == _sha(payload[:MAX_SAMPLE_BYTES])
    assert report["reason_codes"] == [reason]
    assert report["native_calls"] == []
    assert report["raw_json"] is None and report["projection"] is None
    assert source.read_bytes() == payload


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink"])
def test_probe_rejects_non_regular_sources_before_entering_adapter(tmp_path, capsys, monkeypatch, kind):
    monkeypatch.setattr(cli, "probe_asset_media", _forbid_native)
    source = tmp_path / "source.wav"
    if kind == "directory":
        source.mkdir()
    elif kind == "symlink":
        target = tmp_path / "target.wav"
        target.write_bytes(_wav())
        try:
            source.symlink_to(target)
        except OSError:
            pytest.skip("Host cannot create symlinks")
    _bad(capsys, *_probe_args(source))


@pytest.mark.parametrize("value", ["0", "nan", "31"])
def test_invalid_probe_timeouts_are_input_errors(tmp_path, capsys, value):
    source = tmp_path / "fixture.wav"
    source.write_bytes(_wav())
    error = _bad(capsys, *_probe_args(source, "--timeout", value))
    assert error["error"] == "ValueError"


def test_unsupported_bytes_are_indeterminate_before_executable_discovery(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(media_adapter.shutil, "which", _forbid_native)
    source = tmp_path / "misleading.wav"
    source.write_text("Un document texte, pas un fichier sonore.", encoding="utf-8")
    assert cli.main(_probe_args(source)) == 3
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert output.err == "" and report["status"] == "indeterminate"
    assert report["reason_codes"] == ["unsupported_media_format"]
    assert report["native_calls"] == [] and report["raw_json"] is None


def test_regular_inspection_does_not_select_or_run_ffprobe(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "probe_asset_media", _forbid_native)
    monkeypatch.setattr(media_adapter.shutil, "which", _forbid_native)
    source = tmp_path / FILENAME
    source.write_bytes(_wav())
    report = _ok(capsys, "inspect", source, "--source-id", SOURCE_ID, "--revision", REVISION)
    assert report["analyser"] == {"id": "asset-inspection", "version": "1"}
    assert report["format"]["detected"] == "wav"
    assert not any(item["kind"].startswith("native_media") for item in report["evidence"])


@pytest.mark.parametrize("change", ["id", "revision", "filename", "digest", "incomplete", "failed", "stdout_hash"])
def test_enrich_refuses_mismatched_or_unusable_saved_observations(tmp_path, capsys, monkeypatch, change):
    monkeypatch.setattr(cli, "probe_asset_media", _forbid_native)
    source, inspection_path, observation_path = _setup(tmp_path)
    observation = _read_json(observation_path)
    if change in {"id", "revision", "filename"}:
        observation["source"][change] += ":changed"
    elif change == "digest":
        observation["sample_sha256"] = "f" * 64
    elif change == "incomplete":
        observation["source_complete"] = False
    elif change == "failed":
        observation.update(status="failed", raw_json=None, projection=None)
    else:
        observation["native_calls"][1]["stdout_sha256"] = "f" * 64
    _write_json(observation_path, observation)
    paths = (source, inspection_path, observation_path)
    before = {path: path.read_bytes() for path in paths}
    error = _bad(capsys, "enrich-media", inspection_path, observation_path)
    assert error["error"] == "ValueError"
    assert {path: path.read_bytes() for path in paths} == before
    assert set(tmp_path.iterdir()) == set(paths)


@pytest.mark.parametrize("payload", ["{", '{"schema":1,"schema":2}', '{"streams":[NaN]}'])
def test_enrich_refuses_malformed_json_without_output_or_new_native_call(tmp_path, capsys, monkeypatch, payload):
    monkeypatch.setattr(cli, "probe_asset_media", _forbid_native)
    _, inspection_path, observation_path = _setup(tmp_path)
    observation_path.write_text(payload, encoding="utf-8")
    before = observation_path.read_bytes()
    _bad(capsys, "enrich-media", inspection_path, observation_path)
    assert observation_path.read_bytes() == before


def test_enrichment_persists_through_catalogue_and_exact_review_without_native_calls(
    tmp_path, capsys, monkeypatch,
):
    monkeypatch.setattr(cli, "probe_asset_media", _forbid_native)
    source, inspection_path, observation_path = _setup(tmp_path)
    originals = {path: path.read_bytes() for path in (source, inspection_path, observation_path)}
    enriched = _ok(capsys, "enrich-media", inspection_path, observation_path)
    assert enriched["analyser"] == {"id": "asset-media-enrichment", "version": "1"}
    assert enriched["source"] == _read_json(inspection_path)["source"]
    assert all(item["status"] == "proposed" for item in enriched["tag_proposals"])
    assert any(item["namespace"] == "codec" and item["value"] == "pcm_s16le" for item in enriched["tag_proposals"])
    observation_hash = hash_input(_read_json(observation_path))
    summary = next(item for item in enriched["evidence"] if item["kind"] == "native_media_observation")
    assert summary["observation_hash"] == observation_hash
    assert summary["source_sha256"] == _sha(source.read_bytes())
    assert enriched["limits"]["full_decode"] == "not_established"
    enriched_path = _write_json(tmp_path / "enriched.json", enriched)

    initial, selected, updated = [tmp_path / f"catalog-{index}.json" for index in range(3)]
    empty, accepted = tmp_path / "review-0.json", tmp_path / "review-1.json"
    init = _ok(capsys, "catalog-init", initial, "--catalog-id", "fixture:catalogue-média")
    put = _ok(
        capsys, "catalog-put", initial, enriched_path,
        "--expected-head", init["snapshot_hash"], "--expected-report-hash", "none", "--out", selected,
    )
    assert put["report_count"] == 1
    assert _read_json(selected)["reports"] == [enriched]
    assert _ok(capsys, "review-init", empty)["head_hash"] is None
    query = ["catalog-search", selected, empty, "--tag", "codec:pcm_s16le"]
    assert _ok(capsys, *query)["result"]["count"] == 0
    assert _ok(capsys, *query, "--state", "proposed")["result"]["count"] == 1
    written = _ok(
        capsys, "review-tag", enriched_path, empty, "--tag", "codec:pcm_s16le",
        "--decision", "accept", "--actor", "opératrice", "--reason", "Métadonnées de fixture vérifiées.",
        "--event-id", "media-accept-1", "--expected-head", "none", "--out", accepted,
    )
    assert written["event_created"] is True
    journal = _read_json(accepted)
    assert journal["events"][0]["report_hash"] == hash_input(enriched)
    assert journal["events"][0]["actor_id"] == "opératrice"
    assert "opératrice".encode("utf-8") in accepted.read_bytes()
    found = _ok(capsys, "catalog-search", selected, accepted, "--tag", "codec:pcm_s16le")
    assert found["result"]["count"] == 1
    assert found["result"]["matches"][0]["source"] == enriched["source"]
    assert found["result"]["matches"][0]["tag_states"][0]["status"] == "accepted"

    for path in (enriched_path, initial, selected, empty, accepted):
        originals[path] = path.read_bytes()
    next_data = _wav(6400)
    next_inspection = inspect_asset(next_data, filename=FILENAME, source_id=SOURCE_ID, revision="rév-2")
    next_path = _write_json(tmp_path / "inspection-next.json", next_inspection)
    assert _bad(capsys, "enrich-media", next_path, observation_path)["error"] == "ValueError"
    next_observation = _write_json(tmp_path / "observation-next.json", _observation(next_inspection))
    next_enriched = _ok(capsys, "enrich-media", next_path, next_observation)
    next_enriched_path = _write_json(tmp_path / "enriched-next.json", next_enriched)
    _ok(
        capsys, "catalog-put", selected, next_enriched_path,
        "--expected-head", put["snapshot_hash"], "--expected-report-hash", hash_input(enriched), "--out", updated,
    )
    assert _ok(capsys, "catalog-search", updated, accepted, "--tag", "codec:pcm_s16le")["result"]["count"] == 0
    pending = _ok(capsys, "catalog-search", updated, accepted, "--tag", "codec:pcm_s16le", "--state", "proposed")
    assert pending["result"]["count"] == 1
    assert pending["result"]["matches"][0]["source"]["revision"] == "rév-2"
    assert {path: path.read_bytes() for path in originals} == originals
