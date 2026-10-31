"""Resource, proof and cold-start regressions for advisory local routing."""
import copy
import pytest

from tiberium_ai.local_compute import advise, GIB


def inputs():
    snapshot = {"observed_at": 1000, "hardware_key": "a" * 64,
                "ram_available_bytes": 32 * GIB, "commit_available_bytes": 40 * GIB,
                "disk_free_bytes": 100 * GIB, "gpu_free_bytes": [8 * GIB, 8 * GIB], "heavy_busy": False}
    evidence = {"workload_sha256": "b" * 64, "hardware_key": "a" * 64,
                "recorded_at": 990, "samples": 3, "passed": 3,
                "verifier_revision": "exact/v1", "p50_ms": 2, "p95_ms": 4,
                "cold_start_ms": 100, "warm_start_ms": 1, "cloud_cost_usd": 0}
    route = {"id": "cpu", "task": "json_minify", "device": "cpu", "availability": "ready",
             "warm": True, "heavy": False, "ram_bytes": GIB, "commit_bytes": GIB,
             "disk_bytes": 0, "vram_bytes": 0, "measurement": evidence}
    return {"task": "json_minify", "workload_sha256": "b" * 64}, snapshot, route


def test_proposal_never_authorizes_and_preserves_unknown_energy():
    request, snapshot, route = inputs()
    result = advise(request, snapshot, [route], now=1000)
    assert result["selected"] == "cpu"
    assert result["qualified"][0]["estimated_completion_p95_ms"] == 5
    assert result["auto_act_allowed"] is False
    assert result["electricity_cost"] is None
    assert result["end_to_end_speedup"] is None


def test_cold_start_changes_ranking():
    request, snapshot, route = inputs()
    slower = copy.deepcopy(route)
    slower["id"] = "fast_kernel_cold"
    slower["warm"] = False
    slower["measurement"]["p95_ms"] = 2
    assert advise(request, snapshot, [slower, route], now=1000)["selected"] == "cpu"


@pytest.mark.parametrize("field,value,reason", [
    ("observed_at", 939, "resources_stale_or_future"),
    ("observed_at", 1001, "resources_stale_or_future"),
    ("ram_available_bytes", None, "ram_available_bytes_unknown"),
    ("ram_available_bytes", 5 * GIB, "ram_available_bytes_insufficient"),
    ("commit_available_bytes", 6 * GIB, "commit_available_bytes_insufficient"),
    ("disk_free_bytes", 15 * GIB - 1, "disk_free_bytes_insufficient"),
])
def test_capacity_rejections(field, value, reason):
    request, snapshot, route = inputs()
    snapshot[field] = value
    result = advise(request, snapshot, [route], now=1000)
    assert result["status"] == "abstain"
    assert reason in result["rejected"][0]["reasons"]


def test_vram_is_not_summed_across_devices():
    request, snapshot, route = inputs()
    route.update(device="gpu", vram_bytes=12 * GIB)
    assert "single_gpu_vram_insufficient" in advise(request, snapshot, [route], now=1000)["rejected"][0]["reasons"]


@pytest.mark.parametrize("field,value,reason", [
    ("samples", 2, "quality_gate_not_passed"),
    ("passed", 2, "quality_gate_not_passed"),
    ("workload_sha256", "c" * 64, "workload_evidence_mismatch"),
    ("hardware_key", "c" * 64, "hardware_evidence_mismatch"),
    ("recorded_at", 1001, "measurement_stale_or_future"),
])
def test_evidence_binding(field, value, reason):
    request, snapshot, route = inputs()
    # Keep counters internally consistent when testing insufficient samples.
    if field == "samples":
        route["measurement"]["passed"] = value
    route["measurement"][field] = value
    assert reason in advise(request, snapshot, [route], now=1000)["rejected"][0]["reasons"]


@pytest.mark.parametrize("busy", [True, None])
def test_heavy_requires_known_free_slot(busy):
    request, snapshot, route = inputs()
    route["heavy"] = True
    snapshot["heavy_busy"] = busy
    assert advise(request, snapshot, [route], now=1000)["status"] == "abstain"


def test_latency_and_unknown_cost_gates():
    request, snapshot, route = inputs()
    request["max_latency_ms"] = 4
    assert advise(request, snapshot, [route], now=1000)["selected"] is None
    del request["max_latency_ms"]
    request["objective"] = "cloud_spend"
    route["measurement"]["cloud_cost_usd"] = None
    assert advise(request, snapshot, [route], now=1000)["selected"] is None


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), 10 ** 1000])
def test_invalid_numbers(value):
    request, snapshot, route = inputs()
    route["ram_bytes"] = value
    with pytest.raises(ValueError):
        advise(request, snapshot, [route], now=1000)


def test_duplicate_ids_and_unknown_fields():
    request, snapshot, route = inputs()
    with pytest.raises(ValueError):
        advise(request, snapshot, [route, route], now=1000)
    route["shell"] = "do not execute"
    with pytest.raises(ValueError):
        advise(request, snapshot, [route], now=1000)


def test_npu_does_not_infer_unobserved_capacity():
    request, snapshot, route = inputs()
    route["device"] = "npu"
    assert "npu_capacity_not_observed" in advise(request, snapshot, [route], now=1000)["rejected"][0]["reasons"]


def test_adaptive_log_task_uses_same_evidence_gates():
    request, snapshot, route = inputs()
    request["task"] = route["task"] = "log_compact"
    assert advise(request, snapshot, [route], now=1000)["selected"] == "cpu"
    route["measurement"] = None
    assert advise(request, snapshot, [route], now=1000)["status"] == "abstain"
