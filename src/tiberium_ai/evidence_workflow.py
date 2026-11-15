"""Compact local Parcimonia packets for resume, Git changes and failure logs."""
from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess

from . import evidence_relations
from .evidence_run import (MAX_ARTIFACT, MAX_SNAPSHOT_BYTES, _regular_path, capture_pytest, current_receipt,
                           digest, file_digest, read_bytes, read_json, root_at, snapshot, tracked)
from .repo_evidence import _git, _safe_path, read_git_sources, role_for_path
from .task_followup import USEFUL, VERSION as REVIEW_VERSION
from .execution_profiles import digest as review_digest

CHECKPOINT = "parcimonia.delta-checkpoint/1"
HUNK = re.compile(r"^@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@", re.M)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
MAX_RAW_LOG_BYTES = 12 * 1024
MAX_RAW_LOG_OUTPUT_BYTES = 16 * 1024
MAX_REPO_DELTA_TRACKED = 128
MAX_REPO_DELTA_DISPLAY = 16
RUN_START = re.compile(r"^=+\s*test session starts\s*=+|^Build started(?:\s|$)", re.I)
PYTEST_SUMMARY = re.compile(r"^(?:=+\s*)?\d+ (?:failed|passed|errors?|skipped|deselected|xfailed|xpassed|warnings?)(?:, \d+ (?:failed|passed|errors?|skipped|deselected|xfailed|xpassed|warnings?))* in [\d.]+s(?:\s+.*)?$")
FAIL_LINE = re.compile(r"^\s*E\s+\S|^(?:FAILED|ERROR)\s+\S|:\d+(?::\d+)?:\s*(?:fatal )?error\b|\berror [A-Z]+\d+:|^\s*(?:Error|Exception|AssertionError|TypeError|ValueError|ModuleNotFoundError):", re.I)
TEST_HEADING = re.compile(r"^_{2,}\s+(.+?)\s+_{2,}$")


def _index_binding(root):
    """Reuse tracked membership only for an unchanged, ordinary Git index."""
    harmless = {"GIT_PAGER", "GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT"}
    if any(k.startswith("GIT_") and k not in harmless for k in os.environ):
        return None
    gitdir = root / ".git"
    if (not gitdir.is_dir() or (gitdir / "commondir").exists()
            or (gitdir / "config.worktree").exists() or any(gitdir.glob("sharedindex.*"))):
        return None
    try:
        index = read_bytes(_regular_path(root, ".git/index"))
        config = read_bytes(_regular_path(root, ".git/config"), 256 * 1024)
    except (OSError, ValueError):
        return None
    if not index.startswith(b"DIRC"):
        return None
    return digest({"index": sha256(index).hexdigest(), "config": sha256(config).hexdigest()})


def _receipts(root, paths):
    if len(paths) > 16:
        raise ValueError("too many test receipts")
    state = snapshot(root) if paths else None
    result = []
    for p in paths:
        try:
            result.append(current_receipt(p, state))
        except (OSError, ValueError, KeyError, TypeError):
            result.append({"node": None, "status": "unverified", "reason": "receipt_or_artifact_unreadable",
                           "receipt": str(p), "executed_lines": {}})
    return result


def _repo_delta_paths(root, base):
    fields = _git(root, "diff", "--name-status", "-z", "--no-renames", base, "--").rstrip(b"\0").split(b"\0")
    if fields == [b""]:
        fields = []
    if len(fields) % 2:
        raise ValueError("unexpected Git name-status response")
    paths = {fields[i + 1].decode(): fields[i].decode() for i in range(0, len(fields), 2)}
    for name in _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if name:
            paths.setdefault(name.decode(), "?")
    if _git(root, "ls-files", "--unmerged", "-z"):
        raise ValueError("repository index is unmerged")
    return {p: s for p, s in paths.items() if _safe_path(p) and role_for_path(p)}


def _delta_hash(root, path):
    try:
        return file_digest(root, path, limit=256 * 1024)[0]
    except FileNotFoundError:
        return None


def _save_repository_delta(root):
    try:
        head = _git(root, "rev-parse", "--verify", "HEAD").decode().strip()
        paths = _repo_delta_paths(root, head)
        if len(paths) > MAX_REPO_DELTA_TRACKED:
            return {"status": "baseline_budget_exceeded"}
        files = {p: _delta_hash(root, p) for p in sorted(paths)}
        if (_git(root, "rev-parse", "--verify", "HEAD").decode().strip() != head
                or paths != _repo_delta_paths(root, head)
                or any(_delta_hash(root, p) != h for p, h in files.items())):
            return {"status": "baseline_changed_while_reading"}
        return {"status": "ready", "base": head, "local": files}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"status": "baseline_unavailable"}


def _repository_delta(root, baseline, selected):
    result = {"status": "baseline_unavailable", "files": [], "omitted": 0}
    if not baseline or baseline.get("status") != "ready":
        if baseline:
            result["status"] = baseline["status"]
        return result
    base, old = baseline["base"], baseline["local"]
    try:
        if not re.fullmatch("[0-9a-f]{40}|[0-9a-f]{64}", base):
            raise ValueError("invalid delta revision")
        paths = _repo_delta_paths(root, base)
        candidates = (set(paths) | set(old)) - selected
        rows = []
        skipped = max(0, len(candidates) - MAX_REPO_DELTA_TRACKED)
        hashes = {}
        for p in sorted(candidates)[:MAX_REPO_DELTA_TRACKED]:
            if not _safe_path(p):
                skipped += 1
                continue
            try:
                now = hashes[p] = _delta_hash(root, p)
            except (OSError, ValueError):
                skipped += 1
                continue
            if p in old:
                if old[p] == now:
                    continue
                kind = "new" if old[p] is None else "deleted" if now is None else "modified"
            else:
                status = paths[p]
                kind = "new" if status in {"?", "A"} else "deleted" if now is None else "modified"
            rows.append({"path": p, "state": kind, "role": role_for_path(p), "sha256": now,
                         "test_result": "unverified"})
        if paths != _repo_delta_paths(root, base) or any(_delta_hash(root, p) != h for p, h in hashes.items()):
            return {**result, "status": "changed_while_reading"}
        rows.sort(key=lambda r: ({"new": 0, "modified": 1, "deleted": 2}[r["state"]], r["path"]))
        return {"status": "partial" if skipped or len(rows) > MAX_REPO_DELTA_DISPLAY else "ready",
                "base": base, "files": rows[:MAX_REPO_DELTA_DISPLAY],
                "omitted": skipped + max(0, len(rows) - MAX_REPO_DELTA_DISPLAY)}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {**result, "status": "unavailable"}


def checkpoint(root, files, receipts, output, *, review=None, evidence=None):
    root = root_at(root)
    chosen = {}
    if review is not None:
        report = read_json(review)
        if (not isinstance(report, dict) or report.get("version") != REVIEW_VERSION
                or report.get("review_sha256") != review_digest({k: v for k, v in report.items()
                                                                  if k != "review_sha256"})):
            raise ValueError("invalid existing task review")
        for row in report["files"]:
            source = row["source"]
            if row["status"] in USEFUL and source["root"] == "workspace":
                chosen[source["path"]] = row["content_sha256"]
    for name in files:
        chosen.setdefault(name, None)
    if not chosen or len(chosen) > 32 or len(receipts) > 16:
        raise ValueError("checkpoint requires 1..32 useful files and up to 16 receipts")
    references, omitted = [], 0
    if evidence is not None:
        packet = read_json(evidence)
        if not isinstance(packet, dict) or packet.get("version") != "parcimonia.repo-evidence/1":
            raise ValueError("invalid source evidence packet")
        for lane in packet["roles"].values():
            for file in lane:
                path, sha = file["path"], file["sha256"]
                if path not in chosen:
                    continue
                if chosen[path] is not None and chosen[path] != sha:
                    omitted += len(file["excerpts"])
                    continue
                chosen[path] = sha
                for excerpt in file["excerpts"]:
                    a, b, quote = excerpt["start"], excerpt["end"], excerpt["text"]
                    if (type(a) is not int or type(b) is not int or not 1 <= a <= b
                            or b - a > 32 or not isinstance(quote, str)):
                        raise ValueError("invalid source excerpt")
                    if len(references) == 32:
                        omitted += 1
                    else:
                        references.append({"path": path, "start": a, "end": b,
                                           "sha256": sha, "text_sha256": sha256(quote.encode()).hexdigest()})
    initial_index = _index_binding(root)
    known = set(tracked(root))
    rows = []
    for name, previously_observed in chosen.items():
        if not _safe_path(name) or name not in known:
            raise ValueError("checkpoint requires tracked workspace files")
        # Preserve the previously used bytes from the review. Never silently
        # rebaseline a changed file when making a checkpoint from past work.
        sha = previously_observed or file_digest(root, name)[0]
        if not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{64}", sha):
            raise ValueError("invalid previous source fingerprint")
        rows.append({"path": name, "sha256": sha})
    stable_index = initial_index if initial_index and initial_index == _index_binding(root) else None
    payload = {"version": CHECKPOINT, "root": str(root), "files": rows, "source_refs": references,
               "git_index": stable_index,
               "repository_baseline": _save_repository_delta(root),
               "source_refs_omitted": omitted,
               "receipts": [str(Path(p).resolve()) for p in receipts]}
    output = Path(output).resolve()
    if output.is_relative_to(root):
        raise ValueError("write the checkpoint outside the source checkout")
    with output.open("x", encoding="utf-8") as stream:
        json.dump({**payload, "checkpoint_sha256": digest(payload)}, stream, ensure_ascii=True, indent=2)
        stream.write("\n")
    return {"saved": str(output), "files": len(rows), "receipts": len(receipts),
            "source_references": len(references), "source_references_omitted": omitted}


def resume(root, saved, *, repository_delta=True):
    root = Path(root).resolve(strict=True)
    record = read_json(saved)
    if not isinstance(record, dict):
        raise ValueError("invalid checkpoint")
    sha = record.pop("checkpoint_sha256", None)
    if record.get("version") != CHECKPOINT or sha != digest(record) or record.get("root") != str(root):
        raise ValueError("checkpoint not bound to this checkout")
    rows = record.get("files")
    refs, receipt_paths = record.get("source_refs", []), record.get("receipts", [])
    if (not isinstance(rows, list) or not 1 <= len(rows) <= 32
            or not isinstance(refs, list) or len(refs) > 32
            or not isinstance(receipt_paths, list) or len(receipt_paths) > 16):
        raise ValueError("invalid checkpoint file list")
    current_index = _index_binding(root) if record.get("git_index") else None
    if current_index and current_index == record["git_index"]:
        known = {row["path"] for row in rows}
    else:
        known = set(tracked(root_at(root)))
    changed, retained, current_hashes = [], 0, {}
    cited_paths = {ref["path"] for ref in refs}
    citation_lines = {}
    for row in rows:
        name = row["path"]
        if not _safe_path(name):
            raise ValueError("invalid checkpoint reference")
        now = None
        if name in known:
            try:
                raw = read_bytes(_regular_path(root, name), MAX_SNAPSHOT_BYTES)
                now = sha256(raw).hexdigest()
                if now == row["sha256"] and name in cited_paths and len(raw) <= MAX_ARTIFACT:
                    citation_lines[name] = raw.decode("utf-8-sig").splitlines()
            except (OSError, ValueError):
                pass
        if now == row["sha256"]:
            retained += 1
        else:
            changed.append({"path": name, "state": "changed_requires_reread" if now else "unavailable"})
        current_hashes[name] = now
    retained_citations, stale_citations = 0, 0
    for ref in refs:
        path = ref["path"]
        if path not in current_hashes or current_hashes[path] != ref["sha256"]:
            stale_citations += 1
            continue
        start, end = ref["start"], ref["end"]
        lines = citation_lines.get(path, [])
        text = "\n".join(lines[start-1:end])
        if 1 <= start <= end <= len(lines) and sha256(text.encode()).hexdigest() == ref["text_sha256"]:
            retained_citations += 1
        else:
            stale_citations += 1
    if current_index and current_index == record["git_index"] and _index_binding(root) != current_index:
        raise ValueError("Git index changed while refreshing checkpoint")
    repo_delta = (_repository_delta(root, record.get("repository_baseline"), set(current_hashes))
                  if repository_delta else {"status": "disabled", "files": [], "omitted": 0})
    tests = _receipts(root, receipt_paths)
    return {"kind": "resume", "files_to_review": changed, "files_unchanged": retained,
            "repository_delta": repo_delta,
            "source_references_unchanged": retained_citations, "source_references_stale": stale_citations,
            "source_references_omitted": record.get("source_refs_omitted", 0),
            "tests_to_rerun": [{k: t[k] for k in ("node", "reason", "receipt")}
                               for t in tests if t["status"] == "unverified"],
            "valid_test_evidence": [{k: t[k] for k in ("node", "status", "receipt")}
                                    for t in tests if t["status"] != "unverified"],
            "model_calls": 0, "auto_act_allowed": False}


def git_delta(root, base):
    revision = _git(root, "rev-parse", "--verify", "--end-of-options", base + "^{commit}").decode().strip()
    names = _git(root, "diff", "--name-status", "-z", "--no-renames", revision, "--").split(b"\0")
    names = names[:-1] if names[-1] == b"" else names
    if len(names) % 2:
        raise ValueError("unexpected Git diff names")
    entries = [(names[i].decode(), names[i+1].decode()) for i in range(0, len(names), 2)]
    rows, omitted = [], 0
    for status, path in entries:
        if len(rows) >= 32 or not _safe_path(path):
            omitted += 1
            continue
        # Git interprets a pathspec even after -- unless literal-pathspecs is set.
        patch = subprocess.run(["git", "--literal-pathspecs", "-C", str(root), "diff",
                                "--no-ext-diff", "--no-textconv", "--no-renames", "--unified=0",
                                revision, "--", path], capture_output=True, check=True, timeout=15).stdout
        spans, preview = [], []
        if len(patch) <= 2 * 1024**2:
            decoded = patch.decode("utf-8", errors="replace")
            for match in HUNK.finditer(decoded):
                a, b, c, d = match.groups()
                spans.append({"before_start": int(a), "before_count": int(b or 1),
                              "start": int(c), "count": int(d or 1)})
            seen_hunk = False
            for line in decoded.splitlines():
                if HUNK.match(line):
                    seen_hunk = True
                elif seen_hunk and line.startswith(("+", "-")):
                    preview.append(line if len(line) <= 200 else line[:200] + " [tronqué]")
                    if len(preview) == 4:
                        break
        rows.append({"path": path, "git_status": status, "hunks": spans[:32],
                     "hunks_omitted": max(0, len(spans) - 32), "patch_unavailable": not spans,
                     "patch_sha256": sha256(patch).hexdigest(), "preview": preview})
    return revision, rows, omitted


def diff_packet(root, base, receipts):
    root = root_at(root)
    revision, rows, omitted = git_delta(root, base)
    tests = _receipts(root, receipts)
    raw, skipped = read_git_sources(root)
    docs = {}
    for p, data in raw.items():
        try:
            docs[p] = (role_for_path(p), data, data.decode("utf-8-sig"), 0, {}, set())
        except UnicodeError:
            skipped["not_utf8"] = skipped.get("not_utf8", 0) + 1
    seeds = {r["path"]: [{"start": h["start"], "end": h["start"] + h["count"] - 1}
                          for h in r["hunks"] if h["count"]]
             for r in rows if r["path"] in docs and docs[r["path"]][0] == "code"}
    seeds = {p: spans for p, spans in seeds.items() if spans}
    edges = evidence_relations.discover(docs, seeds, {"tests"}, follow_paths=True) if seeds else []
    def test_names(path):
        try:
            tree = ast.parse(docs[path][2])
        except (SyntaxError, RecursionError):
            return []
        result = []
        for parent in tree.body:
            prefix = parent.name + "::" if isinstance(parent, ast.ClassDef) else ""
            for n in parent.body if prefix else [parent]:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"):
                    result.append((n.lineno, n.end_lineno, prefix + n.name))
        return result

    names = {p: test_names(p) for p in {e.path for e in edges}}
    for row in rows:
        path = row["path"]
        spans = [(h["start"], h["start"] + h["count"]) for h in row["hunks"] if h["count"]]
        changed_count = sum(end - start for start, end in spans)
        matching = [e for e in edges if e.code_path == path]
        observed = []
        covered = set()
        for t in tests:
            hit = sorted({n for n in t["executed_lines"].get(path, ())
                          if any(lo <= n < hi for lo, hi in spans)})
            if hit:
                covered.update(hit)
                observed.append({"node": t["node"], "status": t["status"], "receipt": t["receipt"],
                                 "executed_count": len(hit), "lines": hit[:32]})
        row["observed_tests"] = observed
        bound_nodes = {o["node"] for o in observed}
        candidates = {}
        for e in matching:
            line = e.helper[0] if e.helper else e.anchor
            test_name = next((name for a, b, name in names[e.path] if a <= line <= b), None)
            if test_name is None or f"{e.path}::{test_name}" not in bound_nodes:
                candidates.setdefault((e.path, line), {"path": e.path, "line": line, "test": test_name,
                                                      "status": "found_result_unverified"})
        row["test_candidates"] = list(candidates.values())[:8]
        row["test_candidates_omitted"] = max(0, len(candidates) - 8)
        row["changed_lines"] = changed_count
        row["changed_lines_without_execution_trace"] = changed_count - len(covered)
    # Detect tracked changes while reading the diff/candidates; discard this packet
    # instead of binding line numbers to a different working tree.
    again, same, same_omitted = git_delta(root, revision)
    keys = ("path", "git_status", "hunks", "hunks_omitted", "patch_unavailable", "patch_sha256", "preview")
    if again != revision or same != [{k: r[k] for k in keys} for r in rows] or same_omitted != omitted:
        raise ValueError("Git diff changed while reading")
    if receipts and any(t["status"] != "unverified" for t in tests):
        end = _receipts(root, receipts)
        if end != tests:
            raise ValueError("test binding changed while reading the diff")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z").count(b"\0")
    return {"kind": "diff", "base_revision": revision, "files": rows, "files_omitted": omitted,
            "untracked_excluded": untracked,
            "source_limits": skipped, "unverified_receipts": [
                {k: t[k] for k in ("node", "reason", "receipt")} for t in tests if t["status"] == "unverified"],
            "model_calls": 0, "auto_act_allowed": False}


def log_packet(path, *, context=2, limit=12, view="excerpts", output_format="md"):
    if (type(context) is not int or not 0 <= context <= 5 or type(limit) is not int or not 1 <= limit <= 20
            or view not in {"auto", "raw", "excerpts"} or output_format not in {"md", "json"}):
        raise ValueError("invalid log budget")
    path = Path(path).resolve(strict=True)
    raw = read_bytes(path)
    text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    original = re.split(r"\r\n|\r|\n", text)
    if original[-1] == "":
        original.pop()
    lines = [CONTROLS.sub("", ANSI.sub("", line)) for line in original]
    starts = [i for i, line in enumerate(lines) if RUN_START.search(line)]
    ends = [i+1 for i, line in enumerate(lines) if PYTEST_SUMMARY.match(line.strip())
            or line.strip().casefold() in {"build failed.", "build succeeded."}]
    cuts = sorted(set([0, *starts, *ends, len(lines)]))
    segments, remaining = [], limit
    for start, end in zip(cuts, cuts[1:]):
        groups, heading, summaries = {}, None, []
        for i in range(start, end):
            line = lines[i]
            if match := TEST_HEADING.match(line):
                heading = match[1]
            if PYTEST_SUMMARY.match(line.strip()) or line.strip().casefold() in {"build failed.", "build succeeded."}:
                summary = line.strip()
                summaries.append({"line": i + 1, "text": summary[:300] + (" [tronqué]" if len(summary) > 300 else "")})
            if FAIL_LINE.search(line):
                kind = "pytest_detail" if re.match(r"^\s*E\s+", line) else "diagnostic"
                identity = (heading if kind == "pytest_detail" else None,
                            re.sub(r"0x[0-9a-fA-F]+\b", "0x…", line.strip()))
                if identity in groups:
                    groups[identity]["count"] += 1
                else:
                    lo, hi = max(start, i-context), min(end, i+context+1)
                    excerpt = [{"line": j+1, "text": lines[j][:500], "truncated": len(lines[j]) > 500}
                               for j in range(lo, hi)] if len(groups) < remaining else []
                    groups[identity] = {"first_line": i+1, "count": 1, "excerpt": excerpt}
        shown = [g for g in groups.values() if g["excerpt"]]
        remaining -= len(shown)
        segments.append({"start": start + 1, "end": end, "summaries": summaries[-2:],
                         "multiple_summaries": len(summaries) > 1, "errors": shown,
                         "groups_omitted": len(groups)-len(shown)})
    common = {"kind": "logs", "path": str(path), "sha256": sha256(raw).hexdigest(), "line_count": len(lines),
              "model_calls": 0, "auto_act_allowed": False}
    excerpts = {**common, "view": "excerpts",
            "segments": segments[:32], "segments_omitted": max(0, len(segments)-32),
            "recognized": any(s["summaries"] or s["errors"] or s["groups_omitted"] for s in segments)}
    if view == "excerpts":
        return excerpts
    if len(raw) > MAX_RAW_LOG_BYTES:
        if view == "raw":
            raise ValueError("raw display exceeds log budget")
        return excerpts
    raw_view = {**common, "view": "raw", "lines": lines,
                "terminal_controls_removed": lines != original,
                "first_errors": [e["first_line"] for s in segments[:32] for e in s["errors"]]}
    def size(packet):
        formatted = (render(packet) if output_format == "md" else
                     json.dumps(packet, ensure_ascii=True, indent=2) + "\n")
        return len(formatted.encode("utf-8"))

    raw_size = size(raw_view)
    if raw_size > MAX_RAW_LOG_OUTPUT_BYTES:
        if view == "raw":
            raise ValueError("raw display exceeds log budget")
        return excerpts
    # Near a tie, retain every line rather than trusting a byte/token proxy.
    return raw_view if view == "raw" or not excerpts["recognized"] or raw_size * 10 <= size(excerpts) * 11 else excerpts


def render(packet):
    k = packet["kind"]
    if k == "resume":
        out = [f"# Reprise — {packet['files_unchanged']} fichier(s) inchangé(s), "
               f"{len(packet['files_to_review'])} à relire, {len(packet['tests_to_rerun'])} test(s) à relancer"]
        out.append(f"Citations : {packet['source_references_unchanged']} inchangée(s), "
                   f"{packet['source_references_stale']} à revoir, {packet['source_references_omitted']} omise(s).")
        out.extend(f"- {f['path']} : {f['state']}" for f in packet["files_to_review"])
        out.extend(f"- À relancer : {t['node'] or t['receipt']} ({t['reason']})" for t in packet["tests_to_rerun"])
        out.extend(f"- Preuve encore valide : {t['node']} ({t['status']})" for t in packet["valid_test_evidence"])
        delta = packet.get("repository_delta")
        if delta and (delta["files"] or delta["status"] not in {"ready", "disabled"}):
            out.append("## Hors du point de reprise")
            out.extend(f"- {f['path']} : {f['state']} ; résultat non vérifié." for f in delta["files"])
            if delta["status"] != "ready":
                out.append(f"Périmètre : {delta['status']}, {delta['omitted']} fichier(s) omis.")
    elif k == "diff":
        out = [f"# Diff depuis {packet['base_revision'][:12]}"]
        for f in packet["files"]:
            out.append(f"- {f['path']} ({f['git_status']}) : {f['changed_lines']} ligne(s) courante(s) modifiée(s), "
                       f"{f['changed_lines_without_execution_trace']} sans trace d’exécution.")
            out.extend("    " + line for line in f["preview"])
            if f["patch_unavailable"] or f["hunks_omitted"]:
                out.append("  - Diff textuel absent, non disponible ou tronqué.")
            for t in f["observed_tests"]:
                out.append(f"  - {t['node']} : {t['status']}, {t['executed_count']} ligne(s) du diff exécutée(s).")
            for t in f["test_candidates"]:
                out.append(f"  - {t['path']}:{t['line']} : test trouvé, résultat non vérifié.")
            if not (f["test_candidates"] or f["observed_tests"]):
                out.append("  - Aucun test relié dans les preuves disponibles.")
        if packet["untracked_excluded"] or packet["files_omitted"] or packet["source_limits"]:
            out.append(f"Périmètre : {packet['untracked_excluded']} fichier(s) non suivi(s) exclu(s), "
                       f"{packet['files_omitted']} changement(s) omis, limites : {packet['source_limits']}.")
        for t in packet["unverified_receipts"]:
            out.append(f"- Résultat non réutilisé : {t['node'] or t['receipt']} ({t['reason']}).")
    else:
        target = Path(packet["path"]).as_posix()
        if packet.get("view") == "raw":
            first = packet["first_errors"][0] if packet["first_errors"] else 1
            out = [f"# Log en texte intégral — {packet['line_count']} lignes",
                   f"[Original](<{target}:{first}>) · SHA-256 {packet['sha256'][:12]}…"]
            if packet["terminal_controls_removed"]:
                out.append("Contrôles de terminal retirés de l’affichage.")
            if packet["first_errors"]:
                out.append("Erreurs : " + ", ".join(f"L{i}" for i in packet["first_errors"]))
            largest = max((len(m.group()) for line in packet["lines"] for m in re.finditer(r"`+", line)), default=0)
            fence = "`" * max(3, largest + 1)
            out.extend(["", fence + "text", *packet["lines"], fence])
            return "\n".join(out) + "\n"
        out = [f"# Extraits d’erreurs — {packet['line_count']} lignes",
               f"Log intégral : {target} (SHA-256 {packet['sha256']})"]
        if packet.get("recognized") is False:
            out.append("Aucun résumé ni motif d’erreur reconnu ; consulter le journal intégral.")
        for segment in packet["segments"]:
            if not (segment["summaries"] or segment["errors"] or segment["groups_omitted"]):
                continue
            out.append(f"## Lignes {segment['start']}–{segment['end']}")
            cited = set()
            for s in segment["summaries"]:
                out.append(f"- Résumé trouvé à L{s['line']} : {s['text']}")
            for g in segment["errors"]:
                out.append(f"- [Première occurrence, L{g['first_line']}](<{target}:{g['first_line']}>) ×{g['count']}")
                for line in g["excerpt"]:
                    if line["line"] not in cited:
                        out.append(f"    {line['line']}: {line['text']}" + (" [tronqué]" if line["truncated"] else ""))
                        cited.add(line["line"])
            if segment["groups_omitted"]:
                out.append(f"- {segment['groups_omitted']} groupe(s) omis par le budget.")
        if packet["segments_omitted"]:
            out.append(f"- {packet['segments_omitted']} segment(s) omis.")
    return "\n".join(out) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--format", choices=("md", "json"), default="md")
    sub = p.add_subparsers(dest="action", required=True)
    save = sub.add_parser("checkpoint")
    save.add_argument("--file", action="append", default=[])
    save.add_argument("--review", type=Path)
    save.add_argument("--evidence", type=Path)
    save.add_argument("--receipt", action="append", type=Path, default=[])
    save.add_argument("--out", required=True, type=Path)
    load = sub.add_parser("resume")
    load.add_argument("checkpoint", type=Path)
    load.add_argument("--no-repo-delta", action="store_true")
    diff = sub.add_parser("diff")
    diff.add_argument("--base", default="HEAD")
    diff.add_argument("--receipt", action="append", type=Path, default=[])
    logs = sub.add_parser("logs")
    logs.add_argument("log", type=Path)
    logs.add_argument("--context", type=int, default=2)
    logs.add_argument("--limit", type=int, default=12)
    logs.add_argument("--view", choices=("auto", "raw", "excerpts"), default="auto")
    test = sub.add_parser("run-tests")
    test.add_argument("test")
    test.add_argument("--out", type=Path, required=True)
    test.add_argument("--no-coverage", action="store_true")
    test.add_argument("--timeout", type=int, default=60)
    args = p.parse_args(argv)
    try:
        if args.action == "checkpoint":
            result = checkpoint(args.root, args.file, args.receipt, args.out, review=args.review,
                                evidence=args.evidence)
        elif args.action == "resume":
            result = resume(args.root, args.checkpoint, repository_delta=not args.no_repo_delta)
        elif args.action == "diff":
            result = diff_packet(args.root, args.base, args.receipt)
        elif args.action == "logs":
            result = log_packet(args.log, context=args.context, limit=args.limit,
                                view=args.view, output_format=args.format)
        else:
            receipt = capture_pytest(args.root, args.test, args.out, coverage=not args.no_coverage, timeout=args.timeout)
            result = {"receipt": str(args.out.resolve() / "receipt.json"), "test": receipt["node"],
                      "outcome": receipt["outcome"], "bound": receipt["bound"],
                      "limits": receipt["state"]["limits"], "model_calls": 0}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        p.exit(2, f"Preuve locale non disponible ({type(exc).__name__})\n")
    print(render(result), end="") if args.format == "md" and "kind" in result else print(
        json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
