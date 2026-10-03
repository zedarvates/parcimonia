import json
from collections import Counter

import pytest
from test_tev1_transport import IDENTITY, server

from examples.tev1_shadow import capture_run, comparison, replay_run
from tiberium_ai.tev1_cases import agrees, corpus_revision, rule_baseline, tev1_cases


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
        "model": IDENTITY.model,
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
        _,
    ):
        report = capture_run(
            model=IDENTITY.model, base_url=url, budget_ms=2000, out=tmp_path / "run"
        )
    assert report["attempted"] == 24
    assert report["model"]["answered_usable"] == 0
    assert report["model"]["agreement_all_cases"] == 0
    assert report["model"]["agreement_answered"] is None
    assert report["resources"]["input_tokens"] is None
    assert not list((tmp_path / "run" / "records").glob("*.json"))
    replayed = replay_run(tmp_path / "run")
    assert replayed["model"] == report["model"]


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
