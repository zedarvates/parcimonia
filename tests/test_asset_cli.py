"""File-boundary and installed-module-style checks for the advisory CLI."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tiberium_ai.asset_cli import main
from tiberium_ai.asset_inspection import MAX_SAMPLE_BYTES, inspect_asset


def _inspect_args(path, *extra):
    return ["inspect", str(path), "--source-id", "fixture", "--revision", "v1", *extra]


def test_inspection_does_not_write_tags_or_change_the_original(tmp_path, capsys):
    path = tmp_path / "notes.txt"
    path.write_text("Un robot dans un jardin.", encoding="utf-8")
    before = path.read_bytes()
    topics = tmp_path / "topics.json"
    topics.write_text(json.dumps({"robotique": ["robot"]}), encoding="utf-8")
    assert main(_inspect_args(path, "--topics", str(topics))) == 0
    report = json.loads(capsys.readouterr().out)
    assert any(t["namespace"] == "topic" and t["value"] == "robotique" for t in report["tag_proposals"])
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["notes.txt", "topics.json"]


def test_large_regular_file_is_an_explicit_prefix_not_a_full_digest(tmp_path, capsys):
    path = tmp_path / "large.txt"
    payload = b"a" * (MAX_SAMPLE_BYTES + 37)
    path.write_bytes(payload)
    assert main(_inspect_args(path)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "partial"
    assert report["sample"]["complete"] is False
    assert report["sample"]["content_sha256"] is None
    assert report["sample"]["sha256"] == hashlib.sha256(payload[:MAX_SAMPLE_BYTES]).hexdigest()
    assert report["sample"]["total_bytes"] == len(payload)


def test_unknown_binary_has_distinct_indeterminate_exit(tmp_path, capsys):
    path = tmp_path / "unknown.bin"
    path.write_bytes(b"\xff\x00\x01")
    assert main(_inspect_args(path)) == 3
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "indeterminate"


@pytest.mark.parametrize("case", ["missing", "directory", "symlink", "fifo"])
def test_unsupported_or_unreadable_source_is_not_an_empty_asset(tmp_path, capsys, case):
    path = tmp_path / "source"
    if case == "directory":
        path.mkdir()
    elif case == "symlink":
        target = tmp_path / "target.txt"
        target.write_text("text", encoding="utf-8")
        try:
            path.symlink_to(target)
        except OSError:
            pytest.skip("Host cannot create symlinks")
    elif case == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("Host has no FIFO support")
        os.mkfifo(path)
    assert main(_inspect_args(path)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "error" in json.loads(output.err)


def test_observed_source_change_refuses_the_report(tmp_path, capsys, monkeypatch):
    path = tmp_path / "source.txt"
    path.write_text("before", encoding="utf-8")
    native = os.fstat
    calls = 0
    def changed(descriptor):
        nonlocal calls
        calls += 1
        info = native(descriptor)
        return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size + (1 if calls == 2 else 0), st_mtime_ns=info.st_mtime_ns, st_mode=info.st_mode)
    monkeypatch.setattr("tiberium_ai.asset_cli.os.fstat", changed)
    assert main(_inspect_args(path)) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "changed" in json.loads(output.err)["detail"]


def test_catalogue_cli_filters_proposed_tags_and_bbox(tmp_path, capsys):
    reports = [
        inspect_asset(b"robot", filename="notes.txt", source_id="text", revision="v1", topic_terms={"robotique": ["robot"]}),
        inspect_asset(b'{"type":"Point","coordinates":[0,0]}', filename="map.geojson", source_id="map", revision="v1"),
    ]
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps(reports), encoding="utf-8")
    assert main(["search", str(path), "--tag", "topic:robotique"]) == 0
    tags = json.loads(capsys.readouterr().out)
    assert [item["source"]["id"] for item in tags["matches"]] == ["text"]
    assert main(["search", str(path), "--bbox", "-1", "-1", "1", "1"]) == 0
    spatial = json.loads(capsys.readouterr().out)
    assert [item["source"]["id"] for item in spatial["matches"]] == ["map"]
    assert spatial["matches"][0]["spatial_match"] == "envelope_overlap_candidate"


@pytest.mark.parametrize("value", ['[{"schema":1,"schema":2}]', '[NaN]', '[] trailing', '{'])
def test_catalogue_json_ambiguity_is_refused(tmp_path, capsys, value):
    path = tmp_path / "bad.json"
    path.write_text(value, encoding="utf-8")
    assert main(["search", str(path)]) == 2
    assert capsys.readouterr().out == ""


def test_cli_handles_non_ascii_identifiers_through_ascii_pipe(tmp_path):
    path = tmp_path / "été.txt"
    path.write_text("Données de texte.", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "tiberium_ai.asset_cli", "inspect", str(path), "--source-id", "été", "--revision", "v1"],
        env=dict(os.environ, PYTHONIOENCODING="ascii"), capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.decode("ascii"))
    assert report["source"]["id"] == "été"


def test_demo_catalogue_is_searchable_and_only_contains_proposals():
    result = subprocess.run(
        [sys.executable, "examples/asset_catalog_demo.py", "--summary"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["data_origin"] == "authored_fixture"
    assert report["image_search"]["count"] == 1
    assert report["topic_search"]["count"] == 1
    assert report["spatial_search"]["count"] == 1
