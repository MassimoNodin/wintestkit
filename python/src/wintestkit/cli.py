"""Command-line entry point of WinTestKit (``wtk``)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable, Sequence

from wintestkit import __version__
from wintestkit.commands import common

Handler = Callable[[argparse.Namespace], int]


def _command_modules() -> list[str]:
    return ["run", "discover", "doctor", "highlight", "check", "inspect", "spy"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wtk",
        description="UI test automation for Windows WPF applications.",
    )
    parser.add_argument("--version", action="version", version=f"wintestkit {__version__}")
    parser.add_argument("--root", metavar="DIR", help="project root (default: nearest project)")
    parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        default=os.environ.get("WTK_LOG", "WARNING"),
        help="log level of the wintestkit logger (default: WARNING)",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    import importlib

    for name in _command_modules():
        importlib.import_module(f"wintestkit.commands.{name}").add_parser(subparsers)
    return parser


def _configure_logging(level: str) -> None:
    numeric = logging.getLevelNamesMapping().get(level.upper())
    if numeric is None:
        raise common.CommandError(f"unknown log level {level!r}", common.EXIT_USAGE)
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    logging.getLogger("wintestkit").setLevel(numeric)


def _split_passthrough(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split ``wtk run -k x -- --pytest-arg`` at the first ``--``."""
    if "--" in argv:
        index = argv.index("--")
        return argv[:index], argv[index + 1 :]
    return argv, []


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI; returns the process exit code."""
    own, passthrough = _split_passthrough(list(sys.argv[1:] if argv is None else argv))
    parser = build_parser()
    try:
        args = parser.parse_args(own)
    except SystemExit as exit_request:  # argparse exits on --help, --version and usage errors
        return int(exit_request.code or 0) if isinstance(exit_request.code, int | None) else 2
    args.pytest_args = passthrough
    if not getattr(args, "command", None):
        parser.print_help()
        return common.EXIT_OK
    handler: Handler = args.handler
    try:
        _configure_logging(args.log_level)
        return handler(args)
    except common.CommandError as exc:
        print(f"wtk: {exc}", file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        return _report_exception(exc, args.log_level)


def _report_exception(exc: Exception, log_level: str) -> int:
    from wintestkit.errors import (
        AppNotRunningError,
        ConfigError,
        EnvironmentNotReadyError,
        WtkError,
    )
    from wintestkit.targets import TargetError

    if isinstance(exc, ConfigError | TargetError):
        print(f"wtk: {exc}", file=sys.stderr)
        return common.EXIT_USAGE
    if isinstance(exc, EnvironmentNotReadyError | AppNotRunningError):
        print(f"wtk: {exc}", file=sys.stderr)
        print("wtk: run `wtk doctor` to check the environment", file=sys.stderr)
        return common.EXIT_ENVIRONMENT
    if isinstance(exc, WtkError):
        print(f"wtk: {exc}", file=sys.stderr)
        return common.EXIT_FAILURE
    print(f"wtk: internal error: {exc}", file=sys.stderr)
    print("wtk: rerun with --log-level DEBUG for the traceback", file=sys.stderr)
    if log_level.upper() == "DEBUG":
        import traceback

        traceback.print_exc()
    return common.EXIT_INTERNAL
