from itertools import permutations

import pytest

from tiberium_ai.contracts import Task, CandidateRoute
from tiberium_ai.router import ShadowRouter

def test_shadow_router_is_observation_only():
    task = Task(task_id="t1", kind="example", inputs={})
    candidates = [
        CandidateRoute("deterministic", ["rule:example"], confidence=0.99),
        CandidateRoute("llm", ["model:baseline"], confidence=0.95),
    ]
    decision = ShadowRouter().propose(task, candidates)
    assert decision.mode == "shadow"
    assert decision.selected_route_id == "deterministic"
    assert not decision.abstained

def test_shadow_router_abstains_without_confidence():
    task = Task(task_id="t2", kind="example", inputs={})
    decision = ShadowRouter().propose(
        task, [CandidateRoute("unknown", ["x"], confidence=None)]
    )
    assert decision.abstained


@pytest.mark.parametrize("confidence", [None, -0.1, 1.1, float("nan"), float("inf"),
                                        -float("inf"), True, "0.99", 0.89])
def test_invalid_or_insufficient_confidence_cannot_win(confidence):
    decision = ShadowRouter().propose(
        Task("confidence", "example", {}),
        [CandidateRoute("unreliable", ["example"], confidence=confidence)],
    )
    assert decision.abstained
    assert decision.selected_route_id is None
    assert decision.mode == "shadow"


def test_low_cost_does_not_override_confidence_requirement():
    decision = ShadowRouter().propose(
        Task("quality", "example", {}),
        [
            CandidateRoute("unreliable", ["rule"], estimated_cost=0, confidence=0.8),
            CandidateRoute("baseline", ["model"], estimated_cost=5, confidence=0.99),
        ],
    )
    assert decision.selected_route_id == "baseline"


def test_cheapest_sufficiently_confident_route_is_proposed():
    decision = ShadowRouter().propose(
        Task("cost", "example", {}),
        [
            CandidateRoute("baseline", ["model"], estimated_cost=5, confidence=0.99),
            CandidateRoute("rule", ["rule"], estimated_cost=0, confidence=0.9),
        ],
    )
    assert decision.selected_route_id == "rule"
    assert not decision.abstained
    assert decision.mode == "shadow"


def test_unknown_cost_is_not_treated_as_free():
    decision = ShadowRouter().propose(
        Task("unknown-cost", "example", {}),
        [
            CandidateRoute("unknown", ["model"], confidence=1),
            CandidateRoute("known", ["rule"], estimated_cost=1, confidence=0.95),
        ],
    )
    assert decision.selected_route_id == "known"


@pytest.mark.parametrize("cost", [-1, float("nan"), float("inf"), -float("inf"),
                                  True, "0"])
def test_invalid_cost_is_excluded_even_with_high_confidence(cost):
    decision = ShadowRouter().propose(
        Task("invalid-cost", "example", {}),
        [
            CandidateRoute("invalid", ["x"], estimated_cost=cost, confidence=1),
            CandidateRoute("valid", ["y"], estimated_cost=1, confidence=0.95),
        ],
    )
    assert decision.selected_route_id == "valid"


@pytest.mark.parametrize("cost", [None, 0.25])
def test_equal_scores_are_independent_of_candidate_order(cost):
    candidates = [
        CandidateRoute(route_id, ["example"], estimated_cost=cost, confidence=0.95)
        for route_id in ("zeta", "alpha", "beta")
    ]
    decisions = [
        ShadowRouter().propose(Task("tie", "example", {}), list(order))
        for order in permutations(candidates)
    ]
    assert all(d.selected_route_id == "alpha" for d in decisions)
    assert all(d == decisions[0] for d in decisions)


def test_confidence_breaks_equal_cost_ties_before_route_id():
    decision = ShadowRouter().propose(
        Task("confidence-tie", "example", {}),
        [
            CandidateRoute("alpha", ["x"], estimated_cost=1, confidence=0.9),
            CandidateRoute("zeta", ["y"], estimated_cost=1, confidence=0.99),
        ],
    )
    assert decision.selected_route_id == "zeta"


def test_all_unknown_costs_use_confidence_without_claiming_savings():
    decision = ShadowRouter().propose(
        Task("no-estimates", "example", {}),
        [
            CandidateRoute("alpha", ["x"], confidence=0.9),
            CandidateRoute("zeta", ["y"], confidence=0.99),
        ],
    )
    assert decision.selected_route_id == "zeta"
    assert "unknown" in decision.rationale.lower()


def test_empty_candidates_abstain():
    decision = ShadowRouter().propose(Task("empty", "example", {}), [])
    assert decision.abstained
    assert decision.selected_route_id is None


def test_custom_threshold_is_inclusive_and_can_require_more_confidence():
    candidate = CandidateRoute("candidate", ["rule"], confidence=0.95)
    task = Task("threshold", "example", {})
    assert not ShadowRouter(min_confidence=0.95).propose(task, [candidate]).abstained
    assert ShadowRouter(min_confidence=0.96).propose(task, [candidate]).abstained


@pytest.mark.parametrize("threshold", [-1, 1.1, float("nan"), float("inf"),
                                       True, None, "0.9"])
def test_invalid_threshold_is_a_configuration_error(threshold):
    with pytest.raises(ValueError, match="min_confidence"):
        ShadowRouter(min_confidence=threshold)


@pytest.mark.parametrize("threshold", [0, 1])
def test_threshold_endpoints_are_supported(threshold):
    decision = ShadowRouter(min_confidence=threshold).propose(
        Task("endpoint", "example", {}),
        [CandidateRoute("candidate", ["rule"], confidence=threshold)],
    )
    assert decision.selected_route_id == "candidate"


@pytest.mark.parametrize("requirements", [
    {"risk_class": "high"},
    {"risk_class": "unknown"},
    {"evidence_level": "strict"},
    {"locality": "local"},
    {"locality": "unknown"},
])
def test_unsupported_task_requirements_abstain(requirements):
    decision = ShadowRouter().propose(
        Task("restricted", "example", {}, **requirements),
        [CandidateRoute("confident", ["example"], estimated_cost=0, confidence=1)],
    )
    assert decision.abstained
    assert decision.selected_route_id is None
    assert decision.mode == "shadow"
    assert "unsupported" in decision.rationale.lower()


@pytest.mark.parametrize("route_id", ["", " ", " padded ", None, 123])
def test_invalid_route_identity_abstains(route_id):
    decision = ShadowRouter().propose(
        Task("identity", "example", {}),
        [CandidateRoute(route_id, ["example"], confidence=1)],
    )
    assert decision.abstained
    assert decision.selected_route_id is None


def test_duplicate_route_ids_abstain_regardless_of_order():
    candidates = [
        CandidateRoute("same-id", ["rule"], estimated_cost=0, confidence=0.95),
        CandidateRoute("same-id", ["model"], estimated_cost=5, confidence=0.99),
    ]
    decisions = [
        ShadowRouter().propose(Task("duplicates", "example", {}), list(order))
        for order in permutations(candidates)
    ]
    assert all(d.abstained and d.selected_route_id is None for d in decisions)
    assert decisions[0] == decisions[1]


def test_proposal_preserves_candidate_order_and_task_inputs():
    task_inputs = {"text": "original"}
    task = Task("unchanged", "example", task_inputs)
    candidates = [
        CandidateRoute("zeta", ["rule:zeta"], estimated_cost=5, confidence=1),
        CandidateRoute("alpha", ["rule:alpha"], estimated_cost=0, confidence=0.95),
    ]
    ShadowRouter().propose(task, candidates)
    assert [c.route_id for c in candidates] == ["zeta", "alpha"]
    assert task_inputs == {"text": "original"}
