"""Bounded local source retrieval. Scores are lexical, never probabilities.

This self-contained entry point can ship in a plugin without importing the
larger decision runtime. Inputs are supplied documents, not filesystem paths.
"""
from __future__ import annotations

import ast
from collections import Counter, OrderedDict
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
import unicodedata

REVISION = "parcimonia.context-selection/2"
MAX_FILES = 128
MAX_FILE_BYTES = 262144
MAX_TOTAL_BYTES = 16 * 1024 * 1024
STOP = set("the a an and or of in to for from with where how is are be this that which as on at by it its find including before after".split())
STOP.update("le la les de des du un une en dans pour avec sur sont est comment ou qui que ses leurs par aux trouver retrouver chercher".split())
# Closed lexical aliases only. No semantic translation or confidence model.
# Negations are deliberately retained as terms; the proposal stays advisory.
ALIASES = {
    "fichier": "file", "fichiers": "file", "files": "file",
    "reponse": "response", "reponses": "response", "responses": "response",
    "modele": "model", "modeles": "model", "models": "model",
    "contexte": "context", "contextes": "context",
    "donnee": "data", "donnees": "data", "contenu": "content",
    "profil": "profile", "profils": "profile", "profiles": "profile",
    "attestations": "attestation", "hote": "host", "hotes": "host",
    "verifie": "verified", "verifies": "verified", "verifiees": "verified",
    "validation": "validate", "valider": "validate", "controle": "validate", "controlees": "validate",
    "test": "test", "tests": "test", "regressions": "regression",
    "execution": "execution", "executer": "execute",
    "relecture": "reread", "relire": "reread", "rereading": "reread",
    "modifie": "changed", "modifies": "changed", "modifiees": "changed",
    "suivi": "followup", "note": "note", "notes": "note",
    "obsolete": "stale", "obsoletes": "stale", "perime": "stale", "perimes": "stale",
    "reference": "reference", "references": "reference",
    "locales": "local", "locaux": "local", "locale": "local",
    "manquant": "missing", "manquants": "missing", "manquantes": "missing",
    "schema": "schema", "schemas": "schema", "erreur": "error", "erreurs": "error", "errors": "error",
    "mesure": "measurement", "mesures": "measurement", "measurements": "measurement",
    "octet": "bytes", "octets": "bytes", "byte": "bytes",
    "restauration": "restore", "restitution": "restore", "restoring": "restore",
    "demarrage": "startup", "froid": "cold", "chaud": "warm",
    "memoire": "memory", "conseiller": "advisor", "additionner": "sum",
    "distinctes": "separate", "distincts": "separate", "graphiques": "gpu", "gpus": "gpu",
    "lecture": "read", "lire": "read", "ecriture": "write", "ecrire": "write",
    "cout": "cost", "couts": "cost", "vitesse": "speed", "budget": "budget",
}


def terms(text):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = unicodedata.normalize("NFKD", text).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return [ALIASES.get(token, token) for token in re.findall(r"[a-z0-9]+", text)
            if len(token) >= 2 and token not in STOP]


def source_path(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        raise ValueError("Invalid relative source path")
    path = PurePosixPath(value)
    if (path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in value.split("/"))
            or "\\" in value or ":" in value or any(ord(c) < 32 for c in value)):
        raise ValueError("Source path must stay relative")
    return value


def validate_documents(documents):
    if not isinstance(documents, list) or len(documents) > MAX_FILES:
        raise ValueError("At most 128 documents")
    seen, total = set(), 0
    for document in documents:
        if not isinstance(document, dict) or set(document) != {"id", "path", "text", "content_sha256"}:
            raise ValueError("Invalid document fields")
        ident = document["id"]
        if (not isinstance(ident, str) or not 1 <= len(ident) <= 768
                or ident in seen or any(ord(c) < 32 for c in ident)):
            raise ValueError("Unique short document id required")
        seen.add(ident)
        source_path(document["path"])
        if not isinstance(document["text"], str):
            raise ValueError("Document text required")
        raw = document["text"].encode("utf-8")
        total += len(raw)
        if len(raw) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("Document byte budget exceeded")
        if hashlib.sha256(raw).hexdigest() != document["content_sha256"]:
            raise ValueError("Document hash mismatch")
    return total


def symbols(text, path):
    if not path.endswith(".py"):
        return []
    try:
        tree = ast.parse(text, filename="<provided-text>")
        return sorted({node.name for node in ast.walk(tree)
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))})[:256]
    except (SyntaxError, ValueError, RecursionError):
        return []


def _derive(document):
    body = Counter(terms(document["text"]))
    path_terms = set(terms(document["path"]))
    names = symbols(document["text"], document["path"])
    name_terms = [(name, set(terms(name))) for name in names]
    symbol_terms = set().union(*(value for _, value in name_terms)) if name_terms else set()
    return body, path_terms, symbol_terms, name_terms


class ContextSelector:
    """Bounded ephemeral derived-data cache, with no source text or queries.

    Every call still validates all exact document bytes. Reuse depends on path,
    content hash and normalizer revision; content or path changes recompute.
    """
    def __init__(self, *, max_cache_bytes=4 * 1024 * 1024, max_entries=128):
        if (type(max_cache_bytes) is not int or not 0 <= max_cache_bytes <= 16 * 1024 * 1024
                or type(max_entries) is not int or not 0 <= max_entries <= 128):
            raise ValueError("Invalid derived-data cache budget")
        self.max_cache_bytes, self.max_entries = max_cache_bytes, max_entries
        self.cache, self.cache_bytes = OrderedDict(), 0
        self.hits = self.misses = 0

    def derive(self, document):
        key = hashlib.sha256((REVISION + "\0" + document["path"] + "\0" + document["content_sha256"]).encode()).hexdigest()
        if key in self.cache:
            self.hits += 1
            entry = self.cache.pop(key)
            self.cache[key] = entry
            return entry[0]
        self.misses += 1
        derived = _derive(document)
        body, paths, symbols_, names = derived
        payload = [dict(body), sorted(paths), sorted(symbols_), [(name, sorted(values)) for name, values in names]]
        size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + len(key)
        if self.max_entries and size <= self.max_cache_bytes:
            while self.cache and (self.cache_bytes + size > self.max_cache_bytes or len(self.cache) >= self.max_entries):
                _, (_, removed) = self.cache.popitem(last=False)
                self.cache_bytes -= removed
            self.cache[key] = (derived, size)
            self.cache_bytes += size
        return derived

    def select(self, query, documents, *, top_k=5, max_selected_bytes=512 * 1024):
        before = self.hits, self.misses
        value = select_context(query, documents, top_k=top_k, max_selected_bytes=max_selected_bytes, _cache=self)
        value["metrics"].update(derived_cache_hits=self.hits - before[0], derived_cache_misses=self.misses - before[1],
                                derived_cache_payload_bytes=self.cache_bytes, derived_cache_entries=len(self.cache))
        return value


def select_context(query, documents, *, top_k=5, max_selected_bytes=512 * 1024, _cache=None):
    """Return source references; never return or persist whole file contents.

    Uses inverse document frequency with length normalization and explicit
    path/symbol matches. Budget skips are reported, never silently truncated.
    """
    total = validate_documents(documents)
    if not isinstance(query, str) or not query.strip() or len(query.encode("utf-8")) > 16000:
        raise ValueError("Query must contain 1..16000 UTF-8 bytes")
    if type(top_k) is not int or not 1 <= top_k <= 16:
        raise ValueError("top_k must be 1..16")
    if type(max_selected_bytes) is not int or not 1 <= max_selected_bytes <= MAX_TOTAL_BYTES:
        raise ValueError("Invalid selected-source byte budget")
    wanted = set(terms(query))
    rows, frequencies = [], Counter()
    for document in documents:
        body, path_terms, symbol_terms, names = _cache.derive(document) if _cache is not None else _derive(document)
        frequencies.update(set(body) | path_terms | symbol_terms)
        rows.append((document, body, path_terms, symbol_terms, names))
    average = sum(sum(body.values()) for _, body, _, _, _ in rows) / max(1, len(rows))
    ranked = []
    for document, body, path_terms, symbol_terms, names in rows:
        matched = wanted & (set(body) | path_terms | symbol_terms)
        if not matched:
            continue
        length = sum(body.values())
        score = 0.0
        for token in matched:
            idf = math.log(1 + (len(rows) - frequencies[token] + .5) / (frequencies[token] + .5))
            count = body[token]
            normal = count * 2.2 / (count + 1.2 * (.25 + .75 * length / max(1, average)))
            score += idf * (normal + 2 * (token in path_terms) + (token in symbol_terms))
        ranked.append({"id": document["id"], "path": document["path"],
                       "content_sha256": document["content_sha256"], "score": round(score, 6),
                       "matched_terms": sorted(matched),
                       "matched_symbols": [name for name, tokens in names if wanted & tokens][:8],
                       "source_bytes": len(document["text"].encode("utf-8"))})
    ranked.sort(key=lambda row: (-row["score"], row["id"]))
    selected, omitted, used = [], [], 0
    for row in ranked:
        reason = "file_count_budget" if len(selected) >= top_k else (
            "source_byte_budget" if used + row["source_bytes"] > max_selected_bytes else None)
        if reason:
            omitted.append({"id": row["id"], "reason": reason})
        else:
            selected.append(row)
            used += row["source_bytes"]
    return {"schema": "parcimonia.context-selection/v1", "revision": REVISION,
            "status": "proposed" if selected else "abstain", "files": selected,
            "omitted": omitted, "unmatched_count": len(rows) - len(ranked),
            "metrics": {"indexed_files": len(rows), "indexed_source_bytes": total,
                        "selected_source_bytes": used, "model_calls": 0,
                        "billed_tokens_saved": None, "task_completion_gain": None},
            "score_kind": "lexical_not_probability", "requires_agent_review": True,
            "auto_act_allowed": False, "coverage": "supplied_documents_only"}
