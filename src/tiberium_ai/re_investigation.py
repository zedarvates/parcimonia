"""Observation-only REA/LeanREA advice over host-curated files and evidence.

No target execution or implicit network access. A typed judgment may reorder
eligible proposals; it cannot manufacture coverage, permissions or a PASS.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re
from time import perf_counter

from .decision_adapter import DecisionRequest, capture_decision, replay_decision
from .decision_clock import DecisionBudget, DecisionTiming
from .decision_json import canonical_json
from .execution_profiles import digest
from .reflex import ReflexKind, ReflexQuestion
from .task_followup import continue_task
from .task_preparation import build_index, prepare_task

VERSION = "re-investigation/1"
LEVELS = frozenset({"static", "browser", "export", "runtime", "visual", "roundtrip"})
KINDS = frozenset({"inventory", "source_slice", "decompile", "observe", "verify"})
HASH = re.compile(r"[0-9a-f]{64}\Z")


def _text(value, name, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"invalid {name}")


def _number(value, name, nullable=False):
    if nullable and value is None:
        return
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"invalid {name}")


def _fields(row, expected, name):
    if not isinstance(row, dict) or set(row) != set(expected.split()):
        raise ValueError(f"invalid {name} fields")


def _rows(value, name, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"invalid {name} list")


def validate_state(state):
    """Validate a bounded host snapshot; unknown availability remains unknown."""
    _fields(state, "schema_version investigation_id stage_id objective target_sha256 target_revision "
            "requirements evidence routes budget_ms state_age_ms max_state_age_ms", "state")
    if type(state["schema_version"]) is not int or state["schema_version"] != 1:
        raise ValueError("unsupported investigation schema")
    for key in ("investigation_id", "stage_id", "objective", "target_revision"):
        _text(state[key], key)
    if not isinstance(state["target_sha256"], str) or not HASH.fullmatch(state["target_sha256"]):
        raise ValueError("invalid target hash")
    for key in ("budget_ms", "state_age_ms", "max_state_age_ms"):
        _number(state[key], key, nullable=key != "budget_ms")
    _rows(state["requirements"], "requirements", 16)
    if not state["requirements"]:
        raise ValueError("requirements cannot be empty")
    requirement_keys = []
    for row in state["requirements"]:
        _fields(row, "claim scenario levels", "requirement")
        _text(row["claim"], "claim", 120)
        _text(row["scenario"], "scenario", 120)
        _rows(row["levels"], "levels", len(LEVELS))
        if not row["levels"] or len(row["levels"]) != len(set(row["levels"])) or any(x not in LEVELS for x in row["levels"]):
            raise ValueError("invalid evidence levels")
        requirement_keys.append((row["claim"], row["scenario"]))
    if len(requirement_keys) != len(set(requirement_keys)):
        raise ValueError("duplicate requirement")
    _rows(state["evidence"], "evidence", 256)
    evidence_ids = []
    for row in state["evidence"]:
        _fields(row, "id claim scenario target_sha256 target_revision level outcome value reference artifact_sha256", "evidence")
        for key in ("id", "claim", "scenario", "reference", "target_revision"):
            _text(row[key], key)
        for key in ("target_sha256", "artifact_sha256"):
            if not isinstance(row[key], str) or not HASH.fullmatch(row[key]):
                raise ValueError("invalid evidence hash")
        if row["level"] not in LEVELS or row["outcome"] not in {"pass", "fail", "unknown"}:
            raise ValueError("invalid evidence outcome or level")
        canonical_json(row["value"])
        evidence_ids.append(row["id"])
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("duplicate evidence id")
    _rows(state["routes"], "routes", 16)
    route_ids = []
    for row in state["routes"]:
        _fields(row, "id tool kind availability levels estimated_ms", "route")
        _text(row["id"], "route id", 120)
        if row["tool"] not in {"leanrea", "rea", "agent"} or row["kind"] not in KINDS:
            raise ValueError("invalid route tool or kind")
        if row["availability"] not in {"available", "unavailable", "unknown"}:
            raise ValueError("invalid availability")
        _rows(row["levels"], "route levels", len(LEVELS))
        if not row["levels"] or len(row["levels"]) != len(set(row["levels"])) or any(x not in LEVELS for x in row["levels"]):
            raise ValueError("invalid route evidence levels")
        _number(row["estimated_ms"], "estimated cost", nullable=True)
        route_ids.append(row["id"])
    if len(route_ids) != len(set(route_ids)):
        raise ValueError("duplicate route id")
    if len(canonical_json(state).encode("utf-8")) > 262144:
        raise ValueError("investigation state exceeds byte budget")


def evidence_coverage(state):
    """Recompute coverage by target, scenario and level; never certify reports."""
    validate_state(state)
    current = [e for e in state["evidence"] if e["target_sha256"] == state["target_sha256"]
               and e["target_revision"] == state["target_revision"]]
    missing, contradictions = [], []
    for requirement in state["requirements"]:
        matching = [e for e in current if all(e[k] == requirement[k] for k in ("claim", "scenario"))]
        known = [e for e in matching if e["outcome"] != "unknown"]
        # Values refer to the same host-declared property/scenario. Different
        # scenarios are never compared; null is an unobserved value, not zero.
        values = {canonical_json(e["value"]) for e in known if e["value"] is not None}
        outcomes = {e["outcome"] for e in known}
        conflict = len(values) > 1 or outcomes == {"pass", "fail"}
        if conflict:
            contradictions.append({"claim":requirement["claim"], "scenario":requirement["scenario"],
                "evidence_ids":[e["id"] for e in known], "status":"requires_discriminating_test"})
        for level in requirement["levels"]:
            found = [e for e in matching if e["level"] == level]
            if conflict or not any(e["outcome"] == "pass" for e in found):
                missing.append({"id":f"gap_{len(missing)+1}", "claim":requirement["claim"],
                    "scenario":requirement["scenario"], "level":level,
                    "reason":"contradiction" if conflict else "failed" if any(e["outcome"] == "fail" for e in found) else "unproven"})
    return {"missing":missing, "contradictions":contradictions,
        "historical_evidence_ids":[e["id"] for e in state["evidence"] if e not in current],
        "coverage":"reported_levels_present" if not missing else "incomplete",
        "proof_status":"reported_not_independently_verified", "completion_verified":False}


def advise_investigation(state, packet, *, transport=None, decision_record=None,
                         backend_id=None, backend_version=None):
    """Three bounded questions: first file, next probe, missing proof.

    A pinned injected transport or an offline record may add shadow judgments.
    Eligibility, coverage and permissions are always recomputed by local code.
    """
    started = perf_counter()
    state = deepcopy(state)
    coverage = evidence_coverage(state)
    if packet.get("auto_act_allowed") is not False or packet.get("goal") != state["objective"]:
        raise ValueError("incompatible observation packet")
    if transport is not None and decision_record is not None:
        raise ValueError("choose capture or replay")
    files = deepcopy(packet.get("files", []))
    _rows(files, "packet files", 16)
    file_options = {f"file_{i+1}":canonical_json(f["source"]) for i,f in enumerate(files)}
    for row in files:
        if not HASH.fullmatch(row.get("content_sha256", "")):
            raise ValueError("packet source hash missing")
    wanted = {x["level"] for x in coverage["missing"]}
    eligible = [r for r in state["routes"] if r["availability"] == "available" and wanted.intersection(r["levels"])]
    # Cheap static inspection precedes decompilation; the LLM is not asked to
    # guess formats, executable availability or return codes.
    order = {"inventory":0, "source_slice":1, "decompile":2, "observe":3, "verify":4}
    eligible.sort(key=lambda r:(order[r["kind"]], r["estimated_ms"] is None,
                               r["estimated_ms"] if r["estimated_ms"] is not None else 0, r["id"]))
    if coverage["contradictions"]:
        eligible.sort(key=lambda r:r["kind"] not in {"observe", "verify"})
    route_options = {f"probe_{i+1}":r["id"] for i,r in enumerate(eligible)}
    gap_options = {g["id"]:canonical_json(g) for g in coverage["missing"][:16]}
    if not coverage["missing"]:
        route_options["review_completion"] = "Review scope and evidence; this is not a PASS"
        gap_options["review_scope"] = "All declared levels reported; independent verification remains"
    questions = tuple(ReflexQuestion(name, ReflexKind.CHOICE, instructions,
        criteria={**options,"needs_context":"Abstain: ask the main agent for more context"})
        for name,instructions,options in (
            ("first_file","Which proposed file should the agent read first?",file_options),
            ("next_probe","Which eligible investigation would best reduce the remaining uncertainty?",route_options),
            ("proof_gap","Which declared proof gap should be addressed first?",gap_options))
        if options)
    # At most sixteen candidates plus abstention; no per-symbol/model loop.
    decision_state = canonical_json({"target_sha256":state["target_sha256"],
        "target_revision":state["target_revision"], "objective":state["objective"],
        "stage_id":state["stage_id"], "files":files, "coverage":coverage, "eligible_routes":eligible})
    pinned = decision_record is not None or transport is not None
    if pinned and (not backend_id or not backend_version):
        raise ValueError("decision backend identity and version are required")
    request = DecisionRequest(state["investigation_id"]+":"+state["stage_id"], decision_state, questions,
        state_age_ms=state["state_age_ms"], budget=DecisionBudget(state["budget_ms"],state["max_state_age_ms"],"agent_review"),
        backend_id=backend_id, backend_version=backend_version)
    judgments, record, judgment_status, transport_calls = {}, None, "not_run", 0
    # Refuse stale/unknown-age states and exhausted budgets BEFORE calling out.
    timing = DecisionTiming(0, state["state_age_ms"])
    from .decision_clock import assess_decision_timing
    preflight = assess_decision_timing(request.budget, timing)
    if state["budget_ms"] == 0 or not preflight.usable:
        judgment_status = "budget_exhausted" if state["budget_ms"] == 0 else preflight.reason_code
    elif pinned:
        try:
            if decision_record is not None:
                replay = replay_decision(decision_record,request,timing=timing)
                record = decision_record.to_dict()
                judgment_status = replay.detail_code
            else:
                transport_calls = 1
                capture = capture_decision(request,backend_id=backend_id,backend_version=backend_version,transport=transport)
                elapsed = (perf_counter()-started)*1000
                record = capture.record.to_dict() if capture.record else None
                replay = replay_decision(capture.record,request,timing=DecisionTiming(elapsed,state["state_age_ms"])) if capture.record else None
                judgment_status = capture.detail_code
            if replay is not None and replay.usable:
                judgments = {answer.name:answer.choice for answer in replay.batch.answers}
                judgment_status = "shadow_judgments"
            elif replay is not None:
                judgment_status = replay.timing.reason_code if replay.timing else replay.detail_code
        except (TypeError,ValueError,KeyError):
            judgment_status = "invalid_decision_record"
            judgments = {}
    report = {"version":VERSION,"mode":"shadow","investigation_id":state["investigation_id"],
        "stage_id":state["stage_id"],"state_sha256":digest(state),"packet_sha256":digest(packet),
        "decision_request":request.to_payload(),"decision_request_sha256":request.fingerprint(),
        "coverage":coverage,"files":files,"eligible_routes":eligible,
        "unavailable_or_unknown_routes":[r for r in state["routes"] if r["availability"] != "available"],
        "baseline":{"first_file":next(iter(file_options),"needs_context"),
                    "next_probe":next(iter(route_options),"needs_context"),
                    "proof_gap":next(iter(gap_options),"needs_context")},
        "option_bindings":{"first_file":file_options,"next_probe":route_options,"proof_gap":gap_options},
        "judgments":judgments,"judgment_status":judgment_status,"decision_record":record,
        "requires_agent_review":True,"auto_act_allowed":False,"execution":"not_run",
        "metrics":{"decision_transport_calls":transport_calls,"model_calls":None if transport_calls else 0,
            "files_proposed":len(files),"proof_gaps":len(coverage["missing"]),
            "proof_gaps_omitted_from_model_question":max(0,len(coverage["missing"])-16),
            "total_wall_ms":(perf_counter()-started)*1000,"task_time_saved":None,"monetary_cost":None}}
    report["report_sha256"] = digest(report)
    return report


def prepare_investigation(state, inventory, roots, *, policy=None, previous_index=None,
                          previous_packet=None, review=None, **decision_options):
    """Reuse existing preparation, profile filtering and file-review continuity."""
    validate_state(state)
    index = build_index(inventory,roots,previous=previous_index)
    if (previous_packet is None) != (review is None):
        raise ValueError("continuation requires both previous packet and review")
    if review is None:
        packet = prepare_task(state["objective"],inventory,index,policy=policy)
    else:
        packet = continue_task(state["objective"],inventory,index,previous_packet=previous_packet,
            review=review,roots=roots,task_id=state["investigation_id"],stage_id=state["stage_id"],policy=policy)
    advice = advise_investigation(state,packet,**decision_options)
    return {"index":index,"packet":packet,"advice":advice}
