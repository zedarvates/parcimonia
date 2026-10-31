"""Explicit adapters from execution metadata to existing route/skill selection."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict

from .execution_profiles import digest


def filter_profiled_routes(registry, task, *, catalog, bindings, policy,
                           observed_content, trusted_claims=(), required_capabilities=()):
    """Retain legacy route constraints, then apply execution-profile constraints.

    bindings is supplied by the host: route ID -> execution profile ID. No
    name-based guess or fallback for unprofiled routes is allowed in this mode.
    """
    candidates = registry.candidates_for(task, required_capabilities=required_capabilities)
    ids = list(dict.fromkeys(bindings[c.route_id] for c in candidates if c.route_id in bindings))
    assessment = catalog.assess(ids, policy, observed_content=observed_content, trusted_claims=trusted_claims)
    eligible = set(assessment["eligible_ids"])
    kept = [c for c in candidates if bindings.get(c.route_id) in eligible]
    trace = {"schema_version": 1, "kind": "profiled-route-filter", "registry_version": registry.version,
             "request_sha256": digest({"task_id": task.task_id, "kind": task.kind,
                 "inputs": task.inputs, "risk_class": task.risk_class,
                 "evidence_level": task.evidence_level, "locality": task.locality,
                 "required_capabilities": list(required_capabilities)}),
             "assessment": assessment, "bindings": {c.route_id: bindings.get(c.route_id) for c in candidates},
             "candidate_snapshot": [asdict(c) for c in candidates],
             "eligible_routes": [c.route_id for c in kept],
             "missing_bindings": [c.route_id for c in candidates if c.route_id not in bindings],
             "profile_refs": [catalog.reference(i) for i in ids if i in eligible],
             "auto_act_allowed": False}
    return kept, trace


def select_profiled_skill(query, skills, session, *, catalog, bindings, policy,
                          observed_content, trusted_claims=(), explicit_id=None):
    """Filter before legacy skill selection; preserve its proposal and full audit.

    Raw-byte content hashes must be observed by the host, independently of old
    SkillCatalog hashes (which hash JSON-encoded text). Never equate the two.
    """
    from .agent_recipes.recipes import select_skill

    skills = deepcopy(list(skills))
    ids = [skill["id"] for skill in skills]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate skill id")
    profile_ids = list(dict.fromkeys(bindings[i] for i in ids if i in bindings))
    for identifier in profile_ids:
        try:
            profile = catalog.profile(identifier)
        except ValueError:
            continue  # assess records a missing profile, never permits it.
        if profile["kind"] != "skill":
            raise ValueError("skill binding must refer to a skill profile")
    assessment = catalog.assess(profile_ids, policy, observed_content=observed_content, trusted_claims=trusted_claims)
    eligible = set(assessment["eligible_ids"])
    filtered = [s for s in skills if bindings.get(s["id"]) in eligible]
    for skill in filtered:
        identifier = bindings[skill["id"]]
        skill["execution_profile"] = {"reference": catalog.reference(identifier),
                                      "facets": catalog.profile(identifier)["facets"]}
    proposal = select_skill(query, filtered, session, explicit_id=explicit_id)
    return proposal, {"schema_version": 1, "kind": "profiled-skill-selection",
        "query_sha256": digest(query), "assessment": assessment,
        "bindings": {i: bindings.get(i) for i in ids},
        "eligible_skills": [s["id"] for s in filtered],
        "missing_bindings": [i for i in ids if i not in bindings],
        "profile_refs": [catalog.reference(i) for i in profile_ids if i in eligible],
        "proposal_sha256": digest(proposal.to_dict()), "auto_act_allowed": False}
