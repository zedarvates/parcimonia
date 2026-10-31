"""Versioned metadata prefilter. No execution, permission or automatic discovery.

Verified claims need a separate host attestation. A publisher cannot make its
own metadata trusted by writing status='verified'. Snapshots contain no secrets.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from .decision_json import canonical_json

SCHEMA_VERSION = 1
TAXONOMY_VERSION = "execution-tags/1"
TAXONOMY = {
    "domains": frozenset({"code", "research", "image", "video", "audio", "3d", "documents", "data", "administration", "communication", "game", "general"}),
    "operations": frozenset({"search", "read", "analyze", "generate", "modify", "delete", "publish", "send", "execute", "select", "verify"}),
    "environments": frozenset({"windows", "linux", "macos", "browser", "git", "native-app", "python", "server"}),
    "locations": frozenset({"local", "lan", "cloud"}),
    "effects": frozenset({"read", "write", "delete", "external-send", "publish", "process-start", "service-change"}),
    "scopes": frozenset({"workspace", "directory", "account", "system", "recipient"}),
    "data_classes": frozenset({"public", "private", "secret"}),
    "network": frozenset({"offline", "lan", "internet"}),
    "resources": frozenset({"cpu", "gpu", "ram-heavy", "vram-heavy", "paid"}),
    "availability": frozenset({"available", "unavailable"}),
}
FLEXIBLE_FACETS = frozenset({"input_formats", "output_formats"})
FACETS = frozenset(TAXONOMY) | FLEXIBLE_FACETS
_TOKEN = re.compile(r"[a-z0-9][a-z0-9._+/-]*\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def digest(value: Any) -> str:
    """Canonical JSON SHA-256; distinct from the source bytes hash."""
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_digest(content: bytes) -> str:
    if not isinstance(content, bytes):
        raise TypeError("source content must be bytes")
    return sha256(content).hexdigest()


def _text(value, label):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be a nonempty trimmed string")


def _keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"invalid {label} fields")


def _hash(value):
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError("expected lowercase SHA-256")


def _stamp(value):
    _text(value, "observed_at")
    if datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is None:
        raise ValueError("observed_at needs timezone")


def _tags(facet, tags):
    if not isinstance(tags, list) or not all(isinstance(t, str) and _TOKEN.fullmatch(t) for t in tags):
        raise ValueError(f"invalid tags for {facet}")
    if len(set(tags)) != len(tags):
        raise ValueError("duplicate tags")
    if facet in TAXONOMY and not set(tags) <= TAXONOMY[facet]:
        raise ValueError(f"unknown tag in {facet}")


def validate_claim(facet, claim):
    if facet not in FACETS:
        raise ValueError(f"unknown facet {facet}")
    _keys(claim, {"status", "tags", "source", "observed_at", "evidence"}, "claim")
    if claim["status"] not in {"unknown", "declared", "verified"}:
        raise ValueError("invalid claim status")
    _text(claim["source"], "source")
    _stamp(claim["observed_at"])
    if claim["status"] == "unknown":
        if claim["tags"] is not None or claim["evidence"] is not None:
            raise ValueError("unknown claim must have null tags and evidence")
    else:
        _tags(facet, claim["tags"])
        if claim["status"] == "verified":
            _text(claim["evidence"], "evidence")
        elif claim["evidence"] is not None:
            _text(claim["evidence"], "evidence")


def validate_profile(profile):
    _keys(profile, {"schema_version", "taxonomy_version", "id", "kind", "revision",
                    "content_sha256", "facets", "dependencies"}, "profile")
    if type(profile["schema_version"]) is not int or profile["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported profile schema")
    if profile["taxonomy_version"] != TAXONOMY_VERSION:
        raise ValueError("unsupported taxonomy")
    for key in ("id", "revision"):
        _text(profile[key], key)
    _hash(profile["content_sha256"])
    if profile["kind"] not in {"tool", "skill", "mechanism"}:
        raise ValueError("invalid profile kind")
    if not isinstance(profile["facets"], dict):
        raise ValueError("facets must be an object")
    for facet, claim in profile["facets"].items():
        validate_claim(facet, claim)
    if not isinstance(profile["dependencies"], list):
        raise ValueError("dependencies must be a list")
    if len(profile["dependencies"]) > 32:
        raise ValueError("profile exceeds 32 direct dependencies")
    seen = set()
    for dependency in profile["dependencies"]:
        _keys(dependency, {"id", "revision", "profile_sha256"}, "dependency")
        _text(dependency["id"], "dependency id")
        _text(dependency["revision"], "dependency revision")
        _hash(dependency["profile_sha256"])
        if dependency["id"] in seen:
            raise ValueError("duplicate dependency")
        seen.add(dependency["id"])


def claim_attestation(profile, facet):
    """Host approval of one exact property, bound to source and full profile.

    A digest is not a signature. Only the host may supply the trusted set.
    """
    validate_profile(profile)
    if facet not in profile["facets"]:
        raise ValueError("missing facet")
    return digest({"profile_sha256": digest(profile), "facet": facet})


def _policy(policy):
    _keys(policy, {"version", "required", "allowed", "require_verified"}, "policy")
    _text(policy["version"], "policy version")
    if type(policy["require_verified"]) is not bool:
        raise ValueError("require_verified must be boolean")
    for mode in ("required", "allowed"):
        if not isinstance(policy[mode], dict):
            raise ValueError("policy facets must be objects")
        for facet, tags in policy[mode].items():
            if facet not in FACETS:
                raise ValueError("unknown policy facet")
            _tags(facet, tags)


class ExecutionCatalog:
    """One immutable snapshot. Missing profiles/dependencies fail closed."""

    def __init__(self, version: str, profiles: Sequence[Mapping[str, Any]]):
        _text(version, "catalog version")
        records = [deepcopy(dict(p)) for p in profiles]
        if len(records) > 512:
            raise ValueError("catalog exceeds 512 profiles")
        for profile in records:
            validate_profile(profile)
        if len({p["id"] for p in records}) != len(records):
            raise ValueError("duplicate profile id")
        self._snapshot = canonical_json({"schema_version": SCHEMA_VERSION,
                                        "taxonomy_version": TAXONOMY_VERSION,
                                        "catalog_version": version, "profiles": records})

    def to_record(self):
        return json.loads(self._snapshot)

    @property
    def snapshot_hash(self):
        return digest(self.to_record())

    def profile(self, identifier):
        for profile in self.to_record()["profiles"]:
            if profile["id"] == identifier:
                return profile
        raise ValueError(f"unknown profile {identifier}")

    def reference(self, identifier):
        profile = self.profile(identifier)
        return {"id": identifier, "revision": profile["revision"],
                "content_sha256": profile["content_sha256"], "profile_sha256": digest(profile),
                "catalog_sha256": self.snapshot_hash,
                "schema_version": SCHEMA_VERSION, "taxonomy_version": TAXONOMY_VERSION}

    def assess(self, identifiers, policy, *, observed_content, trusted_claims=()):
        """Match tags, exact current source hashes and pinned dependency closure.

        required = all requested tags must be provided; allowed = every possible
        exposure must be allowed. Missing/unknown is never an empty tag set.
        Scope tags are categories, not path/recipient enforcement.
        """
        _policy(policy)
        ids = list(identifiers)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate requested ids")
        for identifier in ids:
            _text(identifier, "requested id")
        trusted = frozenset(trusted_claims)
        for value in trusted:
            _hash(value)
        observed = dict(observed_content)
        for identifier, value in observed.items():
            _text(identifier, "observed id")
            _hash(value)
        profiles = {p["id"]: p for p in self.to_record()["profiles"]}
        visits = 0

        def check(identifier, stack):
            nonlocal visits
            visits += 1
            if visits > 4096:
                return [f"{identifier}:dependency_budget_exceeded"]
            if len(stack) >= 16:
                return [f"{identifier}:dependency_depth_exceeded"]
            if identifier in stack:
                return [f"{identifier}:dependency_cycle"]
            if identifier not in profiles:
                return [f"{identifier}:missing_profile"]
            profile = profiles[identifier]
            reasons = []
            if observed.get(identifier) != profile["content_sha256"]:
                reasons.append(f"{identifier}:content_unobserved_or_changed")
            required = policy["required"] if not stack else {
                k: v for k, v in policy["required"].items() if k == "availability"}
            for facet in sorted(set(required) | set(policy["allowed"])):
                claim = profile["facets"].get(facet)
                if claim is None or claim["status"] == "unknown":
                    reasons.append(f"{identifier}:{facet}:unknown")
                    continue
                if policy["require_verified"] and (claim["status"] != "verified" or
                        claim_attestation(profile, facet) not in trusted):
                    reasons.append(f"{identifier}:{facet}:not_host_verified")
                tags = set(claim["tags"])
                if not set(required.get(facet, [])) <= tags:
                    reasons.append(f"{identifier}:{facet}:required_missing")
                if facet in policy["allowed"] and not tags <= set(policy["allowed"][facet]):
                    reasons.append(f"{identifier}:{facet}:exposure_not_allowed")
            for dependency in profile["dependencies"]:
                if visits > 4096:
                    reasons.append(f"{identifier}:dependency_budget_exceeded")
                    break
                child = profiles.get(dependency["id"])
                if child is None or child["revision"] != dependency["revision"] or digest(child) != dependency["profile_sha256"]:
                    reasons.append(f"{identifier}:dependency_changed_or_missing:{dependency['id']}")
                else:
                    reasons.extend(check(dependency["id"], stack + (identifier,)))
            return sorted(set(reasons))

        decisions = [{"id": identifier, "reasons": check(identifier, ())} for identifier in ids]
        return {"schema_version": 1, "catalog_sha256": self.snapshot_hash,
                "policy": deepcopy(policy), "policy_sha256": digest(policy),
                "observed_content": observed, "trusted_claims": sorted(trusted),
                "decisions": decisions,
                "eligible_ids": [d["id"] for d in decisions if not d["reasons"]],
                "auto_act_allowed": False}

    def bind_invocation(self, identifier, arguments, *, assessment, policy, observed_content,
                        trusted_claims=(), call_facets=None, trusted_call_claims=()):
        """Record a proposal bound to arguments, profile and effective effects.

        Narrowing broad tool effects requires host-attested call facts bound to
        the exact arguments and full profile. No raw arguments are retained.
        """
        if assessment["catalog_sha256"] != self.snapshot_hash:
            raise ValueError("assessment belongs to another catalog")
        ids = [d["id"] for d in assessment["decisions"]]
        fresh = self.assess(ids, policy, observed_content=observed_content, trusted_claims=trusted_claims)
        if fresh != assessment or identifier not in fresh["eligible_ids"]:
            raise ValueError("ineligible or modified assessment")
        profile = self.profile(identifier)
        args_hash = digest(arguments)
        trusted_call_claims = tuple(trusted_call_claims)
        effective = deepcopy(profile["facets"])
        if call_facets is not None and not isinstance(call_facets, dict):
            raise ValueError("call facets must be an object")
        call_facets = deepcopy(call_facets if call_facets is not None else {})
        for key in trusted_call_claims:
            _hash(key)
        for facet, claim in call_facets.items():
            validate_claim(facet, claim)
            if facet not in {"effects", "scopes", "data_classes", "network"}:
                raise ValueError("unsupported call facet")
            key = call_attestation(self.reference(identifier), args_hash, facet, claim)
            if claim["status"] != "verified" or key not in trusted_call_claims:
                raise ValueError("call claim not host verified")
            effective[facet] = claim
        # Apply constraints again after call-specific effects are known.
        for mode in ("required", "allowed"):
            for facet, tags in fresh["policy"][mode].items():
                claim = effective.get(facet)
                if claim is None or claim["tags"] is None:
                    raise ValueError("unknown call facet")
                actual = set(claim["tags"])
                if (mode == "required" and not set(tags) <= actual) or (mode == "allowed" and not actual <= set(tags)):
                    raise ValueError("call facets violate policy")
        record = {"schema_version": 1, "profile_ref": self.reference(identifier),
                  "arguments_sha256": args_hash, "assessment_sha256": digest(assessment),
                  "effective_facets": effective, "call_facets": call_facets,
                  "call_attestations": sorted(trusted_call_claims),
                  "auto_act_allowed": False, "status": "proposed"}
        record["invocation_sha256"] = digest(record)
        return record

    def replay_invocation(self, record, arguments, *, assessment, policy, observed_content,
                          trusted_claims=(), trusted_call_claims=()):
        """Check an old proposal against an exact snapshot and current host facts."""
        expected = self.bind_invocation(record["profile_ref"]["id"], arguments,
            assessment=assessment, policy=policy, observed_content=observed_content,
            trusted_claims=trusted_claims, call_facets=record["call_facets"],
            trusted_call_claims=trusted_call_claims)
        return expected == record


def call_attestation(profile_ref, arguments_sha256, facet, claim):
    _hash(arguments_sha256)
    validate_claim(facet, claim)
    return digest({"profile_ref": profile_ref, "arguments_sha256": arguments_sha256,
                   "facet": facet, "claim": claim})


def load_execution_catalog(path):
    """Strict JSON loader, including duplicate-key and non-finite rejection."""
    from pathlib import Path
    from .registry import _reject_constant, _reject_duplicate_keys

    record = json.loads(Path(path).read_text(encoding="utf-8"),
                        parse_constant=_reject_constant, object_pairs_hook=_reject_duplicate_keys)
    _keys(record, {"schema_version", "taxonomy_version", "catalog_version", "profiles"}, "catalog")
    if type(record["schema_version"]) is not int or record["schema_version"] != SCHEMA_VERSION or record["taxonomy_version"] != TAXONOMY_VERSION:
        raise ValueError("unsupported catalog schema or taxonomy")
    if not isinstance(record["profiles"], list):
        raise ValueError("profiles must be a list")
    return ExecutionCatalog(record["catalog_version"], record["profiles"])
