import json

import pytest

from tiberium_ai.decision_adapter import (
    DECIDED_SINGLE_STAGE,
    DECIDED_TWO_STAGE,
    DECISION_CAPABILITY,
    DECISION_VERIFIER_ID,
    DECISION_VERIFIER_VERSION,
    MAX_CHOICE_OPTIONS,
    SINGLE_STAGE_CHOICE_CAP,
    UNDETERMINED_INCOMPLETE,
    DecisionRecord,
    DecisionRequest,
    OptionSetQuestion,
    TwoStagePlan,
    capture_decision,
    compose_two_stage,
    decision_route_entry,
    plan_two_stage,
    register_decision_verifiers,
    replay_decision,
    stage_questions,
    two_stage_verifier,
)
from tiberium_ai.decision_clock import DecisionBudget, DecisionTiming
from tiberium_ai.verification import VerifierRegistry

BACKEND_ID = "fixture.decision"
BACKEND_VERSION = "1"


def option_question(count=28, name="mechanism"):
    return OptionSetQuestion(
        name=name,
        instructions="Which mechanism satisfies the task at the required level?",
        options=tuple(f"route.{index:03d}" for index in range(count)),
    )


def pick(name, keys):
    """Deterministic fixture choices: no model is called anywhere in this file."""
    if name.endswith(".stage2"):
        return "g1"
    if name.endswith(".stage1.g1"):
        return keys[-1]
    return keys[0]


def fixture_transport(usage=None):
    def transport(payload):
        answers = {}
        for question in payload["questions"]:
            keys = list(question["criteria"])
            chosen = pick(question["name"], keys)
            answers[question["name"]] = {
                "choice": chosen,
                "probabilities": {
                    key: (1.0 if key == chosen else 0.0) for key in keys
                },
                "confidence": 0.9,
            }
        response = {"answers": answers}
        if usage is not None:
            response["usage"] = usage
        return response

    return transport


def build(count=28, **request_kwargs):
    question = option_question(count)
    plan = plan_two_stage(question)
    request = DecisionRequest(
        "req-001",
        "which mechanism should handle this task",
        stage_questions(plan, question),
        **request_kwargs,
    )
    return question, plan, request


def captured(count=28, **kwargs):
    question, plan, request = build(count, **kwargs)
    capture = capture_decision(
        request,
        backend_id=BACKEND_ID,
        backend_version=BACKEND_VERSION,
        transport=fixture_transport(),
    )
    assert capture.performed is True
    assert capture.record is not None
    return question, plan, request, capture.record


# --- option sets and plans -------------------------------------------------


def test_an_option_set_needs_two_distinct_trimmed_options():
    with pytest.raises(ValueError, match="at least two"):
        OptionSetQuestion("q", "pick", ("only",))
    with pytest.raises(ValueError, match="must not repeat"):
        OptionSetQuestion("q", "pick", ("a", "a"))
    with pytest.raises(ValueError, match="capped at 255"):
        OptionSetQuestion("q", "pick", tuple(f"o{index}" for index in range(256)))


def test_criteria_cannot_describe_options_outside_the_set():
    with pytest.raises(ValueError, match="outside the set"):
        OptionSetQuestion("q", "pick", ("a", "b"), criteria={"c": "unknown"})
    with pytest.raises(ValueError, match="nonempty, trimmed description"):
        OptionSetQuestion("q", "pick", ("a", "b"), criteria={"a": "  "})


def test_a_single_call_covers_up_to_the_cap():
    plan = plan_two_stage(option_question(SINGLE_STAGE_CHOICE_CAP))
    assert plan.decomposed is False
    assert plan.stages == 1
    assert plan.groups == (option_question(SINGLE_STAGE_CHOICE_CAP).options,)


def test_a_remainder_never_produces_a_one_option_group():
    plan = plan_two_stage(option_question(21))
    assert [len(group) for group in plan.groups] == [11, 10]
    assert plan.decomposed is True


def test_the_widest_option_set_stays_within_both_caps():
    plan = plan_two_stage(option_question(MAX_CHOICE_OPTIONS))
    assert len(plan.groups) == 13
    assert all(2 <= len(group) <= SINGLE_STAGE_CHOICE_CAP for group in plan.groups)
    assert sum(len(group) for group in plan.groups) == MAX_CHOICE_OPTIONS
    assert len(plan.final_stage_options) <= SINGLE_STAGE_CHOICE_CAP


def test_groups_must_partition_the_options_exactly_once():
    question = option_question(4)
    with pytest.raises(ValueError, match="partition"):
        TwoStagePlan("mechanism", question.options, (("route.000", "route.001"),), 20)
    with pytest.raises(ValueError, match="at least two"):
        TwoStagePlan(
            "mechanism",
            question.options,
            (
                ("route.000", "route.001", "route.002"),
                ("route.003",),
            ),
            20,
        )


def test_a_stage_size_that_would_overflow_the_second_stage_is_refused():
    with pytest.raises(ValueError, match="second-stage candidates"):
        plan_two_stage(option_question(MAX_CHOICE_OPTIONS), max_stage_options=2)
    with pytest.raises(ValueError, match="max_stage_options"):
        plan_two_stage(option_question(28), max_stage_options=1)
    with pytest.raises(ValueError, match="max_stage_options"):
        plan_two_stage(option_question(28), max_stage_options=21)


def test_stage_questions_are_one_call_each_and_in_order():
    question, plan, _ = build()
    questions = stage_questions(plan, question)
    assert [q.name for q in questions] == list(plan.stage_question_names())
    assert [q.name for q in questions] == [
        "mechanism.stage1.g1",
        "mechanism.stage1.g2",
        "mechanism.stage2",
    ]
    for question_ in questions:
        assert len(question_.criteria) <= SINGLE_STAGE_CHOICE_CAP


def test_a_single_stage_question_keeps_the_declared_name():
    question = option_question(SINGLE_STAGE_CHOICE_CAP)
    plan = plan_two_stage(question)
    questions = stage_questions(plan, question)
    assert [q.name for q in questions] == [question.name]


def test_a_plan_from_another_option_set_is_refused():
    question, plan, _ = build()
    other = option_question(28, name="other")
    with pytest.raises(ValueError, match="not built for this option set"):
        compose_two_stage(other, plan, {})
    with pytest.raises(ValueError, match="not built for this option set"):
        stage_questions(plan, other)


# --- composition ----------------------------------------------------------


def test_a_single_stage_decision_is_taken_as_declared():
    question = option_question(SINGLE_STAGE_CHOICE_CAP)
    plan = plan_two_stage(question)
    decision = compose_two_stage(question, plan, {question.name: question.options[3]})
    assert decision.determined is True
    assert decision.winner == question.options[3]
    assert decision.reason_code == DECIDED_SINGLE_STAGE


def test_the_winner_comes_from_the_group_the_second_stage_selected():
    question, plan, _, record = captured()
    choices = {
        name: answer["choice"] for name, answer in record.answers.items()
    }
    decision = compose_two_stage(question, plan, choices)
    assert decision.determined is True
    assert decision.reason_code == DECIDED_TWO_STAGE
    assert decision.final_choice == "g1"
    assert decision.winner == plan.groups[0][-1]
    assert decision.winner != plan.groups[0][0]


def test_a_missing_group_answer_abstains_instead_of_defaulting():
    question, plan, _, record = captured()
    answers = dict(record.answers)
    answers.pop("mechanism.stage1.g2")
    choices = {name: answer["choice"] for name, answer in answers.items()}
    decision = compose_two_stage(question, plan, choices)
    assert decision.determined is False
    assert decision.winner is None
    assert decision.reason_code == UNDETERMINED_INCOMPLETE


def test_a_missing_final_answer_abstains_and_keeps_the_group_choices():
    question, plan, _, record = captured()
    answers = dict(record.answers)
    answers.pop("mechanism.stage2")
    choices = {name: answer["choice"] for name, answer in answers.items()}
    decision = compose_two_stage(question, plan, choices)
    assert decision.determined is False
    assert set(decision.group_choices) == {"g1", "g2"}


def test_an_answer_outside_the_declared_group_raises():
    question, plan, _, record = captured()
    choices = {name: answer["choice"] for name, answer in record.answers.items()}
    choices["mechanism.stage1.g1"] = "route.999"
    with pytest.raises(ValueError, match="not in group g1"):
        compose_two_stage(question, plan, choices)


def test_a_final_answer_outside_the_group_ids_raises():
    question, plan, _, record = captured()
    choices = {name: answer["choice"] for name, answer in record.answers.items()}
    choices["mechanism.stage2"] = "route.000"
    with pytest.raises(ValueError, match="final answer"):
        compose_two_stage(question, plan, choices)


# --- verification ---------------------------------------------------------


def test_the_verifier_accepts_a_recomputed_claim():
    question, plan, _, record = captured()
    choices = {name: answer["choice"] for name, answer in record.answers.items()}
    decision = compose_two_stage(question, plan, choices)
    payload = {
        "question": question.to_record(),
        "max_stage_options": SINGLE_STAGE_CHOICE_CAP,
        "choices": choices,
        "claimed_winner": decision.winner,
    }
    assert two_stage_verifier(payload) is True


def test_the_verifier_rejects_a_tampered_claim():
    question, plan, _, record = captured()
    choices = {name: answer["choice"] for name, answer in record.answers.items()}
    payload = {
        "question": question.to_record(),
        "max_stage_options": SINGLE_STAGE_CHOICE_CAP,
        "choices": choices,
        "claimed_winner": plan.groups[0][0],
    }
    assert two_stage_verifier(payload) is False


def test_the_verifier_rejects_an_inconsistent_claim_instead_of_abstaining():
    question, plan, _, record = captured()
    choices = {name: answer["choice"] for name, answer in record.answers.items()}
    choices["mechanism.stage1.g1"] = "route.999"
    payload = {
        "question": question.to_record(),
        "max_stage_options": SINGLE_STAGE_CHOICE_CAP,
        "choices": choices,
        "claimed_winner": plan.groups[0][-1],
    }
    # The payload is well formed, so this is a rejection rather than an
    # abstention, which the registry must report as a rejected verdict.
    assert two_stage_verifier(payload) is False
    registry = VerifierRegistry()
    register_decision_verifiers(registry)
    verdict = registry.verify(DECISION_VERIFIER_ID, DECISION_VERIFIER_VERSION, payload)
    assert verdict.verdict is False
    assert verdict.detail_code is None


def test_an_undetermined_decision_is_never_verified():
    question, plan, _, record = captured()
    choices = {name: answer["choice"] for name, answer in record.answers.items()}
    choices.pop("mechanism.stage2")
    payload = {
        "question": question.to_record(),
        "max_stage_options": SINGLE_STAGE_CHOICE_CAP,
        "choices": choices,
        "claimed_winner": plan.groups[0][-1],
    }
    assert two_stage_verifier(payload) is False


def test_the_registry_abstains_on_a_malformed_claim():
    registry = VerifierRegistry()
    register_decision_verifiers(registry)
    assert registry.is_registered(DECISION_VERIFIER_ID, DECISION_VERIFIER_VERSION)
    verdict = registry.verify(DECISION_VERIFIER_ID, DECISION_VERIFIER_VERSION, {"nope": 1})
    assert verdict.verdict is None
    assert verdict.detail_code == "verifier_error:ValueError"


def test_the_registry_accepts_a_recomputed_claim():
    question, plan, _, record = captured()
    choices = {name: answer["choice"] for name, answer in record.answers.items()}
    decision = compose_two_stage(question, plan, choices)
    registry = VerifierRegistry()
    register_decision_verifiers(registry)
    payload = {
        "question": question.to_record(),
        "max_stage_options": SINGLE_STAGE_CHOICE_CAP,
        "choices": choices,
        "claimed_winner": decision.winner,
    }
    verdict = registry.verify(DECISION_VERIFIER_ID, DECISION_VERIFIER_VERSION, payload)
    assert verdict.verdict is True
    assert verdict.input_hash == registry.verify(
        DECISION_VERIFIER_ID, DECISION_VERIFIER_VERSION, payload
    ).input_hash


def test_registering_requires_a_registry():
    with pytest.raises(TypeError, match="VerifierRegistry"):
        register_decision_verifiers(object())


# --- requests, records and replay ----------------------------------------


def test_the_request_payload_is_serialisable_and_stable():
    _, _, request = build()
    payload = request.to_payload()
    assert json.dumps(payload, sort_keys=True, allow_nan=False)
    assert request.fingerprint() == request.fingerprint()
    assert len(request.fingerprint()) == 64
    assert payload["schema_version"] == 1
    assert payload["backend"] is None


def test_a_pinned_backend_needs_a_version():
    with pytest.raises(ValueError, match="not provenance"):
        build(backend_id="fixture.decision")
    _, _, request = build(backend_id=BACKEND_ID, backend_version=BACKEND_VERSION)
    assert request.to_payload()["backend"] == {
        "backend_id": BACKEND_ID,
        "backend_version": BACKEND_VERSION,
    }


def test_question_names_must_be_unique_in_a_request():
    question = option_question(SINGLE_STAGE_CHOICE_CAP)
    plan = plan_two_stage(question)
    stage = stage_questions(plan, question)[0]
    with pytest.raises(ValueError, match="unique"):
        DecisionRequest("req-001", "state", (stage, stage))


def test_a_record_round_trips_and_rejects_an_unknown_field():
    _, _, _, record = captured()
    payload = record.to_dict()
    assert DecisionRecord.from_dict(payload).to_dict() == payload
    payload["extra"] = 1
    with pytest.raises(ValueError, match="exactly"):
        DecisionRecord.from_dict(payload)


def test_a_record_refuses_a_placeholder_hash_and_an_unknown_origin():
    _, _, request, record = captured()
    payload = record.to_dict()
    payload["request_hash"] = "not-a-hash"
    with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
        DecisionRecord.from_dict(payload)
    payload = record.to_dict()
    payload["data_origin"] = "invented"
    with pytest.raises(ValueError, match="data_origin"):
        DecisionRecord.from_dict(payload)
    assert request.fingerprint() == record.request_hash


def test_capture_refuses_an_unsupported_usage_field():
    _, _, request = build()
    capture = capture_decision(
        request,
        backend_id=BACKEND_ID,
        backend_version=BACKEND_VERSION,
        transport=lambda _payload: {
            "answers": {"mechanism.stage1.g1": {"choice": "route.000"}},
            "usage": {"cost_usd": 0.1},
        },
    )
    assert capture.status == "error"
    assert capture.detail_code == "invalid_response"
    with pytest.raises(ValueError, match="unsupported field"):
        DecisionRecord(
            backend_id=BACKEND_ID,
            backend_version=BACKEND_VERSION,
            request_hash=request.fingerprint(),
            answers={"mechanism.stage1.g1": {"choice": "route.000"}},
            usage={"cost_usd": 0.1},
        )


def test_replay_refuses_a_record_for_another_request():
    _, _, _, record = captured()
    _, _, other = build(count=21)
    replay = replay_decision(record, other)
    assert replay.status == "request_mismatch"
    assert replay.detail_code == "request_hash_mismatch"
    assert replay.performed is False


def test_replay_refuses_a_backend_version_the_request_pinned_otherwise():
    _, _, request, record = captured()
    pinned = DecisionRequest(
        request.request_id,
        request.state,
        request.questions,
        state_age_ms=request.state_age_ms,
        backend_id=BACKEND_ID,
        backend_version="2",
    )
    # The pin is part of the request, so a record claiming this request hash
    # while carrying another backend version is a contradiction, not a match.
    payload = record.to_dict()
    payload["request_hash"] = pinned.fingerprint()
    replay = replay_decision(DecisionRecord.from_dict(payload), pinned)
    assert replay.status == "backend_mismatch"
    assert replay.detail_code == "backend_version_mismatch"


def test_replay_reports_an_incomplete_record():
    _, _, request, record = captured()
    answers = dict(record.answers)
    answers.pop("mechanism.stage2")
    payload = record.to_dict()
    payload["answers"] = answers
    replay = replay_decision(DecisionRecord.from_dict(payload), request)
    assert replay.status == "incomplete"
    assert replay.detail_code == "missing_answer"


def test_replay_carries_a_timing_verdict_only_with_a_declared_budget():
    _, _, request, record = captured()
    plain = replay_decision(record, request)
    assert plain.performed is True
    assert plain.timing is None
    assert plain.usable is True
    with pytest.raises(ValueError, match="declared budget"):
        replay_decision(record, request, timing=DecisionTiming(elapsed_ms=10.0))


def test_a_decision_that_missed_its_deadline_is_not_usable():
    question = option_question(28)
    plan = plan_two_stage(question)
    budget = DecisionBudget(
        250.0, max_state_age_ms=1000.0, fallback_route_id="route.rule"
    )
    timed = DecisionRequest(
        "req-002",
        "state",
        stage_questions(plan, question),
        state_age_ms=1.0,
        budget=budget,
    )
    capture = capture_decision(
        timed,
        backend_id=BACKEND_ID,
        backend_version=BACKEND_VERSION,
        transport=fixture_transport(),
    )
    assert capture.performed is True
    assert capture.record is not None
    record = capture.record
    clean = replay_decision(
        record, timed, timing=DecisionTiming(elapsed_ms=10.0, state_age_ms=5.0)
    )
    assert clean.performed is True
    assert clean.usable is True
    late = replay_decision(
        record, timed, timing=DecisionTiming(elapsed_ms=260.0, state_age_ms=5.0)
    )
    assert late.performed is True
    assert late.usable is False
    assert late.timing.status.value == "deadline_missed"
    assert late.timing.fallback_route_id == "route.rule"
    stale = replay_decision(
        record, timed, timing=DecisionTiming(elapsed_ms=1.0, state_age_ms=5000.0)
    )
    assert stale.performed is True
    assert stale.usable is False
    assert stale.timing.status.value == "state_stale"


def test_a_budgeted_record_can_be_hash_checked_only_against_its_own_request():
    _, _, request, record = captured()
    timed = DecisionRequest(
        request.request_id,
        request.state,
        request.questions,
        state_age_ms=request.state_age_ms,
        budget=DecisionBudget(250.0),
    )
    # Only the budget differs here: it belongs to the request identity because a
    # decision taken under another deadline is a different commitment.
    assert replay_decision(record, timed).status == "request_mismatch"


# --- capture --------------------------------------------------------------


def test_capture_without_a_transport_is_typed_unavailable():
    _, _, request = build()
    capture = capture_decision(
        request, backend_id=BACKEND_ID, backend_version=BACKEND_VERSION
    )
    assert capture.status == "unavailable"
    assert capture.detail_code == "no_transport_configured"
    assert capture.record is None
    assert capture.usable is False


def test_capture_reports_an_unavailable_transport():
    _, _, request = build()

    def transport(_payload):
        raise OSError("no route to host")

    capture = capture_decision(
        request,
        backend_id=BACKEND_ID,
        backend_version=BACKEND_VERSION,
        transport=transport,
    )
    assert capture.status == "unavailable"
    assert capture.detail_code == "transport_unavailable"


def test_capture_reports_a_transport_error_and_an_invalid_response():
    _, _, request = build()

    def boom(_payload):
        raise RuntimeError("boom")

    capture = capture_decision(
        request,
        backend_id=BACKEND_ID,
        backend_version=BACKEND_VERSION,
        transport=boom,
    )
    assert capture.status == "error"
    assert capture.detail_code == "transport_error:RuntimeError"

    capture = capture_decision(
        request,
        backend_id=BACKEND_ID,
        backend_version=BACKEND_VERSION,
        transport=lambda _payload: {"unexpected": True},
    )
    assert capture.status == "error"
    assert capture.detail_code == "invalid_response"


def test_capture_records_the_usage_and_replays_it():
    _, _, request = build()
    usage = {
        "input_tokens_total": 0,
        "output_tokens_total": 0,
        "n_retries": 0,
        "latency_ms": 41.5,
    }
    capture = capture_decision(
        request,
        backend_id=BACKEND_ID,
        backend_version=BACKEND_VERSION,
        transport=fixture_transport(usage),
        captured_at_ms=1_000.0,
    )
    assert capture.performed is True
    assert capture.record is not None
    assert capture.record.data_origin == "recorded"
    assert capture.record.captured_at_ms == 1_000.0
    assert capture.record.usage is not None
    assert capture.record.usage["latency_ms"] == 41.5
    assert capture.replay is not None
    assert capture.replay.performed is True


def test_capture_refuses_a_backend_the_request_pinned_otherwise():
    _, _, request = build(backend_id=BACKEND_ID, backend_version=BACKEND_VERSION)
    with pytest.raises(ValueError, match="pins backend"):
        capture_decision(
            request,
            backend_id="other.backend",
            backend_version=BACKEND_VERSION,
            transport=fixture_transport(),
        )
    with pytest.raises(ValueError, match="pins backend version"):
        capture_decision(
            request,
            backend_id=BACKEND_ID,
            backend_version="9",
            transport=fixture_transport(),
        )


# --- route entry ----------------------------------------------------------


def test_the_route_entry_carries_no_invented_cost():
    entry = decision_route_entry(estimated_cost=None, estimated_latency_ms=None)
    assert entry["capability_ids"] == [DECISION_CAPABILITY]
    assert entry["estimated_cost"] is None
    assert entry["confidence"] is None
    assert entry["verifier"] == {
        "verifier_id": DECISION_VERIFIER_ID,
        "verifier_version": DECISION_VERIFIER_VERSION,
    }
    with pytest.raises(TypeError):
        decision_route_entry()
