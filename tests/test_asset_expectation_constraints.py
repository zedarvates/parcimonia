"""Small independent oracles and certificate tampering at the real boundary."""

from copy import deepcopy
from itertools import combinations_with_replacement
import json

import pytest

from examples.asset_catalog_demo import _png
from tiberium_ai.asset_expectation_constraints import (
    check_asset_expectations, register_asset_expectation_verifier,
    verify_asset_expectation_constraints,
)
from tiberium_ai.asset_expectations import audit_asset_expectations
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.verification import VerifierRegistry, hash_input


def check(op="gte", value=512, *, fact="metadata.width", ident="minimum"):
    return {"id": ident, "fact": fact, "op": op, "value": value}


def contract(*checks):
    return {"schema": "parcimonia.asset-expectations/v1", "id": "fixture:constraints", "assets": [
        {"source": {"id": "image", "revision": "v1"}, "checks": list(checks) or [check()]},
    ]}


def conflicting():
    return contract(check(), check("lte", 256, ident="maximum"))


def fact(report, index=0):
    return report["results"][0]["facts"][index]


def test_width_contradiction_cites_two_exact_rules_and_not_a_source_observation():
    request = conflicting()
    report = check_asset_expectations(request)
    assert report["status"] == "contradictory"
    assert fact(report) == {
        "fact": "metadata.width", "status": "contradictory", "check_ids": ["minimum", "maximum"],
        "candidate": None, "conflict": {"kind": "disjoint_integer_bounds",
            "check_ids": ["minimum", "maximum"], "check_paths": ["/assets/0/checks/0", "/assets/0/checks/1"]},
    }
    assert verify_asset_expectation_constraints(request, report)
    assert report["limits"]["cross_fact_relations"] == "not_modelled"
    for rule in request["assets"][0]["checks"]:
        assert check_asset_expectations(contract(rule))["status"] == "no_conflict_detected"


def test_numeric_results_match_an_independent_exhaustive_oracle_for_815_models():
    rules = [(op, value) for op in ["eq", "gte", "lte"] for value in range(5)]
    comparisons = {"eq": lambda a, b: a == b, "gte": lambda a, b: a >= b, "lte": lambda a, b: a <= b}
    count = 0
    for size in (1, 2, 3):
        for model in combinations_with_replacement(rules, size):
            expected = [v for v in range(5) if all(comparisons[op](v, threshold) for op, threshold in model)]
            request = contract(*(check(op, value, ident=str(i)) for i, (op, value) in enumerate(model)))
            report = check_asset_expectations(request)
            assert (report["status"] == "no_conflict_detected") == bool(expected), model
            if expected:
                assert fact(report)["candidate"] in expected
            else:
                ids = fact(report)["conflict"]["check_ids"]
                pair = [request["assets"][0]["checks"][int(i)] for i in ids]
                assert not any(all(comparisons[r["op"]](v, r["value"]) for r in pair) for v in range(5))
            assert verify_asset_expectation_constraints(request, report)
            count += 1
    assert count == 815


@pytest.mark.parametrize("rules,status,candidate", [
    ([("gte", 0), ("lte", 0)], "no_conflict_detected", 0),
    ([("gte", 2**63-1), ("lte", 2**63-1)], "no_conflict_detected", 2**63-1),
    ([("eq", 2**63-1), ("lte", 2**63-2)], "contradictory", None),
    ([("eq", 0), ("gte", 1)], "contradictory", None),
    ([("eq", 6), ("eq", 6), ("lte", 6)], "no_conflict_detected", 6),
])
def test_inclusive_endpoints_and_equalities_use_exact_63_bit_integers(rules, status, candidate):
    request = contract(*(check(op, value, ident=str(i)) for i, (op, value) in enumerate(rules)))
    report = check_asset_expectations(request)
    assert report["status"] == status and fact(report)["candidate"] == candidate
    assert verify_asset_expectation_constraints(request, report)


@pytest.mark.parametrize("name,values,status", [
    ("sample.complete", [True, False], "contradictory"),
    ("sample.complete", [False, False], "no_conflict_detected"),
    ("format.detected", ["png", "jpeg"], "contradictory"),
    ("format.detected", ["png", "PNG"], "contradictory"),
    ("spatial.crs", ["é", "e\u0301"], "contradictory"),
    ("tag:topic:forêt", [True, True], "no_conflict_detected"),
])
def test_text_booleans_and_proposal_presence_preserve_exact_semantics(name, values, status):
    request = contract(*(check("eq", value, fact=name, ident=str(i)) for i, value in enumerate(values)))
    report = check_asset_expectations(request)
    assert report["status"] == status
    assert verify_asset_expectation_constraints(request, report)


def test_same_check_ids_in_other_assets_and_other_facts_are_not_cross_compared():
    request = contract(check("eq", 1, ident="same"), check("eq", 512, fact="metadata.height", ident="height"))
    other = deepcopy(request["assets"][0])
    other["source"]["revision"] = "v2"
    other["checks"] = [check("eq", 999, ident="same")]
    request["assets"].append(other)
    report = check_asset_expectations(request)
    assert report["status"] == "no_conflict_detected"
    assert verify_asset_expectation_constraints(request, report)
    report["results"][1]["source"]["revision"] = "v1"
    assert not verify_asset_expectation_constraints(request, report)


def test_absence_of_same_fact_conflict_is_not_a_file_existence_or_physics_claim():
    request = contract(check("eq", 1, fact="metadata.observed_vertex_count", ident="vertices"),
                       check("gte", 10, fact="metadata.observed_face_count", ident="faces"),
                       check("eq", "png", fact="format.detected", ident="format"))
    report = check_asset_expectations(request)
    assert report["status"] == "no_conflict_detected"
    assert verify_asset_expectation_constraints(request, report)
    assert report["limits"]["file_existence_quality_completeness"] == "not_established"


def test_abstract_integer_domain_does_not_silently_model_an_inspector_size_cap():
    request = contract(check("gte", 2*1024*1024, fact="sample.bytes"))
    report = check_asset_expectations(request)
    assert report["status"] == "no_conflict_detected"
    assert report["limits"]["producer_profile_caps"] == "not_modelled"
    assert verify_asset_expectation_constraints(request, report)


def test_requirement_consistency_and_observed_audit_remain_separate():
    request = contract(check())
    inspection = inspect_asset(_png(), filename="image.png", source_id="image", revision="v1")
    assert check_asset_expectations(request)["status"] == "no_conflict_detected"
    assert audit_asset_expectations([inspection], request)["results"][0]["status"] == "contradicted"
    assert check_asset_expectations(conflicting())["status"] == "contradictory"
    assert audit_asset_expectations([], conflicting())["results"][0]["status"] == "missing_report"


def test_noncanonical_satisfying_values_and_conflict_pairs_are_valid_certificates(monkeypatch):
    request = contract(check("gte", 5), check("lte", 20, ident="max"))
    report = check_asset_expectations(request)
    fact(report)["candidate"] = 12
    request2 = contract(check("gte", 5), check("lte", 4, ident="max"), check("lte", 3, ident="other"))
    report2 = check_asset_expectations(request2)
    fact(report2)["conflict"] = {"kind": "disjoint_integer_bounds", "check_ids": ["minimum", "max"],
                                 "check_paths": ["/assets/0/checks/0", "/assets/0/checks/1"]}
    def forbidden(*args, **kwargs):
        raise AssertionError("producer must not run during certificate verification")
    monkeypatch.setattr("tiberium_ai.asset_expectation_constraints.check_asset_expectations", forbidden)
    assert verify_asset_expectation_constraints(request, report)
    assert verify_asset_expectation_constraints(request2, report2)


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(schema="future"), lambda r: r.update(input_hash="0"*64),
    lambda r: r["expectations"].update(id="other"), lambda r: r.update(mode="active"),
    lambda r: r["analyser"].update(version="2"), lambda r: r.update(extra=1),
    lambda r: r.update(status="no_conflict_detected"), lambda r: r.update(results=[]),
    lambda r: r["results"][0].update(source={"id":"other","revision":"v1"}),
    lambda r: r["results"][0].update(status="no_conflict_detected"),
    lambda r: r["results"][0].update(facts=[]),
    lambda r: fact(r).update(fact="metadata.height"),
    lambda r: fact(r).update(check_ids=["minimum"]),
    lambda r: fact(r).update(candidate=256), lambda r: fact(r).update(conflict=None),
    lambda r: fact(r)["conflict"].update(check_ids=["minimum","minimum"]),
    lambda r: fact(r)["conflict"].update(check_ids=["minimum","unknown"]),
    lambda r: fact(r)["conflict"].update(check_paths=["/assets/1/checks/0","/assets/0/checks/1"]),
    lambda r: fact(r)["conflict"].update(kind="different_exact_values"),
    lambda r: r["limits"].update(integer_domain=[False,2**63-1]),
    lambda r: r["limits"].update(cross_fact_relations="verified"),
])
def test_every_scope_binding_and_conflict_shape_is_checked(mutation):
    request = conflicting()
    report = check_asset_expectations(request)
    mutation(report)
    assert not verify_asset_expectation_constraints(request, report)


def test_a_rehashed_changed_contract_cannot_make_an_invalid_pair_a_proof():
    request = conflicting()
    report = check_asset_expectations(request)
    request["assets"][0]["checks"][0]["value"] = 64
    report["input_hash"] = hash_input({"analyser":report["analyser"],"expectations":request})
    report["expectations"]["hash"] = hash_input(request)
    assert not verify_asset_expectation_constraints(request, report)


def test_incompatible_whole_group_cannot_certify_an_compatible_selected_pair():
    request = contract(check("gte", 10), check("lte", 5, ident="upper"), check("gte", 1, ident="weak"))
    report = check_asset_expectations(request)
    fact(report)["conflict"].update(check_ids=["weak","upper"],check_paths=["/assets/0/checks/2","/assets/0/checks/1"])
    assert not verify_asset_expectation_constraints(request, report)


@pytest.mark.parametrize("candidate", [True, False, 1.0, -1, 2**63, "1", None])
def test_candidate_types_cannot_exploit_python_coercions(candidate):
    request = contract(check("gte", 0))
    report = check_asset_expectations(request)
    fact(report)["candidate"] = candidate
    assert not verify_asset_expectation_constraints(request, report)


@pytest.mark.parametrize("case", ["tuple", "cycle", "nan", "int-key", "oversized"])
def test_non_json_and_oversized_records_return_false(case):
    request = contract()
    report = check_asset_expectations(request)
    if case == "tuple": report["results"] = tuple(report["results"])
    elif case == "cycle": report["results"].append(report)
    elif case == "nan": fact(report)["candidate"] = float("nan")
    elif case == "int-key": report[1] = True
    else: report["extra"] = "x" * (256*1024)
    assert not verify_asset_expectation_constraints(request, report)


def test_registry_binds_input_packet_and_abstains_for_unknown_version():
    request = conflicting()
    packet = {"expectations":request,"report":check_asset_expectations(request)}
    registry = VerifierRegistry()
    register_asset_expectation_verifier(registry)
    proof = registry.verify("asset-expectation-constraints", "1", packet)
    assert proof.verdict is True and proof.input_hash == hash_input(packet)
    assert registry.verify("asset-expectation-constraints", "2", packet).verdict is None
    fact(packet["report"])["conflict"]["check_ids"] = ["minimum","minimum"]
    assert registry.verify("asset-expectation-constraints", "1", packet).verdict is False


def test_determinism_detached_results_json_and_no_io(monkeypatch):
    request = conflicting()
    before = deepcopy(request)
    report = check_asset_expectations(request)
    assert report == check_asset_expectations(request)
    assert json.loads(json.dumps(report,allow_nan=False)) == report
    def forbidden(*args, **kwargs): raise AssertionError("unexpected I/O")
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    assert verify_asset_expectation_constraints(request, check_asset_expectations(request))
    report["results"][0]["source"]["id"] = "modified"
    report["limits"]["integer_domain"][0] = 12
    assert request == before
    assert check_asset_expectations(request)["limits"]["integer_domain"][0] == 0


@pytest.mark.parametrize("bad_check", [check(value=True),check(value=-1),check(value=2**63),check("eq",False,fact="tag:topic:forest"),check(fact="unknown"),check("eq",None)])
def test_existing_closed_contract_validation_is_reused(bad_check):
    request = contract(bad_check)
    with pytest.raises(ValueError): check_asset_expectations(request)
    assert not verify_asset_expectation_constraints(request,{})


@pytest.mark.parametrize("assets,checks,valid", [(64,1,True),(65,1,False),(8,32,True),(9,32,False),(1,33,False)])
def test_existing_exact_asset_and_check_budgets(assets,checks,valid):
    request = contract()
    request["assets"] = [{"source":{"id":str(i),"revision":"v1"},"checks":[check(value=j,ident=str(j)) for j in range(checks)]} for i in range(assets)]
    if valid:
        report = check_asset_expectations(request)
        assert verify_asset_expectation_constraints(request,report)
    else:
        with pytest.raises(ValueError): check_asset_expectations(request)
