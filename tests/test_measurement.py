import json
from datetime import datetime

import pytest

from tiberium_ai.measurement import (
    WALL_CLOCK_METHOD,
    Environment,
    read_measurement,
    run_baseline,
    write_measurement,
)


def environment(**overrides):
    values = {"machine_id": "odin-pc", "runtime_versions": {"python": "3.14.0"}}
    values.update(overrides)
    return Environment(**values)


def clock_from(*ticks):
    return iter(ticks).__next__


def fixed_now(value="2026-09-18T06:00:00+00:00"):
    return lambda: value


def successful_run(**overrides):
    arguments = dict(
        task_id="task-1",
        route_id="rule",
        run=lambda: "output",
        cost_unit="USD per 1k tasks",
        environment=environment(),
        clock=clock_from(10.0, 10.25),
        now=fixed_now(),
        cost=0.5,
    )
    arguments.update(overrides)
    return run_baseline(**arguments)


def test_successful_run_records_measured_provenance():
    result = successful_run()
    record = result.to_record()
    assert record["kind"] == "measurement"
    assert record["schema_version"] == 1
    assert record["data_origin"] == "measured"
    assert record["method"] == WALL_CLOCK_METHOD
    assert record["outcome"] == {"ok": True, "error_type": None}
    assert record["latency_ms"] == 250.0
    assert record["cost"] == 0.5
    assert record["cost_unit"] == "USD per 1k tasks"
    assert record["environment"] == {
        "machine_id": "odin-pc",
        "runtime_versions": {"python": "3.14.0"},
    }
    assert record["measured_at"] == "2026-09-18T06:00:00+00:00"


def test_failed_run_records_error_type_without_the_message():
    def failing():
        raise ValueError("PRIVATE_PAYLOAD")

    result = successful_run(run=failing, clock=clock_from(1.0, 1.5))
    record = result.to_record()
    assert record["outcome"] == {"ok": False, "error_type": "ValueError"}
    assert record["latency_ms"] == 500.0
    assert "PRIVATE" not in json.dumps(record)


def test_run_is_called_once_and_never_retried():
    calls = []

    def failing():
        calls.append(1)
        raise RuntimeError("boom")

    successful_run(run=failing)
    assert calls == [1]


def test_keyboard_interrupt_is_not_swallowed():
    def interrupted():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        successful_run(run=interrupted)


def test_backwards_clock_is_rejected():
    with pytest.raises(ValueError, match="clock"):
        successful_run(clock=clock_from(10.0, 9.0))


@pytest.mark.parametrize("overrides", [
    {"task_id": ""},
    {"task_id": " padded "},
    {"route_id": ""},
    {"route_id": " "},
    {"cost_unit": ""},
    {"run": None},
])
def test_invalid_inputs_are_rejected(overrides):
    with pytest.raises((TypeError, ValueError)):
        successful_run(**overrides)


@pytest.mark.parametrize("cost", [-1, float("nan"), float("inf"), True, "1"])
def test_cost_must_be_null_or_nonnegative_finite(cost):
    with pytest.raises(ValueError, match="cost"):
        successful_run(cost=cost)


def test_cost_is_optional():
    assert successful_run(cost=None).to_record()["cost"] is None


@pytest.mark.parametrize("overrides", [
    {"machine_id": ""},
    {"machine_id": " padded "},
    {"runtime_versions": {"python": ""}},
    {"runtime_versions": {"python": 3}},
    {"runtime_versions": "python"},
])
def test_environment_must_be_explicit_and_nonempty(overrides):
    with pytest.raises((TypeError, ValueError)):
        Environment(**{**{"machine_id": "odin-pc"}, **overrides})


@pytest.mark.parametrize("value", [
    "not-a-date",
    "2026-09-18T06:00:00",
    "",
])
def test_measured_at_must_carry_a_timezone(value):
    with pytest.raises(ValueError, match="measured_at"):
        successful_run(now=fixed_now(value))


def test_zulu_suffix_is_accepted_and_normalised_to_an_offset():
    record = successful_run(now=fixed_now("2026-09-18T06:00:00Z")).to_record()
    assert record["measured_at"] == "2026-09-18T06:00:00+00:00"


def test_default_timestamp_is_timezone_aware():
    record = run_baseline(
        task_id="task-1",
        route_id="rule",
        run=lambda: None,
        cost_unit="unit/task",
        environment=environment(),
        clock=clock_from(0.0, 0.0),
    ).to_record()
    parsed = datetime.fromisoformat(record["measured_at"])
    assert parsed.tzinfo is not None


def test_record_round_trip(tmp_path):
    record = successful_run().to_record()
    path = tmp_path / "run.json"
    write_measurement(path, record)
    assert read_measurement(path) == record


def test_write_is_non_destructive_and_requires_a_directory(tmp_path):
    record = successful_run().to_record()
    existing = tmp_path / "run.json"
    existing.write_text("keep-me", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_measurement(existing, record)
    assert existing.read_text(encoding="utf-8") == "keep-me"
    with pytest.raises(FileNotFoundError):
        write_measurement(tmp_path / "missing" / "run.json", record)


def test_invalid_record_is_rejected_before_creating_a_file(tmp_path):
    record = successful_run().to_record()
    record["latency_ms"] = -1
    path = tmp_path / "run.json"
    with pytest.raises(ValueError):
        write_measurement(path, record)
    assert not path.exists()


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(kind="observation"),
    lambda r: r.update(data_origin="synthetic"),
    lambda r: r.update(schema_version=2),
    lambda r: r.update(latency_ms=None),
    lambda r: r.update(outcome={"ok": True, "error_type": "ValueError"}),
    lambda r: r.update(outcome={"ok": False, "error_type": None}),
    lambda r: r.update(cost_unit=""),
    lambda r: r.update(measured_at="2026-09-18T06:00:00"),
    lambda r: r.update(extra="payload"),
    lambda r: r.pop("route_id"),
])
def test_incoherent_records_are_rejected_on_read(tmp_path, mutate):
    record = successful_run().to_record()
    mutate(record)
    path = tmp_path / "run.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError):
        read_measurement(path)


@pytest.mark.parametrize("invalid_json", [
    '{"schema_version": 1, "schema_version": 1}',
    '{"latency_ms": NaN}',
    "[1, 2]",
    "{broken",
])
def test_reader_rejects_ambiguous_or_malformed_json(tmp_path, invalid_json):
    path = tmp_path / "run.json"
    path.write_text(invalid_json, encoding="utf-8")
    with pytest.raises(ValueError):
        read_measurement(path)
