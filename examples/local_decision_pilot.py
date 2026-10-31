"""Paired shadow pilot on existing authored French signature cases."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import version as package_version
import json
from pathlib import Path
import platform
from statistics import median
from time import perf_counter

from tiberium_ai.laya_backend import LayaBackend
from tiberium_ai.jeff_backend import JeffBackend
from tiberium_ai.signature_backends import KnnSignatureBackend, VerbFrameSignatureBackend, memory_from_cases
from tiberium_ai.signature_corpus import aligned_cases, example_schema, paraphrase_cases
from tiberium_ai.task_signature import RuleBasedSignatureBackend, calibrate_signatures


FRENCH_IDS = frozenset({"paraphrase-00", "paraphrase-01", "paraphrase-03",
                        "paraphrase-05", "paraphrase-07", "paraphrase-08"})


def process_memory():
    """Windows process working set, including runtime; not isolated model RAM."""
    if platform.system() != "Windows":
        return None
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("peak", "current", "paged_peak", "paged",
                                               "nonpaged_peak", "nonpaged", "pagefile", "pagefile_peak")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not kernel.K32GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return {"working_set_bytes": counters.current, "peak_working_set_bytes": counters.peak,
            "scope": "whole_pilot_process_including_runtime"}


class TraceBackend:
    latin_only = False

    def __init__(self, backend):
        self.backend = backend
        self.rows = []

    def evaluate(self, state_text, questions):
        before = perf_counter()
        row = {"state_sha256": sha256(state_text.encode()).hexdigest(),
               "questions": [asdict(q) for q in questions], "status": "error"}
        self.rows.append(row)
        try:
            answers = self.backend.evaluate(state_text, questions)
            row.update(status="ok", answers=answers)
            return answers
        finally:
            row["elapsed_ms"] = (perf_counter() - before) * 1000
            row["usage"] = dict(getattr(self.backend, "last_usage", {}))
            raw = getattr(self.backend, "last_raw_answers", None)
            if raw is not None:
                row["provider_answers_before_normalization"] = raw
            if hasattr(self.backend, "last_stages"):
                row["cascade"] = {
                    "route": self.backend.last_route,
                    "stages": list(self.backend.last_stages),
                    "calls": self.backend.calls,
                    "fallback_calls": self.backend.fallback_calls,
                }


def run_arm(name, backend, cases, schema, version):
    trace = TraceBackend(backend)
    row = {"arm": name, "version": version, "status": "error",
           "model_called": isinstance(backend, LayaBackend),
           "memory_bytes": None, "energy_joules": None, "monetary_cost": None}
    try:
        result = calibrate_signatures(cases, schema=schema, predictor=trace,
                                     predictor_id=name, predictor_version=version)
        row.update(status="ok", metrics=result.to_record())
        durations = sorted(r["elapsed_ms"] for r in trace.rows)
        row["latency_ms"] = {"first": trace.rows[0]["elapsed_ms"],
                             "median": median(durations), "max": max(durations),
                             "median_after_first": median(r["elapsed_ms"] for r in trace.rows[1:]) if len(trace.rows) > 1 else None}
        # All-case error counts include abstentions; conditional agreement alone
        # would flatter a candidate that only answers easy cases.
        correct = 0
        raw_correct = 0
        brier = []
        for case, record in zip(cases, trace.rows):
            answer = record["answers"]["kind"]
            probs = answer["probabilities"]
            raw_correct += answer["choice"] == case.kind
            correct += answer["choice"] == case.kind and probs[answer["choice"]] >= schema.min_kind_confidence
            brier.append(sum((p - (1 if key == case.kind else 0)) ** 2 for key, p in probs.items()))
        row["kind_correct_and_covered"] = correct
        row["kind_raw_correct"] = raw_correct
        row["kind_errors_or_abstentions"] = len(cases) - correct
        row["kind_brier"] = sum(brier) / len(brier)
    except Exception as exc:
        # Errors can contain paths, prompts or credentials. Preserve type only.
        row["error_type"] = type(exc).__name__
    row["traces"] = trace.rows
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/local-decision-pilot/report.json"))
    parser.add_argument("--laya", action="store_true", help="download/load pinned weights and run real inference")
    parser.add_argument("--revision", help="immutable 40-character Hugging Face commit")
    parser.add_argument("--jeff", action="store_true", help="load cached pinned Jeff Qwen 0.8B on CPU")
    parser.add_argument("--jeff-revision", help="immutable Jeff checkpoint SHA")
    parser.add_argument("--jeff-runtime-revision", help="immutable installed Jeff SDK git SHA")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args(argv)
    if args.laya and not args.revision:
        parser.error("--laya requires --revision")
    if args.jeff and (not args.jeff_revision or not args.jeff_runtime_revision):
        parser.error("--jeff requires checkpoint and runtime revisions")
    if args.jeff and args.laya:
        parser.error("run neural arms in separate processes to keep memory measurements comparable")
    if args.jeff and args.device != "cpu":
        parser.error("the Jeff pilot supports CPU only")
    schema = example_schema()
    training = aligned_cases()
    cases = tuple(c for c in paraphrase_cases() if c.case_id in FRENCH_IDS)
    assert not {c.prompt for c in cases} & {c.prompt for c in training}
    arms = [("rule.keyword", RuleBasedSignatureBackend(schema), "1"),
            ("frame.verb-object", VerbFrameSignatureBackend(schema), "1"),
            ("knn.aligned", KnnSignatureBackend(memory_from_cases(training, schema)), "1")]
    report = {"kind": "local_decision_pilot", "schema_version": 1,
              "data_origin": "fixture", "claim_allowed": False, "auto_act_allowed": False,
              "python": platform.python_version(), "platform": platform.platform(),
              "evaluation_cases": [asdict(c) for c in cases],
              "training_case_ids": [c.case_id for c in training],
              "schema": schema.to_record(), "arms": []}
    corpus = json.dumps(report["evaluation_cases"], ensure_ascii=False, sort_keys=True).encode()
    report["corpus_sha256"] = sha256(corpus).hexdigest()
    for name, backend, version in arms:
        report["arms"].append(run_arm(name, backend, cases, schema, version))
    if args.laya:
        before = perf_counter()
        memory_before = process_memory()
        try:
            backend = LayaBackend.load(revision=args.revision, allow_download=True,
                                       device=args.device, max_calls=len(cases))
            load_ms = (perf_counter() - before) * 1000
            row = run_arm(backend.backend_id, backend, cases, schema, args.revision)
            row.update(load_ms=load_ms, runtime_version=backend.runtime_version,
                       device_requested=args.device, device_actual=backend.device,
                       process_memory_before_load=memory_before, process_memory_after_inference=process_memory(),
                       packages={name: package_version(name) for name in
                                 ("laya", "torch", "transformers", "huggingface-hub", "safetensors")})
        except Exception as exc:
            row = {"arm": "laya.sdk.multilingual@1", "status": "unavailable",
                   "revision": args.revision, "error_type": type(exc).__name__}
        report["arms"].append(row)
    else:
        report["arms"].append({"arm": "laya.sdk.multilingual@1", "status": "not_requested"})
    if args.jeff:
        before = perf_counter()
        memory_before = process_memory()
        try:
            backend = JeffBackend.load(revision=args.jeff_revision,
                                       runtime_revision=args.jeff_runtime_revision,
                                       allow_load=True, max_calls=len(cases))
            load_ms = (perf_counter() - before) * 1000
            row = run_arm(backend.backend_id, backend, cases, schema, args.jeff_revision)
            row.update(load_ms=load_ms, runtime_version=backend.runtime_version,
                       runtime_revision=backend.runtime_revision, model=backend.model,
                       device_actual=backend.device, device_requested="cpu",
                       process_memory_before_load=memory_before, process_memory_after_inference=process_memory(),
                       packages={name: package_version(name) for name in
                                 ("jeff", "torch", "transformers", "huggingface-hub", "safetensors")})
        except Exception as exc:
            row = {"arm": JeffBackend.backend_id, "status": "unavailable",
                   "revision": args.jeff_revision, "runtime_revision": args.jeff_runtime_revision,
                   "error_type": type(exc).__name__}
        report["arms"].append(row)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(cases), "output": str(args.output),
                      "arms": [{k: v for k, v in row.items() if k in
                                ("arm", "status", "kind_correct_and_covered", "kind_errors_or_abstentions", "error_type")}
                               for row in report["arms"]]}, indent=2))
    return 1 if any(r["status"] in ("error", "unavailable") for r in report["arms"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
