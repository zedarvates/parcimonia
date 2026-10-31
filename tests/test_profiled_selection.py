from copy import deepcopy

import pytest

from tiberium_ai.agent_recipes.core import DecisionSession
from tiberium_ai.execution_profiles import ExecutionCatalog, digest
from tiberium_ai.profiled_selection import filter_profiled_routes, select_profiled_skill
from tiberium_ai.registry import RouteRegistry

from test_execution_profiles import claim, host, policy, profile


def routes():
    return RouteRegistry.from_manifest({"schema_version": 1, "registry_version": "fixture/1",
        "routes": [{"route_id": i, "capability_ids": ["read@1"],
            "estimated_cost": None, "estimated_latency_ms": None, "confidence": None,
            "constraints": {"risk_classes": ["low"], "evidence_levels": ["normal"], "localities": ["local"]},
            "verifier": {"verifier_id": "fixture/read", "verifier_version": "1"}}
            for i in ("first", "second", "unprofiled")]})


def test_route_adapter_preserves_legacy_constraints_and_unbound_abstention():
    from tiberium_ai.contracts import Task

    p = profile()
    remote = profile("tool:remote")
    remote["facets"]["locations"] = claim(["cloud"])
    catalog = ExecutionCatalog("fixture/1", [p, remote])
    kwargs = {"catalog": catalog, "bindings": {"first": p["id"], "second": remote["id"]},
              "policy": policy(), **host([p, remote])}
    eligible, trace = filter_profiled_routes(routes(), Task("t", "read", {}, locality="local"), **kwargs)
    assert [c.route_id for c in eligible] == ["first"]
    assert trace["missing_bindings"] == ["unprofiled"]
    assert trace["profile_refs"][0] == catalog.reference(p["id"])
    assert trace["auto_act_allowed"] is False
    ineligible, _ = filter_profiled_routes(routes(), Task("t", "read", {}, locality="cloud"), **kwargs)
    assert ineligible == []
    ineligible, _ = filter_profiled_routes(routes(), Task("t", "read", {}, locality="local"),
                                          **kwargs, required_capabilities=["absent"])
    assert ineligible == []


def test_skill_filter_and_trace_work_without_model_for_explicit_selection():
    p = profile("skill:local", kind="skill")
    catalog = ExecutionCatalog("fixture/1", [p])
    skills = [{"id": "s", "name": "local", "description": "review code", "content_hash": "legacy-json-text-hash"}]
    original = deepcopy(skills)
    session = DecisionSession()
    proposal, trace = select_profiled_skill("review", skills, session, catalog=catalog,
        bindings={"s": p["id"]}, policy=policy(), explicit_id="s", **host([p]))
    assert proposal.data == "s"
    assert proposal.auto_act_allowed is False
    assert trace["proposal_sha256"] == digest(proposal.to_dict())
    assert trace["eligible_skills"] == ["s"]
    assert not session.calls and skills == original


def test_blocked_explicit_skill_cannot_bypass_profile_filter():
    p = profile("skill:local", kind="skill")
    catalog = ExecutionCatalog("fixture/1", [p])
    proposal, trace = select_profiled_skill("review", [{"id": "s"}], DecisionSession(), catalog=catalog,
        bindings={"s": p["id"]}, policy=policy(), observed_content={}, explicit_id="s")
    assert proposal.status == "abstained"
    assert trace["eligible_skills"] == []


def test_skill_model_input_keeps_versioned_profile_and_no_authority():
    from tiberium_ai.reflex import InjectedReflexBackend

    p = profile("skill:local", kind="skill")
    catalog = ExecutionCatalog("fixture/1", [p])
    session = DecisionSession(InjectedReflexBackend({"choice": {"choice": "s", "confidence": 1,
        "probabilities": {"s": 1, "none": 0}}}, latin_only=False))
    proposal, _ = select_profiled_skill("review", [{"id": "s", "name": "local", "description": "code"}],
        session, catalog=catalog, bindings={"s": p["id"]}, policy=policy(), **host([p]))
    assert proposal.data == "s"
    state = session.calls[0]["request"]["state"]
    # Legacy selection serializes its state before the backend call.
    import json
    if isinstance(state, str):
        state = json.loads(state)
    assert state["skills"][0]["execution_profile"]["reference"] == catalog.reference(p["id"])


def test_wrong_kind_skill_binding_is_rejected():
    p = profile()
    with pytest.raises(ValueError, match="skill profile"):
        select_profiled_skill("read", [{"id": "s"}], DecisionSession(),
            catalog=ExecutionCatalog("fixture/1", [p]), bindings={"s": p["id"]}, policy=policy(), **host([p]))
