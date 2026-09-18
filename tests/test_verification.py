import pytest

from tiberium_ai.contracts import Verification
from tiberium_ai.verification import (
    attributed_evidence,
    exact_match_verifier,
    hash_input,
    shape_verifier,
    runner_result_verifier,
    validate_verification_record,
    VerifierRegistry,
)


def registry_with(verifier_id="shape", version="1", verifier=None):
    registry = VerifierRegistry()
    registry.register(
        verifier_id,
        version,
        verifier if verifier is not None else shape_verifier({"answer": "str"}),
    )
    return registry


def test_registered_verifier_returns_an_attributed_verdict():
    result = registry_with().verify("shape", "1", {"answer": "ok"})
    assert result.verifier_id == "shape"
    assert result.verifier_version == "1"
    assert result.verdict is True
    assert result.detail_code is None
    assert len(result.input_hash) == 64
    assert all(character in "0123456789abcdef" for character in result.input_hash)


def test_same_input_and_version_produce_the_same_verdict():
    registry = registry_with()
    value = {"answer": "ok", "extra": [1, 2, 3]}
    first = registry.verify("shape", "1", value)
    second = registry.verify("shape", "1", dict(reversed(list(value.items()))))
    assert first == second


def test_versions_of_the_same_verifier_coexist():
    registry = VerifierRegistry()
    registry.register("shape", "1", shape_verifier({"answer": "str"}))
    registry.register("shape", "2", shape_verifier({"answer": "str", "score": "float"}))
    value = {"answer": "ok"}
    assert registry.verify("shape", "1", value).verdict is True
    assert registry.verify("shape", "2", value).verdict is False


def test_unknown_identity_abstains_without_a_verdict():
    registry = registry_with()
    unknown_id = registry.verify("absent", "1", {"answer": "ok"})
    unknown_version = registry.verify("shape", "9", {"answer": "ok"})
    for result in (unknown_id, unknown_version):
        assert result.verdict is None
        assert result.detail_code == "unregistered_verifier"
        assert len(result.input_hash) == 64


def test_duplicate_registration_is_rejected():
    registry = registry_with()
    with pytest.raises(ValueError, match="already registered"):
        registry.register("shape", "1", shape_verifier({"answer": "str"}))


@pytest.mark.parametrize("verifier_id,version", [
    ("", "1"), (" padded ", "1"), (123, "1"), ("shape", ""), ("shape", " "), ("shape", 1),
])
def test_invalid_identity_is_rejected(verifier_id, version):
    registry = VerifierRegistry()
    with pytest.raises(ValueError):
        registry.register(verifier_id, version, shape_verifier({}))


def test_non_callable_verifier_is_rejected():
    with pytest.raises(TypeError):
        VerifierRegistry().register("shape", "1", "not-callable")


@pytest.mark.parametrize("returned", ["yes", 1, 0, None])
def test_verifier_must_return_a_boolean(returned):
    registry = registry_with(verifier=lambda value: returned)
    with pytest.raises(TypeError, match="boolean"):
        registry.verify("shape", "1", {"answer": "ok"})


def test_crashing_verifier_abstains_with_an_error_code():
    def crashing(value):
        raise ValueError("private detail")

    result = registry_with(verifier=crashing).verify("shape", "1", {"answer": "ok"})
    assert result.verdict is None
    assert result.detail_code == "verifier_error:ValueError"


def test_keyboard_interrupt_is_not_swallowed_by_the_registry():
    def interrupted(value):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        registry_with(verifier=interrupted).verify("shape", "1", {"answer": "ok"})


def test_hash_is_canonical_and_key_order_independent():
    assert hash_input({"b": 1, "a": 2}) == hash_input({"a": 2, "b": 1})
    assert hash_input({"a": 2}) != hash_input({"a": 3})
    assert hash_input("text") == hash_input("text")


@pytest.mark.parametrize("value", [object(), float("nan"), float("inf")])
def test_input_must_be_serialisable_and_finite(value):
    with pytest.raises(ValueError, match="input"):
        hash_input(value)


@pytest.mark.parametrize("value,expected", [
    ({"answer": "ok"}, True),
    ({"answer": "ok", "score": 0.5}, True),
    ({"answer": 1}, False),
    ({"answer": True}, False),
    ({}, False),
    (["answer"], False),
    ("answer", False),
])
def test_shape_verifier_checks_required_fields_and_types(value, expected):
    verifier = shape_verifier({"answer": "str"})
    assert verifier(value) is expected


@pytest.mark.parametrize("value,expected", [
    ({"count": 1}, True),
    ({"count": True}, False),
    ({"count": 1.5}, False),
    ({"count": "1"}, False),
])
def test_shape_verifier_distinguishes_booleans_from_integers(value, expected):
    verifier = shape_verifier({"count": "int"})
    assert verifier(value) is expected


def test_shape_verifier_rejects_unknown_type_names():
    with pytest.raises(ValueError, match="type"):
        shape_verifier({"answer": "string"})


@pytest.mark.parametrize("value,expected", [
    ({"a": [1, {"b": 2}]}, True),
    ({"a": [1, {"b": 3}]}, False),
    ({"a": 1}, False),
    (True, False),
])
def test_exact_match_compares_json_values(value, expected):
    verifier = exact_match_verifier({"a": [1, {"b": 2}]})
    assert verifier(value) is expected


def test_exact_match_distinguishes_boolean_from_number():
    assert exact_match_verifier(1)(True) is False
    assert exact_match_verifier(True)(1) is False


@pytest.mark.parametrize("value,expected", [
    ({"exit_code": 0}, True),
    ({"exit_code": 0, "failed": 0, "passed": 3}, True),
    ({"exit_code": 1}, False),
    ({"exit_code": 0, "failed": 3}, False),
    ({"exit_code": True}, False),
    ({"exit_code": "0"}, False),
    ("passed", False),
])
def test_test_result_verifier_requires_a_clean_run(value, expected):
    verifier = runner_result_verifier()
    assert verifier(value) is expected


def test_verification_record_round_trip():
    verification = registry_with().verify("shape", "1", {"answer": "ok"})
    record = verification.to_record()
    assert record == {
        "verifier_id": "shape",
        "verifier_version": "1",
        "verdict": True,
        "input_hash": verification.input_hash,
        "detail_code": None,
    }
    validate_verification_record(record)


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(verifier_id=""),
    lambda r: r.update(verifier_version=" padded "),
    lambda r: r.update(verdict="true"),
    lambda r: r.update(input_hash="short"),
    lambda r: r.update(input_hash="A" * 64),
    lambda r: r.update(detail_code=""),
    lambda r: r.update(detail_code=None),
    lambda r: r.update(extra="payload"),
    lambda r: r.pop("verdict"),
])
def test_invalid_verification_records_are_rejected(mutate):
    record = {
        "verifier_id": "shape",
        "verifier_version": "1",
        "verdict": None,
        "input_hash": "a" * 64,
        "detail_code": "unregistered_verifier",
    }
    mutate(record)
    with pytest.raises(ValueError):
        validate_verification_record(record)


def test_abstained_verification_requires_a_detail_code_record():
    verification = Verification(
        verifier_id="shape",
        verifier_version="1",
        verdict=None,
        input_hash="a" * 64,
        detail_code="unregistered_verifier",
    )
    validate_verification_record(verification.to_record())


def test_attributed_evidence_binds_the_verifier_run():
    verification = registry_with().verify("shape", "1", {"answer": "ok"})
    evidence = attributed_evidence(
        verification,
        task_id="task-1",
        route_id="rule",
        measured_latency_ms=12.5,
        measured_cost=0.01,
    )
    assert evidence.task_id == "task-1"
    assert evidence.route_id == "rule"
    assert evidence.verifier_ok is True
    assert evidence.verification == verification
    assert evidence.measured_latency_ms == 12.5
    assert evidence.measured_cost == 0.01


def test_attributed_evidence_marks_an_abstention_as_not_ok():
    verification = registry_with().verify("absent", "1", {"answer": "ok"})
    evidence = attributed_evidence(verification, task_id="task-1", route_id="rule")
    assert evidence.verification is verification
    assert evidence.verifier_ok is False
