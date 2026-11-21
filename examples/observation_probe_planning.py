"""Authored probe comparisons; no host, model, network or game is contacted."""
from copy import deepcopy
import json

from tiberium_ai.execution_profiles import digest
from tiberium_ai.probe_planning import plan_observation_probes


def authored_inputs():
    hypotheses = ["client_stale", "session_lost", "transport_broken", "recovered"]
    requirements = [
        {"id": name, "source_id": "fixture-client-server", "source_revision": "fixture/1",
         "input_sha256": digest({"authored": name}), "verifier_id": "fixture-verifier",
         "verifier_version": "1", "max_age_seconds": 60}
        for name in ("connected", "spawned", "moving")
    ]
    request = {
        "task_id": "fixture-reconnection", "task_revision": "fixture/1",
        "requirements": requirements, "observations": [],
        "probes": [
            {"id": "broad-summary", "requirement_ids": [r["id"] for r in requirements],
             "estimated_latency_ms": 5},
            {"id": "client-status", "requirement_ids": ["connected"],
             "estimated_latency_ms": 30},
            {"id": "session-status", "requirement_ids": ["spawned"],
             "estimated_latency_ms": 20},
            {"id": "full-diagnostic", "requirement_ids": ["moving"],
             "estimated_latency_ms": 400},
        ],
    }

    def probe(identifier, groups, cost):
        return {"id": identifier, "estimated_cost": cost,
                "unmodelled_outcome_possible": False,
                "outcomes": [{"id": f"result-{index}", "hypothesis_ids": group}
                             for index, group in enumerate(groups)]}

    model = {
        "schema": "parcimonia.probe-planning-model/v1",
        "task_id": request["task_id"], "task_revision": request["task_revision"],
        "revision": "authored/1", "observation_request_sha256": digest(request),
        "cost_unit": "authored-cost-unit", "hypothesis_ids": hypotheses,
        "probes": [
            probe("broad-summary", [hypotheses], 0),
            probe("client-status", [hypotheses[:1], hypotheses[1:]], 0),
            probe("session-status", [hypotheses[:2], hypotheses[2:]], 0),
            probe("full-diagnostic", [[item] for item in hypotheses], 2),
        ],
    }
    return request, model


def summarize(report):
    return {"status": report["status"],
            "next_probe": report["next_probe"]["id"] if report["next_probe"] else None,
            "frontier_probe_ids": report["frontier_probe_ids"]}


def main():
    request, model = authored_inputs()
    bounded = plan_observation_probes(request, model, max_estimated_latency_ms=50,
                                     max_estimated_cost=0, now=1000)
    if bounded["status"] != "proposed" or bounded["next_probe"]["id"] != "session-status":
        raise RuntimeError("Expected the bounded authored session check")
    baseline = bounded["observation_review"]["next_probe"]
    if baseline is None or baseline["id"] != "broad-summary":
        raise RuntimeError("Expected the existing coverage heuristic to retain its behavior")

    tradeoff = plan_observation_probes(request, model, now=1000)
    if tradeoff["status"] != "needs_preference" or tradeoff["next_probe"] is not None:
        raise RuntimeError("Expected an explicit information/latency/cost tradeoff")

    uncertain_model = deepcopy(model)
    for probe in uncertain_model["probes"]:
        probe["unmodelled_outcome_possible"] = True
    uncertain = plan_observation_probes(request, uncertain_model, now=1000)
    if uncertain["status"] != "abstained" or uncertain["next_probe"] is not None:
        raise RuntimeError("An unmodelled result must not establish a comparison")

    failed_request = deepcopy(request)
    requirement = failed_request["requirements"][0]
    failed_request["observations"] = [{
        **{key: value for key, value in requirement.items() if key not in ("id", "max_age_seconds")},
        "id": "fixture-failure", "requirement_id": requirement["id"],
        "task_id": request["task_id"], "task_revision": request["task_revision"],
        "observed_at": 1000, "outcome": "fail",
    }]
    failed_model = deepcopy(model)
    failed_model["observation_request_sha256"] = digest(failed_request)
    failed = plan_observation_probes(failed_request, failed_model, now=1000)
    if failed["status"] != "blocked" or failed["next_probe"] is not None:
        raise RuntimeError("A current failure must remain blocked")

    print(json.dumps({"data_origin": "authored", "coverage_baseline_probe": baseline["id"],
                      "bounded": summarize(bounded),
                      "unbounded": summarize(tradeoff), "unmodelled": summarize(uncertain),
                      "current_failure": summarize(failed), "probe_executed": False,
                      "measured_savings": None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
