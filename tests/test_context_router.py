from dataclasses import replace

import pytest

from tiberium_ai.compact_memory import CompactMemory, MemoryFact
from tiberium_ai.context_router import ContextShadowRouter
from tiberium_ai.contracts import CandidateRoute, Task
from tiberium_ai.verification import VerifierRegistry


def context(entity="a", version="v1", value=10, missing=False):
    registry = VerifierRegistry()
    registry.register("facts", "1", lambda p: True)
    m = CompactMemory(lambda e, k, v: None if missing else MemoryFact(e, k, v, value, "facts", "1"), registry)
    return m.context(entity, version, ["budget"])


def task(entity="a", version="v1", **extra):
    return Task("request", "choose", {"entity_id": entity, "source_version": version, **extra})


def candidates(a=1.0, b=1.01):
    return [CandidateRoute("a", ("solve",), a, confidence=0.95),
            CandidateRoute("b", ("solve",), b, confidence=0.95)]


def propose(router, options, *, t=None, c=None, epoch="tools-v1", critical=False, required=()):
    return router.propose(t or task(), options, context=c or context(), routing_epoch=epoch,
                          critical_change=critical, required_capabilities=required)


def test_marginal_persistence_is_bounded_and_never_executes_a_route():
    router = ContextShadowRouter(max_holds=2, relative_cost_margin=0.02)
    assert propose(router, candidates()).selected_route_id == "a"
    for _ in range(2):
        decision = propose(router, candidates(1.01, 1.0))
        assert decision.selected_route_id == "a"
        assert decision.mode == "shadow"
        assert "uncalibrated" in decision.rationale
    assert propose(router, candidates(1.01, 1.0)).selected_route_id == "b"


@pytest.mark.parametrize("change", ["critical", "value", "version", "epoch", "inputs", "failure_modes"])
def test_context_task_or_policy_changes_break_persistence(change):
    router = ContextShadowRouter(relative_cost_margin=0.02)
    propose(router, candidates())
    options, kwargs = candidates(1.01, 1.0), {}
    if change == "critical":
        kwargs["critical"] = True
    elif change == "value":
        kwargs["c"] = context(value=20)
    elif change == "version":
        kwargs.update(t=task(version="v2"), c=context(version="v2"))
    elif change == "epoch":
        kwargs["epoch"] = "tools-v2"
    elif change == "inputs":
        kwargs["t"] = task(objective="different")
    else:
        options[0] = replace(options[0], known_failure_modes=("new_failure",))
    assert propose(router, options, **kwargs).selected_route_id == "b"


@pytest.mark.parametrize("change", ["cheap", "unknown", "confidence", "capability", "duplicate"])
def test_ineligibility_unknown_cost_or_substantial_gain_breaks_persistence(change):
    router = ContextShadowRouter(relative_cost_margin=0.02)
    propose(router, candidates())
    options = candidates(1.01, 1.0)
    if change == "cheap":
        options[1] = replace(options[1], estimated_cost=0.1)
    elif change == "unknown":
        options[0] = replace(options[0], estimated_cost=None)
    elif change == "confidence":
        options[0] = replace(options[0], confidence=0.2)
    elif change == "capability":
        options[0] = replace(options[0], capability_ids=("other",))
    else:
        options[1] = replace(options[1], route_id="a")
    decision = propose(router, options)
    assert decision.selected_route_id == (None if change == "duplicate" else "b")


def test_incomplete_or_wrong_scope_abstains_and_drops_previous_state():
    router = ContextShadowRouter(relative_cost_margin=0.02)
    propose(router, candidates())
    assert propose(router, candidates(), c=context(missing=True)).abstained
    assert propose(router, candidates(1.01, 1.0)).selected_route_id == "b"
    assert propose(router, candidates(), c=context(entity="homonym")).abstained
    assert propose(router, candidates(), t=Task("x", "choose", {})).abstained


def test_capabilities_are_checked_for_explicit_candidates_and_default_margin_is_zero():
    router = ContextShadowRouter()
    propose(router, candidates())
    assert propose(router, candidates(1.01, 1.0)).selected_route_id == "b"
    assert propose(router, candidates(), required=("absent",)).abstained
    unsupported = replace(task(), risk_class="high")
    assert propose(router, candidates(), t=unsupported).abstained


def test_entity_states_are_bounded_and_do_not_mix_homonyms():
    router = ContextShadowRouter(relative_cost_margin=0.02, max_entities=1)
    propose(router, candidates())
    assert propose(router, candidates(1.01, 1.0), t=task("b"), c=context("b")).selected_route_id == "b"
    assert propose(router, candidates(1.01, 1.0)).selected_route_id == "b"


@pytest.mark.parametrize("kwargs", [{"max_holds": True}, {"max_holds": -1},
                                     {"relative_cost_margin": 0.11},
                                     {"relative_cost_margin": float("nan")}, {"max_entities": 0}])
def test_invalid_persistence_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        ContextShadowRouter(**kwargs)
