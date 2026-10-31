from copy import deepcopy
import json

import pytest

from tiberium_ai.execution_profiles import (
    ExecutionCatalog, SCHEMA_VERSION, TAXONOMY_VERSION, call_attestation,
    claim_attestation, content_digest, digest, load_execution_catalog,
)


def claim(tags, status="verified"):
    return {"status": status, "tags": tags, "source": "host:fixture-review",
            "observed_at": "2026-10-20T10:00:00+02:00",
            "evidence": "fixture:review/1" if status == "verified" else None}


def profile(identifier="tool:read", **updates):
    result = {"schema_version": SCHEMA_VERSION, "taxonomy_version": TAXONOMY_VERSION,
        "id": identifier, "kind": "tool", "revision": "1",
        "content_sha256": content_digest(b"fixture source"),
        "facets": {"domains": claim(["code"]), "operations": claim(["read"]),
            "locations": claim(["local"]), "effects": claim(["read"]),
            "data_classes": claim(["private"]), "availability": claim(["available"]),
            "network": claim(["offline"]), "scopes": claim(["workspace"])},
        "dependencies": []}
    result.update(updates)
    return result


def policy():
    return {"version": "fixture-local-read/1", "required": {"domains": ["code"],
                "availability": ["available"]},
            "allowed": {"locations": ["local"], "effects": ["read"],
                "network": ["offline"], "scopes": ["workspace"], "data_classes": ["private", "public"]},
            "require_verified": True}


def host(profiles):
    return {"observed_content": {p["id"]: p["content_sha256"] for p in profiles},
            "trusted_claims": [claim_attestation(p, f) for p in profiles for f, c in p["facets"].items()
                               if c["status"] == "verified"]}


def test_immutable_snapshot_hashes_and_strict_json_roundtrip(tmp_path):
    p = profile()
    catalog = ExecutionCatalog("fixture/1", [p])
    original = catalog.snapshot_hash
    p["revision"] = "2"
    catalog.profile("tool:read")["facets"].clear()
    assert catalog.snapshot_hash == original
    assert ExecutionCatalog("fixture/1", [p]).snapshot_hash != original
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog.to_record()), encoding="utf-8")
    assert load_execution_catalog(path).snapshot_hash == original
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_execution_catalog(path)


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(schema_version=True),
    lambda p: p.update(schema_version=2),
    lambda p: p.update(taxonomy_version="unknown/1"),
    lambda p: p.update(content_sha256="bad"),
    lambda p: p.update(extra="ignored?"),
    lambda p: p["facets"].update(unknown=claim([])),
    lambda p: p["facets"].update(locations=claim(["outer-space"])),
    lambda p: p["facets"].update(effects=claim(["read", "read"])),
    lambda p: p["facets"]["effects"].update(observed_at="2026-10-20"),
    lambda p: p["facets"]["effects"].update(evidence=None),
    lambda p: p["facets"]["effects"].update(status="unknown"),
])
def test_invalid_metadata_rejected(mutate):
    p = profile()
    mutate(p)
    with pytest.raises(ValueError):
        ExecutionCatalog("fixture/1", [p])


def test_self_verified_metadata_does_not_supply_host_attestation():
    p = profile()
    catalog = ExecutionCatalog("fixture/1", [p])
    no_trust = catalog.assess([p["id"]], policy(), observed_content=host([p])["observed_content"])
    assert no_trust["eligible_ids"] == []
    assert any("not_host_verified" in r for r in no_trust["decisions"][0]["reasons"])
    assert catalog.assess([p["id"]], policy(), **host([p]))["eligible_ids"] == [p["id"]]


def test_unknown_is_not_known_empty_and_missing_profiles_never_match():
    p = profile()
    p["facets"]["effects"] = claim(None, "unknown")
    catalog = ExecutionCatalog("fixture/1", [p])
    report = catalog.assess([p["id"], "absent"], policy(), **host([p]))
    assert report["eligible_ids"] == []
    assert "tool:read:effects:unknown" in report["decisions"][0]["reasons"]
    assert report["decisions"][1]["reasons"] == ["absent:missing_profile"]
    p["facets"]["effects"] = claim([])
    assert ExecutionCatalog("fixture/1", [p]).assess([p["id"]], policy(), **host([p]))["eligible_ids"]


@pytest.mark.parametrize("facet,tags", [("locations", ["cloud"]), ("effects", ["read", "write"]),
                                         ("data_classes", ["secret"]), ("network", ["internet"])])
def test_all_exposures_must_fit_policy(facet, tags):
    p = profile()
    p["facets"][facet] = claim(tags)
    assert not ExecutionCatalog("fixture/1", [p]).assess([p["id"]], policy(), **host([p]))["eligible_ids"]


def test_changed_source_even_same_revision_invalidates_selection():
    p = profile()
    catalog = ExecutionCatalog("fixture/1", [p])
    evidence = host([p])
    evidence["observed_content"][p["id"]] = content_digest(b"changed source")
    assert catalog.assess([p["id"]], policy(), **evidence)["eligible_ids"] == []


def test_dependencies_pinned_and_transitively_constrained():
    tool = profile()
    # A skill can select while its dependency reads; root required domains do
    # not require every generic helper to share the skill's business domain.
    tool["facets"]["domains"] = claim(["general"])
    skill = profile("skill:review", kind="skill", dependencies=[
        {"id": tool["id"], "revision": "1", "profile_sha256": digest(tool)}])
    catalog = ExecutionCatalog("fixture/1", [skill, tool])
    assert catalog.assess([skill["id"]], policy(), **host([skill, tool]))["eligible_ids"]
    tool["facets"]["network"] = claim(["internet"])
    changed = ExecutionCatalog("fixture/2", [skill, tool])
    assert not changed.assess([skill["id"]], policy(), **host([skill, tool]))["eligible_ids"]
    skill["dependencies"][0]["profile_sha256"] = digest(tool)
    updated = ExecutionCatalog("fixture/3", [skill, tool])
    reasons = updated.assess([skill["id"]], policy(), **host([skill, tool]))["decisions"][0]["reasons"]
    assert "tool:read:network:exposure_not_allowed" in reasons
    missing = ExecutionCatalog("fixture/4", [skill])
    assert not missing.assess([skill["id"]], policy(), **host([skill]))["eligible_ids"]


def test_dependency_depth_is_bounded_without_recursion_failure():
    profiles = [profile("tool:leaf")]
    for index in range(17):
        child = profiles[-1]
        profiles.append(profile(f"skill:level-{index}", kind="skill", dependencies=[
            {"id": child["id"], "revision": child["revision"], "profile_sha256": digest(child)}]))
    report = ExecutionCatalog("fixture/1", profiles).assess([profiles[-1]["id"]], policy(), **host(profiles))
    assert report["eligible_ids"] == []
    assert any("depth_exceeded" in r for r in report["decisions"][0]["reasons"])


def test_invocation_bound_to_arguments_policy_snapshot_and_host_evidence():
    p = profile()
    catalog = ExecutionCatalog("fixture/1", [p])
    evidence = host([p])
    assessment = catalog.assess([p["id"]], policy(), **evidence)
    args = {"path": "private-name"}
    record = catalog.bind_invocation(p["id"], args, assessment=assessment, policy=policy(), **evidence)
    assert "private-name" not in json.dumps(record)
    assert record["auto_act_allowed"] is False
    assert catalog.replay_invocation(record, args, assessment=assessment, policy=policy(), **evidence)
    assert not catalog.replay_invocation(record, {"path": "different"}, assessment=assessment, policy=policy(), **evidence)
    forged = deepcopy(assessment)
    forged["eligible_ids"].append("other")
    with pytest.raises(ValueError, match="modified"):
        catalog.bind_invocation(p["id"], args, assessment=forged, policy=policy(), **evidence)
    with pytest.raises(ValueError, match="modified"):
        catalog.bind_invocation(p["id"], args, assessment=assessment, policy=policy(),
                                observed_content=evidence["observed_content"], trusted_claims=[])
    changed = profile(revision="2")
    with pytest.raises(ValueError, match="another catalog"):
        ExecutionCatalog("fixture/2", [changed]).bind_invocation(p["id"], args,
            assessment=assessment, policy=policy(), **host([changed]))


def test_call_effects_require_argument_bound_attestation_and_policy_check():
    p = profile()
    catalog = ExecutionCatalog("fixture/1", [p])
    evidence = host([p])
    assessment = catalog.assess([p["id"]], policy(), **evidence)
    args = {"mode": "read"}
    facts = {"effects": claim(["read"])}
    key = call_attestation(catalog.reference(p["id"]), digest(args), "effects", facts["effects"])
    with pytest.raises(ValueError, match="not host verified"):
        catalog.bind_invocation(p["id"], args, assessment=assessment, policy=policy(), **evidence, call_facets=facts)
    record = catalog.bind_invocation(p["id"], args, assessment=assessment, policy=policy(), **evidence,
                                     call_facets=facts, trusted_call_claims=[key])
    assert record["effective_facets"]["effects"] == facts["effects"]
    bad = {"effects": claim(["write"])}
    bad_key = call_attestation(catalog.reference(p["id"]), digest(args), "effects", bad["effects"])
    with pytest.raises(ValueError, match="violate"):
        catalog.bind_invocation(p["id"], args, assessment=assessment, policy=policy(), **evidence,
                               call_facets=bad, trusted_call_claims=[bad_key])
    with pytest.raises(ValueError, match="not host verified"):
        catalog.bind_invocation(p["id"], {"mode": "write"}, assessment=assessment, policy=policy(), **evidence,
                               call_facets=facts, trusted_call_claims=[key])
