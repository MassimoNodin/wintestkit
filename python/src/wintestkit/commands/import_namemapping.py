"""Opt-in TestComplete NameMapping importer."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from wintestkit.commands import common
from wintestkit.name_mapping import convert


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("import-namemapping", help="generate a Python page from NameMapping XML")
    parser.add_argument("xml", metavar="XML", help="TestComplete NameMapping export")
    parser.add_argument("output", metavar="PY", help="new Python page skeleton")
    parser.add_argument("--force", action="store_true", help="overwrite the output file")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    source, target = Path(args.xml), Path(args.output)
    if target.exists() and not args.force:
        raise common.CommandError(f"{target} exists; pass --force to overwrite", common.EXIT_USAGE)
    try:
        text = convert(source)
    except (OSError, ValueError) as exc:
        raise common.CommandError(str(exc), common.EXIT_USAGE) from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"Generated {target}; review aliases and locators before use.")
    return common.EXIT_OK
