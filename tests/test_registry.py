import json

import pytest

from tiberium_ai.contracts import CandidateRoute, Task
from tiberium_ai.observations import compare_observation, record_observation, replay_observation
from tiberium_ai.registry import load_route_registry, RouteRegistry
from tiberium_ai.router import ShadowRouter
from tiberium_ai.verification import VerifierRegistry, exact_match_verifier, shape_verifier


def verifiers():
    registry = VerifierRegistry()
    registry.register("shape/answer", "1", shape_verifier({"answer": "str"}))
    registry.register("math/exact", "1", exact_match_verifier({"total": 1}))
    return registry


def route(route_id, **overrides):
    values = {
        "route_id": route_id,
        "capability_ids": ["format"],
        "estimated_cost": 1.0,
        "estimated_latency_ms": 900.0,
        "confidence": 0.99,
        "constraints": {
            "risk_classes": ["low"],
            "evidence_levels": ["normal"],
            "localities": ["any"],
        },
        "verifier": {"verifier_id": "shape/answer", "verifier_version": "1"},
    }
    values.update(overrides)
    return values


def manifest(**overrides):
    values = {
        "schema_version": 1,
        "registry_version": "routes/2026-09-18",
        "routes": [
            route("rule", capability_ids=["format", "rule:format"], estimated_cost=0.01,
                  estimated_latency_ms=30.0, confidence=0.95),
            route("baseline"),
        ],
    }
    values.update(overrides)
    return values


def registry(**overrides):
    return RouteRegistry.from_manifest(manifest(**overrides), verifiers=verifiers())


def test_candidates_follow_manifest_order():
    candidates = registry().candidates_for(Task("t1", "format", {}))
    assert [candidate.route_id for candidate in candidates] == ["rule", "baseline"]
    assert candidates[0].estimated_cost == 0.01
    assert candidates[0].confidence == 0.95
    assert list(candidates[0].capability_ids) == ["format", "rule:format"]


def test_constraints_filter_routes_for_a_task():
    local_only = route(
        "local",
        constraints={
            "risk_classes": ["low"],
            "evidence_levels": ["normal"],
            "localities": ["local"],
        },
    )
    registry_with_local = RouteRegistry.from_manifest(
        manifest(routes=[local_only]), verifiers=verifiers()
    )
    assert registry_with_local.candidates_for(Task("t1", "format", {})) == []
    assert len(
        registry_with_local.candidates_for(
            Task("t1", "format", {}, locality="local")
        )
    ) == 1


def test_risk_classes_filter_routes_for_a_task():
    assert registry().candidates_for(Task("t1", "format", {}, risk_class="high")) == []


def test_required_capabilities_must_all_be_present():
    candidates = registry().candidates_for(
        Task("t1", "format", {}), required_capabilities=["rule:format"]
    )
    assert [candidate.route_id for candidate in candidates] == ["rule"]
    assert registry().candidates_for(
        Task("t1", "format", {}), required_capabilities=["absent"]
    ) == []


def test_verifier_declarations_must_be_registered():
    broken = manifest(
        routes=[route("rule", verifier={"verifier_id": "absent", "verifier_version": "1"})]
    )
    with pytest.raises(ValueError, match="verifier"):
        RouteRegistry.from_manifest(broken, verifiers=verifiers())


def test_known_capabilities_are_enforced_when_provided():
    with pytest.raises(ValueError, match="unknown capabilities"):
        RouteRegistry.from_manifest(
            manifest(), known_capabilities={"format"}, verifiers=verifiers()
        )


def test_duplicate_route_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        registry(routes=[route("rule"), route("rule")])


def test_verifier_lookup_returns_the_declared_identity():
    assert registry().verifier_for("rule") == ("shape/answer", "1")


@pytest.mark.parametrize("mutate", [
    lambda m: m.update(schema_version=2),
    lambda m: m.update(registry_version=""),
    lambda m: m.update(routes=[]),
    lambda m: m.update(extra="x"),
    lambda m: m.pop("routes"),
    lambda m: m.update(routes=[route("rule", estimated_cost=-1)]),
    lambda m: m.update(routes=[route("rule", estimated_cost=float("nan"))]),
    lambda m: m.update(routes=[route("rule", confidence=1.5)]),
    lambda m: m.update(routes=[route("rule", capability_ids=[])]),
    lambda m: m.update(routes=[route("rule", capability_ids=["format", "format"])]),
    lambda m: m.update(routes=[route(" padded ")]),
    lambda m: m.update(routes=[route("rule", constraints={"risk_classes": []})]),
    lambda m: m.update(routes=[route("rule", verifier={"verifier_id": "x"})]),
])
def test_invalid_manifests_are_rejected(mutate):
    broken = manifest()
    mutate(broken)
    with pytest.raises(ValueError):
        RouteRegistry.from_manifest(broken, verifiers=verifiers())


def test_registry_version_changes_the_policy_version():
    first = registry(registry_version="routes/one")
    second = registry(registry_version="routes/two")
    assert first.policy_version("shadow-routing/1") == "shadow-routing/1+registry:routes/one"
    assert second.policy_version("shadow-routing/1") != first.policy_version("shadow-routing/1")
    assert ShadowRouter(registry=first).policy_version.endswith("registry:routes/one")
    assert ShadowRouter().policy_version == "shadow-routing/1"


def test_the_router_proposes_from_the_registry():
    decision = ShadowRouter(registry=registry()).propose(Task("t1", "format", {}))
    assert decision.selected_route_id == "rule"
    assert decision.mode == "shadow"
    assert not decision.abstained


def test_an_unknown_capability_makes_the_router_abstain():
    decision = ShadowRouter(registry=registry()).propose(
        Task("t1", "format", {}), required_capabilities=["absent"]
    )
    assert decision.abstained
    assert decision.selected_route_id is None


def test_the_router_requires_candidates_without_a_registry():
    with pytest.raises(ValueError, match="candidates"):
        ShadowRouter().propose(Task("t1", "format", {}))


def test_a_registry_must_expose_the_expected_interface():
    with pytest.raises(TypeError, match="registry"):
        ShadowRouter(registry=object())


def test_observation_records_the_registry_version_and_replays():
    source = registry(registry_version="routes/one")
    record = record_observation(
        Task("t1", "format", {}),
        registry=source,
        baseline_route_id="baseline",
        cost_unit="unit/task",
        data_origin="synthetic",
    )
    assert record["router"]["policy_version"] == "shadow-routing/1+registry:routes/one"
    assert replay_observation(record).selected_route_id == "rule"
    assert compare_observation(record)["status"] == "insufficient_evidence"


def test_observation_needs_candidates_or_a_registry():
    with pytest.raises(ValueError, match="registry"):
        record_observation(
            Task("t1", "format", {}),
            baseline_route_id="baseline",
            cost_unit="unit/task",
            data_origin="synthetic",
        )


def test_load_route_registry_reads_a_strict_json_file(tmp_path):
    path = tmp_path / "routes.json"
    path.write_text(json.dumps(manifest()), encoding="utf-8")
    loaded = load_route_registry(path, verifiers=verifiers())
    assert loaded.version == "routes/2026-09-18"


@pytest.mark.parametrize("payload", [
    '{"schema_version": 1, "schema_version": 1, "registry_version": "x", "routes": []}',
    '{"schema_version": 1, "registry_version": "x", "routes": [], "extra": NaN}',
    "[1, 2]",
    "{broken",
])
def test_load_route_registry_rejects_ambiguous_json(tmp_path, payload):
    path = tmp_path / "routes.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError):
        load_route_registry(path, verifiers=verifiers())


def test_candidate_route_contract_is_respected():
    candidate = registry().candidates_for(Task("t1", "format", {}))[0]
    assert isinstance(candidate, CandidateRoute)
