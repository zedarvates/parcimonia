"""Opt-in temporal persistence around ShadowRouter; proposals only."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
from typing import Sequence

from .compact_memory import MemoryContext, _identity
from .contracts import CandidateRoute, Decision, Task
from .router import ShadowRouter, is_nonnegative_number
from .verification import hash_input


class ContextShadowRouter:
    """Hold an eligible proposal for a bounded number of marginal changes.

    A missing fact, critical change, changed context/tool epoch, ineligible route,
    unknown cost, different capability family or substantial price change
    immediately defeats persistence. No production router is intercepted.
    """

    def __init__(self, router: ShadowRouter | None = None, *,
                 max_holds: int = 3, relative_cost_margin: float = 0.0,
                 max_entities: int = 8) -> None:
        if router is not None and not isinstance(router, ShadowRouter):
            raise TypeError("router must be a ShadowRouter.")
        if type(max_holds) is not int or max_holds < 0:
            raise ValueError("max_holds must be a nonnegative integer.")
        if type(max_entities) is not int or max_entities < 1:
            raise ValueError("max_entities must be a positive integer.")
        if not is_nonnegative_number(relative_cost_margin) or relative_cost_margin > 0.1:
            raise ValueError("relative_cost_margin must be in [0, 0.1].")
        self._router = router or ShadowRouter()
        self.max_holds = max_holds
        self.relative_cost_margin = relative_cost_margin
        self.max_entities = max_entities
        self._states: OrderedDict[str, tuple[str, str, int]] = OrderedDict()

    @property
    def policy_version(self) -> str:
        config = {"max_holds": self.max_holds, "relative_cost_margin": self.relative_cost_margin,
                  "max_entities": self.max_entities, "base": self._router.policy_version}
        return "context-shadow/1:" + hash_input(config)

    def propose(self, task: Task, candidates: list[CandidateRoute], *,
                context: MemoryContext, routing_epoch: str,
                critical_change: bool = False,
                required_capabilities: Sequence[str] = ()) -> Decision:
        if not isinstance(context, MemoryContext):
            raise TypeError("context must be a MemoryContext.")
        _identity(routing_epoch, "routing_epoch")
        if type(critical_change) is not bool:
            raise ValueError("critical_change must be a boolean.")
        record = context.to_record()
        entity_id = record["entity_id"]
        _identity(entity_id, "entity_id")
        if isinstance(required_capabilities, (str, bytes)):
            raise ValueError("required_capabilities must be a sequence of identifiers.")
        required = tuple(required_capabilities)
        for capability in required:
            _identity(capability, "required_capability")
        if (task.inputs.get("entity_id"), task.inputs.get("source_version")) != (
            entity_id, record["source_version"]
        ):
            self._states.pop(entity_id, None)
            return Decision(task.task_id, None, abstained=True,
                            rationale="Shadow abstention: task and context scopes differ.")
        # Explicit candidates normally skip registry capability filtering.
        # Preserve invalid-ID abstention on the original candidate set first.
        base = self._router.propose(task, candidates, required_capabilities=required)
        if not context.complete or base.abstained:
            self._states.pop(entity_id, None)
            if not context.complete:
                return Decision(task.task_id, None, abstained=True,
                                rationale="Shadow abstention: required context facts are unresolved.")
            return base
        eligible = [c for c in candidates if set(required) <= set(c.capability_ids)]
        base = self._router.propose(task, eligible, required_capabilities=required)
        if base.abstained:
            self._states.pop(entity_id, None)
            return base
        fingerprint = hash_input({
            "context": context.fingerprint, "routing_epoch": routing_epoch,
            "policy": self.policy_version, "kind": task.kind,
            "task_inputs": dict(task.inputs),
            "requirements": [task.risk_class, task.evidence_level, task.locality],
            "capabilities": sorted(set(required)),
            "routes": sorted((c.route_id, sorted(set(c.capability_ids)),
                              sorted(set(c.known_failure_modes))) for c in candidates),
        })
        previous = self._states.get(entity_id)
        held, decision = 0, base
        by_id = {c.route_id: c for c in eligible}
        if previous and not critical_change and previous[0] == fingerprint:
            old_id, old_holds = previous[1:]
            old = by_id.get(old_id)
            chosen = by_id[base.selected_route_id]
            if old and old_id != base.selected_route_id and old_holds < self.max_holds:
                old_proposal = self._router.propose(task, [old], required_capabilities=required)
                if (not old_proposal.abstained
                        and old.estimated_cost is not None and chosen.estimated_cost is not None
                        and set(old.capability_ids) == set(chosen.capability_ids)
                        and old.estimated_cost <= chosen.estimated_cost * (1 + self.relative_cost_margin)):
                    held = old_holds + 1
                    decision = replace(base, selected_route_id=old_id, rationale=(
                        f"Shadow persistence only: hold {held}/{self.max_holds} within "
                        f"relative estimated-cost margin {self.relative_cost_margin:g}; "
                        "confidence remains caller-declared and uncalibrated."
                    ))
        self._states[entity_id] = (fingerprint, decision.selected_route_id, held)
        self._states.move_to_end(entity_id)
        while len(self._states) > self.max_entities:
            self._states.popitem(last=False)
        return decision
