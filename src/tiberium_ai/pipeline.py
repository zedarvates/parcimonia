"""End-to-end continuation pipeline (TASK-056).

Wires local kanban selection, Astral Resonance Director authorization,
typed reflex (advisory unless calibrated), continuation arbitration,
schema-constrained emit, JEPA-style action gating, and WebBrain request
construction. No network calls, no weight downloads, no live execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from .continuation import (
    ContinuationAction,
    ContinuationVerdict,
    QuotaMetrics,
    RouteKind,
    TimeBudget,
    LocalCapacity,
)
from .director import AstralDirector, DirectorCounters, DirectorMode, DirectorProposal
from .kanban import KanbanBoard
from .reflex import (
    CalibrationSnapshot,
    ReflexBatch,
    ReflexEngine,
    ReflexQuestion,
    default_reflex_questions,
)
from .schema_emit import EmitBand, EmitVerdict, ProposedCall, SchemaEmitEngine, ToolSpec
from .surface import (
    ProjectSurface,
    RuntimePlan,
    RuntimeState,
    TaskExpectation,
    UsageEvent,
    UsageReport,
    compare_usage,
    expectation_from_kanban_task,
    ingest_turn_report,
    plan_runtime,
)
from .webbrain import WebBrainMode, WebBrainRequest, build_webbrain_request
from .world_model import ActionDescriptor, ActionGateVerdict, GateRecommendation, JEPAActionGate, StateVector

__all__ = [
    "ContinuityPipeline",
    "PipelineContext",
    "PipelineHalt",
    "PipelineTrace",
    "default_reflex_questions",
]


class PipelineHalt(str, Enum):
    CONTINUE_READY = "continue_ready"
    WAITING_APPROVAL = "waiting_approval"
    FROZEN_QUOTA = "frozen_quota"
    REQUIRE_HUMAN = "require_human"
    PRUNED = "pruned"
    REFUSED_EMIT = "refused_emit"
    UNCALIBRATED = "uncalibrated"
    NO_TASK = "no_task"


@dataclass(frozen=True)
class PipelineContext:
    quota: QuotaMetrics
    time_budget: TimeBudget | None = None
    consecutive_stalls: int = 0
    source_text: str = ""
    current_state: StateVector | None = None
    predicted_next_state: StateVector | None = None
    target_state: StateVector | None = None
    proposed_action: ActionDescriptor | None = None
    proposed_call: ProposedCall | None = None
    tools: tuple[ToolSpec, ...] = ()
    calibration: CalibrationSnapshot | None = None
    reflex_state: str | Mapping[str, Any] | None = None
    trust_reflex: bool = False
    webbrain_mode: WebBrainMode = WebBrainMode.ASK
    surface: ProjectSurface | None = None
    expectation: TaskExpectation | None = None
    runtime_state: Mapping[str, RuntimeState] | None = None
    usage_events: tuple[UsageEvent, ...] = ()
    turn_report: Mapping[str, Any] | None = None
    capacity: LocalCapacity | None = None


@dataclass(frozen=True)
class PipelineTrace:
    halt: PipelineHalt
    reason: str
    proposal: DirectorProposal | None
    reflex: ReflexBatch | None
    continuation: ContinuationVerdict | None
    emit: EmitVerdict | None
    gate: ActionGateVerdict | None
    webbrain_request: WebBrainRequest | None
    counters: DirectorCounters
    usage_report: UsageReport | None = None
    runtime_plan: RuntimePlan | None = None


class ContinuityPipeline:
    def __init__(
        self,
        director: AstralDirector | None = None,
        reflex: ReflexEngine | None = None,
        emit: SchemaEmitEngine | None = None,
        gate: JEPAActionGate | None = None,
        questions: Sequence[ReflexQuestion] | None = None,
    ) -> None:
        self.director = director if director is not None else AstralDirector()
        self.reflex = reflex
        self.emit = emit if emit is not None else SchemaEmitEngine()
        self.gate = gate if gate is not None else JEPAActionGate()
        self.questions = tuple(questions) if questions is not None else default_reflex_questions()
        self._usage_report = None
        self._runtime_plan = None

    def run_once(self, board: KanbanBoard, context: PipelineContext) -> PipelineTrace:
        if not isinstance(board, KanbanBoard):
            raise TypeError("board must be a KanbanBoard instance.")
        if not isinstance(context, PipelineContext):
            raise TypeError("context must be a PipelineContext instance.")

        self._usage_report = None
        self._runtime_plan = None
        eligible = board.get_next_eligible_task()
        if context.surface is not None and eligible is not None:
            expectation = context.expectation or expectation_from_kanban_task(eligible)
            events = (
                ingest_turn_report(context.turn_report)
                if context.turn_report is not None
                else context.usage_events
            )
            self._usage_report = compare_usage(
                context.surface, expectation, events
            )
            self._runtime_plan = plan_runtime(
                context.surface,
                expectation,
                context.runtime_state or {},
                observed=events,
                capacity=context.capacity,
            )

        proposal = self.director.propose_from_kanban(
            board,
            quota=context.quota,
            consecutive_stalls=context.consecutive_stalls,
            time_budget=context.time_budget,
            capacity=context.capacity,
        )
        if proposal is None:
            return self._trace(
                PipelineHalt.NO_TASK,
                "No eligible kanban task; dependencies unresolved or board empty.",
                None,
                None,
                None,
                None,
                None,
                None,
            )

        reflex_batch = self._run_reflex(proposal, context)
        if context.trust_reflex:
            if reflex_batch is None or reflex_batch.uncalibrated or reflex_batch.refused_script:
                return self._trace(
                    PipelineHalt.UNCALIBRATED,
                    "Reflex authorization was requested but calibration is unmeasured or the script was refused.",
                    proposal,
                    reflex_batch,
                    proposal.verdict,
                    None,
                    None,
                    None,
                )
            continue_answer = reflex_batch.get("should_continue")
            if (
                continue_answer is not None
                and continue_answer.auto_act_allowed
                and continue_answer.noul is not None
                and continue_answer.noul < 0.3
            ):
                return self._trace(
                    PipelineHalt.REQUIRE_HUMAN,
                    "Calibrated reflex noul says the task should not continue now.",
                    proposal,
                    reflex_batch,
                    proposal.verdict,
                    None,
                    None,
                    None,
                )

        verdict = proposal.verdict
        if verdict.action == ContinuationAction.FREEZE_QUOTA:
            return self._trace(
                PipelineHalt.FROZEN_QUOTA,
                verdict.reason,
                proposal,
                reflex_batch,
                verdict,
                None,
                None,
                None,
            )
        if verdict.action == ContinuationAction.REQUIRE_HUMAN:
            return self._trace(
                PipelineHalt.REQUIRE_HUMAN,
                verdict.reason,
                proposal,
                reflex_batch,
                verdict,
                None,
                None,
                None,
            )

        emit_verdict = None
        if context.tools or context.proposed_call is not None:
            emit_verdict = self.emit.emit(
                context.source_text or str(proposal.task.inputs.get("title") or ""),
                context.tools,
                context.proposed_call,
            )
            if emit_verdict.band == EmitBand.REFUSE:
                return self._trace(
                    PipelineHalt.REFUSED_EMIT,
                    emit_verdict.reasoning,
                    proposal,
                    reflex_batch,
                    verdict,
                    emit_verdict,
                    None,
                    None,
                )
            if emit_verdict.band == EmitBand.CONFIRM and self.director.mode == DirectorMode.AUTO:
                return self._trace(
                    PipelineHalt.WAITING_APPROVAL,
                    emit_verdict.reasoning,
                    proposal,
                    reflex_batch,
                    verdict,
                    emit_verdict,
                    None,
                    None,
                )

        gate_verdict = None
        if (
            context.current_state is not None
            and context.predicted_next_state is not None
            and context.proposed_action is not None
        ):
            gate_verdict = self.gate.evaluate(
                context.current_state,
                context.proposed_action,
                context.predicted_next_state,
                target_state=context.target_state,
            )
            if gate_verdict.recommendation in (
                GateRecommendation.PRUNE_LOOP,
                GateRecommendation.PRUNE_ANOMALY,
            ):
                return self._trace(
                    PipelineHalt.PRUNED,
                    gate_verdict.rationale,
                    proposal,
                    reflex_batch,
                    verdict,
                    emit_verdict,
                    gate_verdict,
                    None,
                )

        webbrain_request = None
        if verdict.target_route == RouteKind.WEBBRAIN_MCP:
            task = proposal.task
            inputs = dict(task.inputs)
            if "prompt" not in inputs:
                inputs["prompt"] = str(inputs.get("title") or task.kind)
            prompted = task.__class__(
                task_id=task.task_id,
                kind=task.kind,
                inputs=inputs,
                risk_class=task.risk_class,
                evidence_level=task.evidence_level,
                locality=task.locality,
            )
            webbrain_request = build_webbrain_request(prompted, mode=context.webbrain_mode)

        if self.director.mode == DirectorMode.OFF:
            return self._trace(
                PipelineHalt.WAITING_APPROVAL,
                "Director mode is OFF: proposal is telemetry only.",
                proposal,
                reflex_batch,
                verdict,
                emit_verdict,
                gate_verdict,
                webbrain_request,
            )

        if self.director.mode == DirectorMode.SEMI_AUTO and not proposal.approved:
            return self._trace(
                PipelineHalt.WAITING_APPROVAL,
                "Silence is not approval: proposal logged, delivery blocked.",
                proposal,
                reflex_batch,
                verdict,
                emit_verdict,
                gate_verdict,
                webbrain_request,
            )

        self.director.deliver(proposal.proposal_id)
        return self._trace(
            PipelineHalt.CONTINUE_READY,
            "Proposal delivered in shadow; effector is not executed.",
            proposal,
            reflex_batch,
            verdict,
            emit_verdict,
            gate_verdict,
            webbrain_request,
        )

    def _run_reflex(self, proposal: DirectorProposal, context: PipelineContext) -> ReflexBatch | None:
        if self.reflex is None:
            return None
        state: str | Mapping[str, Any]
        if context.reflex_state is not None:
            state = context.reflex_state
        else:
            state = context.source_text or str(proposal.task.inputs.get("title") or proposal.task.kind)
        return self.reflex.evaluate(state, self.questions, calibration=context.calibration)

    def _trace(
        self,
        halt: PipelineHalt,
        reason: str,
        proposal: DirectorProposal | None,
        reflex: ReflexBatch | None,
        continuation: ContinuationVerdict | None,
        emit: EmitVerdict | None,
        gate: ActionGateVerdict | None,
        webbrain_request: WebBrainRequest | None,
    ) -> PipelineTrace:
        return PipelineTrace(
            halt=halt,
            reason=reason,
            proposal=proposal,
            reflex=reflex,
            continuation=continuation,
            emit=emit,
            gate=gate,
            webbrain_request=webbrain_request,
            counters=self.director.counters,
            usage_report=self._usage_report,
            runtime_plan=self._runtime_plan,
        )
