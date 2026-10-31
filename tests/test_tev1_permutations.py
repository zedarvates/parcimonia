import copy
import json
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import replace

import pytest
from test_tev1_comparison import LARGE, fixture_report
from test_tev1_shadow import authored_response
from test_tev1_transport import IDENTITY, server

from examples.tev1_shadow import capture_run, comparison, replay_run
from tiberium_ai.tev1_cases import corpus_revision, tev1_cases
from tiberium_ai.tev1_comparison import compare_tev1_runs
from tiberium_ai.tev1_permutations import (
    CHOICE_ORDER_CORPUS,
    choice_order_cases,
    revision_for,
)


def order_report(identity=IDENTITY, edit=None):
    rows = []
    for case in choice_order_cases():
        keys = case.question.option_keys
        if case.question.kind.value == "choice":
            probabilities = {key: float(key == case.expected) for key in keys}
        elif case.question.kind.value == "noul":
            probabilities = {
                "false": 0.1 if case.expected else 0.9,
                "true": 0.9 if case.expected else 0.1,
            }
        else:
            probabilities = {
                key: float(i == case.expected) for i, key in enumerate(keys)
            }
        row = {
            "observed": case.expected,
            "probabilities": probabilities,
            "status": "ok",
            "detail_code": "fixture",
            "attempt_latency_ms": 10,
            "usage": {},
        }
        if edit is not None:
            edit(case, row)
        rows.append(row)
    return comparison(
        rows,
        identity=identity,
        capture_origin="fixture",
        budget_ms=2000,
        corpus_kind=CHOICE_ORDER_CORPUS,
    )


def test_variants_keep_semantics_and_leave_boolean_and_ordinal_controls_alone():
    original = {case.case_id: case for case in tev1_cases()}
    variants = choice_order_cases()
    assert len(variants) == len({case.case_id for case in variants}) == 104
    counts = Counter(case.source_case_id for case in variants)
    assert Counter(counts.values()) == {6: 16, 1: 8}
    for case in variants:
        base = original[case.source_case_id]
        assert (case.state, case.expected, case.family) == (
            base.state,
            base.expected,
            base.family,
        )
        assert case.question.instructions == base.question.instructions
        assert case.question.kind == base.question.kind
        assert case.question.criteria == base.question.criteria
        assert case.question.option_keys == case.ordered_keys
        if case.order_id == "control":
            assert case.question == base.question
    for source in original.values():
        orders = [
            case.ordered_keys
            for case in variants
            if case.source_case_id == source.case_id
        ]
        assert len(orders) == len(set(orders))


def test_revision_binds_presentation_order_without_changing_the_original_corpus(
    monkeypatch,
):
    assert (
        corpus_revision()
        == "2e9b42a985296a959d75d522a80724ab4714d7878f5655f44336b40c5af7bbed"
    )
    revision = revision_for(CHOICE_ORDER_CORPUS)
    assert revision != revision_for("base")
    variants = list(choice_order_cases())
    variants[0] = replace(
        variants[0], ordered_keys=tuple(reversed(variants[0].ordered_keys))
    )
    monkeypatch.setattr(
        "tiberium_ai.tev1_permutations.choice_order_cases", lambda: tuple(variants)
    )
    assert revision_for(CHOICE_ORDER_CORPUS) != revision


def test_unknown_protocol_is_rejected_before_any_model_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "examples.tev1_shadow.probe_tev1_model", lambda **_: pytest.fail("no probe")
    )
    with pytest.raises(ValueError, match="unknown_corpus_kind"):
        capture_run(
            model=IDENTITY.model,
            base_url="http://127.0.0.1:11434",
            budget_ms=2000,
            out=tmp_path / "run",
            corpus_kind="unrecognized",
        )
    assert not (tmp_path / "run").exists()


def test_cli_plans_both_corpora_offline():
    for args, count in [([], 24), (["--corpus", CHOICE_ORDER_CORPUS], 104)]:
        completed = subprocess.run(
            [sys.executable, "examples/tev1_shadow.py", "plan", *args],
            text=True,
            capture_output=True,
            check=True,
        )
        plan = json.loads(completed.stdout)
        assert len(plan["cases"]) == count and plan["model_called"] is False
        assert plan["label_origin"] == "fixture"


@pytest.fixture(scope="module")
def captured_order_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("choice-order") / "run"
    with server(response=authored_response) as (url, calls):
        captured = capture_run(
            model=IDENTITY.model,
            base_url=url,
            budget_ms=2000,
            out=out,
            corpus_kind=CHOICE_ORDER_CORPUS,
        )
        posts = [call[2] for call in calls if call[0] == "POST"]
        assert len(posts) == 104
        for payload, case in zip(posts, choice_order_cases()):
            criteria = payload["questions"]["decision"]["criteria"]
            if case.question.kind.value == "choice":
                assert tuple(criteria) == case.ordered_keys
                assert criteria == case.question.criteria
    return out, captured


def test_capture_replay_and_source_denominators_are_not_104_independent_samples(
    captured_order_run,
):
    out, captured = captured_order_run
    replayed = replay_run(out)  # HTTP stub has stopped.
    assert captured["cases"] == replayed["cases"]
    assert captured["order_stability"] == replayed["order_stability"]
    assert json.loads((out / "run.json").read_text())["schema_version"] == 4
    assert len(list((out / "records").glob("*.json"))) == 104
    for report in [captured, replayed]:
        assert (
            report["case_count"]
            == report["attempted"]
            == report["model"]["correct"]
            == 104
        )
        assert report["observation_unit"] == "request_variant"
        summary = report["order_stability"]
        assert (
            summary["source_case_count"] == summary["fully_answered_source_cases"] == 24
        )
        assert summary["all_variants_correct_source_cases"] == 24
        assert (
            summary["invariant_choice_sources"]
            == summary["complete_choice_sources"]
            == 16
        )
        assert summary["independent_sample_count"] is None
        assert report["label_origin"] == "fixture"
        assert report["auto_act_allowed"] is report["saving_claim"] is False


def test_stable_but_wrong_choice_is_not_reported_as_quality():
    def edit(case, row):
        if case.source_case_id == "fr-01":
            row["observed"] = "cache"
            row["probabilities"] = {
                key: float(key == "cache") for key in case.ordered_keys
            }

    summary = order_report(edit=edit)["order_stability"]
    assert summary["invariant_choice_sources"] == 16
    assert summary["stable_but_wrong_sources"] == 1
    assert summary["all_variants_correct_source_cases"] == 23
    assert summary["source_agreement_all_cases"] == 23 / 24


def test_first_position_bias_is_visible_by_semantic_key():
    def edit(case, row):
        if case.question.kind.value == "choice":
            row["observed"] = case.ordered_keys[0]
            row["probabilities"] = {
                key: float(key == row["observed"]) for key in case.ordered_keys
            }

    summary = order_report(edit=edit)["order_stability"]
    assert summary["changed_choice_sources"] == 16
    assert summary["all_variants_correct_source_cases"] == 8
    assert all(row["max_pairwise_probability_delta"] == 1 for row in summary["choices"])


def test_equal_probabilities_can_still_change_the_returned_winner():
    def edit(case, row):
        if case.question.kind.value == "choice":
            row["observed"] = case.ordered_keys[0]
            row["probabilities"] = {key: 0.2 for key in case.ordered_keys}

    summary = order_report(edit=edit)["order_stability"]
    assert summary["changed_choice_sources"] == 16
    for row in summary["choices"]:
        assert row["max_pairwise_probability_delta"] == 0
        assert row["winner_changes_from_original"] == 5
        for variant in row["variants"]:
            assert variant["margin_top_two"] == 0
            assert len(variant["max_tie_options"]) == 5


def test_small_numerical_drift_and_winner_changes_are_reported_separately():
    def edit(case, row):
        if case.source_case_id == "fr-01":
            row["observed"] = "cache" if case.order_id == "rotate-1" else "rule"
            row["probabilities"] = {key: 0.0 for key in case.ordered_keys}
            row["probabilities"].update(rule=0.5, cache=0.5)
            row["probabilities"][row["observed"]] += 0.000001
            row["probabilities"]["rule" if row["observed"] == "cache" else "cache"] -= (
                0.000001
            )

    summary = order_report(edit=edit)["order_stability"]
    first = summary["choices"][0]
    assert first["winner_changes_from_original"] == 1
    assert first["max_pairwise_probability_delta"] == pytest.approx(0.000002)
    assert len(first["variants"][0]["max_tie_options"]) == 1
    assert first["variants"][0]["margin_top_two"] == pytest.approx(0.000002)


def test_failed_second_order_stops_and_does_not_invent_stability(tmp_path):
    attempts = 0

    def response(payload):
        nonlocal attempts
        attempts += 1
        return authored_response(payload, missing=attempts == 2)

    out = tmp_path / "partial"
    with server(response=response) as (url, calls):
        captured = capture_run(
            model=IDENTITY.model,
            base_url=url,
            budget_ms=2000,
            out=out,
            corpus_kind=CHOICE_ORDER_CORPUS,
        )
        assert sum(call[0] == "POST" for call in calls) == 2
    replayed = replay_run(out)
    assert captured["cases"] == replayed["cases"]
    assert captured["order_stability"] == replayed["order_stability"]
    assert captured["status_counts"] == {"ok": 1, "error": 1, "not_attempted": 102}
    assert all(row["attempt_latency_ms"] is None for row in captured["cases"][2:])
    summary = captured["order_stability"]
    assert summary["fully_answered_source_cases"] == 0
    assert summary["incomplete_choice_sources"] == 16
    assert summary["invariant_choice_sources"] == summary["changed_choice_sources"] == 0
    for row in summary["choices"]:
        assert row["choice_invariant"] is None
        assert row["max_pairwise_probability_delta"] is None
        assert row["winner_changes_from_original"] is None


@pytest.mark.parametrize(
    "edit,error",
    [
        (lambda run: run.update(corpus_kind="base"), "invalid_run_corpus_kind"),
        (lambda run: run.pop("corpus_kind"), "invalid_run_manifest"),
        (lambda run: run.update(corpus_revision="0" * 64), "corpus_revision_mismatch"),
        (lambda run: run["cases"].pop(), "all_cases_must_be_counted"),
        (
            lambda run: run["cases"][0].update(case_id="fr-01-rotate-1"),
            "case_manifest_mismatch",
        ),
        (lambda run: run["cases"][0].update(option_order=[]), "case_manifest_mismatch"),
        (lambda run: run.update(budget_ms=2001), "request_hash_mismatch"),
    ],
)
def test_order_manifest_cannot_be_relabelled_or_have_variants_hidden(
    tmp_path, captured_order_run, edit, error
):
    original, _ = captured_order_run
    out = tmp_path / "tampered"
    shutil.copytree(original, out)
    path = out / "run.json"
    manifest = json.loads(path.read_text())
    edit(manifest)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=error):
        replay_run(out)


def test_a_record_from_another_order_cannot_be_replayed(tmp_path, captured_order_run):
    original, _ = captured_order_run
    out = tmp_path / "swapped"
    shutil.copytree(original, out)
    records = out / "records"
    shutil.copyfile(records / "fr-01-rotate-0.json", records / "fr-01-rotate-1.json")
    with pytest.raises(ValueError, match="request_hash_mismatch"):
        replay_run(out)


def test_replay_ignores_cached_stability_and_pair_recomputes_source_results(
    tmp_path, captured_order_run
):
    original, _ = captured_order_run
    out = tmp_path / "cached"
    shutil.copytree(original, out)
    (out / "comparison.json").write_text(
        '{"correct":999,"order_stability":{"invariant_choice_sources":999}}'
    )
    small = replay_run(out)
    assert small["order_stability"]["invariant_choice_sources"] == 16
    small["order_stability"] = {"invariant_choice_sources": 999}
    large = order_report(LARGE)
    large["capture_origin"] = small["capture_origin"]
    paired = compare_tev1_runs(small, large)
    assert paired["case_count"] == 104
    assert paired["attempted_per_model"] == {"small": 104, "large": 104}
    assert paired["order_stability"]["small"]["invariant_choice_sources"] == 16
    assert paired["order_stability"]["large"]["source_case_count"] == 24
    assert paired["selected_model"] is None


def test_original_and_order_corpora_cannot_be_compared_as_the_same_cases():
    with pytest.raises(ValueError, match="pair_corpus_mismatch"):
        compare_tev1_runs(fixture_report(IDENTITY), order_report(LARGE))


def test_cli_compares_order_records_offline_and_refuses_to_replace_a_report(
    tmp_path, captured_order_run
):
    small, _ = captured_order_run
    large = tmp_path / "large"
    with server(response=authored_response, model_identity=LARGE) as (url, _):
        capture_run(
            model=LARGE.model,
            base_url=url,
            budget_ms=2000,
            out=large,
            corpus_kind=CHOICE_ORDER_CORPUS,
        )
    output = tmp_path / "paired.json"
    command = [
        sys.executable,
        "examples/tev1_shadow.py",
        "compare",
        "--small",
        str(small),
        "--large",
        str(large),
        "--out",
        str(output),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=True)
    report = json.loads(completed.stdout)
    assert report == json.loads(output.read_text())
    assert report["attempted_per_model"] == {"small": 104, "large": 104}
    assert all(
        value["source_case_count"] == 24 for value in report["order_stability"].values()
    )
    assert report["auto_act_allowed"] is report["saving_claim"] is False
    original_bytes = output.read_bytes()
    repeated = subprocess.run(command, text=True, capture_output=True, check=False)
    assert repeated.returncode == 1 and output.read_bytes() == original_bytes


def test_cli_order_capture_signals_a_partial_run_and_keeps_103_unattempted_cases(
    tmp_path,
):
    out = tmp_path / "stopped"
    with server(response=lambda payload: authored_response(payload, missing=True)) as (
        url,
        calls,
    ):
        command = [
            sys.executable,
            "examples/tev1_shadow.py",
            "capture",
            "--corpus",
            CHOICE_ORDER_CORPUS,
            "--model",
            IDENTITY.model,
            "--base-url",
            url,
            "--out",
            str(out),
        ]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        assert sum(call[0] == "POST" for call in calls) == 1
    assert completed.returncode == 2
    captured = json.loads(completed.stdout)
    assert captured["attempted"] == 1 and captured["not_attempted"] == 103
    assert captured["order_stability"]["complete_choice_sources"] == 0
    assert captured["cases"] == replay_run(out)["cases"]


@pytest.mark.parametrize(
    "edit,error",
    [
        (lambda r: r.update(corpus_kind="base"), "invalid_pair_corpus_kind"),
        (lambda r: r["cases"][0].update(option_order=[]), "pair_option_order_mismatch"),
        (
            lambda r: r["cases"][0].update(source_case_id="fr-02"),
            "pair_option_order_mismatch",
        ),
        (
            lambda r: r["cases"][0].update(probabilities={}),
            "invalid_pair_probabilities",
        ),
        (
            lambda r: r["cases"][0]["probabilities"].update(rule=float("nan")),
            "invalid_pair_probabilities",
        ),
        (
            lambda r: r["cases"][0]["probabilities"].update(rule=0.0, cache=1.0),
            "pair_choice_probability_mismatch",
        ),
    ],
)
def test_paired_order_diagnostic_rejects_changed_options_or_distributions(edit, error):
    small, large = order_report(), copy.deepcopy(order_report(LARGE))
    edit(large)
    with pytest.raises(ValueError, match=error):
        compare_tev1_runs(small, large)


@pytest.mark.parametrize(
    "kind,error",
    [
        ("noul", "pair_noul_probability_mismatch"),
        ("score", "pair_score_probability_mismatch"),
    ],
)
def test_control_values_must_still_match_their_probability_distribution(kind, error):
    small, large = order_report(), order_report(LARGE)
    for case, row in zip(choice_order_cases(), large["cases"]):
        if case.question.kind.value == kind:
            row["model"] = not row["model"] if kind == "noul" else 2.0
            break
    with pytest.raises(ValueError, match=error):
        compare_tev1_runs(small, large)
