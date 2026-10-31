"""Compare advice preparation arms; labels come from an explicit held-out corpus.

This measures retrieval/route proposals, never task completion or a program's
behavior. Expected labels are kept outside the advisor's state.
"""
from __future__ import annotations

from copy import deepcopy
from time import perf_counter

from .re_investigation import prepare_investigation


def compare_cases(cases):
    """Compare rules and rehashed-index reuse; model arms require separate runs."""
    if not isinstance(cases,list) or not cases or len(cases)>100:
        raise ValueError("provide 1..100 explicitly labelled cases")
    ids=[c["id"] for c in cases]
    if len(ids)!=len(set(ids)):
        raise ValueError("duplicate benchmark case")
    arms={"rules":[],"rules_retrieval":[]}
    for case in cases:
        if case["origin"] not in {"authored_fixture","independent_task"}:
            raise ValueError("explicit corpus origin required")
        if not isinstance(case["expected_files"],list) or not case["expected_files"]:
            raise ValueError("nonempty held-out file labels required")
        previous_index=None
        for arm in arms:
            started=perf_counter()
            result=prepare_investigation(deepcopy(case["state"]),case["inventory"],case["roots"],previous_index=previous_index)
            elapsed=(perf_counter()-started)*1000
            offered={f["source"]["path"] for f in result["packet"]["files"]}
            expected=set(case["expected_files"])
            probe=result["advice"]["baseline"]["next_probe"]
            binding=result["advice"]["option_bindings"]["next_probe"].get(probe)
            arms[arm].append({"case_id":case["id"],"origin":case["origin"],
                "expected_files":len(expected),"useful_files_found":len(expected&offered),
                "missing_files":sorted(expected-offered),"proposed_files":len(offered),
                "route_matches_label":binding==case["expected_route"],"wall_ms":elapsed,
                "index_files_read":result["index"]["metrics"]["files_read"],
                "derived_reused":result["index"]["metrics"]["derived_reused"]})
            previous_index=result["index"]
    return {"version":"re-investigation-bench/1","arms":arms,
        "jev":{"status":"not_run"},"local_model":{"status":"not_run"},"sft":{"status":"not_run"},
        "scope":"preparation and host-labelled suggestions only; warm reads rehash source bytes",
        "quality_ground_truth":"host supplied; authored fixtures do not prove generalization",
        "task_time_saved":None,"monetary_savings":None,"auto_act_allowed":False}
