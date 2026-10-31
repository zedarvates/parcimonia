"""Offline demonstration of declared tags, strict filtering and invocation replay.

Only repository-local fixture sources are read. No model or selected skill runs.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from tiberium_ai.agent_recipes.core import DecisionSession
from tiberium_ai.decision_json import canonical_json
from tiberium_ai.execution_profiles import (
    ExecutionCatalog, SCHEMA_VERSION, TAXONOMY_VERSION, content_digest, digest,
    load_execution_catalog,
)
from tiberium_ai.profiled_selection import select_profiled_skill

ROOT = Path(__file__).resolve().parents[1]


def build():
    sources = {
        "tool:fixture-table": ROOT / "src/tiberium_ai/decision_gym.py",
        "skill:fixture-review": ROOT / "examples/fixtures/skills/offline_table_review/SKILL.md",
    }
    observed = {identifier: content_digest(path.read_bytes()) for identifier, path in sources.items()}
    values = {"domains": ["data"], "operations": ["analyze", "verify"],
        "environments": ["python"], "locations": ["local"], "effects": ["read"],
        "scopes": ["workspace"], "data_classes": ["public"], "network": ["offline"],
        "resources": ["cpu"], "input_formats": ["json"], "output_formats": ["json"],
        "availability": ["available"]}
    profiles = []
    for identifier, path in sources.items():
        facets = {facet: {"status": "declared", "tags": tags,
            "source": "repository-fixture:" + path.relative_to(ROOT).as_posix(),
            "observed_at": "2026-10-20T00:00:00+02:00", "evidence": None}
            for facet, tags in values.items()}
        profiles.append({"schema_version": SCHEMA_VERSION, "taxonomy_version": TAXONOMY_VERSION,
            "id": identifier, "kind": identifier.split(":")[0], "revision": "fixture/1",
            "content_sha256": observed[identifier], "facets": facets,
            "dependencies": [] if not profiles else [{"id": profiles[0]["id"],
                "revision": profiles[0]["revision"], "profile_sha256": digest(profiles[0])}]})
    catalog = ExecutionCatalog("fixture-execution-profiles/1", profiles)
    policy = {"version": "fixture-local-read/1", "required": {"domains": ["data"],
        "availability": ["available"]}, "allowed": {"locations": ["local"], "effects": ["read"],
        "network": ["offline"], "data_classes": ["public"], "scopes": ["workspace"]},
        "require_verified": False}
    return catalog, observed, policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.relative_to((ROOT / "runs").resolve())
    catalog, observed, policy = build()
    identifier = "skill:fixture-review"
    assessment = catalog.assess([identifier], policy, observed_content=observed)
    invocation = catalog.bind_invocation(identifier, {"fixture": "table-review/1"},
        assessment=assessment, policy=policy, observed_content=observed)
    strict_policy = dict(policy, require_verified=True)
    strict = catalog.assess([identifier], strict_policy, observed_content=observed)
    proposal, selection = select_profiled_skill("review fixture table", [{"id": "fixture-review",
        "name": "fixture-review", "description": "Review a synthetic table"}], DecisionSession(),
        catalog=catalog, bindings={"fixture-review": identifier}, policy=policy,
        observed_content=observed, explicit_id="fixture-review")
    output.mkdir(parents=True, exist_ok=False)
    (output / "catalog.json").write_text(canonical_json(catalog.to_record()), encoding="utf-8")
    restored = load_execution_catalog(output / "catalog.json")
    replay_ok = restored.replay_invocation(invocation, {"fixture": "table-review/1"},
        assessment=assessment, policy=policy, observed_content=observed)
    report = {"data_origin": "fixture", "declared_assessment": assessment,
        "strict_assessment": strict, "invocation": invocation,
        "skill_selection": selection, "skill_proposal": proposal.to_dict(),
        "replay_matches": replay_ok, "auto_act_allowed": False,
        "execution": "not_run", "limits": ["tags declared only", "no independent semantic attestation",
                                              "no installed catalog migrated"]}
    (output / "report.json").write_text(canonical_json(report), encoding="utf-8")
    print(f"declared={len(assessment['eligible_ids'])} strict={len(strict['eligible_ids'])} replay={replay_ok}")


if __name__ == "__main__":
    main()
