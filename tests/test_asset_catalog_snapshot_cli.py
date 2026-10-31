"""Persistent catalogue boundaries preserve assets and exact review choices."""

from copy import deepcopy
import json
import os
import subprocess
import sys

import pytest

from tiberium_ai.asset_cli import main
from tiberium_ai.asset_catalog_snapshot import MAX_SNAPSHOT_BYTES, MAX_SNAPSHOT_NODES
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import create_tag_journal
from tiberium_ai.asset_tag_review import search_reviewed_assets
from tiberium_ai.verification import hash_input


def _dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _ok(capsys, *args):
    assert main([str(arg) for arg in args]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    return json.loads(output.out)


def _bad(capsys, *args):
    assert main([str(arg) for arg in args]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    error = json.loads(output.err)
    assert error["error"] and error["detail"]
    return error


def _report(source="asset", revision="v1", *, text=b"A robot in a garden."):
    return inspect_asset(text, filename=f"{source}.txt", source_id=source, revision=revision, topic_terms={"robotique": ["robot"]})


def _initial(tmp_path, capsys):
    path = tmp_path / "catalog-0.json"
    output = _ok(capsys, "catalog-init", path, "--catalog-id", "fixture:catalog")
    assert output["schema"] == "parcimonia.asset-catalog-write/v1"
    assert output["write"] == "created" and output["generation"] == 0 and output["report_count"] == 0
    assert output["snapshot_hash"] == _load(path)["snapshot_hash"]
    return path


def _put(capsys, current, report_path, output, *, expected="none"):
    written = _ok(capsys, "catalog-put", current, report_path, "--expected-head", _load(current)["snapshot_hash"], "--expected-report-hash", expected, "--out", output)
    assert written["snapshot_hash"] == _load(output)["snapshot_hash"]
    assert written["generation"] == _load(output)["generation"]
    assert written["report_count"] == len(_load(output)["reports"])
    return written


def _selected(tmp_path, capsys):
    initial = _initial(tmp_path, capsys)
    report = _report()
    report_path = _dump(tmp_path / "report.json", report)
    selected = tmp_path / "catalog-1.json"
    _put(capsys, initial, report_path, selected)
    return selected, report_path, report


def _decide(capsys, report, current, output, event):
    head = _load(current)["head_hash"]
    return _ok(capsys, "review-tag", report, current, "--tag", "topic:robotique", "--decision", "accept", "--actor", "fixture:reviewer", "--reason", "Authored fixture reviewed", "--event-id", event, "--expected-head", "none" if head is None else head, "--out", output)


def test_persisted_lifecycle_keeps_other_reviews_and_never_changes_old_files(tmp_path, capsys):
    sources = [tmp_path / "first.txt", tmp_path / "second.txt"]
    for source in sources:
        source.write_bytes(b"A robot in a garden.")
    reports = [_report("first"), _report("second")]
    paths = [_dump(tmp_path / f"report-{index}.json", report) for index, report in enumerate(reports)]
    initial = _initial(tmp_path, capsys)
    first, both, replaced, removed = [tmp_path / f"catalog-{index}.json" for index in range(1, 5)]
    _put(capsys, initial, paths[0], first)
    _put(capsys, first, paths[1], both)
    empty, accepted_first, accepted_both = [tmp_path / f"journal-{index}.json" for index in range(3)]
    _ok(capsys, "review-init", empty)
    _decide(capsys, paths[0], empty, accepted_first, "first-accept")
    _decide(capsys, paths[1], accepted_first, accepted_both, "second-accept")
    accepted = _ok(capsys, "catalog-search", both, accepted_both, "--tag", "topic:robotique")
    assert [match["source"]["id"] for match in accepted["result"]["matches"]] == ["first", "second"]
    before = {path: path.read_bytes() for path in [*sources, *paths, initial, first, both, empty, accepted_first, accepted_both]}
    current_report = _report("first", "v2", text=b"A robot in another garden.")
    current_path = _dump(tmp_path / "report-current.json", current_report)
    written = _put(capsys, both, current_path, replaced, expected=hash_input(reports[0]))
    assert written["snapshot_changed"] is True and written["generation"] == 3
    assert _load(replaced)["parent_hash"] == _load(both)["snapshot_hash"]
    found = _ok(capsys, "catalog-search", replaced, accepted_both, "--tag", "topic:robotique")
    assert [match["source"]["id"] for match in found["result"]["matches"]] == ["second"]
    proposed = _ok(capsys, "catalog-search", replaced, accepted_both, "--tag", "topic:robotique", "--state", "proposed")
    assert [match["source"]["revision"] for match in proposed["result"]["matches"]] == ["v2"]
    assert proposed["result"]["matches"][0]["source"]["id"] == "first"
    exported = _ok(capsys, "catalog-export", replaced)
    assert exported == [current_report, reports[1]]
    compatibility = _dump(tmp_path / "export.json", exported)
    legacy = _ok(capsys, "search-reviewed", compatibility, accepted_both, "--tag", "topic:robotique")
    assert legacy == found["result"]
    view = _ok(capsys, "review-view", compatibility, accepted_both)
    assert view["unapplied_events"] == [{"event_id": "first-accept", "source": {"id": "first", "revision": "v1"}, "reason": "source_revision_changed"}]
    before[replaced] = replaced.read_bytes()
    _ok(capsys, "catalog-remove", replaced, "--source-id", "first", "--expected-head", _load(replaced)["snapshot_hash"], "--expected-report-hash", hash_input(current_report), "--out", removed)
    assert _ok(capsys, "catalog-export", removed) == [reports[1]]
    assert _load(removed)["generation"] == 4
    assert _load(removed)["parent_hash"] == _load(replaced)["snapshot_hash"]
    assert {path: path.read_bytes() for path in before} == before


def test_exact_retry_creates_an_independent_file_without_advancing_snapshot(tmp_path, capsys):
    current, report_path, report = _selected(tmp_path, capsys)
    output = tmp_path / "retry.json"
    written = _put(capsys, current, report_path, output, expected=hash_input(report))
    assert written["snapshot_changed"] is False
    assert output.read_bytes() == current.read_bytes()
    output.unlink()
    assert _load(current)["generation"] == 1


@pytest.mark.parametrize("command", ["catalog-put", "catalog-remove"])
@pytest.mark.parametrize("condition", ["stale_head", "wrong_old_hash", "malformed_head", "malformed_old_hash", "missing_old_hash"])
def test_precondition_failure_creates_no_output_and_preserves_input(tmp_path, capsys, command, condition):
    current, report_path, report = _selected(tmp_path, capsys)
    before = current.read_bytes()
    head, old = _load(current)["snapshot_hash"], hash_input(report)
    if condition == "stale_head":
        head = "f" * 64
    elif condition == "wrong_old_hash":
        old = "f" * 64
    elif condition == "malformed_head":
        head = "A" * 64
    elif condition == "malformed_old_hash":
        old = "not-a-hash"
    else:
        old = "none"
    output = tmp_path / "refused.json"
    args = [command, current, report_path] if command == "catalog-put" else [command, current, "--source-id", "asset"]
    _bad(capsys, *args, "--expected-head", head, "--expected-report-hash", old, "--out", output)
    assert not output.exists() and current.read_bytes() == before


def test_removing_unselected_source_does_not_create_a_successor(tmp_path, capsys):
    current, _, report = _selected(tmp_path, capsys)
    output = tmp_path / "missing-source.json"
    _bad(capsys, "catalog-remove", current, "--source-id", "missing", "--expected-head", _load(current)["snapshot_hash"], "--expected-report-hash", hash_input(report), "--out", output)
    assert not output.exists()


@pytest.mark.parametrize("command", ["catalog-init", "catalog-put", "catalog-remove", "catalog-export"])
@pytest.mark.parametrize("target_kind", ["regular", "symlink", "dangling_symlink"])
def test_outputs_are_exclusive_and_never_follow_or_replace_links(tmp_path, capsys, command, target_kind):
    current, report_path, report = _selected(tmp_path, capsys)
    output, target = tmp_path / "output.json", tmp_path / "link-target.json"
    if target_kind == "regular":
        output = current
    else:
        if target_kind == "symlink":
            target.write_bytes(b"must stay unchanged")
        try:
            output.symlink_to(target)
        except OSError:
            pytest.skip("Host cannot create symlinks")
    before = current.read_bytes()
    if command == "catalog-init":
        args = [command, output, "--catalog-id", "other"]
    elif command == "catalog-export":
        args = [command, current, "--out", output]
    elif command == "catalog-put":
        args = [command, current, report_path, "--expected-head", _load(current)["snapshot_hash"], "--expected-report-hash", hash_input(report), "--out", output]
    else:
        args = [command, current, "--source-id", "asset", "--expected-head", _load(current)["snapshot_hash"], "--expected-report-hash", hash_input(report), "--out", output]
    assert _bad(capsys, *args)["error"] == "FileExistsError"
    assert current.read_bytes() == before
    if target_kind != "regular":
        assert output.is_symlink() and output.readlink() == target
        if target_kind == "symlink":
            assert target.read_bytes() == b"must stay unchanged"
        else:
            assert not target.exists()


@pytest.mark.parametrize("case", ["missing", "directory", "symlink", "fifo"])
def test_catalogue_input_requires_an_explicit_regular_file(tmp_path, capsys, case):
    initial = _initial(tmp_path, capsys)
    path = tmp_path / "unreadable.json"
    if case == "directory":
        path.mkdir()
    elif case == "symlink":
        try:
            path.symlink_to(initial)
        except OSError:
            pytest.skip("Host cannot create symlinks")
    elif case == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("Host has no FIFO support")
        os.mkfifo(path)
    _bad(capsys, "catalog-export", path)


@pytest.mark.parametrize("payload", [b"{", b"[]", b"{}", b"{} trailing", b'{"schema":1,"schema":2}', b'{"x":NaN}', b"\xff"])
def test_ambiguous_malformed_or_non_utf8_catalogue_is_refused(tmp_path, capsys, payload):
    path = tmp_path / "bad.json"
    path.write_bytes(payload)
    _bad(capsys, "catalog-export", path)
    assert path.read_bytes() == payload


@pytest.mark.parametrize("field,value", [
    ("schema", "foreign/v1"), ("catalog_id", ""), ("catalog_id", 1),
    ("generation", True), ("generation", 1.0), ("generation", -1),
    ("generation", 2**63), ("parent_hash", "a" * 64), ("reports", {}),
    ("snapshot_hash", "A" * 64), ("snapshot_hash", "f" * 64), ("snapshot_hash", None),
])
def test_unknown_schema_invalid_sha_and_wrong_snapshot_types_are_refused(tmp_path, capsys, field, value):
    path = _initial(tmp_path, capsys)
    snapshot = _load(path)
    snapshot[field] = value
    _dump(path, snapshot)
    _bad(capsys, "catalog-export", path)


@pytest.mark.parametrize("report", [{}, [], {"schema": "foreign/v1"}])
def test_invalid_report_never_creates_a_catalogue_successor(tmp_path, capsys, report):
    current = _initial(tmp_path, capsys)
    report_path = _dump(tmp_path / "bad-report.json", report)
    output = tmp_path / "not-created.json"
    _bad(capsys, "catalog-put", current, report_path, "--expected-head", _load(current)["snapshot_hash"], "--expected-report-hash", "none", "--out", output)
    assert not output.exists()


@pytest.mark.parametrize("budget", ["bytes", "nodes", "depth"])
def test_catalogue_reader_refuses_total_json_budgets(tmp_path, capsys, budget):
    path = _initial(tmp_path, capsys)
    snapshot = _load(path)
    if budget == "bytes":
        with path.open("ab") as stream:
            stream.write(b" " * MAX_SNAPSHOT_BYTES)
    elif budget == "nodes":
        snapshot["reports"] = [0] * MAX_SNAPSHOT_NODES
        _dump(path, snapshot)
    else:
        nested = 0
        for _ in range(65):
            nested = [nested]
        snapshot["reports"] = nested
        _dump(path, snapshot)
    error = _bad(capsys, "catalog-export", path)
    assert "budget" in error["detail"].lower()


def _fixture_snapshot(reports):
    snapshot = {"schema": "parcimonia.asset-catalog-snapshot/v1", "catalog_id": "fixture:budget", "generation": 1, "parent_hash": "0" * 64, "reports": reports}
    return dict(snapshot, snapshot_hash=hash_input(snapshot))


@pytest.mark.parametrize("budget", ["bytes", "nodes", "depth"])
def test_put_refuses_a_successor_exceeding_total_write_budget(tmp_path, capsys, budget):
    count = 10 if budget == "bytes" else 11 if budget == "nodes" else 0
    reports = [_report(f"asset-{index:02}") for index in range(count + 1)]
    if budget == "depth":
        padding = 0
        for _ in range(61):
            padding = [padding]
    else:
        padding = "é" * 800_000 if budget == "bytes" else [0] * 17_000
    for report in reports:
        report["limits"]["fixture_padding"] = deepcopy(padding)
    current = _dump(tmp_path / "current.json", _fixture_snapshot(reports[:-1]))
    report_path = _dump(tmp_path / "candidate.json", reports[-1])
    # Both input files individually fit the reader; only the successor fails.
    assert current.stat().st_size <= MAX_SNAPSHOT_BYTES
    assert report_path.stat().st_size <= 2 * 1024 * 1024
    output = tmp_path / "must-not-exist.json"
    before = current.read_bytes()
    _bad(capsys, "catalog-put", current, report_path, "--expected-head", _load(current)["snapshot_hash"], "--expected-report-hash", "none", "--out", output)
    assert not output.exists() and current.read_bytes() == before


def test_catalog_search_wraps_existing_state_bbox_and_limit_semantics(tmp_path, capsys):
    reports = [
        inspect_asset(b'{"type":"Point","coordinates":[0,0]}', filename="map.geojson", source_id="map", revision="v1"),
        _report("robot"),
    ]
    current = _dump(tmp_path / "current.json", _fixture_snapshot(reports))
    journal = create_tag_journal()
    journal_path = _dump(tmp_path / "journal.json", journal)
    for options, query in [
        (["--tag", "topic:robotique", "--state", "proposed", "--limit", "1"], {"tags": ["topic:robotique"], "states": ["proposed"], "limit": 1}),
        (["--bbox", "-1", "-1", "1", "1", "--limit", "1"], {"bbox": [-1.0, -1.0, 1.0, 1.0], "limit": 1}),
    ]:
        result = _ok(capsys, "catalog-search", current, journal_path, *options)
        snapshot = _load(current)
        reference = {"id": snapshot["catalog_id"], "generation": snapshot["generation"], "snapshot_hash": snapshot["snapshot_hash"]}
        assert result["schema"] == "parcimonia.asset-catalog-reviewed-search/v1"
        assert result["catalog"] == reference
        assert result["result"] == search_reviewed_assets(reports, journal, **query)
        assert result["input_hash"] == hash_input({"catalog": reference, "search_input_hash": result["result"]["input_hash"]})
        assert result["result"]["count"] == 1


@pytest.mark.parametrize("option", [["--limit", "0"], ["--tag", "invalid"], ["--bbox", "nan", "0", "1", "1"]])
def test_catalog_search_rejects_invalid_queries(tmp_path, capsys, option):
    current = _initial(tmp_path, capsys)
    journal = _dump(tmp_path / "journal.json", create_tag_journal())
    _bad(capsys, "catalog-search", current, journal, *option)


def test_large_unicode_export_requires_utf8_file_and_remains_legacy_searchable(tmp_path, capsys):
    reports = [_report(f"unicode-{index}") for index in range(6)]
    for report in reports:
        report["metadata"].append({"name": "authored_unicode_padding", "value": "一" * 500_000})
    snapshot = _fixture_snapshot(reports)
    current = _dump(tmp_path / "unicode-catalog.json", snapshot)
    assert current.stat().st_size < MAX_SNAPSHOT_BYTES
    # Each character needs six ASCII escape bytes but only three UTF-8 bytes.
    assert 6 * 500_000 * len("\\u4e00") > MAX_SNAPSHOT_BYTES
    before = current.read_bytes()
    error = _bad(capsys, "catalog-export", current)
    assert "--out" in error["detail"]
    exported = tmp_path / "exported-reports.json"
    written = _ok(capsys, "catalog-export", current, "--out", exported)
    assert written == {
        "schema": "parcimonia.asset-catalog-export-write/v1",
        "output": str(exported), "catalog_id": snapshot["catalog_id"],
        "generation": snapshot["generation"], "snapshot_hash": snapshot["snapshot_hash"],
        "report_count": 6, "write": "created",
    }
    stored = exported.read_bytes()
    assert len(stored) < MAX_SNAPSHOT_BYTES and not stored.endswith(b"\n")
    assert "一".encode("utf-8") in stored
    assert stored == json.dumps(reports, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert _ok(capsys, "search", exported, "--tag", "topic:robotique")["count"] == 6
    journal = _dump(tmp_path / "journal.json", create_tag_journal())
    assert _ok(capsys, "search-reviewed", exported, journal, "--tag", "topic:robotique", "--state", "proposed")["count"] == 6
    assert current.read_bytes() == before


def test_utf8_compact_storage_round_trips_through_ascii_only_stdout(tmp_path):
    initial, selected = tmp_path / "été-0.json", tmp_path / "été-1.json"
    report = _report("été", "révision-1")
    report_path = _dump(tmp_path / "rapport.json", report)
    command = [sys.executable, "-m", "tiberium_ai.asset_cli"]
    environment = dict(os.environ, PYTHONIOENCODING="ascii")
    first = subprocess.run(command + ["catalog-init", str(initial), "--catalog-id", "médiathèque"], capture_output=True, env=environment, timeout=10)
    assert first.returncode == 0, first.stderr
    head = json.loads(first.stdout.decode("ascii"))["snapshot_hash"]
    second = subprocess.run(command + ["catalog-put", str(initial), str(report_path), "--expected-head", head, "--expected-report-hash", "none", "--out", str(selected)], capture_output=True, env=environment, timeout=10)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout.decode("ascii"))["catalog_id"] == "médiathèque"
    stored = selected.read_bytes()
    assert "médiathèque".encode() in stored and "révision-1".encode() in stored
    assert stored == json.dumps(_load(selected), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert not stored.endswith(b"\n")
    exported = subprocess.run(command + ["catalog-export", str(selected)], capture_output=True, env=environment, timeout=10)
    assert exported.returncode == 0, exported.stderr
    assert json.loads(exported.stdout.decode("ascii")) == [report]
