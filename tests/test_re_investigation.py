from copy import deepcopy
from dataclasses import replace
import json

import pytest

from tiberium_ai.decision_adapter import DecisionRecord
from tiberium_ai.re_investigation import advise_investigation, evidence_coverage, prepare_investigation, validate_state
from tiberium_ai.task_followup import record_file_review
from test_task_preparation import inventory


def state():
    return {"schema_version":1,"investigation_id":"re-test","stage_id":"inspect",
        "objective":"Verifier les profils outils versionnes","target_sha256":"a"*64,"target_revision":"fixture/1",
        "requirements":[{"claim":"saved_geometry","scenario":"nested","levels":["static","roundtrip"]}],
        "evidence":[],"routes":[
            {"id":"lean.inspect","tool":"leanrea","kind":"source_slice","availability":"available","levels":["static"],"estimated_ms":10},
            {"id":"rea.deep","tool":"rea","kind":"decompile","availability":"available","levels":["static"],"estimated_ms":None},
            {"id":"agent.roundtrip","tool":"agent","kind":"verify","availability":"available","levels":["roundtrip"],"estimated_ms":50}],
        "budget_ms":10000,"state_age_ms":0,"max_state_age_ms":1000}


def evidence(identifier="e1", level="static", outcome="pass", value=1, **extra):
    return {"id":identifier,"claim":"saved_geometry","scenario":"nested","target_sha256":"a"*64,
        "target_revision":"fixture/1","level":level,"outcome":outcome,"value":value,
        "reference":"fixture:artifact","artifact_sha256":"b"*64,**extra}


@pytest.fixture
def prepared(tmp_path):
    s=state(); inv=inventory(tmp_path); roots={"workspace":tmp_path}
    return s,inv,roots,prepare_investigation(s,inv,roots)


def choose_first(payload):
    answers={}
    for q in payload["questions"]:
        choices=list(q["criteria"])
        chosen=choices[0]
        answers[q["name"]]={"choice":chosen,"probabilities":{c:float(c==chosen) for c in choices},"confidence":1.0}
    return {"answers":answers}


def test_existing_preparation_is_reused_without_activation(prepared):
    s,inv,roots,p=prepared
    assert {f["source"]["path"] for f in p["advice"]["files"]}=={"sample.py","tests/test_sample.py"}
    assert p["packet"]["capabilities"][0]["id"]=="mechanism:inspect"
    assert p["advice"]["baseline"]["next_probe"]=="probe_1"
    assert p["advice"]["option_bindings"]["next_probe"]["probe_1"]=="lean.inspect"
    assert p["advice"]["auto_act_allowed"] is False
    assert p["advice"]["execution"]=="not_run"
    assert p["advice"]["metrics"]["model_calls"]==0
    assert p["advice"]["metrics"]["task_time_saved"] is None


def test_static_pass_cannot_close_roundtrip_or_runtime_requirement():
    s=state();s["requirements"][0]["levels"].append("runtime");s["evidence"]=[evidence()]
    coverage=evidence_coverage(s)
    assert {g["level"] for g in coverage["missing"]}=={"roundtrip","runtime"}
    assert coverage["completion_verified"] is False


def test_old_target_and_other_scenario_are_not_current_proof():
    s=state();s["evidence"]=[evidence(target_sha256="c"*64),evidence("other",scenario="different")]
    coverage=evidence_coverage(s)
    assert len(coverage["missing"])==2
    assert coverage["historical_evidence_ids"]==["e1"]


def test_old_build_revision_does_not_prove_new_reconstruction():
    s=state();s["evidence"]=[evidence(target_revision="previous-build")]
    assert len(evidence_coverage(s)["missing"])==2


@pytest.mark.parametrize("second",[evidence("e2",level="roundtrip",value=2),evidence("e2",outcome="fail")])
def test_contradictions_keep_gap_open_and_prioritize_discriminating_test(prepared,second):
    s,_,_,p=prepared;s["evidence"]=[evidence(),second]
    report=advise_investigation(s,p["packet"])
    assert report["coverage"]["contradictions"]
    assert all(g["reason"]=="contradiction" for g in report["coverage"]["missing"])
    assert report["eligible_routes"][0]["id"]=="agent.roundtrip"


def test_unknown_evidence_remains_unproven():
    s=state();s["evidence"]=[evidence(outcome="unknown",value=None)]
    assert all(g["reason"]=="unproven" for g in evidence_coverage(s)["missing"])


def test_all_reported_levels_still_require_independent_review(prepared):
    s,_,_,p=prepared;s["evidence"]=[evidence(),evidence("e2",level="roundtrip")]
    report=advise_investigation(s,p["packet"])
    assert report["coverage"]["coverage"]=="reported_levels_present"
    assert report["coverage"]["completion_verified"] is False
    assert report["baseline"]["next_probe"]=="review_completion"


@pytest.mark.parametrize("availability",["unknown","unavailable"])
def test_unavailable_or_unknown_routes_are_never_eligible(prepared,availability):
    s,_,_,p=prepared
    for r in s["routes"]:r["availability"]=availability
    report=advise_investigation(s,p["packet"])
    assert not report["eligible_routes"]
    assert report["baseline"]["next_probe"]=="needs_context"
    assert len(report["unavailable_or_unknown_routes"])==3


def test_capture_and_offline_replay_share_bound_identity(prepared):
    s,_,_,p=prepared
    captured=advise_investigation(s,p["packet"],transport=choose_first,backend_id="fixture.choice",backend_version="1")
    assert captured["judgment_status"]=="shadow_judgments"
    assert set(captured["judgments"])=={"first_file","next_probe","proof_gap"}
    assert captured["auto_act_allowed"] is False
    record=DecisionRecord(**captured["decision_record"])
    replayed=advise_investigation(s,p["packet"],decision_record=record,backend_id="fixture.choice",backend_version="1")
    assert replayed["judgments"]==captured["judgments"]
    assert replayed["metrics"]["decision_transport_calls"]==0
    s["target_sha256"]="c"*64
    stale=advise_investigation(s,p["packet"],decision_record=record,backend_id="fixture.choice",backend_version="1")
    assert stale["judgment_status"]=="request_hash_mismatch"
    assert stale["judgments"]=={}


@pytest.mark.parametrize("error",[OSError("offline"),RuntimeError("broken")])
def test_transport_failure_preserves_local_advice(prepared,error):
    s,_,_,p=prepared
    def broken(_):raise error
    r=advise_investigation(s,p["packet"],transport=broken,backend_id="fixture.choice",backend_version="1")
    assert not r["judgments"] and r["baseline"]["next_probe"]=="probe_1"
    assert r["auto_act_allowed"] is False


def test_malformed_choice_cannot_override_available_routes(prepared):
    s,_,_,p=prepared
    def wrong(payload):
        r=choose_first(payload)
        r["answers"]["next_probe"]["choice"]="execute_arbitrary_command"
        return r
    r=advise_investigation(s,p["packet"],transport=wrong,backend_id="fixture.choice",backend_version="1")
    assert not r["judgments"]
    assert r["judgment_status"]=="invalid_decision_record"


@pytest.mark.parametrize("changes",[{"budget_ms":0},{"state_age_ms":1001},{"state_age_ms":None}])
def test_bad_deadline_or_stale_state_never_calls_transport(prepared,changes):
    s,_,_,p=prepared;s.update(changes)
    calls=[]
    def counted(payload):calls.append(payload);return choose_first(payload)
    r=advise_investigation(s,p["packet"],transport=counted,backend_id="fixture.choice",backend_version="1")
    assert calls==[] and r["judgments"]=={}


def test_late_reply_is_recorded_but_not_used(prepared,monkeypatch):
    s,_,_,p=prepared;s["budget_ms"]=1
    clock=iter([0,1,1])
    monkeypatch.setattr("tiberium_ai.re_investigation.perf_counter",lambda:next(clock))
    r=advise_investigation(s,p["packet"],transport=choose_first,backend_id="fixture.choice",backend_version="1")
    assert r["decision_record"] is not None
    assert r["judgment_status"]=="elapsed_exceeds_budget"
    assert not r["judgments"]


def test_reused_file_change_invalidates_notes_and_capabilities(prepared,tmp_path):
    s,inv,roots,p=prepared
    source={"root":"workspace","path":"sample.py"}
    feedback={"task_id":s["investigation_id"],"stage_id":s["stage_id"],"reviewer":"fixture", "reviewer_kind":"agent",
        "review_complete":False,"judgments":[{"source":source,"status":"used","reason":"inspected"}],
        "missing_files":[],"notes":[{"kind":"test_result","text":"reported", "sources":[source],"evidence":"fixture:test"}],
        "additional_searches":None,"additional_reads":1}
    review=record_file_review(p["packet"],feedback,roots=roots,at="2026-10-28T16:00:00Z")
    (tmp_path/"sample.py").write_text("def inspect_profile():\n    return 'changed'\n",encoding="utf-8")
    s["stage_id"]="verify"
    refreshed=prepare_investigation(s,inv,roots,previous_packet=p["packet"],review=review,previous_index=p["index"])
    assert refreshed["packet"]["continuity"]["files"][0]["state"]=="changed_requires_reread"
    assert refreshed["packet"]["continuity"]["notes"][0]["continuity_status"]=="stale_requires_review"
    assert refreshed["packet"]["capabilities"]==[]


@pytest.mark.parametrize("key,value",[("budget_ms",True),("budget_ms",float("nan")),("target_sha256","bad"),("schema_version",True)])
def test_invalid_state_rejected(key,value):
    s=state();s[key]=value
    with pytest.raises(ValueError):validate_state(s)


def test_duplicate_evidence_and_injected_authorization_rejected():
    s=state();s["evidence"]=[evidence(),evidence()]
    with pytest.raises(ValueError,match="duplicate"):validate_state(s)
    s=state();s["auto_act_allowed"]=True
    with pytest.raises(ValueError,match="fields"):validate_state(s)


def test_sources_are_never_imported(prepared,tmp_path):
    s,inv,roots,p=prepared
    (tmp_path/"sample.py").write_text("raise RuntimeError('do not execute inspected source')\n",encoding="utf-8")
    prepared_again=prepare_investigation(s,inv,roots)
    assert prepared_again["packet"]["capabilities"]==[]
