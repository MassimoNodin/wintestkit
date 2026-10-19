"""``wtk run``: run the tests through pytest with the WinTestKit options."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from wintestkit.commands import common

# pytest exit codes -> wtk exit codes
_EXIT_MAP = {0: 0, 1: 1, 2: 4, 3: 4, 4: 2, 5: 5}

_FORWARDED = (
    ("launch", "--wtk-launch"),
    ("timeout", "--wtk-timeout"),
    ("app", "--wtk-app"),
    ("input_mode", "--wtk-input-mode"),
    ("screenshots", "--wtk-screenshots"),
    ("slowmo", "--wtk-slowmo"),
    ("report", "--wtk-report"),
    ("events", "--wtk-events"),
    ("replay", "--wtk-replay"),
    ("replay_fps", "--wtk-replay-fps"),
    ("replay_scope", "--wtk-replay-scope"),
)


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "run",
        help="run tests",
        description="Run the tests with pytest. Put raw pytest arguments after `--`.",
    )
    parser.add_argument("tests", nargs="*", metavar="TESTS", help="test ids or paths")
    parser.add_argument("--launch", choices=("per-test", "attach"))
    parser.add_argument("--timeout", type=float, metavar="SECONDS")
    parser.add_argument("--app", metavar="PATH")
    parser.add_argument("--input-mode", dest="input_mode", choices=("pattern", "mouse"))
    parser.add_argument("--screenshots", choices=("off", "on-failure", "every-step"))
    parser.add_argument("--highlight", action="store_true")
    parser.add_argument("--slowmo", type=int, metavar="MS")
    parser.add_argument("--report", metavar="DIR")
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--no-html", action="store_true", help="write results.json only")
    parser.add_argument("--junit", metavar="PATH")
    parser.add_argument("--events", metavar="URL")
    parser.add_argument("--replay", choices=("off", "on", "retain-on-failure"))
    parser.add_argument("--replay-fps", type=float, metavar="FPS")
    parser.add_argument("--replay-scope", choices=("window", "desktop"))
    parser.add_argument("-k", dest="keyword", metavar="EXPR")
    parser.add_argument("-m", dest="marker", metavar="EXPR")
    parser.add_argument("-x", dest="exitfirst", action="store_true")
    parser.add_argument("--lf", action="store_true", help="re-run the last failures")
    parser.add_argument(
        "--no-env-check", action="store_true", help="skip the environment check before running"
    )
    parser.set_defaults(handler=run)


def build_pytest_args(args: argparse.Namespace) -> list[str]:
    """The pytest command line equivalent to the ``wtk run`` arguments."""
    argv: list[str] = []
    for attribute, option in _FORWARDED:
        value = getattr(args, attribute, None)
        if value is not None:
            argv += [option, str(value)]
    if args.highlight:
        argv.append("--wtk-highlight")
    if args.no_report:
        argv.append("--wtk-no-report")
    if args.no_html:
        argv.append("--wtk-no-html")
    if args.junit:
        argv.append(f"--junitxml={args.junit}")
    if args.keyword:
        argv += ["-k", args.keyword]
    if args.marker:
        argv += ["-m", args.marker]
    if args.exitfirst:
        argv.append("-x")
    if args.lf:
        argv.append("--lf")
    if os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD"):
        argv += ["-p", "wintestkit.pytest_plugin"]  # the entry point will not load it
    argv += list(args.tests)
    argv += list(getattr(args, "pytest_args", []))
    return argv


def _check_environment(root: Path) -> bool:
    """Run the quick environment checks; print the failures and return whether to proceed."""
    from wintestkit.config import load_config
    from wintestkit.doctor import run_checks
    from wintestkit.errors import ConfigError

    try:
        cfg = load_config(root)
    except ConfigError:
        return True  # reported by pytest as a usage error with the full message
    failures = [c for c in run_checks(cfg, quick=True) if c.status == "fail"]
    for check in failures:
        print(f"✗ {check.title}: {check.detail}", file=sys.stderr)
        if check.hint:
            print(f"  {check.hint}", file=sys.stderr)
    if failures:
        print("wtk: the environment is not ready for UI tests (see `wtk doctor`)", file=sys.stderr)
    return not failures


def run(args: argparse.Namespace) -> int:
    import pytest

    root = common.resolve_root(args)
    if not args.no_env_check and not _check_environment(root):
        return common.EXIT_ENVIRONMENT
    argv = build_pytest_args(args)
    previous = Path.cwd()
    os.chdir(root)
    try:
        code = int(pytest.main(argv))
    finally:
        os.chdir(previous)
    return _EXIT_MAP.get(code, common.EXIT_INTERNAL)
