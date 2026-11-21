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
    if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
        base = node.value
        while isinstance(base, (ast.Attribute, ast.Subscript)):
            base = base.value
        if isinstance(base, ast.Name):
            return [base.id]
    if isinstance(node, DEFS):
        return [node.name]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return [item.asname or item.name.split(".")[0] for item in node.names]
    if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
        return [node.name]
    if isinstance(node, ast.MatchMapping) and node.rest:
        return [node.rest]
    return []


def _expression_bindings(node):
    """Names assigned by expressions evaluated in the enclosing scope."""
    def defaults(args):
        return [*args.defaults, *(v for v in args.kw_defaults if v is not None)]

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = node.args
        parameters = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
        stack = [*node.decorator_list, *defaults(args),
                 *(p.annotation for p in parameters if p and p.annotation),
                 *([node.returns] if node.returns else [])]
    elif isinstance(node, ast.ClassDef):
        stack = [*node.decorator_list, *node.bases, *(k.value for k in node.keywords)]
    elif isinstance(node, ast.Lambda):
        stack = defaults(node.args)
    elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        stack = [node]
    else:
        return
    while stack:
        part = stack.pop()
        if isinstance(part, ast.Lambda):
            stack.extend(defaults(part.args))
            continue
        if isinstance(part, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            stack.extend([part.key, part.value] if isinstance(part, ast.DictComp) else [part.elt])
            for generator in part.generators:
                stack.append(generator.iter)
                stack.extend(generator.ifs)
            continue
        if isinstance(part, ast.NamedExpr) and isinstance(part.target, ast.Name):
            yield part.target.id
        stack.extend(ast.iter_child_nodes(part))


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id + "." + node.attr
    return None


def _evaluated_expression_calls(node):
    """Calls in definition headers and eager expressions, with local shadowing."""
    def defaults(args):
        return [*args.defaults, *(x for x in args.kw_defaults if x is not None)]

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        expressions = [*node.decorator_list, *defaults(node.args)]
    elif isinstance(node, ast.ClassDef):
        expressions = [*node.decorator_list, *node.bases, *(x.value for x in node.keywords)]
    elif isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        expressions = [node]
    else:
        return
    stack = [(expr, frozenset()) for expr in expressions]
    while stack:
        part, hidden = stack.pop()
        if isinstance(part, ast.Lambda):
            stack.extend((x, hidden) for x in defaults(part.args))
            continue
        if isinstance(part, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            # Only the first iterable of a generator expression is eager.
            stack.append((part.generators[0].iter, hidden))
            if isinstance(part, ast.GeneratorExp):
                continue
            targets = {n.id for g in part.generators for n in ast.walk(g.target)
                       if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
            inner = hidden | targets
            reachable = True
            for index, generator in enumerate(part.generators):
                if index:
                    stack.append((generator.iter, inner))
                empty_sequence = isinstance(generator.iter, (ast.List, ast.Tuple, ast.Set)) and not generator.iter.elts
                empty_mapping = isinstance(generator.iter, ast.Dict) and not generator.iter.keys
                if empty_sequence or empty_mapping:
                    reachable = False
                    break
                for condition in generator.ifs:
                    stack.append((condition, inner))
                    if ((isinstance(condition, ast.Constant) and not condition.value) or
                            (isinstance(condition, ast.BoolOp) and isinstance(condition.op, ast.And)
                             and any(isinstance(value, ast.Constant) and not value.value
                                     for value in condition.values))):
                        reachable = False
                        break
                if not reachable:
                    break
            if reachable:
                values = [part.key, part.value] if isinstance(part, ast.DictComp) else [part.elt]
                stack.extend((x, inner) for x in values)
            continue
        if isinstance(part, ast.BoolOp):
            # Stop at a literal that decides a short-circuit expression.
            evaluated = []
            for value in part.values:
                evaluated.append(value)
                if isinstance(value, ast.Constant) and (
                    (isinstance(part.op, ast.And) and not value.value) or
                    (isinstance(part.op, ast.Or) and bool(value.value))
                ):
                    break
            stack.extend((value, hidden) for value in evaluated)
            continue
        if isinstance(part, ast.Call):
            yield part, hidden
        stack.extend((x, hidden) for x in ast.iter_child_nodes(part))


def _test_edges(tree, targets, *, follow_paths=False, pytest_collision=False):
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
                shadowed.update(_expression_bindings(node))
                if isinstance(node, ast.Call) and _call_name(node.func) in ('setattr', 'delattr', 'monkeypatch.setattr') and node.args:
                    base = node.args[0]
                    while isinstance(base, (ast.Attribute, ast.Subscript)):
                        base = base.value
                    if isinstance(base, ast.Name):
                        shadowed.add(base.id)
    if "*" in aliases or "*" in shadowed:
        return
    # Only a plain, unique module-level function can be a local bridge.
    helpers = {}
    if follow_paths:
        bindings = defaultdict(int)
        for node in _scope_nodes(tree):
            for name in _bound_names(node):
                bindings[name] += 1
            for name in _expression_bindings(node):
                bindings[name] += 1
        helpers = {fn.name: fn for fn in tree.body if isinstance(fn, ast.FunctionDef)
                   and not fn.name.startswith("test_") and not fn.decorator_list
                   and bindings[fn.name] == 1}

    def calls(fn):
        nodes = list(_scope_nodes(fn))
        excluded = (ast.Global, ast.Nonlocal, ast.Yield, ast.YieldFrom)
        if any(isinstance(n, excluded) for n in nodes):
            return
        args = fn.args
        local = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg] if a}
        local.update(name for node in nodes for name in _bound_names(node))
        local.update(name for node in nodes for name in _expression_bindings(node))
        candidates = ((node, frozenset()) for node in nodes if isinstance(node, ast.Call))
        candidates = [*candidates, *(pair for node in nodes for pair in _evaluated_expression_calls(node))]
        for node, hidden in candidates:
            if called := _call_name(node.func):
                base, _, attr = called.partition(".")
                if base not in local and base not in hidden:
                    yield node.lineno, base, attr

    def resolve(base, attr):
        if base in shadowed or len(aliases.get(base, ())) != 1:
            return None
        package, imported = aliases[base][0]
        if attr:
            return (package + "." + imported if imported else package, attr)
        return (package, imported) if imported else None

    def supported_decorators(fn, class_bindings):
        # A unique, unshadowed pytest import supports the standard parametrizer.
        # All other decorators remain ambiguous and cannot establish a link.
        for decorator in fn.decorator_list:
            if not isinstance(decorator, ast.Call):
                return False
            parametrize = decorator.func
            if (not isinstance(parametrize, ast.Attribute) or parametrize.attr != 'parametrize'
                    or not isinstance(parametrize.value, ast.Attribute) or parametrize.value.attr != 'mark'
                    or not isinstance(parametrize.value.value, ast.Name)):
                return False
            name = parametrize.value.value.id
            if pytest_collision or name in shadowed or name in class_bindings or aliases.get(name) != [('pytest', None)]:
                return False
            values = decorator.args[1] if len(decorator.args) > 1 else next(
                (kw.value for kw in decorator.keywords if kw.arg == 'argvalues'), None)
            if (isinstance(values, (ast.List, ast.Tuple, ast.Set)) and not values.elts) or (
                    isinstance(values, ast.Dict) and not values.keys):
                return False
        return True

    # Cache only direct imported calls from helpers; no recursion or dynamic dispatch.
    bridge = {}
    for name, fn in helpers.items():
        bridge[name] = [(line, target) for line, base, attr in calls(fn)
                        if (target := resolve(base, attr)) in targets]
    for parent in tree.body:
        if isinstance(parent, ast.ClassDef) and parent.decorator_list:
            continue
        functions = parent.body if isinstance(parent, ast.ClassDef) and parent.name.startswith("Test") else [parent]
        class_bindings = ({name for node in _scope_nodes(parent) for name in _bound_names(node)}
                          if isinstance(parent, ast.ClassDef) else set())
        if isinstance(parent, ast.ClassDef):
            for node in _scope_nodes(parent):
                if isinstance(node, ast.Call) and _call_name(node.func) in ('setattr', 'delattr', 'monkeypatch.setattr') and node.args:
                    base = node.args[0]
                    while isinstance(base, (ast.Attribute, ast.Subscript)):
                        base = base.value
                    if isinstance(base, ast.Name):
                        class_bindings.add(base.id)
        for test in functions:
            if (not isinstance(test, (ast.FunctionDef, ast.AsyncFunctionDef))
                    or not test.name.startswith("test_") or not supported_decorators(test, class_bindings)):
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
    pytest_collision = any(
        _module(path) == 'pytest' for path in docs
    )
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
        direct_defs = {node for node in tree.body if isinstance(node, DEFS)}
        # Definitions inside module-level control flow also bind names, but
        # definitions nested inside functions or classes are separate scopes.
        scope_nodes = list(_scope_nodes(tree))
        assigned = {name for node in scope_nodes if node not in direct_defs
                    for name in _bound_names(node)}
        assigned.update(name for node in scope_nodes for name in _expression_bindings(node))
        for name, nodes in defs.items():
            if len(nodes) != 1 or name in assigned or nodes[0].decorator_list:
                continue
            node = nodes[0]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                    isinstance(part, (ast.Yield, ast.YieldFrom)) for part in _scope_nodes(node)):
                continue
            hits = [e for e in excerpts if e["start"] <= node.end_lineno and node.lineno <= e["end"]]
            if hits:
                targets[module, name] = (hits[0], node.lineno)
    result, scanned = [], 0
    if not modules:
        return result
    test_imports = {(module, *module.rpartition(".")[::2]) for module, _ in targets}
    has_docs = "docs" in roles or any(docs[p][0] == "docs" for p in selected_paths)
    unique = _unique_names(docs, targets) if has_docs else {}
    pytest_collision = any(
        _module(path) == 'pytest' for path in docs
    )
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
            for line, anchor, target, helper in _test_edges(tree, targets, follow_paths=follow_paths, pytest_collision=pytest_collision):
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
