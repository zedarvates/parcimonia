"""Local authored fixtures, measured policy phases, and a fully recoverable queue."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tiberium_ai.agent_recipes import (
    DecisionSession, assess_novelty, retrieve_source_candidates, triage_attention,
)
from tiberium_ai.agent_recipes.benchmark import PhaseResult, compare_pipelines, measure_pipeline
from tiberium_ai.agent_recipes.core import fingerprint, unique
from tiberium_ai.agent_recipes.source_triage import (
    RELATIONS, attention_state, novelty_state, verify_source_structure,
)
from tiberium_ai.reflex import InjectedReflexBackend


CORPUS_PATH = Path(__file__).with_name("fixtures") / "source_triage.json"


def disposition(attention, novelty, *, shortlist_limited=False):
    """Only propose suppression when uncertainty has not made that unsafe."""
    if attention.status == "abstained" or attention.data["decision"] in {"defer", "needs_context"}:
        return "defer"
    if attention.data["recall"]["source"].get("protected", False):
        return "process" if attention.data["decision"] == "process" else "defer"
    if novelty.data["decision"] in {"update", "contradiction"}:
        return "process" if attention.data["decision"] == "process" else "defer"
    if attention.data["decision"] == "skip_candidate":
        return "skip_candidate"
    if novelty.data["decision"] == "duplicate":
        return "defer" if shortlist_limited else "skip_candidate"
    return "process"


def fixture_session(case, retrieved):
    if case["attention"] is None:
        return DecisionSession()
    answers = {key: {"noul": p, "probabilities": {"true": p, "false": 1 - p}}
               for key, p in zip(("relevant", "actionable", "needs_context"), case["attention"])}
    for index, candidate in enumerate(retrieved["selected"]):
        label = case["relations"].get(candidate["id"])
        if label is not None:
            answers[f"relation_{index}"] = {"choice": label, "confidence": .96,
                "probabilities": {key: .96 if key == label else .01 for key in RELATIONS}}
    return DecisionSession(InjectedReflexBackend(answers, latin_only=False))


def run_suite():
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    if corpus["origin"] != "authored_fixture" or corpus["independent_labels_established"] is not False:
        raise ValueError("this offline walkthrough requires the authored fixture corpus")
    unique(corpus["cases"])
    rows = []
    for case in corpus["cases"]:
        context = deepcopy(corpus["context"])
        if "context_values" in case:
            context["values"] = case["context_values"]
        inputs = {"source": case["source"], "context": context, "knowledge": case["knowledge"]}
        work = {}

        def retrieve(value):
            work["retrieval"] = retrieve_source_candidates(value["source"], value["knowledge"])
            return PhaseResult(value)

        def decide(value):
            session = fixture_session(case, work["retrieval"])
            work["attention"] = triage_attention(value["source"], value["context"], session)
            work["novelty"] = assess_novelty(value["source"], work["retrieval"]["selected"], session)
            work["calls"] = deepcopy(session.calls)
            return PhaseResult(value)

        def queue(value):
            return PhaseResult({**value, "disposition": disposition(work["attention"], work["novelty"],
                shortlist_limited=work["retrieval"]["shortlist_limited"]),
                "retrieval": work["retrieval"], "attention": work["attention"].to_dict(),
                "novelty": work["novelty"].to_dict(), "calls": work["calls"],
                "auto_act_allowed": False, "delete_allowed": False})

        def verify(value):
            return (value["source"] == inputs["source"] and value["context"] == inputs["context"]
                and value["knowledge"] == inputs["knowledge"] and value["auto_act_allowed"] is False
                and value["delete_allowed"] is False
                and value["retrieval"] == retrieve_source_candidates(inputs["source"], inputs["knowledge"])
                and value["disposition"] == disposition(work["attention"], work["novelty"],
                                                       shortlist_limited=work["retrieval"]["shortlist_limited"])
                and verify_source_structure({"state": attention_state(inputs["source"], inputs["context"]),
                                             "result": value["attention"]})
                and verify_source_structure({"state": novelty_state(inputs["source"], work["retrieval"]["selected"]),
                                             "result": value["novelty"]}))

        candidate = measure_pipeline(case["id"], "attention-novelty", inputs, {
            "collect": lambda value: PhaseResult(deepcopy(value)),
            "retrieve": retrieve, "decide": decide, "queue": queue}, verify)
        baseline = measure_pipeline(case["id"], "process-all-policy", inputs, {
            "collect": lambda value: PhaseResult(deepcopy(value)),
            "queue": lambda value: PhaseResult({**value, "disposition": "process"})},
            lambda value: value == {**inputs, "disposition": "process"})
        proposed = disposition(work["attention"], work["novelty"],
                               shortlist_limited=work["retrieval"]["shortlist_limited"])
        if not candidate["verified"] or proposed != case["expected_disposition"]:
            raise ValueError("fixture policy or structural verification failed")
        rows.append({"case_id": case["id"], "source": deepcopy(inputs["source"]),
            "context": deepcopy(inputs["context"]), "knowledge": deepcopy(inputs["knowledge"]),
            "disposition": proposed, "expected_disposition": case["expected_disposition"],
            "must_retain": case["must_retain"], "retrieval": work["retrieval"],
            "attention": work["attention"].to_dict(), "novelty": work["novelty"].to_dict(),
            "calls": work["calls"], "baseline_measurement": baseline,
            "candidate_measurement": candidate, "comparison": compare_pipelines(baseline, candidate)})
    return {"schema": "source-triage-pilot/1", "origin": "authored_fixture",
        "corpus_hash": fingerprint(corpus), "cases": rows,
        "counts": {"baseline_process": len(rows), **{key: sum(row["disposition"] == key for row in rows)
            for key in ("process", "defer", "skip_candidate")},
            "fixture_required_sources_proposed_skipped": sum(row["must_retain"] and row["disposition"] == "skip_candidate" for row in rows),
            "retained_originals": len(rows), "fixture_backend_calls": sum(len(row["calls"]) for row in rows)},
        "independent_labels_established": False, "quality_metrics": None, "cost_savings": None,
        "claim_allowed": False, "auto_act_allowed": False, "model_inference_executed": False,
        "latency_scope": "local policy, retrieval, injected fixture judgments, queue and structural verifier; no LLM generation",
        "cost_scope": "unknown; no billing or energy measurement", "source_deleted_count": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(args.output)
    report = run_suite()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    print(json.dumps({"counts": report["counts"], "claim_allowed": False,
                      "model_inference_executed": False, "cost_savings": None}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
