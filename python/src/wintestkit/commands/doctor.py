"""``wtk doctor``: check that this machine and session can run UI tests."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from wintestkit.commands import common

if TYPE_CHECKING:
    from wintestkit.doctor import Check

_ICONS = {"ok": "✓", "warn": "!", "fail": "✗", "skip": "-"}


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "doctor",
        help="check the environment",
        description="Check the machine, session, UI Automation and project configuration.",
    )
    parser.add_argument("--json", action="store_true", help="print the checks as JSON")
    parser.set_defaults(handler=run)


def format_checks(checks: list[Check]) -> str:
    lines: list[str] = []
    for check in checks:
        lines.append(f"{_ICONS[check.status]} {check.title}: {check.detail}")
        if check.hint and check.status in ("warn", "fail"):
            lines.append(f"    {check.hint}")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    from wintestkit.config import load_config
    from wintestkit.doctor import has_failures, run_checks
    from wintestkit.errors import ConfigError

    root = common.resolve_root(args)
    try:
        checks = run_checks(load_config(root))
    except ConfigError as error:
        checks = run_checks(None, config_error=error)
    if args.json:
        common.print_json([c.to_dict() for c in checks])
    else:
        print(format_checks(checks))
    return common.EXIT_ENVIRONMENT if has_failures(checks) else common.EXIT_OK
