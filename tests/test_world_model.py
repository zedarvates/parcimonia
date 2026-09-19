import pytest
import math

from tiberium_ai.world_model import (
    ActionDescriptor,
    ActionGateVerdict,
    GateRecommendation,
    JEPAActionGate,
    StateVector,
    TransitionRecord,
)


def test_state_vector_validation_and_distance():
    with pytest.raises(ValueError, match="features tuple cannot be empty"):
        StateVector(())
    with pytest.raises(ValueError, match="All features must be finite numbers"):
        StateVector((1.0, float("nan")))

    s1 = StateVector((0.0, 0.0))
    s2 = StateVector((3.0, 4.0))
    assert s1.distance_to(s2) == 5.0

    sim = s1.cosine_similarity(s2)
    assert sim == 0.0  # Zero vector dot product returns 0.0

    s3 = StateVector((1.0, 1.0))
    s4 = StateVector((2.0, 2.0))
    assert math.isclose(s3.cosine_similarity(s4), 1.0)


def test_action_gate_prune_dead_click_loop():
    gate = JEPAActionGate(min_state_delta=0.05)
    s_curr = StateVector((1.0, 2.0, 3.0))
    # Action is a mutation (e.g. click submit button), but predicted next state is identical
    s_next = StateVector((1.0, 2.0, 3.01))  # delta = 0.01 < 0.05
    action = ActionDescriptor(name="click", target="#submit_button", is_mutation=True)

    verdict = gate.evaluate(s_curr, action, s_next)
    assert verdict.admitted is False
    assert verdict.recommendation == GateRecommendation.PRUNE_LOOP
    assert "Stagnation detected" in verdict.rationale


def test_action_gate_admit_valid_mutation():
    gate = JEPAActionGate(min_state_delta=0.05)
    s_curr = StateVector((1.0, 2.0, 3.0))
    # Action produces a real delta (e.g. page navigated / form submitted)
    s_next = StateVector((1.5, 2.5, 3.5))
    action = ActionDescriptor(name="click", target="#submit_button", is_mutation=True)

    verdict = gate.evaluate(s_curr, action, s_next)
    assert verdict.admitted is True
    assert verdict.recommendation == GateRecommendation.ADMIT


def test_action_gate_prune_energy_anomaly():
    gate = JEPAActionGate(energy_threshold=1.0)
    s_curr = StateVector((1.0, 0.0))
    s_target = StateVector((5.0, 0.0))  # Target is at x=5
    # Action moves in the opposite direction (x=-3, distance becomes 8)
    s_divergent = StateVector((-3.0, 0.0))
    action = ActionDescriptor(name="navigate", target="https://wrong-page.org")

    verdict = gate.evaluate(s_curr, action, s_divergent, target_state=s_target)
    assert verdict.admitted is False
    assert verdict.recommendation == GateRecommendation.PRUNE_ANOMALY
    assert "Energy barrier exceeded" in verdict.rationale


def test_action_gate_admit_convergent_step():
    gate = JEPAActionGate()
    s_curr = StateVector((1.0, 0.0))
    s_target = StateVector((5.0, 0.0))
    s_closer = StateVector((3.0, 0.0))
    action = ActionDescriptor(name="navigate", target="https://correct-flow.org")

    verdict = gate.evaluate(s_curr, action, s_closer, target_state=s_target)
    assert verdict.admitted is True
    assert verdict.recommendation == GateRecommendation.ADMIT
    assert "moves state closer to target" in verdict.rationale


def test_record_transition_dataset():
    gate = JEPAActionGate()
    s1 = StateVector((0.0, 1.0))
    s2 = StateVector((0.0, 2.0))
    action = ActionDescriptor(name="step", target="next")

    rec = gate.record_transition(s1, action, s2, verified=True, metadata={"step": 1})
    assert isinstance(rec, TransitionRecord)
    assert gate.transition_count == 1
    assert rec.verified_success is True
    assert rec.metadata["step"] == 1
