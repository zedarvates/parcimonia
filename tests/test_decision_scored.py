import json

import pytest

from tiberium_ai.audit import (
    AUDIT_CAPABILITY,
    audit_route_entry,
    register_audit_verifiers,
)
from tiberium_ai.contracts import Task
from tiberium_ai.decision_adapter import (
    DECIDED_SCORED,
    DECISION_CAPABILITY,
    DECISION_VERIFIER_ID,
    DECISION_VERIFIER_VERSION,
    DEFAULT_FINALISTS,
    SCHEMA_VERIFIER_ID,
    SCHEMA_VERIFIER_VERSION,
    SCORED_VERIFIER_ID,
    SCORED_VERIFIER_VERSION,
    UNDETERMINED_FINAL,
    UNDETERMINED_SCORES,
    DecisionRecord,
    DecisionRequest,
    OptionSetQuestion,
    ScoredPlan,
    compose_scored,
    decision_route_entry,
    finalist_question,
    plan_scored_stages,
    read_decision_record,
    register_decision_verifiers,
    replay_decision,
    schema_payload,
    schema_verifier,
    scored_payload,
    scored_stage_questions,
    scored_verifier,
    write_decision_record,
)
from tiberium_ai.decision_clock import DecisionBudget
from tiberium_ai.reflex import ReflexKind, ReflexQuestion
from tiberium_ai.registry import RouteRegistry
from tiberium_ai.router import ShadowRouter
from tiberium_ai.verification import VerifierRegistry


def mechanism_question(count=28):
    return OptionSetQuestion(
        name="mechanism",
        instructions="Which mechanism satisfies the task?",
        options=tuple(f"route.{index:03d}" for index in range(count)),
    )


def descending_scores(question):
    total = len(question.options)
    return {
        option: round((total - index) / total, 6)
        for index, option in enumerate(question.options)
    }


def noul_answer(probability):
    return {
        "noul": probability,
        "probabilities": {"false": 1.0 - probability, "true": probability},
        "confidence": probability,
    }


def choice_answer(keys, chosen):
    return {
        "choice": chosen,
        "probabilities": {key: (1.0 if key == chosen else 0.0) for key in keys},
        "confidence": 0.9,
    }


def first_score_question(count=10):
    """Return the first scoring question of a small plan, for schema fixtures."""
    question = mechanism_question(count)
    plan = plan_scored_stages(question)
    return scored_stage_questions(plan, question)[0]


# --- planning -------------------------------------------------------------


def test_one_batch_covers_the_option_set_when_the_cap_allows():
    plan = plan_scored_stages(mechanism_question())
    assert [len(batch) for batch in plan.score_batches] == [28]
    assert plan.score_calls == 1
    assert plan.stage_calls == 2
    assert plan.batched_round_trips == 2


def test_a_small_cap_adds_batches_without_adding_round_trips():
    plan = plan_scored_stages(mechanism_question(), max_questions_per_call=10)
    assert [len(batch) for batch in plan.score_batches] == [10, 10, 8]
    assert plan.score_calls == 3
    assert plan.stage_calls == 4
    # Batch three calls from one cached context, so batching is what makes the
    # wide case affordable rather than a second stage.
    assert plan.batched_round_trips == 2


def test_a_scored_plan_rejects_incoherent_policy():
    question = mechanism_question()
    with pytest.raises(ValueError, match="finalists"):
        plan_scored_stages(question, finalists=1)
    with pytest.raises(ValueError, match="finalists"):
        plan_scored_stages(question, finalists=21)
    with pytest.raises(ValueError, match="exceeds"):
        plan_scored_stages(mechanism_question(4), finalists=8)
    with pytest.raises(ValueError, match="max_questions_per_call"):
        plan_scored_stages(question, max_questions_per_call=0)


def test_score_batches_must_partition_the_options():
    question = mechanism_question(4)
    with pytest.raises(ValueError, match="partition"):
        ScoredPlan(
            "mechanism",
            question.options,
            (("route.000", "route.001"), ("route.002",)),
            2,
            2,
        )


def test_scored_stage_questions_are_one_boolean_per_option():
    question = mechanism_question(5)
    plan = plan_scored_stages(question, finalists=2)
    questions = scored_stage_questions(plan, question)
    assert len(questions) == 5
    assert all(question_.kind is ReflexKind.NOUL for question_ in questions)
    assert [question_.name for question_ in questions] == [
        "mechanism.score.o1",
        "mechanism.score.o2",
        "mechanism.score.o3",
        "mechanism.score.o4",
        "mechanism.score.o5",
    ]
    assert plan.stage_question_names()[-1] == "mechanism.final"


def test_scored_stage_questions_reject_another_option_set():
    question = mechanism_question(5)
    plan = plan_scored_stages(question, finalists=2)
    with pytest.raises(ValueError, match="not built for this option set"):
        scored_stage_questions(plan, mechanism_question(4))


# --- the second stage -----------------------------------------------------


def test_the_final_question_offers_only_the_top_finalists():
    question = mechanism_question()
    plan = plan_scored_stages(question, finalists=4)
    scores = descending_scores(question)
    final_question = finalist_question(question, plan, scores)
    assert list(final_question.criteria) == list(question.options[:4])
    assert final_question.name == plan.final_question_name


def test_a_tie_at_the_cutoff_keeps_the_declared_order():
    question = mechanism_question(4)
    plan = plan_scored_stages(question, finalists=2)
    scores = {
        question.options[0]: 0.9,
        question.options[1]: 0.8,
        question.options[2]: 0.8,
        question.options[3]: 0.1,
    }
    assert list(finalist_question(question, plan, scores).criteria) == list(
        question.options[:2]
    )


def test_an_incomplete_score_vector_is_refused_not_ranked():
    question = mechanism_question()
    plan = plan_scored_stages(question)
    scores = descending_scores(question)
    scores.pop(question.options[3])
    with pytest.raises(ValueError, match="never zero"):
        finalist_question(question, plan, scores)


def test_an_out_of_range_or_unknown_score_raises():
    question = mechanism_question(4)
    plan = plan_scored_stages(question, finalists=2)
    base = {option: 0.5 for option in question.options}
    with pytest.raises(ValueError, match="outside the declared set"):
        finalist_question(question, plan, {**base, "route.999": 0.9})
    with pytest.raises(ValueError, match=r"in \[0, 1\]"):
        finalist_question(question, plan, {**base, question.options[0]: 1.5})


# --- composition ----------------------------------------------------------


def test_the_winner_is_the_explicit_choice():
    question = mechanism_question()
    plan = plan_scored_stages(question)
    scores = descending_scores(question)
    decision = compose_scored(question, plan, scores, question.options[5])
    assert decision.determined is True
    assert decision.winner == question.options[5]
    assert decision.reason_code == DECIDED_SCORED
    assert decision.argmax_agrees is False
    assert len(decision.finalists) == DEFAULT_FINALISTS


def test_the_argmax_is_reported_when_the_choice_agrees():
    question = mechanism_question()
    plan = plan_scored_stages(question)
    scores = descending_scores(question)
    decision = compose_scored(question, plan, scores, question.options[0])
    assert decision.argmax_agrees is True
    assert decision.tie_at_cutoff is False


def test_a_tie_just_outside_the_finalists_is_reported():
    question = mechanism_question(4)
    plan = plan_scored_stages(question, finalists=2)
    scores = {
        question.options[0]: 0.9,
        question.options[1]: 0.4,
        question.options[2]: 0.4,
        question.options[3]: 0.1,
    }
    decision = compose_scored(question, plan, scores, question.options[0])
    assert decision.tie_at_cutoff is True


def test_a_missing_score_abstains_instead_of_scoring_zero():
    question = mechanism_question()
    plan = plan_scored_stages(question)
    scores = descending_scores(question)
    scores.pop(question.options[7])
    decision = compose_scored(question, plan, scores, question.options[0])
    assert decision.determined is False
    assert decision.winner is None
    assert decision.reason_code == UNDETERMINED_SCORES


def test_a_missing_explicit_choice_abstains():
    question = mechanism_question()
    plan = plan_scored_stages(question)
    decision = compose_scored(question, plan, descending_scores(question), None)
    assert decision.determined is False
    assert decision.reason_code == UNDETERMINED_FINAL


def test_a_choice_outside_the_declared_options_or_finalists_raises():
    question = mechanism_question()
    plan = plan_scored_stages(question, finalists=4)
    scores = descending_scores(question)
    with pytest.raises(ValueError, match="never declared"):
        compose_scored(question, plan, scores, "route.999")
    with pytest.raises(ValueError, match="scored finalists"):
        compose_scored(question, plan, scores, question.options[20])


def test_a_scored_decision_from_another_option_set_is_refused():
    question = mechanism_question()
    plan = plan_scored_stages(question)
    with pytest.raises(ValueError, match="not built for this option set"):
        compose_scored(mechanism_question(4), plan, {})


# --- verification ---------------------------------------------------------


def test_the_scored_verifier_accepts_a_supported_choice():
    question = mechanism_question()
    plan = plan_scored_stages(question)
    scores = descending_scores(question)
    assert scored_verifier(scored_payload(question, scores, question.options[3])) is True


def test_the_scored_verifier_rejects_a_claim_outside_the_finalists():
    question = mechanism_question()
    scores = descending_scores(question)
    assert scored_verifier(scored_payload(question, scores, question.options[20])) is False
    assert scored_verifier(scored_payload(question, scores, "route.999")) is False


def test_the_scored_verifier_rejects_an_incomplete_score_vector():
    question = mechanism_question()
    scores = descending_scores(question)
    scores.pop(question.options[1])
    payload = scored_payload(question, scores, question.options[0])
    assert scored_verifier(payload) is False


def test_the_registry_abstains_when_the_scored_payload_is_malformed():
    registry = VerifierRegistry()
    register_decision_verifiers(registry)
    assert registry.is_registered(SCORED_VERIFIER_ID, SCORED_VERIFIER_VERSION)
    verdict = registry.verify(SCORED_VERIFIER_ID, SCORED_VERIFIER_VERSION, {"nope": 1})
    assert verdict.verdict is None
    assert verdict.detail_code == "verifier_error:ValueError"


def test_the_scored_verifier_round_trips_through_the_registry():
    question = mechanism_question()
    scores = descending_scores(question)
    payload = scored_payload(question, scores, question.options[2])
    registry = VerifierRegistry()
    register_decision_verifiers(registry)
    first = registry.verify(SCORED_VERIFIER_ID, SCORED_VERIFIER_VERSION, payload)
    second = registry.verify(SCORED_VERIFIER_ID, SCORED_VERIFIER_VERSION, payload)
    assert first.verdict is True
    assert first.input_hash == second.input_hash


# --- schema conformance ---------------------------------------------------


def test_the_schema_verifier_accepts_a_well_formed_response():
    stage = first_score_question()
    request = DecisionRequest("req-1", "state", (stage,))
    record = DecisionRecord(
        backend_id="fixture.decision",
        backend_version="1",
        request_hash=request.fingerprint(),
        answers={stage.name: noul_answer(0.8)},
    )
    assert schema_verifier(schema_payload(request, record)) is True


def test_the_schema_verifier_rejects_a_missing_or_extra_answer():
    stage = first_score_question()
    request = DecisionRequest("req-1", "state", (stage,))
    base = {
        "backend_id": "fixture.decision",
        "backend_version": "1",
        "request_hash": request.fingerprint(),
    }
    empty = DecisionRecord(answers={"other": noul_answer(0.5)}, **base)
    assert schema_verifier(schema_payload(request, empty)) is False
    both = DecisionRecord(
        answers={stage.name: noul_answer(0.5), "other": noul_answer(0.5)}, **base
    )
    assert schema_verifier(schema_payload(request, both)) is False


def test_the_schema_verifier_rejects_a_shape_that_breaks_the_contract():
    stage = first_score_question()
    request = DecisionRequest("req-1", "state", (stage,))
    base = {
        "backend_id": "fixture.decision",
        "backend_version": "1",
        "request_hash": request.fingerprint(),
    }
    out_of_range = DecisionRecord(
        answers={stage.name: noul_answer(1.5)}, **base
    )
    assert schema_verifier(schema_payload(request, out_of_range)) is False
    unnormalised = DecisionRecord(
        answers={
            stage.name: {
                "noul": 0.5,
                "probabilities": {"false": 0.1, "true": 0.1},
            }
        },
        **base,
    )
    assert schema_verifier(schema_payload(request, unnormalised)) is False


def test_the_schema_verifier_rejects_a_choice_outside_the_option_set():
    question = OptionSetQuestion("pick", "Pick one.", ("a", "b", "c"))
    choice = ReflexQuestion(
        "pick", ReflexKind.CHOICE, "Pick one.", criteria={o: o for o in question.options}
    )
    request = DecisionRequest("req-1", "state", (choice,))
    record = DecisionRecord(
        backend_id="fixture.decision",
        backend_version="1",
        request_hash=request.fingerprint(),
        answers={"pick": choice_answer(["a", "b", "c"], "d")},
    )
    assert schema_verifier(schema_payload(request, record)) is False


def test_the_registry_abstains_when_the_schema_payload_is_malformed():
    registry = VerifierRegistry()
    register_decision_verifiers(registry)
    assert registry.is_registered(SCHEMA_VERIFIER_ID, SCHEMA_VERIFIER_VERSION)
    verdict = registry.verify(SCHEMA_VERIFIER_ID, SCHEMA_VERIFIER_VERSION, {"nope": 1})
    assert verdict.verdict is None
    assert verdict.detail_code == "verifier_error:ValueError"


# --- identity -------------------------------------------------------------


def test_the_budget_belongs_to_the_request_identity():
    stage = first_score_question()
    plain = DecisionRequest("req-1", "state", (stage,))
    budgeted = DecisionRequest(
        "req-1", "state", (stage,), budget=DecisionBudget(250.0)
    )
    assert plain.fingerprint() != budgeted.fingerprint()
    assert plain.to_payload() == budgeted.to_payload()


def test_a_record_captured_without_a_budget_does_not_answer_a_budgeted_request():
    stage = first_score_question()
    plain = DecisionRequest("req-1", "state", (stage,))
    record = DecisionRecord(
        backend_id="fixture.decision",
        backend_version="1",
        request_hash=plain.fingerprint(),
        answers={stage.name: noul_answer(0.8)},
    )
    budgeted = DecisionRequest(
        "req-1", "state", (stage,), budget=DecisionBudget(250.0)
    )
    assert replay_decision(record, plain).performed is True
    assert replay_decision(record, budgeted).status == "request_mismatch"


# --- record files ---------------------------------------------------------


def test_a_record_round_trips_through_a_file(tmp_path):
    stage = first_score_question()
    request = DecisionRequest("req-1", "state", (stage,))
    record = DecisionRecord(
        backend_id="fixture.decision",
        backend_version="1",
        request_hash=request.fingerprint(),
        answers={stage.name: noul_answer(0.8)},
        captured_at_ms=1_000.0,
        usage={"latency_ms": 17.3, "n_retries": 0},
    )
    path = tmp_path / "record.json"
    write_decision_record(path, record)
    assert read_decision_record(path).to_dict() == record.to_dict()
    assert json.loads(path.read_text(encoding="utf-8"))["kind"] == "decision_record"


def test_writing_a_record_never_overwrites(tmp_path):
    stage = first_score_question()
    request = DecisionRequest("req-1", "state", (stage,))
    record = DecisionRecord(
        backend_id="fixture.decision",
        backend_version="1",
        request_hash=request.fingerprint(),
        answers={stage.name: noul_answer(0.8)},
    )
    path = tmp_path / "record.json"
    write_decision_record(path, record)
    with pytest.raises(FileExistsError):
        write_decision_record(path, record)


def test_reading_a_record_refuses_another_kind_or_duplicate_keys(tmp_path):
    other_kind = tmp_path / "other.json"
    other_kind.write_text(json.dumps({"kind": "observation", "record": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="kind must be"):
        read_decision_record(other_kind)
    duplicated = tmp_path / "duplicated.json"
    duplicated.write_text(
        '{"kind": "decision_record", "kind": "decision_record", "record": {}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate key"):
        read_decision_record(duplicated)
    not_json = tmp_path / "broken.json"
    not_json.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        read_decision_record(not_json)


# --- the route is a candidate, not an island ------------------------------


def build_registry(confidence=0.95):
    verifiers = VerifierRegistry()
    register_decision_verifiers(verifiers)
    register_audit_verifiers(verifiers)
    manifest = {
        "schema_version": 1,
        "registry_version": "parcimonia-1",
        "routes": [
            decision_route_entry(
                estimated_cost=0.02, estimated_latency_ms=20.0, confidence=confidence
            ),
            audit_route_entry(
                estimated_cost=0.01, estimated_latency_ms=5.0, confidence=0.99
            ),
        ],
    }
    return RouteRegistry.from_manifest(
        manifest,
        known_capabilities=[DECISION_CAPABILITY, AUDIT_CAPABILITY],
        verifiers=verifiers,
    )


def test_the_decision_route_loads_beside_the_static_audit_route():
    registry = build_registry()
    assert registry.route("route.decision.typed").capability_ids == (
        DECISION_CAPABILITY,
    )
    assert registry.verifier_for("route.decision.typed") == (
        DECISION_VERIFIER_ID,
        DECISION_VERIFIER_VERSION,
    )
    assert registry.policy_version("shadow-routing/1").endswith(
        "+registry:parcimonia-1"
    )


def test_the_router_selects_the_decision_route_when_its_capability_is_required():
    registry = build_registry()
    router = ShadowRouter(min_confidence=0.9, registry=registry)
    decision = router.propose(
        Task("task-1", "route-choice", {}), required_capabilities=[DECISION_CAPABILITY]
    )
    assert decision.selected_route_id == "route.decision.typed"
    assert decision.mode == "shadow"


def test_the_router_keeps_the_cheaper_route_when_no_capability_is_required():
    registry = build_registry()
    router = ShadowRouter(min_confidence=0.9, registry=registry)
    decision = router.propose(Task("task-1", "audit", {}))
    assert decision.selected_route_id == "route.audit.static"
