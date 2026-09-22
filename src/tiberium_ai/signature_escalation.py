"""Turn a signature outcome into a budgeted escalation decision.

An abstention is the most common real outcome: on the author's own asks, no
mechanism reaches about 43 per cent of the message volume. Silence is not an
answer, so an abstention has to become a typed decision with a reason and a bound,
which is what the escalation policy already does for a failed attempt.

The signature is treated as the attempt it is: it ran, it cost something, and it
declined to name an action. So the verdict handed to the policy is None, and the
policy decides between escalating to a declared heavier route and abstaining. The
policy owns the budget, the loop guard and the hard stops; this module only
translates, and it never executes anything.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .escalation import EscalationDecision, EscalationPolicy, EscalationState
from .task_signature import TaskSignature

__all__ = ["decide_after_signature"]


def decide_after_signature(
    signature: TaskSignature,
    *,
    policy: EscalationPolicy,
    attempts: int = 1,
    escalations: int = 0,
    spent_cost: float = 0.0,
    spent_latency_ms: float = 0.0,
    next_route_id: str | None = None,
    next_estimated_cost: float | None = None,
    next_estimated_latency_ms: float | None = None,
) -> EscalationDecision:
    """Return the decision that follows one signature prediction.

    A determined signature is an accepted verdict; an abstention is passed to the
    policy as no verdict at all, so the uncalibrated predictor can neither accept
    nor keep a route by itself. The signature's own reason code is appended to the
    detail, because a decision that hides why the cheap mechanism declined cannot
    be audited.
    """
    if not isinstance(signature, TaskSignature):
        raise TypeError("signature must be a TaskSignature instance.")
    if not isinstance(policy, EscalationPolicy):
        raise TypeError("policy must be an EscalationPolicy instance.")
    if attempts < 1:
        raise ValueError("attempts must be at least 1: the predictor did run.")

    if not signature.abstained:
        # A determined signature names an action; it does not verify a result. The
        # policy's own accept reason says "verified", so it is not borrowed here:
        # the verifier of G2 remains the only thing that may accept a result.
        return EscalationDecision(
            EscalationState.ACCEPT,
            "signature_determined",
            detail=(
                f"The signature named {signature.kind!r}; a mechanism may be "
                "selected for it, and a verifier still owns the result."
            ),
        )

    decision = policy.decide(
        run_ok=True,
        verdict=None,
        attempts=attempts,
        escalations=escalations,
        spent_cost=spent_cost,
        spent_latency_ms=spent_latency_ms,
        next_route_id=next_route_id,
        next_estimated_cost=next_estimated_cost,
        next_estimated_latency_ms=next_estimated_latency_ms,
    )
    cause = signature.reason_code or "abstained"
    predictor = f"{signature.predictor_id}/{signature.predictor_version}"
    return replace(
        decision,
        detail=f"{decision.detail} The signature declined via {cause} "
        f"(predictor {predictor}, data origin {signature.data_origin}).",
    )
