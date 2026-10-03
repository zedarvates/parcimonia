import copy
import json
import subprocess
import sys
from dataclasses import asdict, replace

import pytest
from test_tev1_shadow import authored_response
from test_tev1_transport import IDENTITY, server

from examples.tev1_shadow import capture_run, comparison, preflight, replay_run
from tiberium_ai.measurement import Environment
from tiberium_ai.tev1_cases import tev1_cases
from tiberium_ai.tev1_comparison import compare_tev1_runs

LARGE = replace(IDENTITY, model="tev1:4b", model_digest="sha256:" + "b" * 64)
ENVIRONMENT = asdict(
    Environment("fixture-only", {"python": "3.12.14", "ollama": "0.35.0"})
)


def fixture_report(identity, *, missing=(), wrong=(), environment=None, offset=0):
    rows = []
    for index, case in enumerate(tev1_cases()):
        observed = None if index in missing else case.expected
        if index in wrong:
            observed = next(
                key for key in case.question.option_keys if key != case.expected
            )
        rows.append(
            {
                "observed": observed,
                "status": "error" if observed is None else "ok",
                "detail_code": "fixture",
                "attempt_latency_ms": 10 + index + offset,
                "usage": {}
                if observed is None
                else {"input_tokens_total": 100, "output_tokens_total": 1},
            }
        )
    return comparison(
        rows,
        identity=identity,
        capture_origin="fixture",
        budget_ms=2000,
        environment=environment,
    )


def test_paired_quality_counts_missing_answers_and_recomputes_totals():
    small = fixture_report(IDENTITY, missing=(0,), wrong=(1,))
    large = fixture_report(LARGE, wrong=(2,))
    small["model"]["correct"] = 999  # A precomputed claim must not override cases.
    result = compare_tev1_runs(small, large)
    assert result["attempted_per_model"] == 24
    assert result["small"]["correct"] == 22 and result["small"]["answered_usable"] == 23
    assert result["large"]["correct"] == 23
    assert result["paired_quality_counts"] == {
        "both_correct": 21,
        "small_only_correct": 1,
        "large_only_correct": 2,
        "neither_correct": 0,
    }
    assert sum(family["attempted"] for family in result["by_family"].values()) == 24
    assert result["small"]["resources"]["input_tokens"] is None
    assert result["selected_model"] is None and result["saving_claim"] is False
    assert result["auto_act_allowed"] is False and result["label_origin"] == "fixture"


def test_unknown_environment_never_enables_paired_latency_deltas():
    result = compare_tev1_runs(
        fixture_report(IDENTITY), fixture_report(LARGE, environment=ENVIRONMENT)
    )
    assert result["environment_relation"] == "unknown"
    assert all(row["large_minus_small_latency_ms"] is None for row in result["cases"])
    assert result["total_cost_comparison"] == "unavailable"


def test_declared_environment_deltas_require_two_usable_answers():
    result = compare_tev1_runs(
        fixture_report(IDENTITY, missing=(0,), environment=ENVIRONMENT),
        fixture_report(LARGE, offset=10, environment=ENVIRONMENT),
    )
    assert result["environment_relation"] == "same_declared"
    assert result["cases"][0]["large_minus_small_latency_ms"] is None
    assert result["cases"][1]["large_minus_small_latency_ms"] == 10
    assert result["small"]["latency_ms"]["first_attempt"] == 10
    assert result["small"]["latency_ms"]["p95_all_attempts"] == 32
    assert result["load_state"] == "unobserved"


@pytest.mark.parametrize(
    "edit,error",
    [
        (lambda r: r.update(budget_ms=2001), "pair_budget_mismatch"),
        (
            lambda r: r["identity"].update(ollama_version="0.35.1"),
            "pair_runtime_mismatch",
        ),
        (
            lambda r: r["identity"].update(model_digest=IDENTITY.model_digest),
            "pair_models_share_digest",
        ),
        (lambda r: r.update(capture_origin="recorded"), "pair_origin_mismatch"),
        (lambda r: r.update(corpus_revision="0" * 64), "pair_corpus_mismatch"),
        (lambda r: r["cases"].pop(), "pair_cases_missing"),
        (lambda r: r["cases"].reverse(), "pair_case_order_mismatch"),
        (lambda r: r["cases"][0].update(expected="invented"), "pair_label_mismatch"),
        (
            lambda r: r["cases"][0].update(attempt_latency_ms=float("nan")),
            "invalid_pair_latency",
        ),
        (lambda r: r["cases"][0].update(model=None), "pair_status_mismatch"),
        (lambda r: r.update(auto_act_allowed=True), "pair_is_not_advisory"),
    ],
)
def test_incompatible_or_inflated_pairs_are_refused(edit, error):
    small, large = fixture_report(IDENTITY), fixture_report(LARGE)
    edit(large)
    with pytest.raises(ValueError, match=error):
        compare_tev1_runs(small, large)


def test_different_declared_environments_are_refused():
    another = copy.deepcopy(ENVIRONMENT)
    another["machine_id"] = "different-fixture"
    with pytest.raises(ValueError, match="pair_environment_mismatch"):
        compare_tev1_runs(
            fixture_report(IDENTITY, environment=ENVIRONMENT),
            fixture_report(LARGE, environment=another),
        )


def test_swapped_model_roles_are_refused():
    with pytest.raises(ValueError, match="pair_model_role_mismatch"):
        compare_tev1_runs(fixture_report(LARGE), fixture_report(IDENTITY))


def test_cli_revalidates_both_captures_and_ignores_precomputed_totals(tmp_path):
    directories = (tmp_path / "small", tmp_path / "large")
    for identity, out in zip((IDENTITY, LARGE), directories):
        with server(response=authored_response, model_identity=identity) as (url, _):
            capture_run(
                model=identity.model,
                base_url=url,
                budget_ms=2000,
                out=out,
                machine_id="http-stub-fixture",
            )
    (directories[0] / "comparison.json").write_text('{"correct":999}', encoding="utf-8")
    output = tmp_path / "paired.json"
    command = [
        sys.executable,
        "examples/tev1_shadow.py",
        "compare",
        "--small",
        str(directories[0]),
        "--large",
        str(directories[1]),
        "--out",
        str(output),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=True)
    result = json.loads(completed.stdout)
    assert result == json.loads(output.read_text(encoding="utf-8"))
    assert result["small"]["correct"] == result["large"]["correct"] == 24
    assert result["environment_relation"] == "same_declared"
    assert result["label_origin"] == "fixture" and not result["saving_claim"]
    repeated = subprocess.run(command, text=True, capture_output=True, check=False)
    assert (
        repeated.returncode == 1
        and output.read_text(encoding="utf-8") == completed.stdout
    )


def test_manifest_v1_replays_with_unknown_environment(tmp_path):
    with server(response=authored_response) as (url, _):
        capture_run(
            model=IDENTITY.model, base_url=url, budget_ms=2000, out=tmp_path / "run"
        )
    path = tmp_path / "run" / "run.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    manifest["schema_version"] = 1
    del manifest["environment"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report = replay_run(tmp_path / "run")
    assert report["environment"] is None and report["budget_ms"] == 2000
    assert report["model"]["correct"] == 24


def test_invalid_environment_label_is_refused_before_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "examples.tev1_shadow.probe_tev1_model",
        lambda **_: pytest.fail("must not probe"),
    )
    with pytest.raises(ValueError):
        capture_run(
            model=IDENTITY.model,
            base_url="http://127.0.0.1:11434",
            budget_ms=2000,
            out=tmp_path / "run",
            machine_id=" ",
        )


def test_preflight_inspects_both_installed_models_without_inference():
    with server(installed_models=(IDENTITY, LARGE)) as (url, calls):
        result = preflight(url)
    assert [model["model"] for model in result["models"]] == [
        IDENTITY.model,
        LARGE.model,
    ]
    assert (
        result["inference_performed"] is False and result["models_downloaded"] is False
    )
    assert [call[1] for call in calls] == [
        "/api/version",
        "/api/tags",
        "/api/version",
        "/api/tags",
    ]
    assert all(call[0] == "GET" for call in calls)
