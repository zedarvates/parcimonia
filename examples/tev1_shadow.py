"""Plan, explicitly capture local Tev1, or replay a run without any server.

python examples/tev1_shadow.py plan
python examples/tev1_shadow.py capture --model tev1:0.8b --out runs/tev1-small
python examples/tev1_shadow.py replay --run runs/tev1-small
python examples/tev1_shadow.py compare --small runs/tev1-small --large runs/tev1-large
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import platform
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from statistics import median
from time import perf_counter

from tiberium_ai.decision_adapter import (
    DecisionRequest,
    read_decision_record,
    replay_decision,
    write_decision_record,
)
from tiberium_ai.decision_clock import DecisionBudget, DecisionTiming
from tiberium_ai.measurement import Environment
from tiberium_ai.reflex import ReflexKind
from tiberium_ai.tev1_cases import agrees, corpus_revision, rule_baseline, tev1_cases
from tiberium_ai.tev1_comparison import compare_tev1_runs
from tiberium_ai.tev1_permutations import (
    BASE_CORPUS,
    CHOICE_ORDER_CORPUS,
    CORPUS_KINDS,
    cases_for,
    choice_order_summary,
    order_metadata,
    revision_for,
)
from tiberium_ai.tev1_transport import (
    DEFAULT_BASE_URL,
    SUPPORTED_MODELS,
    OllamaTev1Transport,
    Tev1Identity,
    probe_tev1_model,
)


def build_request(case, identity, budget_ms):
    return DecisionRequest(
        case.case_id,
        case.state,
        (case.question,),
        state_age_ms=0,
        budget=DecisionBudget(
            budget_ms, max_state_age_ms=10000, fallback_route_id="rules"
        ),
        backend_id=identity.backend_id,
        backend_version=identity.backend_version,
    )


def observed_value(case, replay):
    if replay is None or not replay.usable or replay.batch is None:
        return None
    answer = replay.batch.get("decision")
    if case.question.kind == ReflexKind.CHOICE:
        return answer.choice
    if case.question.kind == ReflexKind.NOUL:
        return answer.noul >= 0.5
    return answer.score


def comparison(
    rows,
    *,
    identity,
    capture_origin,
    budget_ms=None,
    environment=None,
    corpus_kind=BASE_CORPUS,
):
    cases = cases_for(corpus_kind)
    output = []
    baseline_times = []
    for case, row in zip(cases, rows):
        started = perf_counter()
        baseline = rule_baseline(case)
        baseline_times.append((perf_counter() - started) * 1000)
        observed = row["observed"]
        output.append(
            {
                "case_id": case.case_id,
                "family": case.family,
                "expected": case.expected,
                "rules": baseline,
                "rules_agree": agrees(case, baseline),
                "model": observed,
                "model_agrees": observed is not None and agrees(case, observed),
                "status": row["status"],
                "detail_code": row["detail_code"],
                "attempt_latency_ms": row["attempt_latency_ms"],
            }
        )
        if corpus_kind == CHOICE_ORDER_CORPUS:
            output[-1].update(order_metadata(case))
            output[-1]["probabilities"] = row["probabilities"]
    if len(rows) != len(cases):
        raise ValueError("all_cases_must_be_counted")
    answered = [row for row in output if row["model"] is not None]
    correct = sum(row["model_agrees"] for row in output)
    attempted = [row for row in rows if row["status"] != "not_attempted"]
    resources = {}
    for key in ("input_tokens", "output_tokens"):
        values = [row.get("usage", {}).get(key + "_total") for row in rows]
        resources[key] = (
            sum(values)
            if all(type(value) is int and value >= 0 for value in values)
            else None
        )
    report = {
        "schema_version": 3 if corpus_kind == CHOICE_ORDER_CORPUS else 2,
        "corpus_revision": revision_for(corpus_kind),
        "label_origin": "fixture",
        "capture_origin": capture_origin,
        "identity": asdict(identity),
        "budget_ms": budget_ms,
        "environment": environment,
        "case_count": len(cases),
        "attempted": len(attempted),
        "not_attempted": len(cases) - len(attempted),
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "rules": {
            "correct": sum(row["rules_agree"] for row in output),
            "agreement_all_cases": sum(row["rules_agree"] for row in output)
            / len(cases),
            "median_latency_ms": median(baseline_times),
        },
        "model": {
            "answered_usable": len(answered),
            "correct": correct,
            "coverage": len(answered) / len(cases),
            "agreement_all_cases": correct / len(cases),
            "agreement_answered": correct / len(answered) if answered else None,
            "median_attempt_latency_ms": median(
                row["attempt_latency_ms"] for row in attempted
            )
            if attempted
            else None,
        },
        "resources": {
            **resources,
            "vram_bytes": None,
            "energy_joules": None,
            "cost": None,
            "downstream_and_fallback_cost": None,
        },
        "auto_act_allowed": False,
        "saving_claim": False,
        "cases": output,
    }
    if corpus_kind == CHOICE_ORDER_CORPUS:
        report.update(
            corpus_kind=corpus_kind,
            observation_unit="request_variant",
            order_stability=choice_order_summary(output),
        )
    return report


def _write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def capture_run(
    *, model, base_url, budget_ms, out, machine_id=None, corpus_kind=BASE_CORPUS
):
    if (
        type(budget_ms) not in (int, float)
        or not math.isfinite(budget_ms)
        or not 0 < budget_ms <= 120000
    ):
        raise ValueError("budget_ms must be in (0, 120000].")
    if out.exists():
        raise ValueError("output_directory_already_exists")
    cases = cases_for(corpus_kind)
    environment = None if machine_id is None else asdict(Environment(machine_id))
    identity = probe_tev1_model(model=model, base_url=base_url)
    if environment is not None:
        environment["runtime_versions"] = {
            "python": platform.python_version(),
            "ollama": identity.ollama_version,
        }
    transport = OllamaTev1Transport(identity, base_url=base_url, timeout_ms=budget_ms)
    out.mkdir(parents=True)
    (out / "records").mkdir()
    rows, manifest_rows = [], []
    stopped = False
    for case in cases:
        if stopped:
            detail = "batch_stopped_after_failed_attempt"
            rows.append(
                {
                    "observed": None,
                    "status": "not_attempted",
                    "detail_code": detail,
                    "attempt_latency_ms": None,
                    "usage": {},
                    "probabilities": None,
                }
            )
            manifest_rows.append(
                {
                    "case_id": case.case_id,
                    "status": "not_attempted",
                    "detail_code": detail,
                    "attempt_latency_ms": None,
                    "has_record": False,
                }
            )
            continue
        request = build_request(case, identity, budget_ms)
        started = perf_counter()
        capture = transport.capture(request)
        elapsed = (perf_counter() - started) * 1000
        if capture.record is not None:
            write_decision_record(
                out / "records" / f"{case.case_id}.json", capture.record
            )
        status = (
            capture.status if not capture.performed or capture.usable else "unusable"
        )
        detail = (
            capture.detail_code
            if status != "unusable"
            else capture.replay.timing.reason_code
        )
        rows.append(
            {
                "observed": observed_value(case, capture.replay),
                "status": status,
                "detail_code": detail,
                "attempt_latency_ms": elapsed,
                "usage": {} if capture.record is None else capture.record.usage,
                "probabilities": dict(
                    capture.replay.batch.get("decision").probabilities
                )
                if capture.usable
                else None,
            }
        )
        manifest_rows.append(
            {
                "case_id": case.case_id,
                "status": status,
                "detail_code": detail,
                "attempt_latency_ms": elapsed,
                "has_record": capture.record is not None,
            }
        )
        stopped = status != "ok"
    manifest = {
        "schema_version": 4 if corpus_kind == CHOICE_ORDER_CORPUS else 3,
        "corpus_revision": revision_for(corpus_kind),
        "identity": asdict(identity),
        "budget_ms": budget_ms,
        "environment": environment,
        "capture_origin": "recorded",
        "cases": manifest_rows,
    }
    if corpus_kind == CHOICE_ORDER_CORPUS:
        manifest["corpus_kind"] = corpus_kind
    report = comparison(
        rows,
        identity=identity,
        capture_origin="recorded",
        budget_ms=budget_ms,
        environment=environment,
        corpus_kind=corpus_kind,
    )
    _write_json(out / "run.json", manifest)
    _write_json(out / "comparison.json", report)
    return report


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_manifest_key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non_finite_manifest_value")


def replay_run(run):
    """Reconstruct requests from the pinned corpus, never from untrusted paths."""
    manifest_path = run / "run.json"
    if manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError("manifest_size_exceeded")
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique,
        parse_constant=_reject_constant,
    )
    fields = {
        "schema_version",
        "corpus_revision",
        "identity",
        "budget_ms",
        "capture_origin",
        "cases",
    }
    version = manifest.get("schema_version") if isinstance(manifest, dict) else None
    if version in (2, 3, 4):
        fields.add("environment")
    if version == 4:
        fields.add("corpus_kind")
    if (
        not isinstance(manifest, dict)
        or set(manifest) != fields
        or type(manifest["schema_version"]) is not int
        or manifest["schema_version"] not in (1, 2, 3, 4)
    ):
        raise ValueError("invalid_run_manifest")
    corpus_kind = BASE_CORPUS
    if version == 4:
        corpus_kind = manifest["corpus_kind"]
        if corpus_kind != CHOICE_ORDER_CORPUS:
            raise ValueError("invalid_run_corpus_kind")
    if manifest["corpus_revision"] != revision_for(corpus_kind):
        raise ValueError("corpus_revision_mismatch")
    if manifest["capture_origin"] not in ("recorded", "fixture"):
        raise ValueError("invalid_capture_origin")
    budget = manifest["budget_ms"]
    if (
        type(budget) not in (int, float)
        or not math.isfinite(budget)
        or not 0 < budget <= 120000
    ):
        raise ValueError("invalid_run_budget")
    identity = Tev1Identity(**manifest["identity"])
    environment = manifest.get("environment")
    if environment is not None:
        if not isinstance(environment, dict) or set(environment) != {
            "machine_id",
            "runtime_versions",
        }:
            raise ValueError("invalid_run_environment")
        environment = asdict(Environment(**environment))
        if environment["runtime_versions"].get("ollama") != identity.ollama_version:
            raise ValueError("environment_runtime_mismatch")
    cases = cases_for(corpus_kind)
    if not isinstance(manifest["cases"], list) or len(manifest["cases"]) != len(cases):
        raise ValueError("all_cases_must_be_counted")
    rows = []
    stopped = False
    for case, stored in zip(cases, manifest["cases"]):
        if (
            not isinstance(stored, dict)
            or set(stored)
            != {"case_id", "status", "detail_code", "attempt_latency_ms", "has_record"}
            or stored["case_id"] != case.case_id
        ):
            raise ValueError("case_manifest_mismatch")
        if type(stored["has_record"]) is not bool or stored["status"] not in (
            "ok",
            "unusable",
            "unavailable",
            "error",
            "not_attempted",
        ):
            raise ValueError("invalid_attempt_status")
        not_attempted = stored["status"] == "not_attempted"
        if not_attempted and version not in (3, 4):
            raise ValueError("invalid_attempt_status")
        latency = stored["attempt_latency_ms"]
        if (not_attempted and latency is not None) or (
            not not_attempted
            and (
                type(latency) not in (int, float)
                or not math.isfinite(latency)
                or latency < 0
            )
        ):
            raise ValueError("invalid_attempt_latency")
        if (
            not isinstance(stored["detail_code"], str)
            or not stored["detail_code"].strip()
        ):
            raise ValueError("invalid_detail_code")
        if stored["has_record"] != (stored["status"] in ("ok", "unusable")):
            raise ValueError("record_status_mismatch")
        if version in (3, 4):
            if stopped != not_attempted:
                raise ValueError("invalid_batch_stop_sequence")
            if stored["status"] != "ok":
                stopped = True
        if not_attempted:
            if stored["detail_code"] != "batch_stopped_after_failed_attempt":
                raise ValueError("invalid_unattempted_detail")
            if (run / "records" / f"{case.case_id}.json").exists():
                raise ValueError("unexpected_unattempted_record")
        observed, usage, probabilities = None, {}, None
        if stored["has_record"]:
            path = run / "records" / f"{case.case_id}.json"
            if path.stat().st_size > 1024 * 1024:
                raise ValueError("record_size_exceeded")
            record = read_decision_record(path)
            if record.data_origin != manifest["capture_origin"]:
                raise ValueError("record_origin_mismatch")
            usage = record.usage or {}
            measured = usage.get("latency_ms")
            if measured is None:
                raise ValueError("record_timing_missing")
            request = build_request(case, identity, manifest["budget_ms"])
            replay = replay_decision(
                record, request, timing=DecisionTiming(measured, measured)
            )
            if not replay.performed:
                raise ValueError(replay.detail_code)
            if replay.usable != (stored["status"] == "ok"):
                raise ValueError("timing_status_mismatch")
            if any(
                answer.auto_act_allowed or answer.confidence is not None
                for answer in replay.batch.answers
            ):
                raise ValueError("record_is_not_advisory")
            observed = observed_value(case, replay)
            if replay.usable:
                probabilities = dict(replay.batch.get("decision").probabilities)
        rows.append(
            {
                "observed": observed,
                "status": stored["status"],
                "detail_code": stored["detail_code"],
                "attempt_latency_ms": latency,
                "usage": usage,
                "probabilities": probabilities,
            }
        )
    return comparison(
        rows,
        identity=identity,
        capture_origin=manifest["capture_origin"],
        budget_ms=budget,
        environment=environment,
        corpus_kind=corpus_kind,
    )


def compare_runs(small, large):
    """Revalidate both sets of records before building a paired offline report."""
    return compare_tev1_runs(replay_run(small), replay_run(large))


def preflight(base_url):
    identities = [
        probe_tev1_model(model=model, base_url=base_url) for model in SUPPORTED_MODELS
    ]
    if identities[0].ollama_version != identities[1].ollama_version:
        raise ValueError("pair_runtime_mismatch")
    if identities[0].model_digest == identities[1].model_digest:
        raise ValueError("pair_models_share_digest")
    return {
        "models": [asdict(identity) for identity in identities],
        "inference_performed": False,
        "models_downloaded": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="Show the authored corpus without any I/O.")
    plan.add_argument("--corpus", choices=CORPUS_KINDS, default=BASE_CORPUS)
    probe = commands.add_parser(
        "preflight", help="Inspect both installed models without inference."
    )
    probe.add_argument("--base-url", default=DEFAULT_BASE_URL)
    capture = commands.add_parser(
        "capture", help="Explicitly call an already installed local model."
    )
    capture.add_argument("--model", choices=SUPPORTED_MODELS, required=True)
    capture.add_argument("--base-url", default=DEFAULT_BASE_URL)
    capture.add_argument("--budget-ms", type=float, default=5000)
    capture.add_argument(
        "--machine-id", help="Caller-declared label for this execution environment."
    )
    capture.add_argument("--out", type=Path, required=True)
    capture.add_argument("--corpus", choices=CORPUS_KINDS, default=BASE_CORPUS)
    replay = commands.add_parser("replay", help="Replay saved records offline.")
    replay.add_argument("--run", type=Path, required=True)
    compare = commands.add_parser(
        "compare", help="Compare the two pinned captures offline."
    )
    compare.add_argument("--small", type=Path, required=True)
    compare.add_argument("--large", type=Path, required=True)
    compare.add_argument(
        "--out", type=Path, help="New JSON file; existing files are refused."
    )
    args = parser.parse_args()
    try:
        if args.command == "plan":
            report = {
                "corpus_revision": revision_for(args.corpus),
                "label_origin": "fixture",
                "model_called": False,
                "cases": [asdict(case) for case in tev1_cases()],
            }
            if args.corpus == CHOICE_ORDER_CORPUS:
                cases = cases_for(args.corpus)
                report.update(
                    corpus_kind=args.corpus,
                    source_case_count=len(tev1_cases()),
                    case_count=len(cases),
                    base_corpus_revision=corpus_revision(),
                    cases=[
                        {
                            **order_metadata(case),
                            "family": case.family,
                            "state": case.state,
                            "expected": case.expected,
                        }
                        for case in cases
                    ],
                )
        elif args.command == "preflight":
            report = preflight(args.base_url)
        elif args.command == "capture":
            report = capture_run(
                model=args.model,
                base_url=args.base_url,
                budget_ms=args.budget_ms,
                out=args.out,
                machine_id=args.machine_id,
                corpus_kind=args.corpus,
            )
        elif args.command == "replay":
            report = replay_run(args.run)
        else:
            report = compare_runs(args.small, args.large)
            if args.out is not None:
                _write_json(args.out, report)
    except (OSError, TypeError, ValueError, http.client.HTTPException) as exc:
        print(f"{args.command}_failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    if args.command == "capture" and any(
        row["status"] != "ok" for row in report["cases"]
    ):
        print(
            "capture_stopped_after_failure: partial run saved; "
            "inspect the server before another capture.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
