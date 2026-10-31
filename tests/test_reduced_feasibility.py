"""Cross-component tests for source semantics, reduction and proof checking."""

from copy import deepcopy
import itertools
import json

import pytest

from tiberium_ai.diagnostics import main
from tiberium_ai.feasibility import diagnose
from tiberium_ai.reduced_feasibility import (
    diagnose_via_2sat,
    register_reduced_feasibility_verifier,
)
from tiberium_ai.two_sat import verify_2sat_result
from tiberium_ai.verification import VerifierRegistry


def _request(variables=None, constraints=None, observations=None):
    return {
        "schema": "parcimonia.feasibility-request/v1",
        "task_id": "fixture-reduction",
        "scope_id": "test",
        "revision": "v1",
        "variables": ["a", "b"] if variables is None else variables,
        "constraints": [] if constraints is None else constraints,
        "observations": [] if observations is None else observations,
    }


def _require(name, value, identifier):
    return {"id": identifier, "kind": "require", "variable": name, "value": value, "source": "fixture:goal"}


def _implies(first, second, identifier):
    return {"id": identifier, "kind": "implies", "if": {"variable": first, "value": True}, "then": {"variable": second, "value": True}, "source": "fixture:dependency"}


def _observe(name, value):
    return {"variable": name, "value": value, "revision": "v1", "source": "fixture:observation"}


def test_observed_missing_dependency_is_blocked_not_impossible():
    request = _request(
        constraints=[_require("a", True, "goal"), _implies("a", "b", "dependency")],
        observations=[_observe("b", False)],
    )
    before = deepcopy(request)
    report = diagnose_via_2sat(request)
    assert request == before
    assert report["feasibility"] == "blocked_current_state"
    assert report["requirements"]["solution"]["status"] == "satisfiable"
    assert report["current_state"]["solution"]["status"] == "unsatisfiable"
    for item in (report["requirements"], report["current_state"]):
        assert verify_2sat_result(item["reduction"]["target"], item["solution"])


def test_hard_contradiction_has_its_own_unsat_certificate():
    report = diagnose_via_2sat(_request(constraints=[
        _require("a", True, "yes"), _require("a", False, "no")
    ]))
    assert report["feasibility"] == "impossible_within_constraints"
    assert report["current_state"] is None
    assert verify_2sat_result(report["requirements"]["reduction"]["target"], report["requirements"]["solution"])


def test_unknown_evidence_is_not_converted_to_an_absence():
    report = diagnose_via_2sat(_request(
        constraints=[_require("b", True, "goal")],
        observations=[_observe("b", None)],
    ))
    assert report["feasibility"] == "consistent_within_constraints"
    assert report["limits"]["completeness"] == "not_assessed"
    assert report["limits"]["world_feasibility"] == "not_established"
    assert report["current_state"]["reduction"]["unknown_observations"] == ["b"]


def test_failed_quality_criterion_does_not_change_satisfiability():
    request = _request()
    request["criteria"] = [{"id": "stability", "status": "fail", "source": "fixture:test"}]
    report = diagnose_via_2sat(request)
    assert report["feasibility"] == "consistent_within_constraints"
    assert report["limits"]["quality"] == "not_assessed"


def test_unsupported_constraint_abstains_before_any_solver_call(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unsupported semantics must not reach the solver")
    monkeypatch.setattr("tiberium_ai.reduced_feasibility.solve_2cnf", forbidden)
    request = _request(constraints=[{"id": "budget", "kind": "numeric", "source": "fixture"}])
    report = diagnose_via_2sat(request)
    assert report["feasibility"] == "indeterminate"
    assert report["requirements"]["solution"] is None
    assert report["current_state"] is None


def test_invalid_solver_certificate_cannot_be_reported_as_success(monkeypatch):
    monkeypatch.setattr("tiberium_ai.reduced_feasibility.solve_2cnf", lambda *args: {"status": "satisfiable"})
    with pytest.raises(RuntimeError, match="invalid certificate"):
        diagnose_via_2sat(_request())


def test_128_variable_chain_uses_the_explicit_polynomial_route():
    variables = [f"v{i:03d}" for i in range(128)]
    constraints = [_require(variables[0], True, "goal")]
    constraints += [_implies(a, b, f"dependency-{i}") for i, (a, b) in enumerate(zip(variables, variables[1:]))]
    request = _request(variables, constraints, [_observe(variables[-1], False)])
    assert diagnose(request)["feasibility"] == "indeterminate"
    assert diagnose_via_2sat(request)["feasibility"] == "blocked_current_state"


@pytest.mark.parametrize("required,observed", list(itertools.product((True, False), (True, False, None))))
def test_new_route_agrees_with_exhaustive_reference_on_small_models(required, observed):
    request = _request(constraints=[_require("a", required, "goal"), _implies("a", "b", "dependency")], observations=[_observe("a", observed)])
    assert diagnose_via_2sat(request)["feasibility"] == diagnose(request)["feasibility"]


def test_replay_binds_report_to_the_exact_source_and_result():
    request = _request(constraints=[_require("a", True, "goal")])
    report = diagnose_via_2sat(request)
    registry = VerifierRegistry()
    register_reduced_feasibility_verifier(registry)
    verify = lambda value: registry.verify("reduced-boolean-feasibility-report", "1", value).verdict
    assert verify({"request": request, "report": report}) is True
    forged = deepcopy(report)
    forged["feasibility"] = "impossible_within_constraints"
    assert verify({"request": request, "report": forged}) is False
    changed = deepcopy(request)
    changed["revision"] = "v2"
    assert verify({"request": changed, "report": report}) is False


@pytest.mark.parametrize("command", ["reduce", "solve"])
def test_cli_new_commands_produce_separate_versioned_reports(tmp_path, capsys, command):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(_request(constraints=[_require("a", True, "goal")], observations=[_observe("a", False)])), encoding="utf-8")
    assert main([command, str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    if command == "reduce":
        assert report["source_question"] == "constraints_satisfiable"
        assert len(report["target"]["clauses"]) == 1
    else:
        assert report["schema"] == "parcimonia.reduced-feasibility-report/v1"
        assert report["feasibility"] == "blocked_current_state"


def test_cli_opt_in_observations_changes_the_decision_question(tmp_path, capsys):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(_request(constraints=[_require("a", True, "goal")], observations=[_observe("a", False)])), encoding="utf-8")
    assert main(["reduce", str(path), "--with-observations"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["source_question"] == "constraints_and_known_observations_satisfiable"
    assert len(report["target"]["clauses"]) == 2


@pytest.mark.parametrize("command", ["reduce", "solve"])
def test_cli_unsupported_constraint_has_indeterminate_exit(tmp_path, capsys, command):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(_request(constraints=[{"id": "unknown", "kind": "temporal", "source": "fixture"}])), encoding="utf-8")
    assert main([command, str(path)]) == 3
    report = json.loads(capsys.readouterr().out)
    assert report.get("status", report.get("feasibility")) == "indeterminate"
