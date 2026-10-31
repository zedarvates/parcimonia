"""Bounded signature fallback with complete, validated response batches."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from .reflex import InjectedReflexBackend, ReflexEngine, ReflexKind, ReflexQuestion, script_kind
from .task_context import ContextAssessment, ContextContract, assess_context
from .task_signature import SignatureSchema, TaskSignature, predict_signature, signature_questions
from .verification import hash_input
from .cascade_resources import CascadeResourceControl, StageMeasurementError


@dataclass(frozen=True)
class ContextCascadeProposal:
    """Selection or collection advice, distinct from execution authorization."""

    status: str
    reason_code: str
    request_hash: str
    context: ContextAssessment
    selected_route: str | None
    signature: TaskSignature | None
    stages: tuple[Mapping[str, str], ...]
    backend_calls: int
    resource_trace: Mapping[str, Any] | None = None
    auto_act_allowed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.status not in {"selected", "collect_context", "repair_context", "budget_exhausted", "backend_error", "abstained"}:
            raise ValueError("unsupported context cascade status.")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise ValueError("a context cascade proposal needs a reason code.")
        if not isinstance(self.context, ContextAssessment):
            raise TypeError("context must be a ContextAssessment.")
        if (not isinstance(self.request_hash, str) or len(self.request_hash) != 64
                or any(c not in "0123456789abcdef" for c in self.request_hash)):
            raise ValueError("request_hash must be a lowercase SHA-256.")
        if type(self.backend_calls) is not int or not 0 <= self.backend_calls <= 2:
            raise ValueError("backend_calls must be a count between zero and two.")
        if self.status == "selected":
            if not self.context.ready or self.selected_route not in {"baseline", "fallback"} or not isinstance(self.signature, TaskSignature) or self.signature.abstained:
                raise ValueError("selection requires ready context and a determined signature.")
        elif self.selected_route is not None or self.signature is not None:
            raise ValueError("a refusal must not carry a selected signature.")

    def to_record(self) -> dict[str, Any]:
        return {"schema_version": 1, "kind": "context_cascade_proposal", "status": self.status,
                "reason_code": self.reason_code, "request_hash": self.request_hash,
                "context": self.context.to_record(), "selected_route": self.selected_route,
                "signature": self.signature.to_record() if self.signature is not None else None,
                "stages": [dict(stage) for stage in self.stages], "backend_calls": self.backend_calls,
                "resource_trace": deepcopy(self.resource_trace), "auto_act_allowed": False,
                "measured_cost": self.resource_trace.get("cost_current") if self.resource_trace and self.resource_trace.get("cost_observations") else None,
                "measured_latency_ms": self.resource_trace.get("elapsed_current_ms") if self.resource_trace and self.resource_trace.get("timing") is not None else None}


class SignatureCascadeBackend:
    """Use the baseline kind probability to decide whether to call a fallback.

    Counters include failed attempts. Selection expresses a descriptor only;
    it grants no execution authorization. A selected batch is never assembled
    from answers produced by different backends.
    """

    def __init__(
        self, baseline: Any, fallback: Any, *, threshold: float = 0.9,
        max_calls: int = 100, max_fallback_calls: int = 100,
    ) -> None:
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
            raise ValueError("threshold must be in (0, 1].")
        for name, value in (("max_calls", max_calls), ("max_fallback_calls", max_fallback_calls)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer.")
        self.baseline = baseline
        self.fallback = fallback
        self.threshold = float(threshold)
        self.max_calls = max_calls
        self.max_fallback_calls = max_fallback_calls
        self.latin_only = bool(getattr(baseline, "latin_only", False) or getattr(fallback, "latin_only", False))
        self.calls = 0
        self.fallback_calls = 0
        self.last_route = "idle"
        self.last_stages: list[dict[str, str]] = []
        self.context_checks = 0

    def _stage(self, route: str, backend: Any, text: str, questions: Sequence[ReflexQuestion]):
        stage = {"route": route, "status": "error"}
        self.last_stages.append(stage)
        raw = backend.evaluate(text, questions)
        if not isinstance(raw, Mapping) or set(raw) != {q.name for q in questions}:
            raise ValueError("backend must return exactly the requested answers.")
        batch = ReflexEngine(InjectedReflexBackend(raw, latin_only=bool(getattr(backend, "latin_only", False)))).evaluate(text, questions)
        stage["status"] = "validated"
        return raw, batch

    def evaluate(self, state_text: str, questions: Sequence[ReflexQuestion]) -> Mapping[str, Mapping[str, Any]]:
        self.last_stages = []
        self.last_route = "error"
        if self.calls >= self.max_calls:
            raise ValueError("call_budget exhausted.")
        if not isinstance(state_text, str):
            raise TypeError("state_text must be a string.")
        questions = tuple(questions)
        if len({q.name for q in questions}) != len(questions):
            raise ValueError("question names must be unique.")
        if not any(q.name == "kind" and q.kind == ReflexKind.CHOICE for q in questions):
            raise ValueError("a kind question of choice type is required.")
        self.calls += 1
        raw, batch = self._stage("baseline", self.baseline, state_text, questions)
        answer = batch.get("kind")
        if not batch.refused_script and answer is not None and answer.probabilities.get(answer.choice, 0.0) >= self.threshold:
            self.last_route = "baseline"
            return raw
        if self.fallback_calls >= self.max_fallback_calls:
            raise ValueError("fallback_budget exhausted.")
        self.fallback_calls += 1
        raw, _ = self._stage("fallback", self.fallback, state_text, questions)
        self.last_route = "fallback"
        return raw

    def propose_signature(
        self, prompt: str, *, schema: SignatureSchema, contract: ContextContract,
        baseline_identity: tuple[str, str], fallback_identity: tuple[str, str],
        context_revision: str, resource_control: CascadeResourceControl | None = None, **context_inputs: Any,
    ) -> ContextCascadeProposal:
        """Opt-in context gate; preserve evaluate() and its historical replay shape.

        Known context is supplied/verified by the host. It is not guessed from
        legacy field predictions. This method calls only supplied predictors,
        with at most one fallback, and never executes a task effector.
        """
        self.last_stages = []
        self.last_route = "error"
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a nonempty string.")
        if not isinstance(schema, SignatureSchema) or not isinstance(contract, ContextContract):
            raise TypeError("signature schema and context contract are required.")
        if contract.task_kind not in {item.name for item in schema.kinds}:
            raise ValueError("contract kind is not declared by the signature schema.")
        for backend, identity in ((self.baseline, baseline_identity), (self.fallback, fallback_identity)):
            if not isinstance(identity, tuple) or len(identity) != 2 or any(not isinstance(v, str) or not v.strip() or v != v.strip() for v in identity):
                raise ValueError("backend identities must be (id, version) tuples.")
            for name, declared in zip(("backend_id", "backend_version"), identity):
                actual = getattr(backend, name, None)
                if actual is not None and actual != declared:
                    raise ValueError("declared identity does not match supplied backend.")
        if resource_control is not None and not isinstance(resource_control, CascadeResourceControl):
            raise TypeError("resource_control must be a CascadeResourceControl or null.")
        resource_session = resource_control.start() if resource_control is not None else None
        context = assess_context(contract, context_revision=context_revision, **context_inputs)
        self.context_checks += 1
        questions = signature_questions(schema)
        threshold = max(self.threshold, schema.min_kind_confidence)
        request_hash = hash_input({"prompt": prompt, "questions": [asdict(q) for q in questions],
            "schema": schema.to_record(), "contract": contract.to_record(), "context_input_hash": context.input_hash,
            "baseline": baseline_identity, "fallback": fallback_identity,
            "budget_before": {"calls": self.calls, "fallback_calls": self.fallback_calls},
            "policy": {"version": "context-cascade/1", "threshold": threshold,
                       "max_calls": self.max_calls, "max_fallback_calls": self.max_fallback_calls}})
        if resource_control is not None:
            request_hash = hash_input({"context_request_hash": request_hash, "resource_control": resource_session.policy_record})
        attempted = 0
        def result(status, reason, route=None, signature=None):
            self.last_route = route or status
            return ContextCascadeProposal(status, reason, request_hash, context, route, signature,
                                          tuple(deepcopy(self.last_stages)), attempted,
                                          deepcopy(resource_session.to_record()) if resource_session is not None else None)
        def resource_refusal(code):
            status = ("collect_context" if code.startswith("state_age_") else
                      "abstained" if code.startswith("unknown_") or code == "abstained_no_verdict" else "budget_exhausted")
            return result(status, code)
        if not context.ready:
            return result("repair_context" if context.invalid_fields else "collect_context", context.status)
        if self.calls >= self.max_calls:
            return result("budget_exhausted", "call_budget_exhausted")
        self.calls += 1
        for route, backend, identity in (("baseline", self.baseline, baseline_identity), ("fallback", self.fallback, fallback_identity)):
            if bool(getattr(backend, "latin_only", False)) and script_kind(prompt) == "non_latin":
                self.last_stages.append({"route": route, "status": "skipped", "decision": "script_unsupported",
                                         "backend_id": identity[0], "backend_version": identity[1]})
                if resource_session is not None:
                    resource_session.skipped()
                if route == "fallback":
                    return result("abstained", "fallback_script_unsupported")
                continue
            if route == "fallback":
                if self.fallback_calls >= self.max_fallback_calls:
                    return result("budget_exhausted", "fallback_budget_exhausted")
            if resource_session is not None:
                try:
                    block = resource_session.before(route, identity[0])
                except StageMeasurementError:
                    return result("backend_error", "resource_clock_invalid")
                if block is not None:
                    return resource_refusal(block)
            try:
                def predict_stage():
                    nonlocal attempted
                    attempted += 1
                    if route == "fallback":
                        self.fallback_calls += 1
                    raw, _ = self._stage(route, backend, prompt, questions)
                    return predict_signature(schema, prompt,
                        predictor=InjectedReflexBackend(raw, latin_only=False), predictor_id=identity[0],
                        predictor_version=identity[1], data_origin="unmeasured")
                signature = (resource_session.execute(route, backend, identity, request_hash, predict_stage)
                             if resource_session is not None else predict_stage())
            except Exception as error:
                # Provider failures may contain credentials or private prompt text.
                if not self.last_stages or self.last_stages[-1]["route"] != route:
                    self.last_stages.append({"route": route, "status": "error"})
                stage = self.last_stages[-1]
                stage.update(status="error", backend_id=identity[0], backend_version=identity[1],
                             error_type=type(error).__name__)
                return result("backend_error", route + "_invalid_or_unavailable")
            stage = self.last_stages[-1]
            stage.update(backend_id=identity[0], backend_version=identity[1])
            if resource_session is not None:
                try:
                    block = resource_session.after()
                except StageMeasurementError:
                    return result("backend_error", "resource_clock_invalid")
                if block is not None:
                    stage["decision"] = block
                    return resource_refusal(block)
            if signature.abstained or signature.kind_confidence is None or signature.kind_confidence < threshold:
                stage["decision"] = "low_kind_confidence"
            elif signature.kind != contract.task_kind:
                stage["decision"] = "kind_contract_mismatch"
            else:
                stage["decision"] = "selected"
                return result("selected", route + "_context_and_kind_satisfied", route, signature)
            if route == "fallback":
                return result("abstained", "fallback_" + stage["decision"])
        raise AssertionError("context cascade must select or refuse one of its bounded stages")
