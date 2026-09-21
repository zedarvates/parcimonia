import pytest

from tiberium_ai.source_scan import SourceScanError, scan_source

COUNTED = "\n".join(
    [
        "# leading comment",
        '"""Doc.',
        "",
        "Two lines.",
        '"""',
        "import os",
        "",
        "def f():",
        "    return os",
    ]
)

BODIES = "\n".join(
    [
        "def passes():",
        "    pass",
        "",
        "def documented():",
        '    """Only a docstring."""',
        "",
        "def ellipsis():",
        "    ...",
        "",
        "def abstract():",
        "    raise NotImplementedError",
        "",
        "def returns():",
        "    return 1",
        "",
        "def documented_and_returns():",
        '    """Doc."""',
        "    return 1",
    ]
)

COMPLEX = "\n".join(
    [
        "def outer(a, b):",
        "    if a and b:",
        "        return 1",
        "    for _ in range(3):",
        "        pass",
        "    return 0",
        "",
        "def wrapping():",
        "    def inner(a):",
        "        if a:",
        "            return 1",
        "        return 0",
        "    return inner",
    ]
)


def test_line_accounting_separates_code_comments_and_docstrings():
    scan = scan_source("sample.py", COUNTED)

    assert scan.line_count == 9
    assert scan.comment_lines == 1
    assert scan.docstring_lines == 4
    assert scan.code_lines == 3


def test_body_is_filled_only_when_it_does_something():
    scan = scan_source("bodies.py", BODIES)
    filled = {function.qualname for function in scan.functions if function.filled_body}

    assert filled == {"returns", "documented_and_returns"}
    assert scan.filled_functions == 2


def test_decision_points_exclude_nested_definitions():
    scan = scan_source("complex.py", COMPLEX)
    points = {function.qualname: function.decision_points for function in scan.functions}

    assert points == {"outer": 3, "wrapping": 0, "wrapping.inner": 1}


def test_imports_are_counted_as_used_only_when_consumed():
    source = "\n".join(
        [
            "from __future__ import annotations",
            "",
            "import os",
            "import sys as system",
            "from collections import OrderedDict",
            "from typing import Mapping",
            "",
            "",
            "def f() -> Mapping[str, object]:",
            '    return {"system": system.platform}',
        ]
    )
    scan = scan_source("imports.py", source)

    assert len(scan.imports) == 5
    assert {binding.bound_name for binding in scan.used_imports} == {
        "annotations",
        "Mapping",
        "system",
    }


def test_future_import_and_star_import_are_never_called_unused():
    source = "\n".join(
        [
            "from __future__ import annotations",
            "from math import *",
        ]
    )
    scan = scan_source("star.py", source)

    assert len(scan.used_imports) == len(scan.imports) == 2


def test_quoted_annotation_counts_as_a_use():
    source = "\n".join(
        [
            "from __future__ import annotations",
            "",
            "from .registry import RouteRegistry",
            "",
            "",
            'def f(registry: "RouteRegistry | None" = None):',
            "    return registry",
        ]
    )
    scan = scan_source("quoted.py", source)

    assert {binding.bound_name for binding in scan.used_imports} == {
        "annotations",
        "RouteRegistry",
    }


def test_reexport_declared_in_all_counts_as_a_use():
    source = "\n".join(
        [
            "from .thing import Thing",
            "",
            '__all__ = ["Thing"]',
        ]
    )
    scan = scan_source("exports.py", source)

    assert scan.reexported_names == {"Thing"}
    assert [binding.bound_name for binding in scan.used_imports] == ["Thing"]


def test_unparsable_source_raises_instead_of_returning_a_scan():
    with pytest.raises(SourceScanError):
        scan_source("broken.py", "def f(:\n")


def test_a_scan_rejects_a_blank_path():
    with pytest.raises(ValueError):
        scan_source("  ", "x = 1\n")


def test_source_must_be_a_string():
    with pytest.raises(TypeError):
        scan_source("sample.py", b"x = 1")
