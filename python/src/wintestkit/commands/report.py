"""Regenerate an HTML report from saved results."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from wintestkit.commands import common
from wintestkit.config import load_config
from wintestkit.report.html import render
from wintestkit.report.results import load_results


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
        results = load_results(directory / "results.json")
        target = directory / "index.html"
        target.write_text(render(results, directory), encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise common.CommandError(f"cannot regenerate report: {exc}", common.EXIT_USAGE) from exc
    print(f"Report: {target.resolve()}")
    audits = [
        (test, step, audit)
        for test in results.get("tests", [])
        for step in test.get("steps", [])
        for audit in step.get("audits", [])
    ]
    if audits:
        counts = {
            outcome: sum(audit.get("outcome") == outcome for _, _, audit in audits)
            for outcome in ("performed", "denied", "failed")
        }
        print(
            f"{len(audits)} writes: {counts['performed']} performed, "
            f"{counts['denied']} denied, {counts['failed']} failed"
        )
        for test, step, audit in audits:
            fields = ("operation", "typeFullName", "memberKey", "outcome", "reason", "timestampUtc")
            detail = " | ".join(str(audit.get(key, "")) for key in fields)
            print(
                f"  {test.get('name', test.get('id', 'Test'))} / "
                f"{step.get('name', step.get('action', 'Step'))}: {detail}"
            )
    if args.open_browser:
        os.startfile(target.resolve())
    return common.EXIT_OK
