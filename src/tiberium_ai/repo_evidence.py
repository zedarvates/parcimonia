"""Read-only repository evidence retrieval. A lexical match is never a verdict."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from collections.abc import Mapping
from hashlib import sha256
import json
from math import log1p
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import unicodedata

from .evidence_relations import discover

ROLES = ("code", "tests", "docs")
CODE = frozenset(".py .pyi .js .jsx .ts .tsx .mjs .cjs .rs .go .zig .cs .java .kt .cpp .c .h .rb .ps1 .sh .sql .toml .yaml .yml .json .jsonl .xml .html .css .lua .swift .gd".split())
DOCS = frozenset((".md", ".rst", ".txt", ".adoc"))
MAX_FILES = 5_000
MAX_FILE_BYTES = 262_144
MAX_BYTES = 32 * 1024 * 1024
STOP = frozenset(("a an and are as at be by can do for from has have in into is it its of on or "
                  "should the their them then this to was were which will with without would you "
                  "add use existing new preserve make must find file files docs code tests test "
                  "au aux avec ce ces dans de des du elle en est et il la le les leur lui ne ou par "
                  "pas pour que qui se ses son sur un une ajouter utiliser nouveau nouvelle garder").split())
ALIASES = {"catalogue": "catalog", "catalogues": "catalog", "catalogs": "catalog",
           "verification": "verify", "verified": "verify", "verifier": "verifier",
           "verificateur": "verifier", "proof": "evidence", "proofs": "evidence",
           "preuve": "evidence", "preuves": "evidence", "rejeu": "replay",
           "contrainte": "constraint", "contradiction": "contradict",
           "requirements": "requirement", "mesure": "measure",
           "mesures": "measure", "measurement": "measure", "measurements": "measure",
           "capturee": "capture", "captured": "capture"}
PRIVATE = frozenset((".git", ".env", ".venv", "node_modules", "runs", "__pycache__",
                     "credentials", "secrets", "id_rsa", "id_ed25519"))
STRUCTURE = re.compile(r"^\s*(?:async\s+)?(?:def|class|fn|func|function|struct|interface)\s|^#{1,6}\s|^\s*(?:export\s+)?(?:public|private)\s")
MARKDOWN_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
SYMBOL_QUERY = re.compile(r"^@([A-Za-z_][A-Za-z0-9_]*)$")
MAX_GOAL_PARTS = 24
MAX_EXACT_REFERENCES = 8


def _tokens(text):
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text).casefold()
    if not text.isascii():
        text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    out = []
    for word in re.findall(r"[a-z0-9]{2,}", text):
        if word in STOP:
            continue
        if word not in ALIASES and len(word) >= 5 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
            word = word[:-1]
        out.append(ALIASES.get(word, word))
    return out


def _safe_path(name):
    if (not isinstance(name, str) or "\\" in name or ":" in name
            or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in name)):
        return False
    path = PurePosixPath(name)
    return (bool(path.parts) and not path.is_absolute() and path.as_posix() == name
            and path.stem.casefold() not in {"credentials", "secrets", "secret"}
            and not any(p in (".", "..") or p.casefold() in PRIVATE or p.casefold().startswith(".env.")
                        for p in path.parts))


def role_for_path(name):
    """Classify documents first, then test sources and fixtures, then code/config."""
    p = PurePosixPath(name.casefold())
    if p.suffix in DOCS:
        return "docs"
    if p.suffix not in CODE:
        return None
    if (set(p.parts[:-1]) & {"test", "tests", "__tests__", "spec", "specs"}
            or p.stem.startswith(("test_", "test-"))
            or p.stem.endswith(("_test", "-test", ".test", ".spec"))):
        return "tests"
    if set(p.parts[:-1]) & {"docs", "wiki"}:
        return None  # structured reports/examples are not documentation proof
    return "code"


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, timeout=15).stdout


def _read_regular(root, name):
    path = root
    parts = PurePosixPath(name).parts
    for i, part in enumerate(parts):
        path = path / part
        info = path.lstat()
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            return None
        if i + 1 < len(parts) and not stat.S_ISDIR(info.st_mode):
            return None
    if not stat.S_ISREG(info.st_mode):
        return None
    with path.open("rb") as stream:
        return stream.read(MAX_FILE_BYTES + 1)


def read_git_sources(root):
    """Read tracked working-tree text only, within explicit resource limits."""
    root = Path(root).resolve(strict=True)
    if _git(root, "rev-parse", "--show-prefix").strip():
        raise ValueError("supply the Git repository root")
    sources, skipped = {}, Counter()
    total = 0
    raw = _git(root, "ls-files", "--cached", "-z")
    paths = sorted(set(raw.rstrip(b"\0").split(b"\0"))) if raw else []
    for name in paths:
        path = name.decode("utf-8", "surrogateescape")
        if not _safe_path(path) or role_for_path(path) is None:
            continue
        if len(sources) >= MAX_FILES or total >= MAX_BYTES:
            skipped["budget"] += 1
            continue
        try:
            data = _read_regular(root, path)
        except (OSError, ValueError):
            skipped["unreadable"] += 1
            continue
        if data is None:
            skipped["non_regular"] += 1
        elif len(data) > MAX_FILE_BYTES or total + len(data) > MAX_BYTES:
            skipped["budget"] += 1
        else:
            sources[path] = data
            total += len(data)
    return sources, dict(skipped)


def _topics(goal):
    return [p.strip() for p in re.split(r"[;\n]|(?<=[.!?])\s+", goal) if _tokens(p)]


def _family(path):
    stem = PurePosixPath(path).stem.casefold().replace("-", "_")
    stem = re.sub(r"^test_|_test$|\.test$|\.spec$", "", stem)
    return stem if "_" in stem or stem not in {"readme", "main", "index", "cli", "__init__"} else ""


def _slices(text, wanted, weights, *, limit=3):
    lines = text.splitlines()
    if not lines:
        return []
    sets = [set(_tokens(line[:600])) & wanted for line in lines]
    windows = []
    for i, hits in enumerate(sets):
        structured = bool(STRUCTURE.search(lines[i]))
        if not hits and not structured:
            continue
        lo, hi = max(0, i - 2), min(len(lines), i + 8)
        neighborhood = set().union(*sets[lo:hi])
        if not neighborhood:
            continue
        score = sum(weights[w] for w in sorted(neighborhood))
        score += 1.4 * sum(weights[w] for w in sorted(hits))
        if structured:
            score *= 1.32
        windows.append((-score, i, lo, hi, neighborhood))
    result = []
    for _, anchor, lo, hi, terms in sorted(windows):
        if any(lo < row["end"] and hi > row["start"] - 1 for row in result):
            continue
        # Do not truncate source lines: a long line cannot be cited verbatim.
        while lo < anchor and len(lines[lo]) > 300:
            lo += 1
        while hi > anchor + 1 and len(lines[hi - 1]) > 300:
            hi -= 1
        if any(len(line) > 300 for line in lines[lo:hi]):
            lo, hi = anchor, anchor + 1
        if len(lines[anchor]) > 300:
            continue
        terms = set().union(*sets[lo:hi])
        if not terms:
            continue
        result.append({"start": lo + 1, "end": hi, "text": "\n".join(lines[lo:hi]),
                       "matches": sorted(terms)})
        if len(result) == limit:
            break
    return result


def _lexical_link(query, excerpts, *, strict=False):
    wanted = set(_tokens(query))
    ranked = []
    threshold = len(wanted) if strict else max(min(2, len(wanted)), (len(wanted) + 1) // 2)
    for ref, matches in excerpts:
        hits = wanted.intersection(matches)
        if hits:
            ranked.append((len(hits), ref, hits))
    if not ranked:
        return {"status": "missing", "citations": [], "missing_terms": sorted(wanted)}
    ranked.sort(key=lambda item: (-item[0], item[1]["path"], item[1]["start"], item[1]["end"]))
    count, ref, hits = ranked[0]
    return {"status": "linked_candidate" if count >= threshold else "insufficient",
            "citations": [{**ref, "matched_terms": sorted(hits)}], "missing_terms": sorted(wanted - hits)}


def _python_declarations(docs, requests):
    """Bind an explicit @symbol to a declaration, ignoring comments and strings."""
    found = {key: [] for key in requests}
    problems = set()
    for path, (role, raw, text, _, _, _) in docs.items():
        if PurePosixPath(path).suffix.lower() not in {".py", ".pyi"}:
            continue
        keys = {key for key in requests if key[0] == role and key[1] in text}
        if not keys:
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, RecursionError):
            problems.update(keys)
            continue
        digest = None
        lines = text.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            key = (role, node.name)
            if key not in keys:
                continue
            if len(found[key]) >= 2:
                continue
            digest = digest or sha256(raw).hexdigest()
            ref = {"role": role, "path": path, "sha256": digest,
                   "start": node.lineno, "end": node.lineno}
            line = lines[node.lineno - 1]
            if len(line) <= 300:
                ref["text"] = line
            found[key].append(ref)
    for links in found.values():
        links.sort(key=lambda e: (e["path"], e["start"]))
    return found, problems


def _named_references(goal, requested, docs, roles, limit, incomplete):
    """Resolve named paths/symbols before the lexical file quota is spent."""
    named = list(requested)
    named += re.findall(r"`([^`\n]+)`", goal)
    named += re.findall(r"\bREADME(?:\.(?:md|rst|txt))?\b|\btest_[A-Za-z0-9_]+\b", goal)
    keys = []
    for token in dict.fromkeys(named):
        if not isinstance(token, str) or not token.strip() or len(token) > 300:
            continue
        token = token.strip().replace("\\", "/")
        p = PurePosixPath(token)
        matches = [path for path in docs if docs[path][0] in roles and
                   (path.casefold() == token.casefold() or
                    (len(p.parts) == 1 and (PurePosixPath(path).name.casefold() == token.casefold()
                     or (token.casefold() == "readme" and PurePosixPath(path).stem.casefold() == "readme"))))]
        if token in matches:
            matches = [token]
        elif token.casefold() == "readme" and (root := [p for p in matches if "/" not in p]):
            matches = root
        symbol = token.removeprefix("@")
        if not matches and (token.startswith("@") or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token)):
            is_explicit = token in requested or token.startswith("@") or "_" in token
            keys.append((token, (), symbol, is_explicit))
        elif matches or token in requested or p.suffix.lower() in (CODE | DOCS):
            keys.append((token, matches, None, True))
    overflow = len(keys) > MAX_EXACT_REFERENCES
    keys = keys[:MAX_EXACT_REFERENCES]
    queries = {(role, sym) for _, _, sym, _ in keys if sym for role in roles if role in {"code", "tests"}}
    declared, bad = _python_declarations(docs, queries) if queries else ({}, set())
    resolved, report = {}, []
    for token, paths, sym, required in keys:
        refs = [r for (role, name), found in declared.items() if name == sym for r in found]
        candidates = [(p, None) for p in paths] + [(r["path"], r["start"]) for r in refs]
        if not candidates and not required:
            continue
        status = "missing"
        if len(candidates) > 1:
            status = "ambiguous"
        elif sym and (incomplete or any(name == sym for _, name in bad)):
            status = "scope_incomplete"
        elif candidates:
            path, line = candidates[0]
            if path not in resolved and len(resolved) >= limit:
                status = "budget"
            else:
                resolved.setdefault(path, set())
                if line is not None:
                    resolved[path].add(line)
                status = "selected"
        report.append({"query": token, "status": status,
                       "candidates": [{"path": p, **({"line": line} if line else {})}
                                      for p, line in sorted(candidates)[:4]]})
    return resolved, report, overflow


def _link_requirements(selected, topics, required_roles, requirements, docs, skipped):
    refs = {r: [] for r in ROLES}
    for role, lane in selected.items():
        for file in lane:
            for e in file["excerpts"]:
                refs[role].append(({"role": role, "path": file["path"], "sha256": file["sha256"],
                                    "start": e["start"], "end": e["end"]}, e["matches"]))
    explicit_symbols = {(r, q[1:]) for r, needs in requirements.items() for q in needs
                        if SYMBOL_QUERY.fullmatch(q)}
    symbols, unreadable = _python_declarations(docs, explicit_symbols) if explicit_symbols else ({}, set())
    ledger, missing = [], []

    def record(kind, role, query, assessment, reason):
        entry = {"id": f"R{len(ledger)+1}", "kind": kind, "role": role, "query": query, **assessment}
        ledger.append(entry)
        if entry["status"] != "linked_candidate":
            gap = {"role": role, "reason": reason, "requirement": entry["id"]}
            if query is not None:
                gap["query"] = query
            missing.append(gap)

    for role in required_roles:
        # A category is covered only if at least one passage can be linked to a
        # specific part of the goal. Do not pool isolated terms across passages.
        if topics:
            matches = [(q, _lexical_link(q, refs[role])) for q in topics]
            query, best = max(matches, key=lambda x: (
                x[1]["status"] == "linked_candidate", bool(x[1]["citations"]),
                -len(x[1]["missing_terms"])))
        else:
            query, best = None, {"status": "missing", "citations": [], "missing_terms": []}
        record("role", role, query, best, "no_sufficient_lexical_excerpt")
        for need in requirements.get(role, ()):
            if SYMBOL_QUERY.fullmatch(need):
                key = (role, need[1:])
                candidates = symbols[key]
                status, reason = "linked_candidate", "requirement_not_located"
                if len(candidates) > 1:
                    status, reason = "ambiguous", "requirement_ambiguous"
                elif key in unreadable or skipped:
                    status, reason = "insufficient", "requirement_scope_incomplete"
                elif not candidates:
                    status = "missing"
                record("symbol", role, need, {"status": status, "citations": candidates, "missing_terms": []}, reason)
            else:
                record("explicit", role, need, _lexical_link(need, refs[role], strict=True),
                       "requirement_not_located")
    all_refs = [e for lane in refs.values() for e in lane]
    for query in topics:
        record("goal", None, query, _lexical_link(query, all_refs), "goal_part_not_located")
    return ledger, missing


def _follow_relations(selected, docs, topics, ledger, missing, limit, *, follow_paths):
    pending = {link["role"]: link for link in ledger if link["kind"] == "role"
               and link["role"] in {"tests", "docs"} and link["status"] != "linked_candidate"}
    if not topics or not (pending or (follow_paths and (selected["tests"] or selected["docs"]))):
        return []
    seeds = {}
    origin_topics = {}
    for f in selected["code"]:
        for e in f["excerpts"]:
            ref = {"path": f["path"], "role": "code", "start": e["start"], "end": e["end"],
                   "sha256": f["sha256"]}
            matches = [(q, _lexical_link(q, [(ref, e["matches"])])) for q in topics]
            # The graph answers category coverage, not whether the complete
            # goal already exists. Two terms locate a candidate code passage;
            # only a resolved call or reference may complete the category.
            linked = [(q, a) for q, a in matches if a["citations"]
                      and len(a["citations"][0]["matched_terms"]) >= 2]
            if linked:
                seeds.setdefault(f["path"], []).append(e)
                origin_topics[f["path"], e["start"], e["end"]] = min(
                    linked, key=lambda item: len(item[1]["missing_terms"]))
    if not seeds:
        return []
    present = {f["path"]: f for lane in selected.values() for f in lane}
    existing_paths = {f["path"] for role in ("tests", "docs") for f in selected[role]} if follow_paths else ()
    edges = discover(docs, seeds, pending, selected_paths=existing_paths, follow_paths=follow_paths)
    seed_rank = {p: i for i, p in enumerate(seeds)}
    edges.sort(key=lambda edge: (edge.path not in present, edge.symbol is None,
                                 edge.helper is not None, seed_rank[edge.code_path], edge.path, edge.line))
    relations = []
    finished = set()

    def contains(file, line):
        return file is not None and any(e["start"] <= line <= e["end"] for e in file["excerpts"])

    def add_line(file, lines, line):
        if not contains(file, line):
            file["excerpts"].append({"start": line, "end": line, "text": lines[line - 1], "matches": []})

    for edge in edges:
        role, path, line, anchor, code_path, symbol, code, declaration, helper = edge
        if role in finished or (path not in present and len(present) == limit):
            continue
        raw, lines = docs[path][1], docs[path][2].splitlines()
        f = present.get(path)
        code_file = present[code_path]
        code_lines = docs[code_path][2].splitlines() if declaration is not None else []
        add_declaration = (declaration is not None and not contains(code_file, declaration)
                           and len(code_lines[declaration - 1]) <= 300)
        add_heading = role == "docs" and anchor != line and not contains(f, anchor) and len(lines[anchor - 1]) <= 300
        if role not in pending and not (add_declaration or add_heading or helper):
            continue
        if helper and len(lines[helper[0] - 1]) > 300:
            continue
        if not contains(f, line):
            # Keep the witnessed call/link verbatim. Prefer its test declaration
            # when it is nearby, without displacing any first-pass excerpt.
            if len(lines[line - 1]) > 300:
                continue
            if f is None:
                f = {"path": path, "sha256": sha256(raw).hexdigest(), "excerpts": []}
                selected[role].append(f)
                present[path] = f
            start = anchor if 0 <= line - anchor < 5 else line
            if any(len(l) > 300 for l in lines[start-1:line]):
                start = line
            f["excerpts"].append({"start": start, "end": line,
                                  "text": "\n".join(lines[start-1:line]), "matches": []})
        query, assessment = origin_topics[code_path, code["start"], code["end"]]
        source = {"role": role, "path": path, "sha256": f["sha256"], "start": line, "end": line}
        kind = ("test_calls_via_helper" if helper else
                "test_calls_code" if role == "tests" else "doc_references_code")
        relation = {"kind": kind,
                    "source": source, "code": assessment["citations"][0], "symbol": symbol}
        if helper:
            add_line(f, lines, helper[0])
            relation["via"] = {**source, "start": helper[0], "end": helper[0], "helper": helper[1]}
        if declaration is not None and (add_declaration or contains(code_file, declaration)):
            add_line(code_file, code_lines, declaration)
            relation["declaration"] = {**relation["code"], "start": declaration, "end": declaration}
        if role == "docs" and anchor != line and (add_heading or contains(f, anchor)):
            add_line(f, lines, anchor)
            relation["section"] = {**source, "start": anchor, "end": anchor}
        if link := pending.get(role):
            link.update(status="linked_candidate", query=query, citations=[source],
                        missing_terms=assessment["missing_terms"], basis=relation["kind"])
            missing[:] = [gap for gap in missing if gap.get("requirement") != link["id"]]
        finished.add(role)
        relations.append(relation)
    return relations


def _refine_slices(text, first, wanted, weights, queries, *, role):
    """Search structure and unexplored terms without widening the excerpt budget."""
    lines = text.splitlines()
    terms = [set(_tokens(line[:600])) & wanted for line in lines]
    budgets = (sum(len(row["text"].encode()) for row in first),
               sum(row["end"] - row["start"] + 1 for row in first))
    candidates = {}
    anchors = []
    fence = None
    for i, line in enumerate(lines):
        if role == "docs" and (match := MARKDOWN_FENCE.match(line)):
            mark = match[1]
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence) and not line[match.end():].strip():
                fence = None
            continue
        if fence is None and STRUCTURE.search(line):
            anchors.append(i)
    for pos, lo in enumerate(anchors):
        if len(lines[lo]) > 300:
            continue
        end = min(anchors[pos + 1] if pos + 1 < len(anchors) else len(lines), lo + 26)
        nearby = set().union(*terms[lo:end])
        if not nearby:
            continue
        # Use the early body as a discovery hint for signatures and generic section titles.
        prefix = set().union(*terms[lo:min(end, lo + 10)])
        for hi in range(lo + 1, min(end, lo + 7) + 1):
            if len(lines[hi - 1]) > 300:
                break
            matched = set().union(*terms[lo:hi])
            if not matched:
                continue
            e = {"start": lo + 1, "end": hi, "text": "\n".join(lines[lo:hi]), "matches": sorted(matched)}
            bonus = 0.34 * sum(weights[w] for w in sorted(prefix)) + 0.62 * sum(
                weights[w] for w in sorted(terms[lo]))
            candidates[lo, hi] = (e, bonus)
    # Keep every first-pass declaration/title and every matched term in the
    # original excerpts. Reclaim only surrounding lines with no such signal.
    picked = []
    for e in first:
        lo, hi = e["start"] - 1, e["end"]
        signal = [i for i in range(lo, hi) if terms[i] or STRUCTURE.search(lines[i])]
        lo, hi = signal[0], signal[-1] + 1
        picked.append({**e, "start": lo + 1, "end": hi, "text": "\n".join(lines[lo:hi])})
    covered = {w for e in picked for w in e["matches"]}
    clauses = [set(_tokens(query)) for query in queries]
    used_bytes = sum(len(e["text"].encode()) for e in picked)
    used_lines = sum(e["end"] - e["start"] + 1 for e in picked)
    while len(picked) < 5:
        options = []
        for (lo, hi), (e, bonus) in candidates.items():
            size = len(e["text"].encode())
            if (size + used_bytes > budgets[0] or hi - lo + used_lines > budgets[1]
                    or any(lo < p["end"] and hi >= p["start"] for p in picked)):
                continue
            new = set(e["matches"]) - covered
            clause_bonus = max((len(new & c) / len(c) for c in clauses if c), default=0)
            value = (sum(weights[w] * (1.6 if w in new else .5) for w in e["matches"])
                     + bonus + clause_bonus)
            options.append((-(value / max(1, size / 220) ** .28), lo, hi, size, e))
        if not options:
            break
        _, lo, hi, size, e = min(options)
        picked.append(e)
        covered.update(e["matches"])
        used_bytes += size
        used_lines += hi - lo
    return picked


def select_repository_evidence(goal, sources, *, limit=16, required_roles=ROLES,
                               requirements=None, skipped=None, refine=True, follow_paths=False,
                               references=()):
    """Rank code/tests/docs independently and return provenance plus explicit gaps."""
    if not isinstance(goal, str) or not goal.strip() or len(goal) > 16_000:
        raise ValueError("goal must contain 1..16000 characters")
    required_roles = tuple(dict.fromkeys(required_roles))
    if (type(limit) is not int or not 1 <= limit <= 16 or not required_roles
            or set(required_roles) - set(ROLES) or type(refine) is not bool or type(follow_paths) is not bool
            or not isinstance(references, (list, tuple)) or len(references) > MAX_EXACT_REFERENCES
            or any(not isinstance(x, str) or not x.strip() or len(x) > 300 for x in references)):
        raise ValueError("invalid evidence limit or roles")
    requirements = {} if requirements is None else requirements
    if (not isinstance(requirements, Mapping) or set(requirements) - set(required_roles)
            or any(not isinstance(queries, (list, tuple)) or len(queries) > 8
                   or any(not isinstance(q, str) or len(q) > 500
                          or (q.startswith("@") and (role == "docs" or not SYMBOL_QUERY.fullmatch(q)))
                          or (not q.startswith("@") and not _tokens(q)) for q in queries)
                   for role, queries in requirements.items())):
        raise ValueError("invalid role requirements")
    topics = _topics(goal)
    topic_budget_exceeded = len(topics) > MAX_GOAL_PARTS
    topics = topics[:MAX_GOAL_PARTS]
    wanted = set(_tokens(goal))
    for queries in requirements.values():
        for query in queries:
            wanted.update(_tokens(query))
    skipped = Counter(skipped or {})
    docs, df, count, total = {}, Counter(), 0, 0
    for path in sorted(sources):
        role = role_for_path(path) if _safe_path(path) else None
        if role is None:
            continue
        raw = sources[path]
        if count >= MAX_FILES or len(raw) > MAX_FILE_BYTES or total + len(raw) > MAX_BYTES:
            skipped["budget"] += 1
            continue
        count += 1
        total += len(raw)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            skipped["not_utf8"] += 1
            continue
        if "\0" in text:
            skipped["binary"] += 1
            continue
        tokens = _tokens(text)
        counts = Counter(w for w in tokens if w in wanted)
        phits = wanted.intersection(_tokens(path))
        df.update(set(counts) | phits)
        docs[path] = (role, raw, text, len(tokens), counts, phits)
    mean = max(1, sum(row[3] for row in docs.values()) / max(1, len(docs)))
    weights = {w: log1p((len(docs) - df[w] + .5) / (df[w] + .5)) for w in sorted(wanted)}
    ranked = {role: [] for role in ROLES}
    for path, (role, raw, text, length, counts, phits) in docs.items():
        if not counts:
            continue
        norm = 1.2 * (.25 + .75 * length / mean)
        score = sum(weights[w] * (2.2 * counts[w] / (counts[w] + norm) + 2.2 * (w in phits))
                    for w in weights)
        ranked[role].append((score, path))
    for lane in ranked.values():
        lane.sort(key=lambda x: (-x[0], x[1]))
    # A related implementation/test/doc basename is an independent discovery hint.
    peers = {role: {_family(p) for _, p in ranked[role][:3]} - {""} for role in ROLES}
    for role, lane in ranked.items():
        other = set().union(*(p for k, p in peers.items() if k != role))
        ranked[role] = sorted(lane, key=lambda x: (-(x[0] * (1.14 if _family(x[1]) in other else 1)), x[1]))
    selected = {role: [] for role in ROLES}
    used = set()
    reserved, named, reference_overflow = _named_references(goal, references, docs, required_roles, limit, skipped)
    for path, lines_required in reserved.items():
        role, raw, source, *_ = docs[path]
        excerpts = _slices(source, wanted, weights)
        lines = source.splitlines()
        if not excerpts and not lines_required:
            first = next((i for i, line in enumerate(lines, 1) if line.strip() and len(line) <= 300), None)
            if first is not None:
                lines_required.add(first)
        for i in sorted(lines_required):
            if not any(e["start"] <= i <= e["end"] for e in excerpts) and len(lines[i-1]) <= 300:
                excerpts.append({"start": i, "end": i, "text": lines[i-1], "matches": []})
        selected[role].append({"path": path, "sha256": sha256(raw).hexdigest(), "excerpts": excerpts})
        used.add(path)
    # Quotas are independent of corpus content and favor preserving each kind of proof.
    schedule = [*required_roles] * 16
    for role in schedule:
        if len(used) >= limit:
            break
        while ranked[role]:
            _, path = ranked[role].pop(0)
            if path in used:
                continue
            _, raw, text, _, _, _ = docs[path]
            excerpts = _slices(text, wanted, weights)
            if excerpts:
                if refine:
                    excerpts = _refine_slices(text, excerpts, wanted, weights,
                                              [*topics, *requirements.get(role, ())], role=role)
                selected[role].append({"path": path, "sha256": sha256(raw).hexdigest(), "excerpts": excerpts})
                used.add(path)
                break
    ledger, missing = _link_requirements(selected, topics, required_roles, requirements, docs, skipped)
    relations = _follow_relations(selected, docs, topics, ledger, missing, limit, follow_paths=follow_paths)
    if reference_overflow:
        missing.append({"role": None, "reason": "exact_reference_budget_exceeded"})
    missing.extend({"role": None, "reason": "exact_reference_" + r["status"], "query": r["query"]}
                   for r in named if r["status"] != "selected")
    if topic_budget_exceeded:
        missing.append({"role": None, "reason": "requirement_budget_exceeded"})
    if skipped:
        missing.append({"role": None, "reason": "repository_scope_incomplete"})
    return {"version": "parcimonia.repo-evidence/1", "status": "gaps_detected" if missing else "review_required",
            "goal": goal, "roles": selected, "missing": missing, "requirement_links": ledger,
            "source_relations": relations, "exact_references": named,
            "scope": {"indexed_files": len(docs), "skipped": dict(skipped)},
            "model_calls": 0, "auto_act_allowed": False, "proof_verified": False}


def render_evidence(result):
    """Compact transport to the reviewer. Source excerpts remain untrusted data."""
    out = ["# Preuves candidates du dépôt", result["goal"],
           "Extraits à vérifier ; aucune couverture sémantique garantie.", f"État : {result['status']}"]
    if result.get("exact_references"):
        out += ["", "## Références demandées"]
        for row in result["exact_references"]:
            paths = ", ".join(r["path"] + (f":{r['line']}" if "line" in r else "") for r in row["candidates"])
            out.append(f"- {row['query']} : {row['status']}" + (f" → {paths}" if paths else ""))
    for role in ROLES:
        out += ["", f"## {role}"]
        for file in result["roles"][role]:
            out.append(f"{file['path']} (sha256 {file['sha256']})")
            for e in file["excerpts"]:
                out.append(f"Lignes {e['start']}–{e['end']} :")
                out.extend("    " + line for line in e["text"].split("\n"))
    if result.get("requirement_links"):
        out += ["", "## Exigences et références"]
        goal_ids = {link["query"]: link["id"] for link in result["requirement_links"] if link["kind"] == "goal"}
        for link in result["requirement_links"]:
            role = link["role"] or "objectif"
            # IDs link omissions back to the requirement without repeating query text.
            if link["kind"] == "role":
                question = " ↔ " + goal_ids[link["query"]] if link["query"] in goal_ids else ""
            else:
                question = " " + " ".join(link["query"].split())
            refs = ", ".join(f"{r['path']}:{r['start']}–{r['end']}" for r in link["citations"])
            out.append(f"- {link['id']} ({role}){question} : {link['status']}" + (f" → {refs}" if refs else ""))
            if link["kind"] == "symbol":
                for ref in link["citations"]:
                    out.append(f"    {ref['path']} sha256 {ref['sha256']}")
                    if "text" in ref:
                        out.append("    " + ref["text"])
    if result.get("source_relations"):
        out += ["", "## Liens source"]
        for edge in result["source_relations"]:
            left, right = edge["source"], edge["code"]
            out.append(f"- {left['path']}:{left['start']} → {right['path']}:{right['start']}–{right['end']}"
                       + (f" ({edge['symbol']})" if edge["symbol"] else ""))
            for field, label in (("via", "Appel du helper"), ("declaration", "Déclaration"), ("section", "Section")):
                if ref := edge.get(field):
                    out.append(f"  {label} : {ref['path']}:{ref['start']}")
    if result["missing"]:
        out += ["", "## Manques détectés"]
        out.extend(f"- {m.get('requirement', m['role'] or 'dépôt')} : {m['reason']}"
                   for m in result["missing"])
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--goal", required=True)
    parser.add_argument("--role", action="append", choices=ROLES)
    parser.add_argument("--need", action="append", default=[], metavar="ROLE:PHRASE")
    parser.add_argument("--reference", action="append", default=[], metavar="PATH_OR_SYMBOL")
    parser.add_argument("--limit", type=int, default=16)
    parser.add_argument("--follow-paths", action="store_true",
                        help="Experimental: also follow one local helper and cite declaration/section anchors")
    parser.add_argument("--format", choices=("md", "json"), default="md")
    args = parser.parse_args(argv)
    needs = {}
    for value in args.need:
        role, sep, phrase = value.partition(":")
        if not sep or role not in ROLES or not phrase.strip():
            parser.error("--need expects code:phrase, tests:phrase, or docs:phrase")
        needs.setdefault(role, []).append(phrase.strip())
    try:
        sources, skipped = read_git_sources(args.root)
        result = select_repository_evidence(args.goal, sources, limit=args.limit,
                                            required_roles=args.role or ROLES,
                                            requirements=needs, skipped=skipped, follow_paths=args.follow_paths,
                                            references=args.reference)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"Repository evidence unavailable ({type(exc).__name__})\n")
    print(json.dumps(result, ensure_ascii=True, indent=2) if args.format == "json"
          else render_evidence(result), end="\n" if args.format == "json" else "")


if __name__ == "__main__":
    main()
