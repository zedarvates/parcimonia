"""Bounded static relations between Python, Python tests and Markdown."""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import PurePosixPath
import posixpath
import re
from typing import NamedTuple

INLINE = re.compile(r"`([^`\n]+)`")
LINK = re.compile(r"(?<!!)\[[^\]\n]*\]\(([^\s()]+)\)")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
MAX_SCAN_FILES = 1_000
HEADING = re.compile(r"^ {0,3}#{1,6}\s+\S")


class Edge(NamedTuple):
    role: str
    path: str
    line: int
    anchor: int
    code_path: str
    symbol: str | None
    code: dict
    declaration: int | None
    helper: tuple[int, str] | None


def _module(path):
    p = PurePosixPath(path)
    parts = list(p.with_suffix("").parts)
    if p.suffix not in {".py", ".pyi"}:
        return None
    if parts[0] == "src":
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts and all(part.isidentifier() for part in parts) else None


def _scope_nodes(node):
    stack = list(reversed(node.body))
    while stack:
        item = stack.pop()
        yield item
        if not isinstance(item, (*DEFS, ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            stack.extend(reversed(list(ast.iter_child_nodes(item))))


def _bound_names(node):
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return [node.id]
    if (isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del))
            and isinstance(node.value, ast.Name)):
        return [node.value.id]
    if isinstance(node, DEFS):
        return [node.name]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return [item.asname or item.name.split(".")[0] for item in node.names]
    if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
        return [node.name]
    if isinstance(node, ast.MatchMapping) and node.rest:
        return [node.rest]
    return []


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id + "." + node.attr
    return None


def _test_edges(tree, targets, *, follow_paths=False):
    aliases, shadowed = defaultdict(list), set()
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom) and stmt.level == 0 and stmt.module:
            for item in stmt.names:
                name = item.asname or item.name
                aliases[name].append((stmt.module, item.name))
        elif isinstance(stmt, ast.Import):
            for item in stmt.names:
                if item.asname or "." not in item.name:
                    aliases[item.asname or item.name].append((item.name, None))
                else:
                    shadowed.add(item.name.split(".")[0])
        else:
            # Conditional bindings and rebinding invalidate the imported name.
            wrapper = ast.Module(body=[stmt], type_ignores=[])
            for node in _scope_nodes(wrapper):
                shadowed.update(_bound_names(node))
    if "*" in aliases or "*" in shadowed:
        return
    # Only a plain, unique module-level function can be a local bridge.
    helpers = {}
    if follow_paths:
        bindings = defaultdict(int)
        for node in _scope_nodes(tree):
            for name in _bound_names(node):
                bindings[name] += 1
        helpers = {fn.name: fn for fn in tree.body if isinstance(fn, ast.FunctionDef)
                   and not fn.name.startswith("test_") and not fn.decorator_list
                   and bindings[fn.name] == 1}

    def calls(fn):
        nodes = list(_scope_nodes(fn))
        excluded = (ast.Global, ast.Nonlocal, ast.Yield, ast.YieldFrom) if follow_paths else (ast.Global, ast.Nonlocal)
        if any(isinstance(n, excluded) for n in nodes):
            return
        args = fn.args
        local = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg] if a}
        local.update(name for node in nodes for name in _bound_names(node))
        for node in nodes:
            if isinstance(node, ast.Call) and (called := _call_name(node.func)):
                base, _, attr = called.partition(".")
                if base not in local:
                    yield node.lineno, base, attr

    def resolve(base, attr):
        if base in shadowed or len(aliases.get(base, ())) != 1:
            return None
        package, imported = aliases[base][0]
        if attr:
            return (package + "." + imported if imported else package, attr)
        return (package, imported) if imported else None

    # Cache only direct imported calls from helpers; no recursion or dynamic dispatch.
    bridge = {}
    for name, fn in helpers.items():
        bridge[name] = [(line, target) for line, base, attr in calls(fn)
                        if (target := resolve(base, attr)) in targets]
    for parent in tree.body:
        functions = parent.body if isinstance(parent, ast.ClassDef) and parent.name.startswith("Test") else [parent]
        for test in functions:
            if not isinstance(test, (ast.FunctionDef, ast.AsyncFunctionDef)) or not test.name.startswith("test_"):
                continue
            for line, base, attr in calls(test):
                if (target := resolve(base, attr)) in targets:
                    yield line, test.lineno, target, None
                elif not attr and base in bridge:
                    for helper_line, target in bridge[base]:
                        yield helper_line, helpers[base].lineno, target, (line, base)


def _doc_targets(text, path, targets, modules, unique):
    fence = None
    comment = False
    heading = None
    for i, line in enumerate(text.splitlines(), 1):
        if comment:
            if "-->" in line:
                comment = False
            continue
        if match := FENCE.match(line):
            mark = match[1]
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence) and not line[match.end():].strip():
                fence = None
            continue
        if fence is not None:
            continue
        if "<!--" in line:
            comment = "-->" not in line.split("<!--", 1)[1]
            line = line.split("<!--", 1)[0]
        if HEADING.match(line):
            heading = i
        for literal in INLINE.findall(line):
            token = literal.removesuffix("()")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", token):
                continue
            pkg, _, name = token.rpartition(".")
            if (pkg, name) in targets:
                yield i, heading or i, (pkg, name)
            elif token in modules and PurePosixPath(modules[token]).name != "__init__.py":
                yield i, heading or i, (token, None)
            elif not pkg and token in unique:
                yield i, heading or i, unique[token]
        for link in LINK.findall(line):
            dest = link.split("#", 1)[0]
            if not dest or dest.startswith("/") or ":" in dest or "\\" in dest or "%" in dest:
                continue
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), dest))
            if resolved in modules.values() and PurePosixPath(resolved).name != "__init__.py":
                yield i, heading or i, (next(key for key, value in modules.items() if value == resolved), None)


def _unique_names(docs, targets):
    """Resolve unqualified Markdown code names only if unique in indexed Python."""
    literals = {literal.removesuffix("()") for path, (role, _, text, *_rest) in docs.items()
                if role == "docs" and path.endswith(".md") for literal in INLINE.findall(text)}
    names = {name for _, name in targets} & literals
    if not names:
        return {}
    observed = defaultdict(list)
    ambiguous = set()
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in sorted(names)) + r")\b")
    for path, (role, _, text, *_rest) in docs.items():
        if role != "code" or not _module(path):
            continue
        present = set(pattern.findall(text))
        if not present:
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, RecursionError):
            ambiguous.update(present)
            continue
        for node in ast.walk(tree):
            if isinstance(node, DEFS) and node.name in present:
                observed[node.name].append((_module(path), node.name))
    return {n: found[0] for n, found in observed.items()
            if n not in ambiguous and len(found) == 1 and found[0] in targets}


def discover(docs, seeds, roles, *, selected_paths=(), follow_paths=False):
    """Return links into selected code passages. No import or execution."""
    by_module = defaultdict(list)
    for path, (role, *_rest) in docs.items():
        if role == "code" and (module := _module(path)):
            by_module[module].append(path)
    modules, targets = {}, {}
    for path, excerpts in seeds.items():
        module = _module(path)
        if not module or by_module[module] != [path]:
            continue
        try:
            tree = ast.parse(docs[path][2])
        except (SyntaxError, RecursionError):
            continue
        modules[module] = path
        defs = defaultdict(list)
        for node in tree.body:
            if isinstance(node, DEFS):
                defs[node.name].append(node)
        assigned = {name for node in _scope_nodes(tree) if not isinstance(node, DEFS)
                    for name in _bound_names(node)}
        for name, nodes in defs.items():
            if len(nodes) != 1 or name in assigned:
                continue
            node = nodes[0]
            hits = [e for e in excerpts if e["start"] <= node.end_lineno and node.lineno <= e["end"]]
            if hits:
                targets[module, name] = (hits[0], node.lineno)
    result, scanned = [], 0
    if not modules:
        return result
    test_imports = {(module, *module.rpartition(".")[::2]) for module, _ in targets}
    has_docs = "docs" in roles or any(docs[p][0] == "docs" for p in selected_paths)
    unique = _unique_names(docs, targets) if has_docs else {}
    for path, (role, _, text, *_rest) in docs.items():
        if (role not in {"tests", "docs"} or (role not in roles and path not in selected_paths)):
            continue
        if scanned >= MAX_SCAN_FILES:
            break
        scanned += 1
        if (role == "tests" and path.endswith(".py")
                and any(module in text or (parent and parent in text and leaf in text)
                        for module, parent, leaf in test_imports)):
            try:
                tree = ast.parse(text)
            except (SyntaxError, RecursionError):
                continue
            for line, anchor, target, helper in _test_edges(tree, targets, follow_paths=follow_paths):
                snippet, declaration = targets[target]
                result.append(Edge(role, path, line, anchor, modules[target[0]], target[1],
                                   snippet, declaration if follow_paths else None, helper))
        elif role == "docs" and path.endswith(".md"):
            for line, heading, target in _doc_targets(text, path, targets, modules, unique):
                code = modules[target[0]]
                excerpt, declaration = targets[target] if target[1] else (seeds[code][0], None)
                result.append(Edge(role, path, line, heading if follow_paths else line, code,
                                   target[1], excerpt, declaration if follow_paths else None, None))
    return result
