"""Exercise the typed-decision contract end to end, offline and deterministically.

An option set wider than one call may offer is cut into stages, answered by an
injected fixture transport, recomposed, stored as a record and then verified by
recomputation rather than trusted. A second scenario shows the single-stage
boundary, a third shows a tampered claim being rejected, and a fourth shows the
three timing outcomes a real-time consumer distinguishes: within budget, missed
deadline and stale state.

No model is called and no network access is used. These fixtures prove the
contract, the provenance and the replay: they say nothing about decision quality
against a real decision model.

Usage:
    python examples/decision_suite.py
    python examples/decision_suite.py --out runs/decisions
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tiberium_ai.decision_adapter import (
    DECISION_VERIFIER_ID,
    DECISION_VERIFIER_VERSION,
    SCHEMA_VERIFIER_ID,
    SCHEMA_VERIFIER_VERSION,
    SCORED_VERIFIER_ID,
    SCORED_VERIFIER_VERSION,
    SINGLE_STAGE_CHOICE_CAP,
    DecisionRecord,
    DecisionRequest,
    OptionSetQuestion,
    TwoStageDecision,
    TwoStagePlan,
    capture_decision,
    compose_scored,
    compose_two_stage,
    decision_route_entry,
    finalist_question,
    plan_scored_stages,
    plan_two_stage,
    register_decision_verifiers,
    schema_payload,
    scored_payload,
    scored_stage_questions,
    stage_questions,
)
from tiberium_ai.decision_clock import (
    DecisionBudget,
    DecisionTiming,
    assess_decision_timing,
)
from tiberium_ai.verification import VerifierRegistry

BACKEND_ID = "fixture.decision"
BACKEND_VERSION = "1"
BUDGET_MS = 250.0
MAX_STATE_AGE_MS = 1000.0
FALLBACK_ROUTE = "route.rule.deterministic"

#: Mechanisms Parcimonia can route to, crossed with the evidence level a task
#: demands. The cross product is the simplest honest way to exceed one call's
#: option cap without inventing an artificial option list.
MECHANISMS = (
    "rule.deterministic",
    "cache.proof_reuse",
    "knn.case_retrieval",
    "nn.nano_classifier",
    "nn.micro_predictor",
    "jepa.shard_predictor",
    "llm.small_local",
    "llm.large_local",
    "llm.cloud_frontier",
    "tool.mcp",
    "tool.cli",
    "browser.webbrain_mcp",
    "audit.static_structure",
    "verifier.deterministic",
)
EVIDENCE_LEVELS = ("normal", "strict")
QUESTION_INSTRUCTIONS = (
    "Which mechanism satisfies this task at the required evidence level?"
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        default=None,
        help="optional directory for summary.json and records.jsonl",
    )
    return parser.parse_args(list(argv))


def mechanism_question() -> OptionSetQuestion:
    options = tuple(
        f"{mechanism}@{level}"
        for mechanism in MECHANISMS
        for level in EVIDENCE_LEVELS
    )
    return OptionSetQuestion(
        name="mechanism",
        instructions=QUESTION_INSTRUCTIONS,
        options=options,
        criteria={
            option: option.replace("@", " at evidence level ") for option in options
        },
    )


def fixture_transport(latency_ms: float):
    """Answer every stage deterministically. No model and no network are used."""

    def pick(name: str, keys: list[str]) -> str:
        if name.endswith(".stage2"):
            return "g1"
        if name.endswith(".stage1.g1"):
            return keys[-1]
        return keys[0]

    def transport(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        answers: dict[str, Any] = {}
        for question in payload["questions"]:
            keys = list(question["criteria"])
            chosen = pick(str(question["name"]), keys)
            answers[str(question["name"])] = {
                "choice": chosen,
                "probabilities": {key: (1.0 if key == chosen else 0.0) for key in keys},
                "confidence": 0.9,
            }
        return {
            "answers": answers,
            "usage": {
                "input_tokens_total": 0,
                "output_tokens_total": 0,
                "n_retries": 0,
                "latency_ms": latency_ms,
            },
        }

    return transport


def decisions_from(record: DecisionRecord) -> dict[str, str]:
    return {str(name): str(answer["choice"]) for name, answer in record.answers.items()}


@dataclass(frozen=True)
class Scenario:
    """One captured, recomposed and time-assessed decision."""

    request: DecisionRequest
    record: DecisionRecord
    question: OptionSetQuestion
    plan: TwoStagePlan
    choices: Mapping[str, str]
    decision: TwoStageDecision
    timing: Mapping[str, Any] | None

    def summary(self) -> dict[str, Any]:
        return {
            "request_id": self.request.request_id,
            "total_options": self.plan.total_options,
            "stages": self.plan.stages,
            "group_sizes": [len(group) for group in self.plan.groups],
            "stage_questions": list(self.plan.stage_question_names()),
            "record_origin": self.record.data_origin,
            "record_hash": self.record.request_hash,
            "decision": self.decision.to_record(),
            "timing": None if self.timing is None else dict(self.timing),
        }


def run_scenario(
    question: OptionSetQuestion,
    *,
    request_id: str,
    state_age_ms: float,
    latency_ms: float,
    budget: DecisionBudget | None = None,
) -> Scenario:
    """Capture, recompose and time one decision without calling any model."""
    plan = plan_two_stage(question)
    request = DecisionRequest(
        request_id,
        "which mechanism should handle this task",
        stage_questions(plan, question),
        state_age_ms=state_age_ms,
        budget=budget,
    )
    capture = capture_decision(
        request,
        backend_id=BACKEND_ID,
        backend_version=BACKEND_VERSION,
        transport=fixture_transport(latency_ms),
    )
    if not capture.performed or capture.record is None:
        raise SystemExit(f"scenario {request_id} did not capture: {capture.detail_code}")
    record = capture.record
    choices = decisions_from(record)
    decision = compose_two_stage(question, plan, choices)
    timing = None
    if budget is not None:
        timing = assess_decision_timing(
            budget, DecisionTiming(elapsed_ms=latency_ms, state_age_ms=state_age_ms)
        ).to_record()
    return Scenario(
        request=request,
        record=record,
        question=question,
        plan=plan,
        choices=choices,
        decision=decision,
        timing=timing,
    )


def verify_claim(
    scenario: Scenario, claimed_winner: str | None, verifiers: VerifierRegistry
) -> str:
    """Recompute a claimed winner through the registered verifier."""
    payload = {
        "question": scenario.question.to_record(),
        "max_stage_options": SINGLE_STAGE_CHOICE_CAP,
        "choices": dict(scenario.choices),
        "claimed_winner": claimed_winner,
    }
    verdict = verifiers.verify(DECISION_VERIFIER_ID, DECISION_VERIFIER_VERSION, payload)
    return str(verdict.verdict)


def scored_scores(question: OptionSetQuestion) -> dict[str, float]:
    """A declared synthetic score vector: earlier options score higher."""
    total = len(question.options)
    return {
        option: round((total - index) / total, 6)
        for index, option in enumerate(question.options)
    }


SCORE_LATENCY_MS = 17.3
FINAL_LATENCY_MS = 61.0


def score_transport(question: OptionSetQuestion, scores: Mapping[str, float]):
    """Answer each per-option question with the score declared for that option.

    Positions in the payload follow the declared option order, so no question
    name is parsed here.
    """

    def transport(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        answers: dict[str, Any] = {}
        for position, item in enumerate(payload["questions"], start=1):
            probability = scores[question.options[position - 1]]
            answers[str(item["name"])] = {
                "noul": probability,
                "probabilities": {"false": 1.0 - probability, "true": probability},
                "confidence": probability,
            }
        return {
            "answers": answers,
            "usage": {
                "input_tokens_total": 0,
                "output_tokens_total": 0,
                "n_retries": 0,
                "latency_ms": SCORE_LATENCY_MS,
            },
        }

    return transport


def pick_transport(pick: str, latency_ms: float):
    """Answer a single choice question with a declared option."""

    def transport(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        answers: dict[str, Any] = {}
        for item in payload["questions"]:
            keys = [str(key) for key in item["criteria"]]
            chosen = pick if pick in keys else keys[0]
            answers[str(item["name"])] = {
                "choice": chosen,
                "probabilities": {key: (1.0 if key == chosen else 0.0) for key in keys},
                "confidence": 0.9,
            }
        return {
            "answers": answers,
            "usage": {
                "input_tokens_total": 0,
                "output_tokens_total": 0,
                "n_retries": 0,
                "latency_ms": latency_ms,
            },
        }

    return transport


def run_scored_scenario(
    question: OptionSetQuestion,
    *,
    request_id: str,
    scores: Mapping[str, float],
    pick_index: int,
    finalists: int = 8,
) -> dict[str, Any]:
    """Score every option in one batch, then choose over the top finalists."""
    verifiers = VerifierRegistry()
    register_decision_verifiers(verifiers)

    plan = plan_scored_stages(question, finalists=finalists)
    score_questions = scored_stage_questions(plan, question)
    score_request = DecisionRequest(
        f"{request_id}-scores",
        "which mechanism should handle this task",
        score_questions,
    )
    score_capture = capture_decision(
        score_request,
        backend_id=BACKEND_ID,
        backend_version=BACKEND_VERSION,
        transport=score_transport(question, scores),
    )
    if not score_capture.performed or score_capture.record is None:
        raise SystemExit(f"scoring {request_id} failed: {score_capture.detail_code}")
    recorded = {
        str(name): float(answer["noul"])
        for name, answer in score_capture.record.answers.items()
    }
    scores_by_option = {
        option: recorded[plan.score_question_name(plan.option_index(option))]
        for option in question.options
    }

    choice = finalist_question(question, plan, scores_by_option)
    # A choice question carries its options as the criteria mapping keys.
    finalists_in_order = [str(key) for key in choice.criteria]
    final_request = DecisionRequest(
        f"{request_id}-final",
        "which mechanism should handle this task",
        (choice,),
    )
    final_capture = capture_decision(
        final_request,
        backend_id=BACKEND_ID,
        backend_version=BACKEND_VERSION,
        transport=pick_transport(finalists_in_order[pick_index], FINAL_LATENCY_MS),
    )
    if not final_capture.performed or final_capture.record is None:
        raise SystemExit(f"final choice {request_id} failed: {final_capture.detail_code}")
    chosen = str(final_capture.record.answers[choice.name]["choice"])
    decision = compose_scored(question, plan, scores_by_option, chosen)

    verified = verifiers.verify(
        SCORED_VERIFIER_ID,
        SCORED_VERIFIER_VERSION,
        scored_payload(question, scores_by_option, decision.winner, finalists=finalists),
    )
    tampered = verifiers.verify(
        SCORED_VERIFIER_ID,
        SCORED_VERIFIER_VERSION,
        scored_payload(question, scores_by_option, question.options[-1], finalists=finalists),
    )
    schema = verifiers.verify(
        SCHEMA_VERIFIER_ID,
        SCHEMA_VERIFIER_VERSION,
        schema_payload(score_request, score_capture.record),
    )
    return {
        "request_id": request_id,
        "plan": plan.to_record(),
        "score_questions": len(score_questions),
        "finalists": finalists_in_order,
        "decision": decision.to_record(),
        "verification": str(verified.verdict),
        "tampered_claim": str(tampered.verdict),
        "schema": str(schema.verdict),
        "records": (score_capture.record, final_capture.record),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    out = Path(args.out) if args.out else None
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        for target in (out / "summary.json", out / "records.jsonl"):
            if target.exists():
                raise SystemExit(f"{target} already exists; use another --out directory")

    verifiers = VerifierRegistry()
    register_decision_verifiers(verifiers)

    question = mechanism_question()
    budget = DecisionBudget(
        BUDGET_MS, max_state_age_ms=MAX_STATE_AGE_MS, fallback_route_id=FALLBACK_ROUTE
    )
    wide = run_scenario(
        question,
        request_id="decision-0001",
        state_age_ms=10.0,
        latency_ms=180.0,
        budget=budget,
    )
    late = run_scenario(
        question,
        request_id="decision-0002",
        state_age_ms=10.0,
        latency_ms=400.0,
        budget=budget,
    )
    stale = run_scenario(
        question,
        request_id="decision-0003",
        state_age_ms=2500.0,
        latency_ms=180.0,
        budget=budget,
    )
    narrow = run_scenario(
        OptionSetQuestion(
            name="mechanism",
            instructions=QUESTION_INSTRUCTIONS,
            options=(
                "rule.deterministic@strict",
                "audit.static_structure@strict",
                "tool.cli@strict",
            ),
        ),
        request_id="decision-0004",
        state_age_ms=5.0,
        latency_ms=40.0,
    )

    scored = run_scored_scenario(
        question,
        request_id="decision-0005",
        scores=scored_scores(question),
        pick_index=3,
    )
    scored_summary = {key: value for key, value in scored.items() if key != "records"}

    accepted = verify_claim(wide, wide.decision.winner, verifiers)
    rejected = verify_claim(wide, question.options[0], verifiers)
    scenarios = (wide, late, stale, narrow)

    summary = {
        "kind": "decision_adapter_suite",
        "data_origin": "fixture",
        "backend": f"{BACKEND_ID}/{BACKEND_VERSION}",
        "model_called": False,
        "route_entry": decision_route_entry(
            estimated_cost=None, estimated_latency_ms=None
        ),
        "scenarios": [scenario.summary() for scenario in scenarios],
        "scored_mode": scored_summary,
        "verification": {"recomputed_claim": accepted, "tampered_claim": rejected},
        "claim": (
            "offline fixture: the contract, the provenance and the replay are "
            "proven; decision quality against a real decision model is not measured"
        ),
    }

    if out is not None:
        (out / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + chr(10),
            encoding="utf-8",
            newline=chr(10),
        )
        records = chr(10).join(
            json.dumps(scenario.record.to_dict(), sort_keys=True)
            for scenario in scenarios
        )
        records = records + chr(10) + chr(10).join(
            json.dumps(record.to_dict(), sort_keys=True) for record in scored["records"]
        )
        (out / "records.jsonl").write_text(
            records + chr(10), encoding="utf-8", newline=chr(10)
        )
        print("wrote:", out / "summary.json")

    print(
        "wide option set:",
        wide.plan.total_options,
        "options in",
        wide.plan.stages,
        "stages",
        [len(group) for group in wide.plan.groups],
    )
    print("stage questions:", list(wide.plan.stage_question_names()))
    print("recomposed winner:", wide.decision.winner)
    print("verification:", summary["verification"])
    print(
        "scored mode:",
        scored["score_questions"],
        "questions in",
        scored["plan"]["score_calls"],
        "call(s),",
        scored["plan"]["batched_round_trips"],
        "batched round trips",
    )
    print("scored finalists:", scored["finalists"])
    print(
        "scored winner:",
        scored["decision"]["winner"],
        "argmax agrees:",
        scored["decision"]["argmax_agrees"],
    )
    print(
        "scored verification:",
        scored["verification"],
        "tampered:",
        scored["tampered_claim"],
        "schema:",
        scored["schema"],
    )
    print("within budget:", (wide.timing or {}).get("status"))
    print(
        "slow call:",
        (late.timing or {}).get("status"),
        "-> fallback",
        FALLBACK_ROUTE,
    )
    print("stale snapshot:", (stale.timing or {}).get("status"))
    print(
        "single stage:",
        narrow.plan.total_options,
        "options in",
        narrow.plan.stages,
        "stage",
    )
    print("note:", summary["claim"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
