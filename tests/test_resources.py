import pytest

from tiberium_ai.measurement import Environment, run_baseline
from tiberium_ai.resources import ResourceVector, pareto_front


def clock_from(*ticks):
    return iter(ticks).__next__


def measurement():
    return run_baseline(
        "task-1",
        "rule",
        lambda: None,
        cost_unit="unit/task",
        environment=Environment("test-machine", {"python": "3.14.0"}),
        clock=clock_from(0.0, 0.25),
        now=lambda: "2026-09-18T06:00:00+00:00",
    ).to_record()


@pytest.mark.parametrize("overrides", [
    {"tokens": -1},
    {"tokens": 1.5},
    {"tokens": True},
    {"latency_ms": -1},
    {"latency_ms": float("nan")},
    {"latency_ms": float("inf")},
    {"latency_ms": True},
    {"vram_mb": -1},
    {"energy_joules": "1"},
])
def test_invalid_dimensions_are_rejected(overrides):
    with pytest.raises(ValueError):
        ResourceVector(**overrides)


def test_an_empty_vector_is_allowed_and_dominates_nothing():
    empty = ResourceVector()
    assert empty.dominates(ResourceVector(latency_ms=1.0)) is False
    assert empty.to_record() == {
        "tokens": None,
        "latency_ms": None,
        "vram_mb": None,
        "energy_joules": None,
    }


def test_dominance_requires_a_strict_improvement_and_no_regression():
    faster = ResourceVector(latency_ms=1.0, tokens=10)
    slower = ResourceVector(latency_ms=2.0, tokens=10)
    assert faster.dominates(slower) is True
    assert slower.dominates(faster) is False


def test_equal_vectors_do_not_dominate_each_other():
    left = ResourceVector(latency_ms=1.0)
    right = ResourceVector(latency_ms=1.0)
    assert left.dominates(right) is False
    assert right.dominates(left) is False


def test_a_regression_on_one_dimension_blocks_dominance():
    cheap_but_bulky = ResourceVector(tokens=5, vram_mb=800.0)
    heavy_but_slim = ResourceVector(tokens=9, vram_mb=200.0)
    assert cheap_but_bulky.dominates(heavy_but_slim) is False
    assert heavy_but_slim.dominates(cheap_but_bulky) is False


def test_unknown_dimensions_are_ignored_instead_of_assumed_equal():
    measured = ResourceVector(latency_ms=1.0, vram_mb=None)
    declared = ResourceVector(latency_ms=2.0, vram_mb=512.0)
    assert measured.dominates(declared) is True


def test_pareto_front_keeps_trade_offs_and_sorts_the_result():
    front = pareto_front(
        {
            "zeta": ResourceVector(latency_ms=5.0, tokens=5),
            "alpha": ResourceVector(latency_ms=1.0, tokens=50),
            "dominated": ResourceVector(latency_ms=9.0, tokens=90),
        }
    )
    assert front == ("alpha", "zeta")


def test_pareto_front_keeps_ties():
    front = pareto_front(
        {
            "left": ResourceVector(latency_ms=1.0),
            "right": ResourceVector(latency_ms=1.0),
        }
    )
    assert front == ("left", "right")


def test_pareto_front_of_an_empty_mapping_is_empty():
    assert pareto_front({}) == ()


def test_a_measurement_record_yields_its_measured_latency():
    vector = ResourceVector.from_measurement(measurement())
    assert vector.latency_ms == 250.0
    assert vector.tokens is None
    assert vector.vram_mb is None
    assert vector.energy_joules is None


def test_a_record_without_a_valid_latency_is_rejected():
    with pytest.raises(ValueError, match="latency"):
        ResourceVector.from_measurement({"latency_ms": None})


def test_vectors_can_be_rebuilt_from_their_record():
    vector = ResourceVector(tokens=3, latency_ms=1.5)
    assert ResourceVector.from_record(vector.to_record()) == vector


def test_from_record_rejects_unknown_dimensions():
    with pytest.raises(ValueError):
        ResourceVector.from_record({"latency_ms": 1.0, "magic": 2.0})
