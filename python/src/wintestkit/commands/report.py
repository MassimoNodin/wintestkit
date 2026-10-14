"""Regenerate an HTML report from saved results."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, cast

from wintestkit.commands import common
from wintestkit.config import load_config
from wintestkit.report.html import render


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("report", help="regenerate a saved HTML report")
    parser.add_argument("directory", nargs="?", metavar="DIR")
    parser.add_argument("--open", action="store_true", dest="open_browser")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    root = common.resolve_root(args)
    directory = Path(args.directory) if args.directory else load_config(root).report_dir
    if not directory.is_absolute():
        directory = root / directory
    try:
        loaded: Any = json.loads((directory / "results.json").read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("expected a JSON object")
        results = cast("dict[str, Any]", loaded)
        if results.get("version") != 1:
            raise ValueError("expected version 1 results")
        target = directory / "index.html"
        target.write_text(render(results), encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise common.CommandError(f"cannot regenerate report: {exc}", common.EXIT_USAGE) from exc
    print(f"Report: {target.resolve()}")
    if args.open_browser:
        os.startfile(target.resolve())
    return common.EXIT_OK
