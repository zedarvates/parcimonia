"""Capture a local pytest observation bound to repository bytes and environment."""
from __future__ import annotations

from hashlib import sha256
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET

from .repo_evidence import _git, _safe_path

RUN_VERSION = "parcimonia.pytest-receipt/1"
MAX_SNAPSHOT_BYTES = 128 * 1024 * 1024
MAX_ARTIFACT = 16 * 1024 * 1024


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def read_bytes(path, limit=MAX_ARTIFACT):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("file exceeds evidence budget")
    return raw


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def _reject_constant(_):
    raise ValueError("invalid JSON constant")


def read_json(path):
    return json.loads(read_bytes(path).decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_reject_constant)


def root_at(path):
    root = Path(path).resolve(strict=True)
    if _git(root, "rev-parse", "--show-prefix").strip():
        raise ValueError("supply the Git repository root")
    return root


def tracked(root):
    return sorted({p.decode("utf-8") for p in _git(root, "ls-files", "-z", "--cached").split(b"\0") if p})


def _regular_path(root, name):
    p = PurePosixPath(name)
    if (not p.parts or p.is_absolute() or p.as_posix() != name
            or ".." in p.parts or "\\" in name or ":" in name):
        raise ValueError("invalid Git path")
    path = root
    for part in p.parts:
        path /= part
        info = path.lstat()
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("link in Git source")
    if not path.is_file():
        raise ValueError("not a regular file")
    return path


def file_digest(root, name, limit=MAX_SNAPSHOT_BYTES):
    path = _regular_path(root, name)
    raw = read_bytes(path, limit)
    return sha256(raw).hexdigest(), len(raw)


def environment_id():
    # Persist only hashes: no environment variable values or credentials in output.
    python = Path(sys.executable).resolve()
    installed = sorted((d.metadata.get("Name") or "", d.version) for d in metadata.distributions())
    return digest({"python": str(python), "python_sha256": sha256(read_bytes(python, 64 * 1024**2)).hexdigest(),
                   "version": sys.version, "platform": platform.platform(), "distributions": installed,
                   "environment": dict(os.environ)})


def snapshot(root):
    head = _git(root, "rev-parse", "--verify", "HEAD").decode().strip()
    paths = tracked(root)
    reasons = set()
    hashes, total = [], 0
    if _git(root, "ls-files", "--others", "--exclude-standard", "-z"):
        reasons.add("untracked_files")
    if _git(root, "ls-files", "--unmerged", "-z"):
        reasons.add("unmerged_index")
    if len(paths) > 5000:
        reasons.add("snapshot_budget")
    for name in paths[:5000]:
        if total >= MAX_SNAPSHOT_BYTES:
            reasons.add("snapshot_budget")
            break
        try:
            sha, size = file_digest(root, name, MAX_SNAPSHOT_BYTES - total)
            hashes.append((name, sha))
            total += size
        except FileNotFoundError:
            hashes.append((name, None))  # a tracked deletion is part of the current state
        except (OSError, ValueError):
            reasons.add("unreadable_or_over_budget")
    return {"root": str(root), "revision": head, "tree": digest(hashes),
            "environment": environment_id(), "limits": sorted(reasons)}


def _outcome(xml, node, code):
    if code not in (0, 1) or not xml:
        return "unverified"
    try:
        text = xml.decode("utf-8-sig")
    except UnicodeError:
        return "unverified"
    if "<!" in text.upper():
        return "unverified"
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return "unverified"
    cases = list(root.iter("testcase"))
    if len(cases) != 1:
        return "unverified"
    test_path, selectors = node.split("::", 1)
    # Pytest uses the filename and optional class in classname, and retains
    # the parameter suffix in name. Separators in a parameter are data.
    signature, sep, suffix = selectors.partition("[")
    *classes, test_name = signature.split("::")
    test_name += sep + suffix
    case = cases[0]
    parent = ".".join([test_path.removesuffix(".py").replace("/", "."), *classes])
    if case.get("name") != test_name or case.get("classname") != parent:
        return "unverified"
    types = [child.tag for child in case if child.tag in {"failure", "error", "skipped"}]
    if code == 0 and not types:
        return "passed"
    if code == 1 and types and set(types) <= {"failure", "error"}:
        return "failed"
    return "unverified"


def _coverage(raw, node, root):
    if not raw:
        return {}
    record = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    if not isinstance(record, dict) or not isinstance(record.get("files"), dict):
        return {}
    by_file = {}
    for path, payload in record["files"].items():
        if not isinstance(payload, dict):
            continue
        candidate = Path(path)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(root)
            except ValueError:
                continue
        name = candidate.as_posix()
        if not _safe_path(name):
            continue
        contexts = payload.get("contexts", {})
        executed = payload.get("executed_lines", [])
        if isinstance(contexts, dict) and isinstance(executed, list):
            lines = [n for n in executed if type(n) is int and n > 0
                     and isinstance(contexts.get(str(n)), list) and node + "|run" in contexts[str(n)]]
            if lines:
                by_file[name] = sorted(set(lines))
    return by_file


def _pytest_config(root, output):
    # Do not inherit an unobserved config from a parent or another checkout.
    candidates = (
        ("pytest.toml", None), (".pytest.toml", None), ("pytest.ini", None), (".pytest.ini", None),
        ("pyproject.toml", r"^\s*\[tool\.pytest(?:\.ini_options)?\]\s*$"),
        ("tox.ini", r"^\s*\[pytest\]\s*$"), ("setup.cfg", r"^\s*\[tool:pytest\]\s*$"),
    )
    known = set(tracked(root))
    for name, marker in candidates:
        if name not in known:
            continue
        try:
            p = _regular_path(root, name)
        except FileNotFoundError:
            continue
        if marker is None or re.search(marker, read_bytes(p, 256 * 1024).decode("utf-8-sig"), re.M):
            return p
    empty = output / "pytest.ini"
    empty.write_text("[pytest]\n", encoding="ascii")
    return empty


def capture_pytest(root, node, output, *, coverage=True, timeout=60):
    root = root_at(root)
    path, sep, selector = node.partition("::")
    if (not sep or not selector or not _safe_path(path) or not path.endswith(".py")
            or path not in tracked(root) or any(ord(c) < 32 for c in node) or len(node) > 1000
            or type(timeout) is not int or not 1 <= timeout <= 120):
        raise ValueError("run-tests requires one exact tracked pytest node")
    _regular_path(root, path)
    output = Path(output).resolve()
    if output.is_relative_to(root):
        raise ValueError("write test evidence outside the source checkout")
    before = snapshot(root)
    output.mkdir(parents=True, exist_ok=False)
    config_path = _pytest_config(root, output)
    cmd = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
           "--rootdir=" + str(root), "-c", str(config_path),
           "--junitxml=" + str(output / "junit.xml")]
    env = {**os.environ, "PYTEST_ADDOPTS": ""}
    if coverage:
        config = output / "coverage.ini"
        config.write_text("[json]\nshow_contexts = True\n", encoding="ascii")
        env["COVERAGE_FILE"] = str(output / ".coverage")
        cmd += ["--cov=.", "--cov-context=test", "--cov-config=" + str(config),
                "--cov-report=json:" + str(output / "coverage.json")]
    with (output / "pytest.log").open("xb") as log:
        try:
            proc = subprocess.run([*cmd, "--", node], cwd=root, stdout=log,
                                  stderr=subprocess.STDOUT, env=env, timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = None
    after = snapshot(root)
    bound = before == after and not before["limits"]
    artifacts = {}
    contents = {}
    for name in ("pytest.log", "junit.xml", "coverage.json"):
        try:
            contents[name] = read_bytes(output / name)
        except (FileNotFoundError, ValueError):
            continue
        artifacts[name] = sha256(contents[name]).hexdigest()
    outcome = _outcome(contents.get("junit.xml", b""), node, code)
    try:
        lines = _coverage(contents.get("coverage.json", b""), node, root)
    except (ValueError, TypeError):
        lines = {}
    payload = {"version": RUN_VERSION, "node": node, "state": before, "end_state": after,
               "bound": bound, "outcome": outcome, "exit_code": code,
               "artifacts": artifacts, "executed_lines": lines if outcome != "unverified" else {},
               "model_calls": 0}
    receipt = {**payload, "receipt_sha256": digest(payload)}
    (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return receipt


def current_receipt(path, current):
    p = Path(path).resolve(strict=True)
    r = read_json(p)
    if not isinstance(r, dict):
        raise ValueError("invalid test receipt")
    fingerprint = r.pop("receipt_sha256", None)
    if r.get("version") != RUN_VERSION or fingerprint != digest(r):
        raise ValueError("invalid test receipt")
    node, code, artifacts = r.get("node"), r.get("exit_code"), r.get("artifacts")
    if not isinstance(node, str) or "::" not in node or not isinstance(artifacts, dict):
        raise ValueError("invalid test receipt fields")
    if set(artifacts) - {"junit.xml", "coverage.json", "pytest.log"}:
        raise ValueError("invalid artifact path")
    content = {}
    for name, expected in artifacts.items():
        raw = read_bytes(p.parent / name)
        if sha256(raw).hexdigest() != expected:
            raise ValueError("test artifact changed")
        content[name] = raw
    state = r.get("state")
    if r.get("bound") is not True or state != r.get("end_state") or current["limits"]:
        reason = "scope_unverified"
    elif state != current:
        reason = "stale_revision_tree_or_environment"
    else:
        outcome = _outcome(content.get("junit.xml", b""), node, code)
        if outcome != "unverified":
            try:
                lines = _coverage(content.get("coverage.json", b""), node, Path(current["root"]))
            except (ValueError, TypeError):
                lines = {}
            return {"node": node, "status": outcome, "reason": None, "receipt": str(p), "executed_lines": lines}
        reason = "run_not_confirmed"
    return {"node": node, "status": "unverified", "reason": reason, "receipt": str(p), "executed_lines": {}}
