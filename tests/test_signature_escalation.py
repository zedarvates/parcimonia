import pytest

from tiberium_ai.decision_adapter import OptionSetQuestion
from tiberium_ai.escalation import Budget, EscalationPolicy, EscalationState
from tiberium_ai.signature_escalation import decide_after_signature
from tiberium_ai.task_signature import (
    DeclaredItem,
    RuleBasedSignatureBackend,
    SignatureSchema,
    predict_signature,
)


def schema():
    return SignatureSchema(
        name="bridge",
        kinds=(DeclaredItem("extract", ("extract",)), DeclaredItem("format", ("format",))),
    )


def signature_of(text):
    active = schema()
    return predict_signature(
        active,
        text,
        predictor=RuleBasedSignatureBackend(active),
        predictor_id="rule.signature",
        predictor_version="1",
    )


def policy(**overrides):
    fields = {"max_cost": 10.0, "max_escalations": 1, "max_attempts": 3}
    fields.update(overrides)
    return EscalationPolicy(Budget(**fields))


def test_a_determined_signature_is_accepted():
    decision = decide_after_signature(signature_of("extract the columns"), policy=policy())
    assert decision.state is EscalationState.ACCEPT
    # Not the policy's "verified_accept": naming an action is not verifying a
    # result, and the verifier owns that word.
    assert decision.reason_code == "signature_determined"
    assert decision.next_route_id is None
    assert "verifier still owns the result" in decision.detail


def test_an_abstention_escalates_to_a_declared_heavier_route():
    decision = decide_after_signature(
        signature_of("zzz"),
        policy=policy(),
        next_route_id="route.fingerprint.chain",
        next_estimated_cost=1.0,
    )
    assert decision.state is EscalationState.ESCALATE
    assert decision.next_route_id == "route.fingerprint.chain"
    # The cause is kept: an escalation that hides why the cheap step declined
    # cannot be audited.
    assert "low_kind_confidence" in decision.detail
    assert "rule.signature/1" in decision.detail


def test_an_abstention_without_room_abstains_instead_of_guessing():
    decision = decide_after_signature(
        signature_of("zzz"), policy=policy(max_escalations=0)
    )
    assert decision.state in (EscalationState.ABSTAIN, EscalationState.ESCALATE)
    assert decision.state is EscalationState.ABSTAIN
    assert decision.next_route_id is None
    assert "low_kind_confidence" in decision.detail


def test_the_exhausted_attempt_budget_stops_hard_even_on_an_abstention():
    decision = decide_after_signature(
        signature_of("zzz"), policy=policy(max_attempts=1), attempts=1
    )
    assert decision.state is EscalationState.FAIL_HARD
    assert decision.reason_code == "attempt_budget_exhausted"


def test_the_bridge_will_not_pretend_an_attempt_did_not_happen():
    with pytest.raises(ValueError, match="at least 1"):
        decide_after_signature(signature_of("zzz"), policy=policy(), attempts=0)
    with pytest.raises(TypeError, match="TaskSignature"):
        decide_after_signature(object(), policy=policy())
    with pytest.raises(TypeError, match="EscalationPolicy"):
        decide_after_signature(signature_of("zzz"), policy=object())
