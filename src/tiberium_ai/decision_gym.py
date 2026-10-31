"""Offline synthetic routing episodes; no model, provider or action authority."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from random import Random
from math import ceil
from time import perf_counter

from .decision_json import canonical_json

VERSION = "parcimonia-decision-gym/1"
SCENARIOS = ("normal", "replaced", "malformed", "stale", "unavailable", "budget")
OPTIONS = ("deterministic", "retrieval", "local_model", "escalate")


def fingerprint(value):
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def generate_episodes(seed=20):
    """300 fixtures, split by document family before creating episode states.

    Each family owns six scenarios. Template overlap across splits is deliberate:
    this is a protocol fixture corpus, not evidence of linguistic generalization.
    """
    rng = Random(seed)
    families = list(range(50))
    rng.shuffle(families)
    episodes = []
    for position, family in enumerate(families):
        split = "train" if position < 25 else "dev" if position < 38 else "test"
        # 150/78/72: whole six-episode families cannot yield 150/75/75.
        rows = [{"item": f"f{family}-r{i}", "value": rng.randint(-20, 100)} for i in range(4)]
        for scenario in SCENARIOS:
            operation = "sum" if family % 2 == 0 else "lookup"
            document = {"revision": 1, "rows": deepcopy(rows)}
            target = deepcopy(document)
            if scenario in {"replaced", "stale"}:
                target["revision"] = 2
                target["rows"][0]["value"] += 7
            state = {
                "version": VERSION, "objective": {"operation": operation, "item": rows[0]["item"]},
                "document": document, "required_revision": target["revision"],
                "options": list(OPTIONS), "available": ["deterministic", "retrieval"],
                "remaining_calls": 0 if scenario == "budget" else 3,
                "previous_error": None,
                "cache": {"document_hash": fingerprint(document), "item": rows[0]["item"],
                          "value": rows[0]["value"]},
            }
            if scenario == "replaced":
                state["document"] = deepcopy(target)  # Cache deliberately remains stale.
            if scenario == "unavailable":
                state["available"] = []
            episodes.append({"episode_id": f"f{family}-{scenario}", "group_id": f"f{family}",
                             "split": split, "scenario": scenario, "initial_state": state,
                             "oracle_document": target})
    return episodes


def verify_result(document, objective, result):
    """Independent result check: no baseline executor or teacher labels reused."""
    if type(result) is not int:
        return False
    if objective["operation"] == "sum":
        expected = 0
        for row in document["rows"]:
            expected += row["value"]
        return result == expected
    matches = [row["value"] for row in document["rows"] if row["item"] == objective["item"]]
    return len(matches) == 1 and matches[0] == result


def propose(state, arm):
    if arm not in {"rules", "rules_retrieval"}:
        raise ValueError("unknown arm")
    if state["remaining_calls"] <= 0:
        return "budget_exhausted"
    if state["document"]["revision"] != state["required_revision"]:
        return "repair_context"
    if arm == "rules_retrieval" and state["objective"]["operation"] == "lookup":
        cache = state["cache"]
        if ("retrieval" in state["available"] and
                cache["document_hash"] == fingerprint(state["document"]) and
                cache["item"] == state["objective"]["item"] and
                state["previous_error"] != "invalid_result"):
            return "retrieval"
    return "deterministic" if "deterministic" in state["available"] else "escalate"


def execute_fixture(state, route):
    if route not in state["available"] or state["remaining_calls"] <= 0:
        raise ValueError("ineligible fixture execution")
    if route == "retrieval":
        return state["cache"]["value"]
    if route != "deterministic":
        raise ValueError("model execution is not implemented")
    rows = state["document"]["rows"]
    if state["objective"]["operation"] == "sum":
        return sum(row["value"] for row in rows)
    return next(row["value"] for row in rows if row["item"] == state["objective"]["item"])


def replay(episode, arm):
    state = deepcopy(episode["initial_state"])
    trace = []
    status = "step_limit"
    for _ in range(4):
        before = deepcopy(state)
        started = perf_counter()
        route = propose(state, arm)
        result = None
        valid = None
        if route == "repair_context":
            # Host fixture event, not a model prediction or silent repair.
            state["document"] = deepcopy(episode["oracle_document"])
            state["previous_error"] = "context_refreshed"
        elif route in {"budget_exhausted", "escalate"}:
            status = route
        else:
            result = execute_fixture(state, route)
            state["remaining_calls"] -= 1
            if episode["scenario"] == "malformed" and not trace:
                result = {"malformed": True}  # Explicit injected fixture fault.
            valid = verify_result(episode["oracle_document"], state["objective"], result)
            state["previous_error"] = None if valid else "invalid_result"
            if valid:
                status = "verified"
        elapsed = perf_counter() - started
        trace.append({"input": before, "input_hash": fingerprint(before), "route": route,
                      "result": result, "verified": valid, "next_state": deepcopy(state),
                      "next_state_hash": fingerprint(state), "wall_seconds": elapsed,
                      "verifier": "fixture-table-result/1", "money": None, "energy": None})
        if status != "step_limit":
            break
    return {"episode_id": episode["episode_id"], "group_id": episode["group_id"],
            "split": episode["split"], "scenario": episode["scenario"], "status": status,
            "trace": trace, "auto_act_allowed": False}


def run_benchmark(episodes):
    results = {}
    for arm in ("rules", "rules_retrieval"):
        records = [replay(episode, arm) for episode in episodes]
        by_split = {}
        for split in ("train", "dev", "test"):
            selected = [r for r in records if r["split"] == split]
            durations = sorted(sum(step["wall_seconds"] for step in r["trace"]) for r in selected)
            by_split[split] = {"episodes": len(selected),
                "verified": sum(r["status"] == "verified" for r in selected),
                "escalated": sum(r["status"] == "escalate" for r in selected),
                "budget_exhausted": sum(r["status"] == "budget_exhausted" for r in selected),
                "mechanism_calls": sum(step["route"] in {"deterministic", "retrieval"}
                                       for r in selected for step in r["trace"]),
                "rejected_results": sum(step["verified"] is False for r in selected for step in r["trace"]),
                "episode_wall_p50_seconds": durations[ceil(len(durations) * .5) - 1] if durations else None,
                "episode_wall_p95_seconds": durations[ceil(len(durations) * .95) - 1] if durations else None,
                "money": None, "energy": None}
        results[arm] = {"status": "executed_fixture", "by_split": by_split, "records": records}
    for arm in ("existing_signature_cascade", "jev", "unadapted_model", "sft"):
        results[arm] = {"status": "not_run", "reason": "no_fixture_adapter_or_inference_requested"}
    return {"version": VERSION, "data_origin": "fixture", "corpus_hash": fingerprint(episodes),
            "auto_act_allowed": False, "promotion": "inconclusive", "arms": results,
            "limits": ["shared linguistic templates across splits", "synthetic host events",
                       "no model inference", "no production savings measured",
                       "money and energy unknown", "test split is protocol-only, not a sealed model evaluation"]}
