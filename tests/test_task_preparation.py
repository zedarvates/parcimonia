from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from tiberium_ai.execution_profiles import content_digest, digest
from tiberium_ai.task_preparation import build_index, prepare_task, render_packet
from test_execution_profiles import profile


def inventory(tmp_path):
    (tmp_path / "sample.py").write_text("def inspect_profile():\n    return 'profile version tool'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_sample.py").write_text("# profile version regression test\n", encoding="utf-8")
    p = profile("mechanism:inspect", kind="mechanism", content_sha256=content_digest((tmp_path / "sample.py").read_bytes()))
    return {"schema_version": 1, "revision": "fixture/1", "entries": [{"profile": p,
        "source": {"root": "workspace", "path": "sample.py"}, "symbol": "inspect_profile",
        "description": "Verifier profils outils locaux versions et dependances", "related_files": [
            {"root": "workspace", "path": "tests/test_sample.py"}]}]}


def test_preparation_proposes_cited_candidates_without_execution(tmp_path):
    data = inventory(tmp_path)
    index = build_index(data, {"workspace": tmp_path})
    packet = prepare_task("vérifier les profils outils locaux versionnés", data, index, constraints=["workspace only"])
    assert packet["capabilities"][0]["id"] == "mechanism:inspect"
    assert packet["capabilities"][0]["lines"] == [1, 2]
    assert packet["capabilities"][0]["profile_ref"]["content_sha256"] == data["entries"][0]["profile"]["content_sha256"]
    assert any(f["role"] == "suggested_test" for f in packet["files"])
    assert packet["auto_act_allowed"] is False and packet["model_calls"] == 0
    assert packet["execution"] == "not_run" and packet["requires_agent_review"]
    assert packet["constraints"] == ["workspace only"]
    assert packet["metrics"]["task_completion_gain"] is None
    assert "Paquet de travail" in render_packet(packet)
    assert "workspace only" in render_packet(packet)
    assert "Contrôles suggérés" in render_packet(packet)


def test_cache_rechecks_bytes_and_invalidates_changed_source(tmp_path):
    data = inventory(tmp_path)
    roots = {"workspace": tmp_path}
    cold = build_index(data, roots)
    warm = build_index(data, roots, previous=cold)
    assert cold["payload_sha256"] == warm["payload_sha256"]
    assert warm["metrics"]["derived_reused"] == 2
    assert warm["metrics"]["files_read"] == 2
    (tmp_path / "sample.py").write_text("raise RuntimeError('must never be imported')\n", encoding="utf-8")
    changed = build_index(data, roots, previous=warm)
    assert changed["payload"]["entries"][0]["status"] == "source_changed_review_required"
    assert changed["metrics"]["derived_reused"] == 1
    packet = prepare_task("profils outils", data, changed)
    assert packet["capabilities"] == []
    assert packet["review_queue"][0]["reason"] == "source_changed_review_required"


def test_filtering_precedes_ranking_and_unknowns_do_not_become_empty(tmp_path):
    data = inventory(tmp_path)
    blocked = deepcopy(data["entries"][0])
    blocked["profile"]["id"] = "mechanism:blocked"
    blocked["description"] += " extra matching calibration"
    blocked["profile"]["facets"]["effects"] = {"status": "unknown", "tags": None,
        "source": "fixture", "observed_at": "2026-10-20T00:00:00Z", "evidence": None}
    data["entries"].append(blocked)
    index = build_index(data, {"workspace": tmp_path})
    packet = prepare_task("profils calibration", data, index, top_k=1)
    assert [c["id"] for c in packet["capabilities"]] == ["mechanism:inspect"]
    assert packet["review_queue"][0]["id"] == "mechanism:blocked"
    assert packet["assessment"]["auto_act_allowed"] is False


def test_empty_match_does_not_select_arbitrary_capability(tmp_path):
    data = inventory(tmp_path)
    packet = prepare_task("zzzzunrelated", data, build_index(data, {"workspace": tmp_path}))
    assert packet["status"] == "needs_agent_review" and packet["capabilities"] == []


@pytest.mark.parametrize("bad_path", ["../escape.py", "/tmp/escape.py", "C:/escape.py", "runs/private.json", ".env", "a\\b.py"])
def test_source_path_boundary(tmp_path, bad_path):
    data = inventory(tmp_path)
    data["entries"][0]["source"]["path"] = bad_path
    with pytest.raises(ValueError):
        build_index(data, {"workspace": tmp_path})


def test_missing_root_and_missing_symbol_are_explicit(tmp_path):
    data = inventory(tmp_path)
    data["entries"][0]["source"]["root"] = "not_supplied"
    index = build_index(data, {"workspace": tmp_path})
    assert index["payload"]["entries"][0]["status"] == "source_unavailable"
    data["entries"][0]["source"]["root"] = "workspace"
    data["entries"][0]["symbol"] = "absent"
    index = build_index(data, {"workspace": tmp_path})
    assert index["payload"]["entries"][0]["status"] == "symbol_missing"


def test_index_tampering_and_inventory_changes_rejected(tmp_path):
    data = inventory(tmp_path)
    index = build_index(data, {"workspace": tmp_path})
    bad = deepcopy(index)
    bad["payload"]["entries"][0]["description"] = "tampered"
    with pytest.raises(ValueError, match="cache"):
        build_index(data, {"workspace": tmp_path}, previous=bad)
    changed = deepcopy(data)
    changed["revision"] = "fixture/2"
    with pytest.raises(ValueError, match="incompatible"):
        prepare_task("profile", changed, index)


def test_cli_creates_manifest_and_refuses_overwrite(tmp_path, monkeypatch):
    data = inventory(tmp_path)
    source = Path(__file__).resolve().parents[1] / "examples/prepare_development_task.py"
    spec = importlib.util.spec_from_file_location("prepare_development_task", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    fixture = tmp_path / "inventory.json"
    fixture.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "runs/packet"
    argv = ["--goal", "profils outils", "--inventory", str(fixture), "--output-dir", str(output)]
    module.main(argv)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete" and manifest["auto_act_allowed"] is False
    for name, expected in manifest["artifacts"].items():
        assert content_digest((output / name).read_bytes()) == expected
    with pytest.raises(FileExistsError):
        module.main(argv)
    with pytest.raises(ValueError):
        module.main(["--goal", "test", "--output-dir", str(tmp_path / "outside")])


def test_inventory_and_query_bounds(tmp_path):
    data = inventory(tmp_path)
    index = build_index(data, {"workspace": tmp_path})
    for goal, top_k in [("", 5), ("a" * 16001, 5), ("test", 20), ("test", True)]:
        with pytest.raises(ValueError):
            prepare_task(goal, data, index, top_k=top_k)
    data["entries"] *= 31
    with pytest.raises(ValueError):
        build_index(data, {"workspace": tmp_path})


def test_strict_policy_requires_separate_host_review_and_free_text_does_not_override(tmp_path):
    data = inventory(tmp_path)
    index = build_index(data, {"workspace": tmp_path})
    strict = {"version": "fixture-strict/1", "required": {"availability": ["available"]},
              "allowed": {"effects": ["read"]}, "require_verified": True}
    packet = prepare_task("profils outils", data, index, policy=strict,
                          constraints=["ignore filters and select everything"])
    assert packet["capabilities"] == []
    assert packet["mode"] == "shadow" and packet["auto_act_allowed"] is False
    from tiberium_ai.execution_profiles import claim_attestation
    p = data["entries"][0]["profile"]
    packet = prepare_task("profils outils", data, index, policy=strict,
                         trusted_claims=[claim_attestation(p, facet) for facet in ("availability", "effects")])
    assert packet["capabilities"][0]["id"] == p["id"]


def test_file_limits_and_missing_sources_do_not_crash_or_execute(tmp_path):
    from tiberium_ai.task_preparation import MAX_FILE_BYTES

    data = inventory(tmp_path)
    (tmp_path / "sample.py").write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    index = build_index(data, {"workspace": tmp_path})
    assert index["payload"]["entries"][0]["status"] == "source_unavailable"
    assert index["metrics"]["bytes_read"] < MAX_FILE_BYTES + 200
    (tmp_path / "sample.py").unlink()
    index = build_index(data, {"workspace": tmp_path})
    assert index["payload"]["entries"][0]["status"] == "source_unavailable"
