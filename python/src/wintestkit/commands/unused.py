"""Conservative static estimate of page definitions without known source references."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

from wintestkit.commands import common
from wintestkit.discovery import discover

_SKIP = {".git", ".venv", "venv", "node_modules", "build", "dist", "__pycache__", ".tox"}


def _python_sources(root):
    for path in root.rglob("*.py"):
        if not any(
            part in _SKIP or part.startswith(".") for part in path.relative_to(root).parts[:-1]
        ):
            yield path


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("unused", help="estimate unused page definitions (static)")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    root = common.resolve_root(args)
    result = discover(root)
    # Parse the project once. Any source syntax/encoding error suppresses positive findings,
    # since a missed reference would otherwise create a false unused marker.
    sources: dict[str, ast.Module] = {}
    errors: list[dict[str, str]] = []
    for path in _python_sources(root):
        try:
            text = path.read_text(encoding="utf-8")
            sources[str(path.resolve())] = ast.parse(text, filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append({"file": path.relative_to(root).as_posix(), "message": str(exc)})

    pages_by_name = {page.name: page for page in result.pages}
    definitions_by_name: dict[str, list[tuple[Any, Any]]] = {}
    for page in result.pages:
        for element in page.elements:
            definitions_by_name.setdefault(element.name, []).append((page, element))
    used: set[tuple[str, str]] = set()
    if errors:
        used.update((page.file, element.name) for page in result.pages for element in page.elements)
    else:
        for page in result.pages:
            page_path = str(Path(page.file).resolve())
            tree = sources.get(page_path)
            if tree is None:
                used.update((page.file, e.name) for e in page.elements)
                continue
            class_node = next(
                (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == page.name),
                None,
            )
            if class_node:
                for base in class_node.bases:
                    if isinstance(base, ast.Name) and base.id in pages_by_name:
                        base_page = pages_by_name[base.id]
                        used.update((base_page.file, e.name) for e in base_page.elements)
            # A mounted component's class can expose its members through delegation even when
            # callers don't spell each member; count those members conservatively as used.
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in pages_by_name
                ):
                    mounted = pages_by_name[node.func.id]
                    used.update((mounted.file, e.name) for e in mounted.elements)
        for file, tree in sources.items():
            for node in ast.walk(tree):
                name = (
                    node.id
                    if isinstance(node, ast.Name)
                    else node.attr
                    if isinstance(node, ast.Attribute)
                    else None
                )
                if name is None:
                    continue
                is_reference = (
                    (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load))
                    or isinstance(node, ast.Attribute)
                    or (isinstance(node, ast.Constant) and node.value == name)
                )
                if is_reference:
                    for page, element in definitions_by_name.get(name, ()):
                        is_own_declaration = (
                            str(Path(page.file).resolve()) == file
                            and node.lineno == element.name_range.start.line + 1
                        )
                        if not is_own_declaration:
                            used.add((page.file, element.name))
    candidates = [
        {"name": element.name, "file": page.file, "line": element.name_range.start.line + 1}
        for page in result.pages
        for element in page.elements
        if (page.file, element.name) not in used
    ]
    if args.json or not common.is_tty():
        common.print_json(
            {
                "estimate": True,
                "label": "Static estimate; dynamic references may be missed.",
                "errors": errors,
                "unused": candidates,
            }
        )
    else:
        print("Unused definitions (static estimate; dynamic references may be missed)")
        for item in candidates:
            print(f"  {item['name']}  {item['file']}:{item['line']}")
    return common.EXIT_OK
