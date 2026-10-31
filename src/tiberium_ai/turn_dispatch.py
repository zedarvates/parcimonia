"""Route a turn to its owning decision layer without executing either route.

Only a whole-text continuation may resume existing work. A short ambiguous
message is unresolved until the caller clarifies it; it cannot invent a task
or silently resume a conversation. New asks use the signature path and its
budgeted escalation, never the Director.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .continuation import LocalCapacity, QuotaMetrics, TimeBudget
from .director import AstralDirector, DirectorProposal
from .escalation import EscalationDecision, EscalationPolicy
from .kanban import KanbanBoard
from .signature_escalation import decide_after_signature
from .signature_taxonomy import classify_prompt, responsible_layer
from .task_signature import SignatureSchema, TaskSignature, predict_signature

__all__ = ["TurnDispatch", "TurnFamily", "dispatch_turn"]


class TurnFamily(str, Enum):
    CONTINUATION = "continuation"
    ASK = "ask"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class TurnDispatch:
    family: TurnFamily
    owner: str | None
    reason_code: str
    proposal: DirectorProposal | None = None
    signature: TaskSignature | None = None
    escalation: EscalationDecision | None = None


def dispatch_turn(
    text: str,
    *,
    board: KanbanBoard | None = None,
    director: AstralDirector | None = None,
    quota: QuotaMetrics | None = None,
    time_budget: TimeBudget | None = None,
    capacity: LocalCapacity | None = None,
    consecutive_stalls: int = 0,
    schema: SignatureSchema | None = None,
    predictor: Any = None,
    predictor_id: str | None = None,
    predictor_version: str | None = None,
    policy: EscalationPolicy | None = None,
    next_route_id: str | None = None,
    next_estimated_cost: float | None = None,
) -> TurnDispatch:
    family, rule = classify_prompt(text)
    if family == "continuation" and rule != "whole_text_term":
        return TurnDispatch(TurnFamily.UNRESOLVED, None, "ambiguous_short_text")

    owner, _required = responsible_layer(family)
    if family == "continuation":
        if board is None or director is None or quota is None:
            return TurnDispatch(TurnFamily.UNRESOLVED, owner, "missing_director_state")
        proposal = director.propose_from_kanban(
            board,
            quota,
            consecutive_stalls=consecutive_stalls,
            time_budget=time_budget,
            capacity=capacity,
        )
        if proposal is None:
            return TurnDispatch(TurnFamily.UNRESOLVED, owner, "no_eligible_task")
        return TurnDispatch(TurnFamily.CONTINUATION, owner, rule, proposal=proposal)

    if (
        schema is None
        or predictor is None
        or predictor_id is None
        or predictor_version is None
        or policy is None
    ):
        return TurnDispatch(TurnFamily.UNRESOLVED, owner, "missing_signature_contract")
    signature = predict_signature(
        schema,
        text,
        predictor=predictor,
        predictor_id=predictor_id,
        predictor_version=predictor_version,
        data_origin="unmeasured",
    )
    escalation = decide_after_signature(
        signature,
        policy=policy,
        next_route_id=next_route_id,
        next_estimated_cost=next_estimated_cost,
    )
    return TurnDispatch(
        TurnFamily.ASK,
        owner,
        "signature_abstained" if signature.abstained else "signature_determined",
        signature=signature,
        escalation=escalation,
    )
