"""Conservative static estimate of page definitions without known source references."""

from __future__ import annotations

import argparse
import ast
from typing import Any

from wintestkit.commands import common
from wintestkit.discovery import discover


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("unused", help="estimate unused page definitions (static)")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    root = common.resolve_root(args)
    result = discover(root)
    # Any source occurrence outside a definition is treated as a use. This intentionally errs
    # toward false negatives: inherited page attributes, mounts, string-based access and flows
    # remain in the source and therefore count as references.
    definitions = {
        (p.file, e.name, e.name_range.start.line) for p in result.pages for e in p.elements
    }
    candidates: list[dict[str, Any]] = []
    for file, name, line in sorted(definitions):
        try:
            source = (root / file).read_text(encoding="utf-8")
        except OSError:
            continue
        hits = []
        for node in ast.walk(ast.parse(source)):
            named_reference = isinstance(node, ast.Name) and node.id == name
            attribute_reference = isinstance(node, ast.Attribute) and node.attr == name
            string_reference = isinstance(node, ast.Constant) and node.value == name
            if (
                (named_reference or attribute_reference) and node.lineno != line + 1
            ) or string_reference:
                hits.append(node)
        # Cross-file uses and dynamic references: conservatively check all discovered Python.
        if not hits:
            for other in root.rglob("*.py"):
                ignored = {".venv", ".git", "__pycache__"}
                if other == root / file or any(part in ignored for part in other.parts):
                    continue
                try:
                    if name in other.read_text(encoding="utf-8"):
                        hits.append(None)
                        break
                except OSError:
                    continue
        if not hits:
            candidates.append({"name": name, "file": file, "line": line + 1})
    if args.json or not common.is_tty():
        common.print_json(
            {
                "estimate": True,
                "label": "Static estimate; dynamic references may be missed.",
                "unused": candidates,
            }
        )
    else:
        print("Unused definitions (static estimate; dynamic references may be missed)")
        for item in candidates:
            print(f"  {item['name']}  {item['file']}:{item['line']}")
    return common.EXIT_OK
