import json

import pytest

from tiberium_ai.stability import inspect_python_stability
from tiberium_ai.verification import hash_input


def inspect(source):
    return inspect_python_stability(source, source_id="fixture.py", revision="fixture-v1")


def rules(report):
    return [finding["rule_id"] for finding in report["findings"]]


@pytest.mark.parametrize("default", ["[]", "{}", "{1}"])
def test_mutable_default_literal_is_an_advisory_risk(default):
    report = inspect(f"def append(item, cache={default}):\n    pass\n")
    assert report["status"] == "risks_identified"
    assert rules(report) == ["mutable_default_argument"]
    finding = report["findings"][0]
    assert finding["line"] == 1
    assert finding["end_line"] == 1
    assert finding["verdict"] == "risk_indicator"


def test_mutable_keyword_only_default_and_async_function_are_supported():
    report = inspect("async def consume(*, state=[]):\n    pass\n")
    assert rules(report) == ["mutable_default_argument"]


def test_fresh_per_call_state_has_no_supported_mutable_default_pattern():
    report = inspect(
        "def consume(item, state=None):\n"
        "    if state is None:\n        state = []\n"
        "    state.append(item)\n    return state\n"
    )
    assert report["status"] == "no_supported_pattern_found"
    assert report["limits"]["stability"] == "not_established"


@pytest.mark.parametrize(
    "condition",
    ["signal > 0.5", "0.5 < signal", "signal >= -0.5", "self.signal <= 2"],
)
def test_single_threshold_reports_possible_oscillation(condition):
    report = inspect(f"if {condition}:\n    active = True\nelse:\n    active = False\n")
    assert rules(report) == ["single_threshold_switch"]
    assert "could" in report["findings"][0]["explanation"]
    assert "Replay" in report["findings"][0]["next_check"]


def test_hysteresis_shape_does_not_match_single_threshold_rule():
    report = inspect(
        "if signal > 0.6:\n    active = True\n"
        "elif signal < 0.4:\n    active = False\n"
    )
    assert rules(report) == []


@pytest.mark.parametrize(
    "source",
    [
        "if signal > 0.5:\n    active = True\nelse:\n    other = False\n",
        "if signal > 0.5:\n    active = True\nelse:\n    active = True\n",
        "if 0 < signal < 1:\n    active = True\nelse:\n    active = False\n",
        "if signal > threshold:\n    active = True\nelse:\n    active = False\n",
        "if signal > True:\n    active = True\nelse:\n    active = False\n",
        "if signal > 0.5:\n    active = select()\nelse:\n    active = False\n",
    ],
)
def test_unsupported_or_non_switch_shapes_are_not_classified(source):
    assert rules(inspect(source)) == []


def test_retry_without_local_exit_is_reported_without_claim_of_nontermination():
    report = inspect(
        "while True:\n    try:\n        connect()\n"
        "    except OSError:\n        record_failure()\n        continue\n"
    )
    assert rules(report) == ["retry_without_visible_exit"]
    finding = report["findings"][0]
    assert finding["line"] == 1
    assert "may still stop" in finding["explanation"]


@pytest.mark.parametrize(
    "source",
    [
        "while True:\n    try:\n        connect()\n        break\n    except OSError:\n        pass\n",
        "def f():\n    while True:\n        try:\n            return connect()\n        except OSError:\n            pass\n",
        "while True:\n    try:\n        connect()\n    except OSError:\n        raise\n",
        "for attempt in range(3):\n    try:\n        connect()\n    except OSError:\n        pass\n",
        "while attempt < 3:\n    try:\n        connect()\n    except OSError:\n        attempt += 1\n",
        "while True:\n    work()\n",
        "while True:\n    try:\n        work()\n    except OSError:\n        pass\n    if cancelled:\n        break\n",
    ],
)
def test_exit_or_attempt_bound_avoids_retry_warning(source):
    assert "retry_without_visible_exit" not in rules(inspect(source))


def test_return_in_nested_function_does_not_count_as_loop_exit():
    report = inspect(
        "while True:\n    def helper():\n        return 1\n"
        "    try:\n        connect()\n    except OSError:\n        pass\n"
    )
    assert rules(report) == ["retry_without_visible_exit"]


def test_ambiguous_nested_loop_does_not_trigger_outer_retry_rule():
    report = inspect(
        "while True:\n    for item in items:\n        break\n"
        "    try:\n        connect()\n    except OSError:\n        pass\n"
    )
    assert rules(report) == []


def test_source_is_never_executed_or_imported(tmp_path):
    target = tmp_path / "must-not-exist"
    report = inspect(
        f"from pathlib import Path\nPath({str(target)!r}).write_text('executed')\n"
        "raise RuntimeError('must never execute')\n"
    )
    assert not target.exists()
    assert report["status"] == "no_supported_pattern_found"


def test_invalid_syntax_remains_indeterminate():
    report = inspect("def broken(:\n")
    assert report["status"] == "indeterminate"
    assert report["reason_codes"] == ["source_syntax_invalid"]
    assert report["findings"] == []


def test_null_bytes_are_indeterminate_syntax():
    report = inspect("x = '\x00'")
    assert report["status"] == "indeterminate"
    assert report["reason_codes"] == ["source_syntax_invalid"]


def test_byte_budget_counts_utf8_bytes_before_parsing():
    report = inspect("#" + "é" * (128 * 1024))
    assert report["status"] == "indeterminate"
    assert report["reason_codes"] == ["source_byte_budget_exceeded"]
    assert report["limits"]["ast_nodes"] is None


def test_deep_ast_remains_indeterminate_instead_of_partial_clean_report():
    report = inspect("x = " + " + ".join(["a"] * 200))
    assert report["status"] == "indeterminate"
    assert report["reason_codes"] == ["ast_depth_budget_exceeded"]
    assert report["findings"] == []


def test_large_ast_remains_indeterminate():
    report = inspect("x = 1\n" * 3000)
    assert report["status"] == "indeterminate"
    assert report["reason_codes"] == ["ast_node_budget_exceeded"]


def test_hash_binds_exact_source_identity_and_revision():
    source = "value = 1\n"
    report = inspect(source)
    assert report == inspect(source)
    assert report["input_hash"] == hash_input(
        {"source": source, "source_id": "fixture.py", "revision": "fixture-v1"}
    )
    assert report["input_hash"] != inspect(source + "\n")["input_hash"]
    assert report["input_hash"] != inspect_python_stability(
        source, source_id="fixture.py", revision="fixture-v2"
    )["input_hash"]


def test_multiple_risks_never_become_demonstrated_instability():
    report = inspect(
        "def consume(state=[]):\n    pass\n"
        "if signal > 0.5:\n    active = True\nelse:\n    active = False\n"
        "while True:\n    try:\n        connect()\n    except OSError:\n        pass\n"
    )
    assert len(report["findings"]) == 3
    assert all(f["verdict"] == "risk_indicator" for f in report["findings"])
    assert report["mode"] == "shadow"
    assert report["limits"]["stability"] == "not_established"
    assert report["limits"]["absence_of_other_risks"] == "not_established"
    encoded = json.dumps(report, allow_nan=False)
    assert "score" not in encoded
    assert "confidence" not in encoded


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source": None},
        {"source_id": ""},
        {"source_id": " fixture.py"},
        {"revision": 1},
        {"revision": "a" * 257},
        {"source": "\ud800"},
    ],
)
def test_invalid_input_types_or_identifiers_are_rejected(kwargs):
    arguments = {"source": "", "source_id": "fixture.py", "revision": "fixture-v1"}
    arguments.update(kwargs)
    with pytest.raises(ValueError):
        inspect_python_stability(**arguments)
