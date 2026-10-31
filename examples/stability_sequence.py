"""Demonstrate one threshold-oscillation hypothesis on an authored fixture.

Small, alternating deviations around 0.5 cause a single-threshold decision to
switch repeatedly. A 0.45/0.55 hysteresis band retains the preceding state within
the band and responds to the fixture's clear 0.60 and 0.40 changes. This trades
responsiveness for fewer switches: a meaningful change that remains inside the
band can be delayed indefinitely. Neither pattern is universally preferable.

This executes only the functions authored below. It does not import or execute
user-supplied code, measure hardware performance, or establish the stability of
any real software. Run with: python examples/stability_sequence.py
"""

from __future__ import annotations

import hashlib
import json


INPUT_SEQUENCE = (0.49, 0.51, 0.48, 0.52, 0.49, 0.51, 0.60, 0.50, 0.48, 0.40)


def _single_threshold(values: tuple[float, ...], threshold: float) -> list[bool]:
    return [value >= threshold for value in values]


def _hysteresis(
    values: tuple[float, ...], low: float, high: float, initial_state: bool
) -> list[bool]:
    state = initial_state
    outputs = []
    for value in values:
        if value >= high:
            state = True
        elif value <= low:
            state = False
        outputs.append(state)
    return outputs


def _switches(outputs: list[bool]) -> int:
    """Count adjacent output transitions; initialization is not a transition."""
    return sum(previous != current for previous, current in zip(outputs, outputs[1:]))


def run_demo() -> dict:
    """Return deterministic, bounded evidence for this authored input sequence."""
    inputs = {
        "sequence": list(INPUT_SEQUENCE),
        "single_threshold": 0.50,
        "hysteresis_low": 0.45,
        "hysteresis_high": 0.55,
        "hysteresis_initial_state": False,
        "jitter_prefix_length": 6,
    }
    canonical_inputs = json.dumps(
        inputs, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    single = _single_threshold(INPUT_SEQUENCE, inputs["single_threshold"])
    hysteresis = _hysteresis(
        INPUT_SEQUENCE,
        inputs["hysteresis_low"],
        inputs["hysteresis_high"],
        inputs["hysteresis_initial_state"],
    )
    prefix = inputs["jitter_prefix_length"]
    return {
        "schema": "parcimonia.stability-sequence/v1",
        "data_origin": "authored_fixture",
        "input_hash": "sha256:" + hashlib.sha256(canonical_inputs).hexdigest(),
        "input_hash_format": "UTF-8 JSON of inputs, sorted keys, compact separators",
        "inputs": inputs,
        "counts": {
            "samples": len(INPUT_SEQUENCE),
            "single_threshold_switches": _switches(single),
            "hysteresis_switches": _switches(hysteresis),
            "single_threshold_jitter_prefix_switches": _switches(single[:prefix]),
            "hysteresis_jitter_prefix_switches": _switches(hysteresis[:prefix]),
        },
        "outputs": {"single_threshold": single, "hysteresis": hysteresis},
        "hardware_performance_not_measured": True,
        "no_general_stability_claim": True,
        "limitations": [
            "Authored fixture only; no real software stability was established.",
            "Hysteresis may delay responses to meaningful changes inside the band.",
            "Counts describe output switching, not latency, speed or resource savings.",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=True, sort_keys=True, allow_nan=False))
