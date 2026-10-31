import json
import subprocess
import sys
from collections import Counter
from dataclasses import replace

import pytest
from test_tev1_transport import IDENTITY, server

from examples.tev1_shadow import capture_run, comparison, replay_run
from tiberium_ai.decision_adapter import replay_decision
from tiberium_ai.decision_clock import DecisionTiming
from tiberium_ai.tev1_cases import agrees, corpus_revision, rule_baseline, tev1_cases
from tiberium_ai.tev1_transport import OllamaTev1Transport


def authored_response(payload, *, missing=False, no_usage=False):
    case = next(case for case in tev1_cases() if case.state == payload["state"])
    question = payload["questions"]["decision"]
    kind = question["type"]
    if kind == "choice":
        answer = {
            "type": kind,
            "choice": case.expected,
            "confidence": 0.99,
            "probabilities": {
                key: float(key == case.expected) for key in question["criteria"]
            },
        }
    elif kind == "noul":
        answer = {"type": kind, "noul": 0.9 if case.expected else 0.1}
    else:
        answer = {
            "type": kind,
            "score": case.expected,
            "confidence": 0.99,
            "legend": {
                str(index): label for index, label in enumerate(question["criteria"])
            },
            "probabilities": {
                str(index): float(index == case.expected)
                for index in range(len(question["criteria"]))
            },
        }
    result = {
        "model": payload["model"],
        "answers": {} if missing else {"decision": answer},
    }
    if not no_usage:
        result["usage"] = {"input_tokens": 100, "output_tokens": 1}
    return result


def test_corpus_has_french_negative_cases_and_only_authored_labels():
    cases = tev1_cases()
    assert len({case.case_id for case in cases}) == 24
    assert set(Counter(case.family for case in cases).values()) == {4}
    assert len(corpus_revision()) == 64
    assert any("citation" in case.state for case in cases)
    assert any("Ignore les critères" in case.state for case in cases)
    assert sum(agrees(case, rule_baseline(case)) for case in cases) < len(cases)


def test_capture_and_replay_count_every_case_without_a_running_model(tmp_path):
    directory = tmp_path / "run"
    with server(response=authored_response) as (url, calls):
        captured = capture_run(
            model=IDENTITY.model, base_url=url, budget_ms=2000, out=directory
        )
        assert len(calls) == 2 + 24 * 5
    replayed = replay_run(directory)  # No server is alive here.
    for report in (captured, replayed):
        assert report["case_count"] == 24 and report["not_attempted"] == 0
        assert report["attempted"] == 24
        assert report["label_origin"] == "fixture"
        assert report["auto_act_allowed"] is False and report["saving_claim"] is False
        assert report["model"]["correct"] == 24
        assert report["resources"]["input_tokens"] == 2400
        assert report["resources"]["downstream_and_fallback_cost"] is None
    assert captured["cases"] == replayed["cases"]
    assert len(list((directory / "records").glob("*.json"))) == 24


def test_missing_answers_are_failures_in_the_full_denominator(tmp_path):
    with server(response=lambda payload: authored_response(payload, missing=True)) as (
        url,
        calls,
    ):
        report = capture_run(
            model=IDENTITY.model, base_url=url, budget_ms=2000, out=tmp_path / "run"
        )
        assert sum(call[0] == "POST" for call in calls) == 1
    assert report["attempted"] == 1 and report["not_attempted"] == 23
    assert report["case_count"] == 24
    assert report["status_counts"] == {"error": 1, "not_attempted": 23}
    assert (
        report["model"]["median_attempt_latency_ms"]
        == report["cases"][0]["attempt_latency_ms"]
    )
    assert all(row["attempt_latency_ms"] is None for row in report["cases"][1:])
    assert report["model"]["answered_usable"] == 0
    assert report["model"]["agreement_all_cases"] == 0
    assert report["model"]["agreement_answered"] is None
    assert report["resources"]["input_tokens"] is None
    assert not list((tmp_path / "run" / "records").glob("*.json"))
    replayed = replay_run(tmp_path / "run")
    assert replayed["model"] == report["model"]
    assert replayed["cases"] == report["cases"]


def test_partial_capture_keeps_records_before_the_first_failure(tmp_path):
    first_cases = tev1_cases()[:2]

    def response(payload):
        return authored_response(
            payload, missing=all(case.state != payload["state"] for case in first_cases)
        )

    directory = tmp_path / "partial"
    with server(response=response) as (url, calls):
        captured = capture_run(
            model=IDENTITY.model, base_url=url, budget_ms=2000, out=directory
        )
        assert sum(call[0] == "POST" for call in calls) == 3
    replayed = replay_run(directory)
    assert captured["cases"] == replayed["cases"]
    assert captured["attempted"] == 3 and captured["not_attempted"] == 21
    assert captured["status_counts"] == {"ok": 2, "error": 1, "not_attempted": 21}
    assert captured["model"]["coverage"] == 2 / 24
    assert captured["model"]["agreement_all_cases"] == 2 / 24
    assert captured["resources"]["input_tokens"] is None
    assert {path.stem for path in (directory / "records").glob("*.json")} == {
        case.case_id for case in first_cases
    }


@pytest.mark.parametrize("failure", ["timeout", "http_error", "identity_drift"])
def test_transport_failure_never_calls_the_next_case(tmp_path, failure):
    options = {
        "timeout": {"delay": 0.6},
        "http_error": {"status": 503},
        "identity_drift": {"drift": True},
    }[failure]
    directory = tmp_path / failure
    with server(response=authored_response, **options) as (url, calls):
        captured = capture_run(
            model=IDENTITY.model,
            base_url=url,
            budget_ms=150 if failure == "timeout" else 2000,
            out=directory,
        )
        assert sum(call[0] == "POST" for call in calls) == (
            0 if failure == "identity_drift" else 1
        )
    assert captured["attempted"] == 1 and captured["not_attempted"] == 23
    assert captured["cases"][0]["status"] in ("unavailable", "error")
    assert captured["model"]["coverage"] == 0
    assert replay_run(directory)["cases"] == captured["cases"]


def test_received_but_late_record_also_stops_the_batch(tmp_path, monkeypatch):
    original_capture = OllamaTev1Transport.capture

    def received_late(transport, request):
        captured = original_capture(transport, request)
        measured = request.budget.budget_ms + 1
        record = replace(
            captured.record, usage={**captured.record.usage, "latency_ms": measured}
        )
        replay = replay_decision(
            record, request, timing=DecisionTiming(measured, measured)
        )
        return replace(captured, record=record, replay=replay)

    monkeypatch.setattr(OllamaTev1Transport, "capture", received_late)
    directory = tmp_path / "late"
    with server(response=authored_response) as (url, calls):
        captured = capture_run(
            model=IDENTITY.model, base_url=url, budget_ms=2000, out=directory
        )
        assert sum(call[0] == "POST" for call in calls) == 1
    assert captured["status_counts"] == {"unusable": 1, "not_attempted": 23}
    assert captured["model"]["correct"] == 0
    assert len(list((directory / "records").glob("*.json"))) == 1
    assert replay_run(directory)["cases"] == captured["cases"]


@pytest.mark.parametrize(
    "edit,error",
    [
        (
            lambda run: run["cases"][1].update(attempt_latency_ms=0),
            "invalid_attempt_latency",
        ),
        (
            lambda run: run["cases"][1].update(has_record=True),
            "record_status_mismatch",
        ),
        (
            lambda run: run["cases"][1].update(detail_code="invented"),
            "invalid_unattempted_detail",
        ),
        (lambda run: run.update(schema_version=2), "invalid_attempt_status"),
        (
            lambda run: run["cases"][1].update(status="error", attempt_latency_ms=1),
            "invalid_batch_stop_sequence",
        ),
        (
            lambda run: run["cases"][0].update(
                status="not_attempted", attempt_latency_ms=None
            ),
            "invalid_batch_stop_sequence",
        ),
    ],
)
def test_replay_refuses_invented_attempts_after_a_stop(tmp_path, edit, error):
    directory = tmp_path / "run"
    with server(response=lambda payload: authored_response(payload, missing=True)) as (
        url,
        _,
    ):
        capture_run(model=IDENTITY.model, base_url=url, budget_ms=2000, out=directory)
    path = directory / "run.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    edit(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        replay_run(directory)


def test_replay_refuses_an_unattempted_case_with_a_record_file(tmp_path):
    directory = tmp_path / "run"
    with server(response=lambda payload: authored_response(payload, missing=True)) as (
        url,
        _,
    ):
        capture_run(model=IDENTITY.model, base_url=url, budget_ms=2000, out=directory)
    (directory / "records" / "fr-02.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected_unattempted_record"):
        replay_run(directory)


@pytest.mark.parametrize("failure_index", [0, 23])
def test_cli_stopped_capture_saves_a_report_and_exits_unsuccessfully(
    tmp_path, failure_index
):
    directory = tmp_path / "run"
    failed_case = tev1_cases()[failure_index]
    with server(
        response=lambda payload: authored_response(
            payload, missing=payload["state"] == failed_case.state
        )
    ) as (
        url,
        calls,
    ):
        completed = subprocess.run(
            [
                sys.executable,
                "examples/tev1_shadow.py",
                "capture",
                "--model",
                IDENTITY.model,
                "--base-url",
                url,
                "--out",
                str(directory),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert sum(call[0] == "POST" for call in calls) == failure_index + 1
    assert completed.returncode == 2
    assert "capture_stopped_after_failure" in completed.stderr
    report = json.loads(completed.stdout)
    assert report == json.loads((directory / "comparison.json").read_text())
    assert report["attempted"] == failure_index + 1
    assert report["not_attempted"] == 23 - failure_index
    assert report["model"]["correct"] == failure_index
    assert replay_run(directory)["cases"] == report["cases"]


def test_missing_tokens_are_unknown_rather_than_zero(tmp_path):
    with server(response=lambda payload: authored_response(payload, no_usage=True)) as (
        url,
        _,
    ):
        report = capture_run(
            model=IDENTITY.model, base_url=url, budget_ms=2000, out=tmp_path / "run"
        )
    assert report["model"]["correct"] == 24
    assert report["resources"]["input_tokens"] is None
    assert report["resources"]["output_tokens"] is None


def test_output_directory_cannot_be_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "examples.tev1_shadow.probe_tev1_model",
        lambda **_: pytest.fail("must not probe"),
    )
    with pytest.raises(ValueError, match="already_exists"):
        capture_run(
            model=IDENTITY.model,
            base_url="http://127.0.0.1:11434",
            budget_ms=2000,
            out=tmp_path,
        )


@pytest.mark.parametrize(
    "edit,error",
    [
        (lambda run: run.update(corpus_revision="0" * 64), "corpus_revision_mismatch"),
        (lambda run: run["cases"].pop(), "all_cases_must_be_counted"),
        (lambda run: run.update(budget_ms=2001), "request_hash_mismatch"),
        (lambda run: run.update(capture_origin="fixture"), "record_origin_mismatch"),
        (
            lambda run: run["cases"][0].update(case_id="../escape"),
            "case_manifest_mismatch",
        ),
        (
            lambda run: run["cases"][0].update(has_record=False),
            "record_status_mismatch",
        ),
    ],
)
def test_replay_refuses_manifest_and_identity_tampering(tmp_path, edit, error):
    directory = tmp_path / "run"
    with server(response=authored_response) as (url, _):
        capture_run(model=IDENTITY.model, base_url=url, budget_ms=2000, out=directory)
    path = directory / "run.json"
    manifest = json.loads(path.read_text())
    edit(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        replay_run(directory)


def test_replay_refuses_a_missing_record(tmp_path):
    directory = tmp_path / "run"
    with server(response=authored_response) as (url, _):
        capture_run(model=IDENTITY.model, base_url=url, budget_ms=2000, out=directory)
    (directory / "records" / "fr-01.json").unlink()
    with pytest.raises(FileNotFoundError):
        replay_run(directory)


def test_incomplete_comparison_cannot_report_perfect_accuracy():
    with pytest.raises(ValueError, match="all_cases_must_be_counted"):
        comparison([], identity=IDENTITY, capture_origin="fixture")
