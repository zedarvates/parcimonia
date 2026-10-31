"""Exercise explicit relation-file preparation and catalogue integration."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from tiberium_ai.asset_cli import main
from tiberium_ai.asset_catalog_snapshot import put_asset_report
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import validated_review_report_hash


def _inputs(tmp_path):
    # The shipped example is also the documented CLI fixture.
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "examples" / "asset_relations_demo.py"
    spec = importlib.util.spec_from_file_location("relations_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog, declarations = module.build_demo_inputs()
    return catalog, declarations


def _dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _call(capsys, *args, code=0):
    assert main([str(value) for value in args]) == code
    captured = capsys.readouterr()
    if code:
        assert not captured.out
        return json.loads(captured.err)
    assert not captured.err
    return json.loads(captured.out)


def _build(tmp_path, capsys):
    catalog, declarations = _inputs(tmp_path)
    source = _dump(tmp_path / "catalog.json", catalog)
    declared = _dump(tmp_path / "declarations.json", declarations)
    output = tmp_path / "relations.json"
    written = _call(capsys, "relations-build", source, declared, "--relations-id", "fixture:relations",
                    "--expected-head", catalog["snapshot_hash"], "--out", output)
    assert written["relation_count"] == 4
    assert written["relations_hash"] == json.loads(output.read_text())["relations_hash"]
    return catalog, source, declared, output


def test_cli_separates_intents_blocks_conflict_and_keeps_input_bytes(tmp_path, capsys):
    _, catalog, declared, relations = _build(tmp_path, capsys)
    original = {path: path.read_bytes() for path in (catalog, declared, relations)}
    similar = _call(capsys, "relations-search", catalog, relations, "--source-id", "fixture:house", "--intent", "similar")
    assert [match["target"]["id"] for match in similar["matches"]] == ["fixture:house-variant"]
    complementary = _call(capsys, "relations-search", catalog, relations, "--source-id", "fixture:house", "--intent", "complementary")
    assert [match["target"]["id"] for match in complementary["matches"]] == ["fixture:roof"]
    assert [match["target"]["id"] for match in complementary["blocked_candidates"]] == ["fixture:stairs"]
    assert complementary["matches"][0]["status"] == "caller_declared"
    assert complementary["matches"][0]["relations"][0]["evidence"][0]["reference"] == "fixture:architecture-recipe"
    reverse = _call(capsys, "relations-search", catalog, relations, "--source-id", "fixture:roof", "--intent", "complementary")
    assert reverse["matches"] == []
    assert {path: path.read_bytes() for path in original} == original


def test_cli_revised_report_does_not_inherit_complementary_link(tmp_path, capsys):
    snapshot, catalog, _, relations = _build(tmp_path, capsys)
    original = next(report for report in snapshot["reports"] if report["source"]["id"] == "fixture:roof")
    revised = inspect_asset(b"new roof", filename="roof.txt", source_id="fixture:roof", revision="v2")
    current = put_asset_report(snapshot, revised, expected_head=snapshot["snapshot_hash"],
                               expected_report_hash=validated_review_report_hash(original))
    updated = _dump(tmp_path / "catalog-v2.json", current)
    found = _call(capsys, "relations-search", updated, relations, "--source-id", "fixture:house", "--intent", "complementary")
    assert not found["matches"]
    assert any(item["id"] == "fixture:roof" for item in found["unapplied_relations"])


@pytest.mark.parametrize("problem", ["stale_head", "unknown_field", "missing_evidence", "unknown_target", "not_array"])
def test_invalid_preparation_creates_no_file(tmp_path, capsys, problem):
    snapshot, declarations = _inputs(tmp_path)
    head = snapshot["snapshot_hash"]
    if problem == "stale_head":
        head = "0" * 64
    elif problem == "unknown_field":
        declarations[0]["confidence"] = 1.0
    elif problem == "missing_evidence":
        declarations[0]["evidence"] = []
    elif problem == "unknown_target":
        declarations[0]["target_id"] = "missing"
    else:
        declarations = {"relations": declarations}
    catalog = _dump(tmp_path / "catalog.json", snapshot)
    declared = _dump(tmp_path / "declared.json", declarations)
    output = tmp_path / "refused.json"
    before = catalog.read_bytes(), declared.read_bytes()
    _call(capsys, "relations-build", catalog, declared, "--relations-id", "fixture:relations",
          "--expected-head", head, "--out", output, code=2)
    assert not output.exists()
    assert before == (catalog.read_bytes(), declared.read_bytes())


@pytest.mark.parametrize("existing", ["regular", "symlink", "dangling_symlink"])
def test_relation_output_never_overwrites_existing_path(tmp_path, capsys, existing):
    snapshot, catalog, declared, relations = _build(tmp_path, capsys)
    target = tmp_path / "target.json"
    output = tmp_path / "other.json"
    if existing == "regular":
        output = relations
    else:
        if existing == "symlink":
            target.write_bytes(b"preserve")
        try:
            output.symlink_to(target)
        except OSError:
            pytest.skip("Host does not support symlinks")
    before = relations.read_bytes()
    _call(capsys, "relations-build", catalog, declared, "--relations-id", "fixture:relations",
          "--expected-head", snapshot["snapshot_hash"], "--out", output, code=2)
    assert relations.read_bytes() == before
    if existing == "symlink":
        assert target.read_bytes() == b"preserve"
    if existing == "dangling_symlink":
        assert not target.exists()


@pytest.mark.parametrize("which", ["catalog", "declarations", "relations"])
def test_relation_commands_refuse_symlink_inputs(tmp_path, capsys, which):
    snapshot, catalog, declared, relations = _build(tmp_path, capsys)
    link = tmp_path / "link.json"
    try:
        link.symlink_to({"catalog": catalog, "declarations": declared, "relations": relations}[which])
    except OSError:
        pytest.skip("Host does not support symlinks")
    if which == "relations":
        _call(capsys, "relations-search", catalog, link, "--source-id", "fixture:house", "--intent", "complementary", code=2)
    else:
        _call(capsys, "relations-build", link if which == "catalog" else catalog,
              link if which == "declarations" else declared, "--relations-id", "fixture:relations",
              "--expected-head", snapshot["snapshot_hash"], "--out", tmp_path / "refused.json", code=2)
        assert not (tmp_path / "refused.json").exists()


def test_module_entrypoint_searches_saved_relations(tmp_path, capsys):
    _, catalog, _, relations = _build(tmp_path, capsys)
    result = subprocess.run(
        [sys.executable, "-m", "tiberium_ai.asset_cli", "relations-search", str(catalog), str(relations),
         "--source-id", "fixture:house", "--intent", "complementary"],
        text=True, capture_output=True, check=True,
    )
    assert not result.stderr
    assert [match["target"]["id"] for match in json.loads(result.stdout)["matches"]] == ["fixture:roof"]
