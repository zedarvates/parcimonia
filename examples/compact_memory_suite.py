"""Authored A/B/C context experiment using the existing benchmark harness.

No model, paid API, private trace or SwiLA implementation is involved. Context
bytes measure prepared UTF-8 JSON, not tokens or a provider bill. Latency covers
only this local Python experiment; source archive storage is reported separately.

Usage: python examples/compact_memory_suite.py --out runs/compact-memory
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from tiberium_ai.benchmark import BenchmarkCase, BenchmarkRoute, run_benchmark
from tiberium_ai.compact_memory import CompactMemory, MemoryContext, MemoryFact, MemoryLimits, SCHEMA
from tiberium_ai.context_router import ContextShadowRouter
from tiberium_ai.contracts import CandidateRoute, Decision, Task
from tiberium_ai.measurement import Environment
from tiberium_ai.router import ShadowRouter
from tiberium_ai.verification import VerifierRegistry, hash_input

VARIANTS = ("full_history", "compact", "compact_persistent")
FACT_VERIFIER = "authored-memory-facts"
VERSION = "1"
LIMITS = MemoryLimits(max_entities=2, max_refs_per_entity=4, max_context_bytes=4096)
# Independent exact facts for the deliberately fictional source.
GOLDEN = {
    ("alpha", "v1"): {"budget": 100, "locality": "local"},
    ("alpha", "v2"): {"budget": 80, "locality": "local"},
    ("beta", "v1"): {"budget": 200, "locality": "any"},
}


def encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class Step:
    entity: str = "alpha"
    version: str = "v1"
    a_cost: float = 1.0
    b_cost: float = 1.01
    epoch: str = "tools-v1"
    critical: bool = False
    objective: str = "same"
    restart: bool = False
    unresolved: str | None = None
    cheap_route: bool = False
    allowed_routes: tuple[str | None, ...] = ("a", "b")


@dataclass(frozen=True)
class Scenario:
    name: str
    noise_entries: int
    steps: tuple[Step, ...]


def scenarios() -> tuple[Scenario, ...]:
    first = Step()
    changed = {"a_cost": 1.01, "b_cost": 1.0, "allowed_routes": ("b",)}
    return (
        Scenario("short", 0, (first,)),
        Scenario("small_history", 2, (first, Step(a_cost=1.01, b_cost=1.0))),
        Scenario("long_history", 300, (first, Step(a_cost=1.01, b_cost=1.0))),
        Scenario("jitter", 40, tuple(Step(a_cost=1.0 if i % 2 == 0 else 1.01,
                                              b_cost=1.01 if i % 2 == 0 else 1.0)
                                      for i in range(8))),
        Scenario("version_change", 40, (first, Step(version="v2", **changed))),
        Scenario("homonyms", 40, (first, Step(entity="beta"), Step())),
        Scenario("missing_fact", 40, (first, Step(unresolved="missing", allowed_routes=(None,)))),
        Scenario("rejected_fact", 40, (first, Step(unresolved="rejected", allowed_routes=(None,)))),
        Scenario("unknown_verifier", 40, (first, Step(unresolved="unknown", allowed_routes=(None,)))),
        Scenario("restart", 40, (first, Step(restart=True, **changed))),
        Scenario("critical_change", 40, (first, Step(critical=True, **changed))),
        Scenario("tool_change", 40, (first, Step(epoch="tools-v2", **changed))),
        Scenario("task_change", 40, (first, Step(objective="different", **changed))),
        Scenario("cheap_deterministic", 40, (first, Step(cheap_route=True, allowed_routes=("rule",)))),
    )


def fact_registry() -> VerifierRegistry:
    registry = VerifierRegistry()

    def verify(payload):
        expected = GOLDEN.get((payload["entity_id"], payload["source_version"]), {})
        return payload["key"] in expected and hash_input(payload["value"]) == hash_input(expected[payload["key"]])

    registry.register(FACT_VERIFIER, VERSION, verify)
    return registry


def full_context(source, registry, step: Step) -> MemoryContext:
    """Independent stateless exact retrieval for the full-history baseline."""
    facts, missing = [], []
    for key in ("budget", "locality"):
        fact = source(step.entity, key, step.version)
        if fact is None:
            missing.append({"key": key, "reason": "source_missing"})
            continue
        verification = registry.verify(fact.verifier_id, fact.verifier_version, fact.payload())
        if verification.verdict is True:
            facts.append({"key": key, "value": fact.value, "verification": verification.to_record()})
        else:
            missing.append({"key": key, "reason": verification.detail_code or "verification_rejected"})
    return MemoryContext(encode({"schema": SCHEMA, "entity_id": step.entity,
                                 "source_version": step.version, "facts": facts, "missing": missing}))


def run_scenario(scenario: Scenario, variant: str) -> dict[str, Any]:
    if variant not in VARIANTS:
        raise ValueError("unknown experiment variant")
    # All variants have the same external archive and exact source. The index
    # belongs to that archive, not to bounded working memory.
    history = [{"event": "irrelevant", "index": i, "text": "Past discussion without a requested constraint. " * 4}
               for i in range(scenario.noise_entries)]
    archive: dict[tuple[str, str, str], MemoryFact] = {}
    for (entity, version), values in GOLDEN.items():
        for key, value in values.items():
            item = MemoryFact(entity, key, version, value, FACT_VERIFIER, VERSION)
            archive[entity, key, version] = item
    current = [scenario.steps[0]]
    retrievals = [0]

    def source(entity, key, version):
        retrievals[0] += 1
        step = current[0]
        if key == "budget":
            if step.unresolved == "missing":
                return None
            if step.unresolved == "rejected":
                return MemoryFact(entity, key, version, 9999, FACT_VERIFIER, VERSION)
            if step.unresolved == "unknown":
                return MemoryFact(entity, key, version, GOLDEN[entity, version][key], "unknown", VERSION)
        return archive.get((entity, key, version))

    registry = fact_registry()
    memory = CompactMemory(source, registry, limits=LIMITS)
    persistent = ContextShadowRouter(max_holds=3, relative_cost_margin=0.02, max_entities=2)
    stateless = ShadowRouter()
    records, context_bytes, checkpoints = [], [], []
    switches = 0
    previous_by_entity: dict[str, str | None] = {}
    visible_versions: set[tuple[str, str]] = set()
    for number, step in enumerate(scenario.steps):
        current[0] = step
        if step.restart:
            saved = memory.checkpoint()
            memory = CompactMemory(source, registry, limits=LIMITS)
            memory.restore(saved)
            # Persistence deliberately resets at process restart.
            persistent = ContextShadowRouter(max_holds=3, relative_cost_margin=0.02, max_entities=2)
        task = Task(f"{scenario.name}-{number}", "fixture-choice",
                    {"entity_id": step.entity, "source_version": step.version, "objective": step.objective})
        context = (full_context(source, registry, step) if variant == "full_history"
                   else memory.context(step.entity, step.version, ("budget", "locality")))
        facts = {f["key"]: f["value"] for f in context.to_record()["facts"]}
        missing = [f["key"] for f in context.to_record()["missing"]]
        if (step.entity, step.version) not in visible_versions:
            for key in ("budget", "locality"):
                history.append({"event": "fact", "display_name": "Alex",
                                **archive[step.entity, key, step.version].payload()})
            visible_versions.add((step.entity, step.version))
        history.append({"event": "lookup", "entity_id": step.entity, "source_version": step.version,
                        "facts": facts, "missing": missing})
        envelope = {"task": dict(task.inputs)}
        if variant == "full_history":
            envelope["history"] = history
        else:
            envelope["memory"] = context.to_record()
        context_bytes.append(len(encode(envelope).encode("utf-8")))
        options = [CandidateRoute("a", ("solve",), step.a_cost, confidence=0.95),
                   CandidateRoute("b", ("solve",), step.b_cost, confidence=0.95)]
        if step.cheap_route:
            options.append(CandidateRoute("rule", ("solve", "deterministic"), 0.1, confidence=0.99))
        if not context.complete:
            if variant == "compact_persistent":
                decision = persistent.propose(task, options, context=context, routing_epoch=step.epoch)
            else:
                decision = Decision(task.task_id, None, abstained=True, rationale="Unresolved fixture fact.")
        elif variant == "compact_persistent":
            decision = persistent.propose(task, options, context=context, routing_epoch=step.epoch,
                                          critical_change=step.critical, required_capabilities=("solve",))
        else:
            decision = stateless.propose(task, options, required_capabilities=("solve",))
        selected = decision.selected_route_id
        if step.entity in previous_by_entity and selected != previous_by_entity[step.entity]:
            switches += 1  # abstentions included and shown in the trace
        previous_by_entity[step.entity] = selected
        records.append({"entity_id": step.entity, "source_version": step.version,
                        "facts": facts, "missing": missing,
                        "selected_route": selected, "mode": decision.mode})
        checkpoints.append(memory.checkpoint())
        history.append({"event": "request", "entity_id": step.entity, "source_version": step.version,
                        "objective": step.objective})
    return {"steps": records, "metrics": {
        "prepared_context_utf8_bytes": sum(context_bytes), "peak_context_utf8_bytes": max(context_bytes),
        "context_utf8_bytes_by_step": context_bytes, "route_switches_including_abstentions": switches,
        "source_retrievals": retrievals[0], "external_archive_utf8_bytes": len(encode({
            "history": history, "facts": [f.payload() for f in archive.values()]
        }).encode("utf-8")),
        "peak_working_reference_utf8_bytes": (None if variant == "full_history" else
                                                max(len(encode(c).encode("utf-8")) for c in checkpoints)),
        "tokens": None, "provider_cost": None, "vram_mb": None, "energy_joules": None,
    }}


def scenario_verifier(scenario: Scenario):
    def verify(output):
        if not isinstance(output, dict) or len(output.get("steps", [])) != len(scenario.steps):
            return False
        for actual, step in zip(output["steps"], scenario.steps):
            expected = dict(GOLDEN[step.entity, step.version])
            missing = []
            if step.unresolved:
                expected.pop("budget")
                missing = ["budget"]
            if (actual.get("entity_id") != step.entity or actual.get("source_version") != step.version
                    or hash_input(actual.get("facts")) != hash_input(expected)
                    or actual.get("missing") != missing
                    or actual.get("selected_route") not in step.allowed_routes
                    or actual.get("mode") != "shadow"):
                return False
        return True
    return verify


def build_cases(outputs: dict[str, dict[str, Any]]) -> list[BenchmarkCase]:
    cases = []
    for scenario in scenarios():
        def run(variant, scenario=scenario):
            result = run_scenario(scenario, variant)
            outputs.setdefault(scenario.name, {})[variant] = result
            return result
        routes = tuple(BenchmarkRoute(variant, lambda variant=variant, run=run: run(variant),
                                       confidence=0.95) for variant in VARIANTS)
        cases.append(BenchmarkCase(Task(scenario.name, "memory-fixture", {}), routes,
                                    "authored-sequence-" + scenario.name, VERSION,
                                    scenario_verifier(scenario), "full_history"))
    return cases


def provenance() -> dict[str, Any]:
    modules = ("benchmark", "capture", "compact_memory", "context_router", "contracts",
               "measurement", "observations", "resources", "router", "verification")
    files = {"tiberium_ai." + name: Path(sys.modules["tiberium_ai." + name].__file__)
             for name in modules}
    files["compact_memory_suite"] = Path(__file__)
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}
    fixture = {"scenarios": [asdict(s) for s in scenarios()], "golden": [
        {"entity_id": e, "source_version": v, "facts": facts} for (e, v), facts in GOLDEN.items()
    ]}
    return {"implementation_sha256": hash_input(hashes), "files_sha256": hashes,
            "fixture_sha256": hash_input(fixture)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("runs/compact-memory"))
    parser.add_argument("--seed", type=int, default=20261003)
    args = parser.parse_args(argv)
    outputs: dict[str, dict[str, Any]] = {}
    try:
        report = run_benchmark(build_cases(outputs), out_dir=args.out, seed=args.seed,
                               environment=Environment("authored-memory-runner", {"python": platform.python_version()}),
                               clock=perf_counter, cost_unit="unmeasured-provider-unit",
                               corpus="authored-memory-fixture-v1")
    except FileExistsError as exc:
        print(f"refusing to overwrite existing records in {args.out}: {exc}", file=sys.stderr)
        return 2
    scope = "Prepared UTF-8 JSON and local Python execution only; no model or production saving claim."
    origin = "authored fixture; all cases public; no private held-out usage data"
    production_claim = {"status": "refused", "reason": "no model or real usage measurement"}
    revision = provenance()
    report.update(claim_scope=scope, origin=origin, production_saving_claim=production_claim,
                  provenance=revision)
    (args.out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "schema": "compact-memory-experiment/1", "corpus": "authored-memory-fixture-v1",
        "seed": args.seed, "split": report["split"], "cases": len(outputs),
        "origin": origin, "claim_scope": scope, "production_saving_claim": production_claim,
        "provenance": revision,
        "variants": {}, "traces": outputs, "verifications": {},
    }
    evidence_registry = VerifierRegistry()
    for scenario in scenarios():
        verifier_id = "authored-sequence-" + scenario.name
        evidence_registry.register(verifier_id, VERSION, scenario_verifier(scenario))
        summary["verifications"][scenario.name] = {
            variant: evidence_registry.verify(verifier_id, VERSION, output).to_record()
            for variant, output in outputs[scenario.name].items()
        }
    for variant in VARIANTS:
        metrics = [variants[variant]["metrics"] for variants in outputs.values()]
        summary["variants"][variant] = {
            "accepted": report["routes"][variant]["accepted"],
            "prepared_context_utf8_bytes": sum(m["prepared_context_utf8_bytes"] for m in metrics),
            "route_switches_including_abstentions": sum(m["route_switches_including_abstentions"] for m in metrics),
            "source_retrievals": sum(m["source_retrievals"] for m in metrics),
            "peak_context_utf8_bytes": max(m["peak_context_utf8_bytes"] for m in metrics),
            "peak_working_reference_utf8_bytes": (None if variant == "full_history" else
                                                    max(m["peak_working_reference_utf8_bytes"] for m in metrics)),
        }
    with (args.out / "context-summary.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"traces", "verifications", "provenance"}}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
