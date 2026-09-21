"""Deterministic structural extraction from one Python source file.

The module is deliberately narrow: one ``ast.parse``, one ``tokenize`` pass, no
import of the analysed module, no execution, no clock and no network. Every
value it returns is derived from the text it was given, so scanning the same
input twice yields the same result.

``scan_source`` fails closed by raising :class:`SourceScanError` when the
source cannot be parsed or tokenised. A caller must never score a file it could
not read: an unreadable file is reported as undetermined, never as clean.
"""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass

__all__ = [
    "FunctionStat",
    "ImportBinding",
    "SourceScan",
    "SourceScanError",
    "scan_source",
]


class SourceScanError(ValueError):
    """Raised when a source file cannot be parsed or tokenised."""


@dataclass(frozen=True)
class ImportBinding:
    """One name bound by an import statement.

    ``is_star`` and ``always_consumed`` mark bindings whose consumption cannot be
    decided locally: a star import binds names this scan cannot enumerate, and a
    ``__future__`` import binds a compiler feature rather than a name. Both are
    counted as consumed, because "undecidable" and "unused" are different claims
    and only the second one is being made here.
    """

    bound_name: str
    module: str
    line: int
    is_star: bool = False
    always_consumed: bool = False


@dataclass(frozen=True)
class FunctionStat:
    """Structural facts about one function or method definition."""

    qualname: str
    line: int
    decision_points: int
    filled_body: bool


@dataclass(frozen=True)
class SourceScan:
    """Everything the audit dimensions and rules need, and nothing else.

    ``code_lines`` counts lines that carry neither a comment nor a docstring,
    apart from blank lines: it is a line-level accounting of the code, not an
    executed-statement count. ``referenced_names`` is the set of bare names used
    by the module, plus the names it re-exports; both are used to decide whether
    an import is actually consumed.
    """

    path: str
    source: str
    tree: ast.Module
    line_count: int
    code_lines: int
    comment_lines: int
    docstring_lines: int
    functions: tuple[FunctionStat, ...]
    imports: tuple[ImportBinding, ...]
    referenced_names: frozenset[str]
    reexported_names: frozenset[str]
    comments: tuple[tuple[int, str], ...]
    docstrings: tuple[tuple[int, str], ...]

    @property
    def filled_functions(self) -> int:
        return sum(1 for function in self.functions if function.filled_body)

    @property
    def used_imports(self) -> tuple[ImportBinding, ...]:
        """Bindings this module consumes, or re-exports, or cannot decide about.

        A star import binds names this scan cannot enumerate, so it is counted
        as consumed: undecidable is not the same as unused, and a false positive
        here would penalise a legitimate pattern.
        """
        return tuple(
            binding
            for binding in self.imports
            if binding.is_star
            or binding.always_consumed
            or binding.bound_name in self.referenced_names
            or binding.bound_name in self.reexported_names
        )


def scan_source(path: str, source: str) -> SourceScan:
    """Parse and tokenise ``source``, or raise :class:`SourceScanError`."""
    if not isinstance(path, str) or not path or path != path.strip():
        raise ValueError("path must be a nonempty, trimmed string.")
    if not isinstance(source, str):
        raise TypeError("source must be a string.")
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        raise SourceScanError(
            f"{path}: source cannot be parsed ({type(exc).__name__})."
        ) from exc
    try:
        comments = _comment_tokens(source)
    except (tokenize.TokenError, SyntaxError, IndentationError, ValueError) as exc:
        raise SourceScanError(
            f"{path}: source cannot be tokenised ({type(exc).__name__})."
        ) from exc

    collector = _Collector()
    collector.visit(tree)
    functions = tuple(sorted(collector.functions, key=lambda item: (item.line, item.qualname)))
    imports = tuple(sorted(collector.imports, key=lambda item: (item.line, item.bound_name)))

    docstrings = collector.docstrings
    docstring_lines: set[int] = set()
    for start, end in collector.docstring_ranges:
        docstring_lines.update(range(start, end + 1))
    comment_lines = {line for line, _ in comments}
    blank_lines = {
        number for number, text in enumerate(source.splitlines(), start=1) if not text.strip()
    }
    excluded = docstring_lines | comment_lines | blank_lines
    line_count = len(source.splitlines())

    return SourceScan(
        path=path,
        source=source,
        tree=tree,
        line_count=line_count,
        code_lines=max(0, line_count - len(excluded)),
        comment_lines=len(comment_lines),
        docstring_lines=len(docstring_lines),
        functions=functions,
        imports=imports,
        referenced_names=frozenset(collector.referenced),
        reexported_names=frozenset(collector.reexported),
        comments=comments,
        docstrings=docstrings,
    )


def _comment_tokens(source: str) -> tuple[tuple[int, str], ...]:
    reader = io.StringIO(source).readline
    found: list[tuple[int, str]] = []
    for token in tokenize.generate_tokens(reader):
        if token.type == tokenize.COMMENT:
            found.append((token.start[0], token.string.strip()))
    return tuple(found)


def _is_docstring_statement(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _is_placeholder_statement(statement: ast.stmt) -> bool:
    """Return whether a statement declares intent without implementing it."""
    if isinstance(statement, ast.Pass):
        return True
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
        value = statement.value.value
        if value is Ellipsis or isinstance(value, str):
            return True
    if isinstance(statement, ast.Raise):
        name = _dotted_name(statement.exc)
        if name in {"NotImplementedError", "NotImplemented"}:
            return True
    return False


def _dotted_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _decision_points(function: ast.AST) -> int:
    """Count decision points in a function, excluding nested definitions."""
    counter = _DecisionCounter()
    for statement in getattr(function, "body", ()):
        counter.visit(statement)
    return counter.count


class _DecisionCounter(ast.NodeVisitor):
    def __init__(self) -> None:
        self.count = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802 - ast API
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        return

    def visit_BoolOp(self, node: ast.BoolOp) -> None:  # noqa: N802
        self.count += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        self.count += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:  # noqa: N802
        self.count += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self.count += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:  # noqa: N802
        self.count += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:  # noqa: N802
        self.count += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # noqa: N802
        self.count += 1
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:  # noqa: N802
        self.count += 1
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:  # noqa: N802
        self.count += 1
        self.generic_visit(node)


class _Collector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.functions: list[FunctionStat] = []
        self.imports: list[ImportBinding] = []
        self.referenced: set[str] = set()
        self.reexported: set[str] = set()
        self.docstrings: list[tuple[int, str]] = []
        self.docstring_ranges: list[tuple[int, int]] = []
        self._stack: list[str] = []

    def visit_Module(self, node: ast.Module) -> None:  # noqa: N802 - ast API
        self._collect_docstring(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self._collect_docstring(node)
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._collect_docstring(node)
        self.referenced.update(_annotation_names(node))
        self.functions.append(
            FunctionStat(
                qualname=".".join([*self._stack, node.name]),
                line=node.lineno,
                decision_points=_decision_points(node),
                filled_body=_body_is_filled(node),
            )
        )
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            bound = alias.asname or alias.name.split(".")[0]
            self.imports.append(ImportBinding(bound, alias.name, node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        is_future = module == "__future__"
        for alias in node.names:
            if alias.name == "*":
                self.imports.append(ImportBinding("*", module, node.lineno, True))
                continue
            bound = alias.asname or alias.name
            self.imports.append(
                ImportBinding(
                    bound,
                    f"{module}.{alias.name}",
                    node.lineno,
                    False,
                    is_future,
                )
            )

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        self.referenced.add(node.id)

    def visit_Global(self, node: ast.Global) -> None:  # noqa: N802
        self.referenced.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:  # noqa: N802
        self.referenced.update(node.names)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        self._collect_reexports(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        self.referenced.update(_annotation_names(node.annotation))
        self._collect_reexports([node.target], node.value)
        self.generic_visit(node)

    def _collect_reexports(self, targets: list[ast.AST], value: ast.AST | None) -> None:
        exports_all = any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in targets
        )
        if not exports_all or not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            return
        for element in value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                self.reexported.add(element.value)

    def _collect_docstring(self, node: ast.AST) -> None:
        body = getattr(node, "body", None)
        if not body:
            return
        first = body[0]
        if not _is_docstring_statement(first):
            return
        value = first.value
        start = value.lineno
        end = getattr(value, "end_lineno", start) or start
        self.docstrings.append((start, value.value))
        self.docstring_ranges.append((start, end))


def _body_is_filled(node: ast.AST) -> bool:
    """Return whether a body does something beyond declaring itself."""
    body = getattr(node, "body", ())
    return any(not _is_placeholder_statement(statement) for statement in body)


def _annotation_names(node: ast.AST) -> set[str]:
    """Collect the names an annotation mentions, including quoted ones.

    A forward reference written as a string (``registry: "RouteRegistry | None"``)
    is the normal way to break an import cycle, so treating it as unused would
    accuse the clearest style in the codebase. A quoted annotation that cannot be
    parsed as an expression is skipped: this collector adds evidence of use, and
    it must never invent it.
    """
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            try:
                quoted = ast.parse(child.value, mode="eval")
            except (SyntaxError, ValueError):
                continue
            found.update(
                inner.id for inner in ast.walk(quoted) if isinstance(inner, ast.Name)
            )
    return found
