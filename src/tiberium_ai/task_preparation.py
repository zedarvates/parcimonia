"""Bounded, local task preparation over a host-curated inventory.

Sources are read and hashed, never imported or executed. Lexical candidates are
proposals, not a semantic selection or evidence of faster task completion.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path, PurePosixPath
import re
from time import perf_counter
import unicodedata

from .decision_json import canonical_json
from .execution_profiles import ExecutionCatalog, content_digest, digest, validate_profile

VERSION = "task-preparation/1"
NORMALIZER = "fr-en-lexical/1"
MAX_FILE_BYTES = 262144
STOP = frozenset("les des une avec pour dans sur du de la le et en un the and with for from to of a an our nos notre".split())
ALIASES = {"outils": "tool", "outil": "tool", "tools": "tool", "profils": "profile", "profil": "profile",
           "profiles": "profile", "versionnes": "version", "versionnement": "version", "versions": "version",
           "dependances": "dependency", "dependencies": "dependency", "verifier": "verify", "verification": "verify",
           "tests": "test", "fichiers": "file", "files": "file", "routes": "route", "skills": "skill",
           "calibration": "calibrate", "contexte": "context", "locaux": "local", "locale": "local"}


def terms(text):
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return sorted({ALIASES.get(t, t) for t in re.findall(r"[a-z0-9]{3,}", text) if t not in STOP})


def _path(roots, reference):
    if not isinstance(reference, dict) or set(reference) != {"root", "path"}:
        raise ValueError("invalid source reference")
    path = PurePosixPath(reference["path"])
    if (not path.parts or path.is_absolute() or ".." in path.parts or "\\" in reference["path"]
            or any(p.startswith(".") or ":" in p or p in {"runs", "node_modules"} for p in path.parts)
            or path.suffix not in {".py", ".md", ".json"}):
        raise ValueError("source path outside supported inventory scope")
    if reference["root"] not in roots:
        return None
    root = Path(roots[reference["root"]]).resolve(strict=True)
    resolved = (root / Path(*path.parts)).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("source escapes declared root")
    return resolved


def validate_inventory(inventory):
    if not isinstance(inventory, dict) or set(inventory) != {"schema_version", "revision", "entries"}:
        raise ValueError("invalid inventory fields")
    if type(inventory["schema_version"]) is not int or inventory["schema_version"] != 1:
        raise ValueError("unsupported inventory schema")
    if not isinstance(inventory["revision"], str) or not inventory["revision"].strip():
        raise ValueError("missing inventory revision")
    if not isinstance(inventory["entries"], list) or not 1 <= len(inventory["entries"]) <= 30:
        raise ValueError("inventory requires 1..30 entries")
    ids = []
    for entry in inventory["entries"]:
        if not isinstance(entry, dict) or set(entry) != {"profile", "source", "symbol", "description", "related_files"}:
            raise ValueError("invalid inventory entry")
        validate_profile(entry["profile"])
        ids.append(entry["profile"]["id"])
        if not isinstance(entry["description"], str) or not entry["description"].strip():
            raise ValueError("missing description")
        if entry["symbol"] is not None and (not isinstance(entry["symbol"], str) or not entry["symbol"]):
            raise ValueError("invalid symbol")
        if not isinstance(entry["related_files"], list) or len(entry["related_files"]) > 5:
            raise ValueError("at most five related files per capability")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate inventory id")


def build_index(inventory, roots, *, previous=None):
    """Reuse derivations only after reading exact current bytes and matching keys.

    The cache is host-local convenience data, not an authenticated proof. All
    paths still come from the curated inventory, never from a cached record.
    """
    started = perf_counter()
    validate_inventory(inventory)
    prior = {}
    if previous is not None:
        if (not isinstance(previous, dict) or previous.get("version") != VERSION or
                previous.get("normalizer") != NORMALIZER or
                previous.get("payload_sha256") != digest(previous.get("payload"))):
            raise ValueError("invalid index cache")
        prior = {row["cache_key"]: row for row in previous["payload"]["files"]}
    files = {}
    issues = []
    stats = {"files_read": 0, "bytes_read": 0, "derived_reused": 0, "derived_built": 0}

    def read(reference):
        identity = canonical_json(reference)
        if identity in files:
            return files[identity]
        if len(files) >= 128:
            raise ValueError("file budget exceeded")
        path = _path(roots, reference)
        if path is None:
            issues.append({"source": reference, "reason": "root_not_supplied"})
            return None
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
            stats["files_read"] += 1
            stats["bytes_read"] += len(raw)
            if len(raw) > MAX_FILE_BYTES:
                raise ValueError("file_too_large")
            text = raw.decode("utf-8-sig")
        except (OSError, UnicodeError, ValueError) as error:
            issues.append({"source": reference, "reason": type(error).__name__})
            return None
        sha = content_digest(raw)
        key = digest({"version": VERSION, "normalizer": NORMALIZER, "source": reference, "content_sha256": sha})
        cached = prior.get(key)
        if cached is not None:
            derived = deepcopy(cached["derived"])
            stats["derived_reused"] += 1
        else:
            symbols = {}
            if path.suffix == ".py":
                try:
                    tree = ast.parse(text)
                    for node in tree.body:
                        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                            symbols[node.name] = [node.lineno, node.end_lineno]
                            if isinstance(node, ast.ClassDef):
                                for method in node.body:
                                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                        symbols[node.name + "." + method.name] = [method.lineno, method.end_lineno]
                except SyntaxError:
                    issues.append({"source": reference, "reason": "invalid_python"})
            derived = {"terms": terms(text), "symbols": symbols}
            stats["derived_built"] += 1
        row = {"source": deepcopy(reference), "content_sha256": sha, "cache_key": key, "derived": derived}
        files[identity] = row
        return row

    entries = []
    for entry in inventory["entries"]:
        row = read(entry["source"])
        status = "ready"
        location = None
        if row is None:
            status = "source_unavailable"
        elif row["content_sha256"] != entry["profile"]["content_sha256"]:
            status = "source_changed_review_required"
        elif entry["symbol"] is not None:
            location = row["derived"]["symbols"].get(entry["symbol"])
            if location is None:
                status = "symbol_missing"
        related = []
        for reference in entry["related_files"]:
            related_row = read(reference)
            if related_row is not None:
                related.append(deepcopy(reference))
        entries.append({"id": entry["profile"]["id"], "status": status, "source": deepcopy(entry["source"]),
                        "symbol": entry["symbol"], "lines": location, "description": entry["description"],
                        "terms": terms(entry["description"] + " " + (entry["symbol"] or "")), "related_files": related})
    payload = {"inventory_sha256": digest(inventory), "entries": entries, "files": list(files.values()), "issues": issues}
    return {"version": VERSION, "normalizer": NORMALIZER, "payload": payload,
            "payload_sha256": digest(payload), "metrics": {**stats, "wall_seconds": perf_counter() - started}}


def preparation_policy(policy=None, *, strict=False):
    """Validate first, then strengthen strict mode without masking bad input."""
    if type(strict) is not bool:
        raise ValueError("strict must be boolean")
    result = deepcopy(policy if policy is not None else {
        "version": "local-task-preparation-shadow/1",
        "required": {"availability": ["available"]}, "allowed": {"locations": ["local"],
            "effects": ["read"], "network": ["offline"]}, "require_verified": False})
    # Use the public catalogue API for its policy contract, with no candidates.
    ExecutionCatalog("preparation-policy-validation/1", []).assess([], result, observed_content={})
    if strict:
        result["require_verified"] = True
        result["version"] += "+strict"
    return result


def prepare_task(goal, inventory, index, *, policy=None, top_k=5, constraints=(), trusted_claims=()):
    """Return a compact work packet; filtering precedes any lexical ranking."""
    started = perf_counter()
    validate_inventory(inventory)
    if not isinstance(goal, str) or not goal.strip() or len(goal) > 16000:
        raise ValueError("goal must contain 1..16000 characters")
    if type(top_k) is not int or not 1 <= top_k <= 19:
        raise ValueError("top_k must be 1..19")
    constraints = tuple(constraints)
    if any(not isinstance(c, str) or not c.strip() for c in constraints):
        raise ValueError("constraints must be nonempty strings")
    if (index.get("version") != VERSION or index.get("normalizer") != NORMALIZER or
            index["payload_sha256"] != digest(index["payload"]) or
            index["payload"]["inventory_sha256"] != digest(inventory)):
        raise ValueError("index incompatible with inventory")
    policy = preparation_policy(policy)
    catalog = ExecutionCatalog(inventory["revision"], [e["profile"] for e in inventory["entries"]])
    rows = index["payload"]["entries"]
    ready = [r["id"] for r in rows if r["status"] == "ready"]
    current = {e["profile"]["id"]: next((f["content_sha256"] for f in index["payload"]["files"]
        if f["source"] == e["source"]), None) for e in inventory["entries"]}
    current = {key: value for key, value in current.items() if value is not None}
    assessment = catalog.assess(ready, policy, observed_content=current, trusted_claims=trusted_claims)
    allowed = set(assessment["eligible_ids"])
    query = set(terms(goal))
    ranked = []
    review = []
    for row in rows:
        overlap = sorted(query & set(row["terms"]))
        if not overlap:
            continue
        candidate = {key: deepcopy(row[key]) for key in ("id", "source", "symbol", "lines", "description", "related_files")}
        candidate.update(lexical_overlap=len(overlap), matched_terms=overlap)
        if row["id"] in allowed:
            candidate["profile_ref"] = catalog.reference(row["id"])
            ranked.append(candidate)
        else:
            candidate["reason"] = row["status"] if row["status"] != "ready" else "profile_constraints_or_review_required"
            review.append(candidate)
    ranked.sort(key=lambda r: (-r["lexical_overlap"], r["id"]))
    review.sort(key=lambda r: (-r["lexical_overlap"], r["id"]))
    selected = ranked[:top_k]
    references = []
    for candidate in selected:
        for reference in [candidate["source"], *candidate["related_files"]]:
            if reference not in references:
                references.append(reference)
    # Independent file retrieval stays within the same explicit inventory.
    file_matches = []
    for file in index["payload"]["files"]:
        if file["source"]["root"] != "workspace":
            continue
        overlap = query & set(file["derived"]["terms"])
        path_overlap = query & set(terms(file["source"]["path"]))
        if overlap or path_overlap:
            file_matches.append((len(overlap) + 4 * len(path_overlap), file["source"]))
    file_matches.sort(key=lambda row: (-row[0], canonical_json(row[1])))
    for _, reference in file_matches[:5]:
        if reference not in references:
            references.append(reference)
    references = references[:16]
    file_rows = []
    for reference in references:
        file = next(f for f in index["payload"]["files"] if f["source"] == reference)
        file_rows.append({"source": reference, "content_sha256": file["content_sha256"],
                          "role": "suggested_test" if reference["path"].startswith("tests/") else "evidence_to_read"})
    packet = {"version": VERSION, "mode": "shadow", "goal": goal,
        "constraints": list(constraints), "inventory_sha256": digest(inventory),
        "index_sha256": index["payload_sha256"], "catalog_sha256": catalog.snapshot_hash,
        "policy": policy, "assessment": assessment,
        "status": "candidates_proposed" if selected else "needs_agent_review",
        "capabilities": selected, "review_queue": review[:top_k], "files": file_rows,
        "verification_plan": ["Read cited source and applicable instructions before use.",
            "Re-observe source hashes before any action.", "Choose scoped tests after reviewing the change; no tests were run by this preparer."],
        "unknowns": ["semantic relevance unverified", "acceptance criteria require agent/user review",
            "curated inventory only; absence is not absence from the whole workspace"],
        "requires_agent_review": True, "auto_act_allowed": False,
        "model_calls": 0, "execution": "not_run"}
    baseline = {"goal": goal, "entries": rows, "files": index["payload"]["files"]}
    compact = {"goal": goal, "constraints": packet["constraints"], "capabilities": selected,
               "review_queue": packet["review_queue"], "files": file_rows,
               "verification_plan": packet["verification_plan"], "unknowns": packet["unknowns"],
               "auto_act_allowed": False, "requires_agent_review": True}
    packet["metrics"] = {"inventory_entries": len(rows), "eligible_entries": len(allowed),
        "matching_eligible_entries": len(ranked), "shortlisted_entries": len(selected),
        "full_index_context_chars": len(canonical_json(baseline)), "compact_context_chars": len(canonical_json(compact)),
        "preparation_wall_seconds": perf_counter() - started,
        "task_completion_gain": None, "quality": None, "api_cost_savings": None}
    packet["compact_context"] = compact
    return packet


def render_packet(packet):
    """Render observations as data; Markdown cannot authorize executing a command."""
    lines = ["# Paquet de travail Parcimonia", "", "Mode observation ; candidats lexicaux à examiner.",
             "", "Objectif (donnée utilisateur) :", "", "    " + packet["goal"].replace("\n", "\n    "), "",
             "## Contraintes fournies (à examiner)", ""]
    lines.extend("    " + value.replace("\n", "\n    ") for value in packet["constraints"])
    if not packet["constraints"]:
        lines.append("Aucune contrainte libre fournie ; la politique structurée reste appliquée.")
    lines.extend(["", "## Capacités proposées", ""])
    for candidate in packet["capabilities"]:
        lines.append(f"- `{candidate['id']}` — {candidate['source']['path']} ; symbole `{candidate['symbol']}` ; correspondances : {', '.join(candidate['matched_terms'])}")
    if not packet["capabilities"]:
        lines.append("Aucun candidat compatible trouvé ; élargir ou revoir la recherche.")
    lines.extend(["", "## Fichiers à lire et tests suggérés", ""])
    lines.extend(f"- `{f['source']['root']}:{f['source']['path']}` — {f['role']}" for f in packet["files"])
    lines.extend(["", "## À examiner séparément", ""])
    lines.extend(f"- `{r['id']}` — {r['reason']}" for r in packet["review_queue"])
    lines.extend(["", "## Contrôles suggérés", ""])
    lines.extend(f"- {step}" for step in packet["verification_plan"])
    lines.extend(["", "## Limites", "", "Aucune exécution, validation sémantique ou économie de travail démontrée.",
                  "Les contraintes libres restent à examiner par l'agent ; seuls les filtres structurés sont appliqués.",
                  "Les références sont bornées au catalogue fourni. Recontrôler les sources avant action.", ""])
    return "\n".join(lines)
