"""Pure receipt checks; fixture reports do not attest a host or an exclusive lock."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from tiberium_ai.execution_profiles import digest
from tiberium_ai.host_memory_receipt import (
    build_host_memory_expectation, review_host_memory_snapshot,
)
from tiberium_ai.runtime_preflight import review_runtime_preflight

from test_runtime_preflight import fixtures


NOW = 1000


def expectation(**changes):
    task, route_id, arguments = fixtures()
    report = review_runtime_preflight(task, route_id, **arguments)
    kwargs = {"expected_preflight_sha256": report["preflight_sha256"],
              "consumer_id": "private-consumer", "provider_id": "botte-host-memory",
              "provider_revision": "pr166-fixture", "scope_id": "private-shared-state",
              "reservation_key": "private/native/key", "max_age_seconds": 2}
    kwargs.update(changes)
    return build_host_memory_expectation(report, arguments["candidate"],
                                         arguments["compute_request"], **kwargs)


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def snapshot(value, **changes):
    budget = value["requested_bytes"]
    result = {"allowed": True, "reason": "admitted", "total_bytes": 16 * 1024 ** 3,
              "available_bytes": 8 * 1024 ** 3, "commit_available_bytes": None,
              "reserved_bytes": budget, "reservation_count": 1,
              "system_reserve_bytes": 2 * 1024 ** 3,
              "measured_at_utc": stamp(NOW), "source": "linux",
              "reservations": [{"key": value["reservation_key"], "requested_bytes": budget}]}
    result.update(changes)
    return result


def review(value, observed, **changes):
    kwargs = {"expected_expectation_sha256": value["expectation_sha256"],
              "observed_at": NOW, "now": NOW}
    kwargs.update(changes)
    return review_host_memory_snapshot(value, observed, **kwargs)


def rehash(record, key):
    record[key] = digest({name: value for name, value in record.items() if name != key})


def test_exact_current_native_budget_is_consistent_but_never_authorizes():
    value = expectation()
    observed = snapshot(value)
    original = deepcopy((value, observed))
    result = review(value, observed)
    assert result["status"] == "consistent_host_memory_snapshot"
    assert result["next_step"] == "host_revalidation_required"
    assert result["memory_budget_bytes"] == value["requested_bytes"]
    assert result["binding_provenance"] == "host_binding_not_provider_observed"
    assert result["native_task_consumer_host_identity"] == "not_observed"
    assert result["reservation_expiry"] == "not_provided_by_provider"
    assert result["fencing"] == "not_provided_by_provider"
    assert result["reservation_exclusivity"] == "not_established"
    assert all(result[name] is False for name in (
        "auto_act_allowed", "reservation_performed", "execution_performed"))
    assert (value, observed) == original
    assert json.loads(json.dumps(result)) == result


def test_budget_explicitly_uses_larger_commit_requirement():
    task, route_id, arguments = fixtures()
    arguments["candidate"]["commit_bytes"] *= 2
    preflight = review_runtime_preflight(task, route_id, **arguments)
    value = build_host_memory_expectation(preflight, arguments["candidate"],
        arguments["compute_request"], expected_preflight_sha256=preflight["preflight_sha256"],
        consumer_id="consumer", provider_id="provider", provider_revision="revision",
        scope_id="scope", reservation_key="key")
    assert value["requested_bytes"] == arguments["candidate"]["commit_bytes"]
    assert value["budget_method"] == "max_ram_commit"


@pytest.mark.parametrize("field", ["consumer_id", "provider_id", "provider_revision", "scope_id",
                                  "reservation_key", "task_id", "task_revision", "host_id",
                                  "route_id", "requested_bytes"])
def test_rehashed_expectation_changes_cannot_replace_external_anchor(field):
    value = expectation()
    original_anchor = value["expectation_sha256"]
    value[field] = value[field] + 1 if isinstance(value[field], int) else "changed"
    rehash(value, "expectation_sha256")
    with pytest.raises(ValueError, match="anchor"):
        review(value, snapshot(value), expected_expectation_sha256=original_anchor)


def test_rehashed_preflight_cannot_replace_external_preflight_anchor():
    task, route_id, arguments = fixtures()
    report = review_runtime_preflight(task, route_id, **arguments)
    anchor = report["preflight_sha256"]
    report["host_id"] = "another-host"
    rehash(report, "preflight_sha256")
    with pytest.raises(ValueError, match="anchor"):
        build_host_memory_expectation(report, arguments["candidate"], arguments["compute_request"],
            expected_preflight_sha256=anchor, consumer_id="consumer", provider_id="provider",
            provider_revision="revision", scope_id="scope", reservation_key="key")


@pytest.mark.parametrize("change", ["candidate", "request", "diagnostic", "schema", "zero_budget",
                                   "context", "context_hash", "diagnostic_schema", "nested_auto_act",
                                   "oversized_collection"])
def test_expectation_refuses_changed_inputs_or_contradictory_preflight(change):
    task, route_id, arguments = fixtures()
    if change == "zero_budget":
        arguments["candidate"].update(ram_bytes=0, commit_bytes=0)
    report = review_runtime_preflight(task, route_id, **arguments)
    if change == "candidate":
        arguments["candidate"]["ram_bytes"] += 1
    elif change == "request":
        arguments["compute_request"]["workload_sha256"] = "c" * 64
    elif change == "diagnostic":
        report["compute_advice"]["selected"] = "other-route"
        rehash(report, "preflight_sha256")
    elif change == "schema":
        report["schema"] = "unrelated/v1"
        rehash(report, "preflight_sha256")
    elif change == "context":
        report["runtime_requirements"]["context"]["host_id"] = "another-host"
        changed_hash = digest(report["runtime_requirements"]["context"])
        report["runtime_requirements"]["context_sha256"] = changed_hash
        report["context_sha256"] = changed_hash
        rehash(report, "preflight_sha256")
    elif change == "context_hash":
        report["context_sha256"] = "d" * 64
        rehash(report, "preflight_sha256")
    elif change == "diagnostic_schema":
        report["compute_advice"]["schema"] = "unrelated/v1"
        rehash(report, "preflight_sha256")
    elif change == "nested_auto_act":
        report["profile_assessment"]["assessment"]["auto_act_allowed"] = True
        rehash(report, "preflight_sha256")
    elif change == "oversized_collection":
        report["runtime_requirements"]["requirements"] = [None] * 257
        rehash(report, "preflight_sha256")
    with pytest.raises(ValueError):
        build_host_memory_expectation(report, arguments["candidate"], arguments["compute_request"],
            expected_preflight_sha256=report["preflight_sha256"], consumer_id="consumer",
            provider_id="provider", provider_revision="revision", scope_id="scope", reservation_key="key")


@pytest.mark.parametrize("field,value,reason", [
    ("observed_at", NOW + 1, "snapshot_observation_future"),
    ("observed_at", NOW - 3, "snapshot_observation_stale"),
    ("now", NOW + 3, "preflight_stale"),
])
def test_stale_or_future_observation_and_old_preflight_are_blocked(field, value, reason):
    expected = expectation()
    result = review(expected, snapshot(expected), **{field: value})
    assert result["status"] == "blocked"
    assert reason in result["reasons"]


@pytest.mark.parametrize("when,reason", [(NOW - 3, "memory_measurement_stale"),
                                        (NOW + 1, "memory_measurement_future")])
def test_native_measurement_time_is_checked_separately(when, reason):
    value = expectation()
    result = review(value, snapshot(value, measured_at_utc=stamp(when)))
    assert result["status"] == "blocked"
    assert reason in result["reasons"]


@pytest.mark.parametrize("measured,observed,reasons", [
    (NOW - 1, NOW, {"memory_measurement_before_preflight"}),
    (NOW, NOW - 1, {"snapshot_observation_before_preflight", "memory_measurement_after_observation"}),
    (NOW - 1, NOW - 1, {"memory_measurement_before_preflight", "snapshot_observation_before_preflight"}),
])
def test_fresh_native_read_cannot_precede_anchored_preflight(measured, observed, reasons):
    value = expectation()
    result = review(value, snapshot(value, measured_at_utc=stamp(measured)), observed_at=observed)
    assert result["status"] == "blocked"
    assert reasons <= set(result["reasons"])


@pytest.mark.parametrize("observed,now", [(NOW, NOW), (NOW + 0.5, NOW + 1)])
def test_preflight_measurement_observation_order_accepts_equal_boundary(observed, now):
    value = expectation()
    result = review(value, snapshot(value, measured_at_utc=stamp(NOW)), observed_at=observed, now=now)
    assert result["status"] == "consistent_host_memory_snapshot"
    assert result["reasons"] == []


@pytest.mark.parametrize("native_stamp", [
    "1970-01-01T00:16:40.0000001+00:00",
    "1970-01-01T00:16:40.0000009Z",
    "1970-01-01T00:16:40.000000001+00:00",
    "1970-01-01T00:16:40.0000000+00:00",
])
def test_native_precision_beyond_microseconds_is_refused_without_rounding(native_stamp):
    value = expectation(max_age_seconds=0)
    with pytest.raises(ValueError):
        review(value, snapshot(value, measured_at_utc=native_stamp))


@pytest.mark.parametrize("suffix", ["+00:00", "Z"])
def test_native_microsecond_precision_preserves_equal_time(suffix):
    value = expectation(max_age_seconds=0)
    result = review(value, snapshot(value, measured_at_utc="1970-01-01T00:16:40.000000" + suffix))
    assert result["status"] == "consistent_host_memory_snapshot"


def test_age_boundaries_and_large_mixed_float_dates_are_exact():
    value = expectation()
    assert review(value, snapshot(value), now=NOW + 2)["status"] == "consistent_host_memory_snapshot"
    assert review(value, snapshot(value), now=NOW + 2.01)["status"] == "blocked"
    value = expectation(max_age_seconds=0)
    value["preflight_reviewed_at"] = 253402300799
    rehash(value, "expectation_sha256")
    result = review(value, snapshot(value, measured_at_utc="9999-12-31T23:59:58.999999+00:00"),
                    observed_at=float(253402300799), now=float(253402300799))
    assert result["status"] == "blocked"
    assert "memory_measurement_stale" in result["reasons"]


def test_missing_released_or_different_native_budget_never_becomes_success():
    value = expectation()
    empty = snapshot(value, reservations=[], reserved_bytes=0, reservation_count=0)
    assert review(value, empty)["reasons"] == ["reservation_missing"]
    wrong = snapshot(value)
    wrong["reservations"][0]["requested_bytes"] += 1
    wrong["reserved_bytes"] += 1
    assert "reservation_budget_mismatch" in review(value, wrong)["reasons"]


@pytest.mark.parametrize("case", ["count", "sum", "duplicate", "bad_margin", "bad_allowed",
                                 "bad_reason", "bool_bytes", "negative", "bad_source",
                                 "windows_commit", "non_utc", "unknown_fields"])
def test_native_aggregate_and_metric_corruption_is_refused(case):
    value = expectation()
    observed = snapshot(value)
    if case == "count": observed["reservation_count"] += 1
    elif case == "sum": observed["reserved_bytes"] += 1
    elif case == "duplicate": observed["reservations"] *= 2
    elif case == "bad_margin": observed["system_reserve_bytes"] = 1
    elif case == "bad_allowed": observed["allowed"] = False
    elif case == "bad_reason": observed["reason"] = "insufficient_ram"
    elif case == "bool_bytes": observed["available_bytes"] = True
    elif case == "negative": observed["reserved_bytes"] = -1
    elif case == "bad_source": observed["source"] = "unknown"
    elif case == "windows_commit": observed["source"] = "windows"
    elif case == "non_utc": observed["measured_at_utc"] = "1970-01-01T00:16:40+01:00"
    else: observed["owner"] = "invented-native-owner"
    with pytest.raises(ValueError):
        review(value, observed)


@pytest.mark.parametrize("source", ["linux", "windows"])
def test_actual_capacity_reason_is_recomputed(source):
    value = expectation()
    observed = snapshot(value, source=source, commit_available_bytes=0 if source == "windows" else None)
    if source == "linux":
        observed.update(available_bytes=0, allowed=False, reason="insufficient_ram")
    else:
        observed.update(allowed=False, reason="insufficient_commit")
    result = review(value, observed)
    assert result["status"] == "blocked"
    assert observed["reason"] in result["reasons"]


@pytest.mark.parametrize("with_rows", [False, True])
def test_unavailable_state_is_unknown_without_claiming_absence_or_release(with_rows):
    value = expectation()
    observed = {"allowed": False, "reason": "resource_state_unavailable"}
    if with_rows:
        observed["reservations"] = [{"key": "another-private-job", "requested_bytes": 123}]
    result = review(value, observed)
    assert result["status"] == "unknown"
    assert result["metrics"] is None
    assert result["reasons"] == ["resource_state_unavailable"]
    assert result["next_step"] == "reconcile"


def test_final_report_never_contains_native_keys_other_jobs_or_private_labels():
    value = expectation()
    observed = snapshot(value)
    observed["reservations"].append({"key": "another-private-job", "requested_bytes": 123})
    observed["reservation_count"] += 1
    observed["reserved_bytes"] += 123
    report = review(value, observed)
    text = json.dumps(report)
    for private in ("private/native/key", "another-private-job", "private-consumer",
                    "private-shared-state", "fixture-host", "task-1", "pr166-fixture"):
        assert private not in text
    assert "reservations" not in report
    assert report["status"] == "consistent_host_memory_snapshot"


def test_collection_and_message_bounds_and_strict_numeric_fields():
    value = expectation()
    observed = snapshot(value)
    observed["reservations"] = [{"key": str(i), "requested_bytes": 1} for i in range(257)]
    with pytest.raises(ValueError): review(value, observed)
    with pytest.raises(ValueError): review(value, snapshot(value), observed_at=True)
    with pytest.raises(ValueError): review(value, snapshot(value), now=float("nan"))
    with pytest.raises(ValueError): expectation(max_age_seconds=True)
    with pytest.raises(ValueError): expectation(consumer_id="x" * 129)
    with pytest.raises(ValueError): expectation(reservation_key="x" * 4097)
    with pytest.raises(ValueError): review(value, {"allowed": False, "reason": "x" * (1024 ** 2)})
