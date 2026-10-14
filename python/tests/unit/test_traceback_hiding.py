"""Frames of wintestkit modules must be hidden from pytest tracebacks.

A failing UI test should show the user's line and the diagnostic message, not twenty frames of
engine internals. pytest hides a frame whose function sets ``__tracebackhide__ = True``; this test
enforces that for every function in the modules a user exception can pass through.
"""

import ast
from pathlib import Path

import pytest

import wintestkit

PACKAGE = Path(wintestkit.__file__).parent
MODULES = [
    "model.py",
    "expect.py",
    "app.py",
    "runtime.py",
    "engine/resolve.py",
    "engine/query.py",
    "engine/waits.py",
    "engine/actions.py",
    "engine/diagnose.py",
    "uia/patterns.py",
    "uia/element.py",
    "uia/com.py",
    "uia/input.py",
]


def _hides(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = node.body
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        if len(body) == 1:
            return True  # docstring-only body: nothing can raise through it
        first = body[1]
    return (
        isinstance(first, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__tracebackhide__" for t in first.targets)
        and isinstance(first.value, ast.Constant)
        and first.value.value is True
    )


@pytest.mark.parametrize("module", MODULES)
def test_every_function_hides_its_frame(module: str) -> None:
    path = PACKAGE / module
    tree = ast.parse(path.read_text(encoding="utf-8"))
    missing: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.body[0].lineno == node.lineno:
            continue  # one-line stubs such as overloads and protocol methods
        if not _hides(node):
            missing.append(f"{module}:{node.lineno} {node.name}")
    assert not missing, "functions without `__tracebackhide__ = True`: " + ", ".join(missing)
