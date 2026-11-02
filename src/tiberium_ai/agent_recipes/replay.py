"""Replay one recipe revision on explicit historical and held-out episodes.

This adapter reuses the normal measured/verifier-bound benchmark contracts. It
does not edit skills, choose an active route, schedule work or promote a result.
Callbacks belong to the host: their declared recipe/source binding is not an
attestation that a model followed those instructions or that a source is real.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from time import perf_counter
from typing import Any, Callable, Sequence

from ..benchmark import BenchmarkCase, BenchmarkRoute, BenchmarkSplit, CaseResult, build_report
from ..capture import capture_run
from ..contracts import Task
from ..decision_json import canonical_json
from ..measurement import Environment
from ..resources import ResourceVector
from ..verification import VerifierRegistry, hash_input


MAX_EPISODES = 256
MAX_JSON_BYTES = 262144


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be nonempty and trimmed")
    return value


def _snapshot(value: Any) -> Any:
    raw = canonical_json(value)
    if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("episode JSON exceeds replay byte limit")
    return json.loads(raw)


@dataclass(frozen=True)
class RecipeRevision:
    recipe_id: str
    version: str
    source_text: str = field(repr=False)
    run: Callable[[str, Any], Any] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _text(self.recipe_id, "recipe_id")
        _text(self.version, "recipe version")
        if not isinstance(self.source_text, str) or not self.source_text.strip():
            raise ValueError("recipe source must be nonempty")
        if len(self.source_text.encode("utf-8")) > MAX_JSON_BYTES:
            raise ValueError("recipe source exceeds replay byte limit")
        if not callable(self.run):
            raise TypeError("recipe run must be callable")

    def identity(self) -> dict[str, str]:
        return {"recipe_id": self.recipe_id, "version": self.version,
                "source_sha256": sha256(self.source_text.encode("utf-8")).hexdigest()}


@dataclass(frozen=True)
class RecipeEpisode:
    episode_id: str
    source_group: str
    source_ref: str
    origin: str
    input_value: Any = field(repr=False)
    verifier_id: str
    verifier_version: str
    verifier: Callable[[Any], bool] | None = field(repr=False, compare=False)
    group_reviewed: bool = False

    def __post_init__(self) -> None:
        for name in ("episode_id", "source_group", "source_ref", "verifier_id", "verifier_version"):
            _text(getattr(self, name), name)
        if self.origin not in {"captured", "public", "authored", "caller_reported"}:
            raise ValueError("unsupported declared episode origin")
        if self.verifier is not None and not callable(self.verifier):
            raise TypeError("episode verifier must be callable or null")
        if type(self.group_reviewed) is not bool:
            raise ValueError("group_reviewed must be boolean")
        _snapshot(self.input_value)


def replay_recipe_candidate(
    baseline: RecipeRevision, candidate: RecipeRevision, *,
    historical: Sequence[RecipeEpisode], heldout: Sequence[RecipeEpisode],
    environment: Environment, clock: Callable[[], float] = perf_counter,
    now: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Execute each revision once per episode and retain no raw inputs/outputs.

    Historical and held-out memberships are explicit and preserved. Source
    groups and exact JSON inputs may not cross that boundary. The host supplies
    reviewed grouping for paraphrases and dependencies; exact-hash checking alone
    cannot discover semantic leakage. Each callback receives a fresh JSON copy.

    Calls are bounded by ``2 * MAX_EPISODES``. There are no retries, network
    clients or built-in model calls. Host callbacks still need their own resource,
    permission and process-time limits. Monetary costs remain unknown here;
    attach actual usage through the host's workflow ledger, not fake zero costs.
    """
    if not isinstance(baseline, RecipeRevision) or not isinstance(candidate, RecipeRevision):
        raise TypeError("baseline and candidate must be RecipeRevision instances")
    if not isinstance(environment, Environment):
        raise TypeError("environment must use the existing Environment contract")
    if baseline.recipe_id != candidate.recipe_id:
        raise ValueError("candidate must revise the same recipe")
    if baseline.identity() == candidate.identity():
        raise ValueError("baseline and candidate revisions are identical")
    historical, heldout = list(historical), list(heldout)
    episodes = [*historical, *heldout]
    if not historical or not heldout or len(episodes) > MAX_EPISODES:
        raise ValueError("nonempty historical and heldout sets within episode limit are required")
    if not all(isinstance(e, RecipeEpisode) for e in episodes):
        raise TypeError("episodes must be RecipeEpisode instances")
    if any(e.group_reviewed is not True for e in episodes):
        raise ValueError("source grouping must be explicitly reviewed before replay")
    ids = [e.episode_id for e in episodes]
    if len(ids) != len(set(ids)):
        raise ValueError("episode identifiers must be unique across both sets")
    if {e.source_group for e in historical} & {e.source_group for e in heldout}:
        raise ValueError("source groups overlap historical and heldout sets")
    snapshots = {e.episode_id: _snapshot(e.input_value) for e in episodes}
    historical_hashes = {hash_input(snapshots[e.episode_id]) for e in historical}
    if historical_hashes & {hash_input(snapshots[e.episode_id]) for e in heldout}:
        raise ValueError("duplicate inputs overlap historical and heldout sets")

    split = BenchmarkSplit(tuple(e.episode_id for e in historical), tuple(e.episode_id for e in heldout))
    heldout_ids = set(split.heldout)
    results, records, manifest = [], [], []
    for episode in episodes:
        value = snapshots[episode.episode_id]
        routes = tuple(BenchmarkRoute(arm, lambda revision=revision, value=value:
                       _snapshot(revision.run(revision.source_text, _snapshot(value))))
                       for arm, revision in (("baseline", baseline), ("candidate", candidate)))
        case = BenchmarkCase(Task(episode.episode_id, "recipe-replay", {}), routes,
                             episode.verifier_id, episode.verifier_version,
                             episode.verifier, "baseline")
        registry = VerifierRegistry()
        if case.verifier is not None:
            def verify(output, verifier=case.verifier):
                verdict = verifier(_snapshot(output))
                if type(verdict) is not bool:
                    raise TypeError("recipe verifier must return a boolean")
                return verdict
            registry.register(case.verifier_id, case.verifier_version, verify)
        captured = {}
        for route in case.routes:
            run = capture_run(task_id=case.task.task_id, route_id=route.route_id,
                              run=route.run, verifier_id=case.verifier_id,
                              verifier_version=case.verifier_version, registry=registry,
                              cost_unit="unreported", environment=environment, clock=clock, now=now)
            captured[route.route_id] = run
            records.append({"episode_id": episode.episode_id, "arm": route.route_id,
                            "measurement": run.measurement,
                            "verification": None if run.verification is None else run.verification.to_record()})
        verdicts = {arm: None if run.verification is None else run.verification.verdict
                    for arm, run in captured.items()}
        results.append(CaseResult(episode.episode_id,
                       "heldout" if episode.episode_id in heldout_ids else "development",
                       "verified" if verdicts["candidate"] is True else "not_verified", verdicts,
                       {arm: ResourceVector.from_measurement(run.measurement) for arm, run in captured.items()},
                       {arm: run.measurement["outcome"]["ok"] for arm, run in captured.items()}))
        manifest.append({"episode_id": episode.episode_id, "source_group": episode.source_group,
                         "source_ref": episode.source_ref, "declared_origin": episode.origin,
                         "group_reviewed": episode.group_reviewed,
                         "input_hash": hash_input(value), "verifier_id": episode.verifier_id,
                         "verifier_version": episode.verifier_version})

    report = build_report(results, seed=0, split=split, environment=environment,
                          corpus="declared_recipe_episodes", baseline_route_id="baseline")
    # The generic benchmark may find a latency dominance on authored fixtures.
    # This adapter's source declarations and callback binding cannot certify a
    # deployment saving, so the nested report must refuse that claim too.
    report["claim"] = {"status": "refused", "reason_code": "recipe_replay_requires_reviewed_real_evidence",
                       "detail": "Offline callback timings do not establish a production gain."}
    regressions = [r.task_id for r in results
                   if r.verdicts["baseline"] is True and r.verdicts["candidate"] is not True]
    rejected = [r.task_id for r in results if r.verdicts["candidate"] is False]
    unknown = [r.task_id for r in results if r.verdicts["candidate"] is None]
    improvements = [r.task_id for r in results
                    if r.verdicts["baseline"] is False and r.verdicts["candidate"] is True]
    status = "rejected" if regressions or rejected else "inconclusive" if unknown else "ready_for_review"
    return {"schema": "parcimonia.recipe-replay/v1", "status": status,
            "baseline": baseline.identity(), "candidate": candidate.identity(),
            "corpus_revision": hash_input({"episodes": manifest, "historical": list(split.development),
                                            "heldout": list(split.heldout)}), "episodes": manifest,
            "split": {"historical": list(split.development), "heldout": list(split.heldout),
                      "basis": "caller_reviewed_source_groups_and_exact_input_hashes"},
            "regressions": regressions, "rejected_cases": rejected, "unknown_cases": unknown,
            "improved_cases": improvements, "runs": records, "benchmark": report,
            "claim_allowed": False, "promotion_allowed": False, "auto_act_allowed": False,
            "review_required": True, "total_cost": None,
            "scope": "offline callback comparison; source origins and callback binding are caller-declared"}
