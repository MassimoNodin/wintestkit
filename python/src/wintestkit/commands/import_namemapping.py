"""Opt-in NameMapping importer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from wintestkit.commands import common
from wintestkit.name_mapping import convert_detailed


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "import-namemapping", help="generate a Python page from NameMapping XML"
    )
    parser.add_argument("xml", metavar="XML", help="NameMapping export")
    parser.add_argument("output", metavar="PY", help="new Python page skeleton")
    parser.add_argument("--force", action="store_true", help="overwrite the output file")
    parser.add_argument(
        "--managed-class-names",
        action="store_true",
        help="match runtime class names using the WPF inspector (requires inspector)",
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    source, target = Path(args.xml), Path(args.output)
    if target.exists() and not args.force:
        raise common.CommandError(f"{target} exists; pass --force to overwrite", common.EXIT_USAGE)
    try:
        result = convert_detailed(source, managed_class_names=args.managed_class_names)
    except (OSError, ValueError) as exc:
        raise common.CommandError(str(exc), common.EXIT_USAGE) from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result.code, encoding="utf-8")
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    todos = "1 TODO comment" if result.todos == 1 else f"{result.todos} TODO comments"
    print(
        f"Generated {target}: {result.declared} windows and elements, {todos}; "
        "review aliases and locators before use."
    )
    return common.EXIT_OK
