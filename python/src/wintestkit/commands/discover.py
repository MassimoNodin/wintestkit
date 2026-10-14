"""``wtk discover``: list tests and screen definitions without importing user code."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from wintestkit.commands import common

if TYPE_CHECKING:
    from wintestkit.discovery import DiscoveryResult, ElementEntry


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "discover",
        help="list tests and screens",
        description="Statically discover tests and screen definitions (no user code is imported).",
    )
    parser.add_argument("paths", nargs="*", metavar="PATHS", help="files or folders to report")
    parser.add_argument("--json", action="store_true", help="print JSON (default when piped)")
    parser.add_argument("--pretty", action="store_true", help="indent the JSON output")
    parser.set_defaults(handler=run)


def describe_element(entry: ElementEntry) -> str:
    """The locator of a discovered element as ``Button[name="Sign in"]`` (best effort)."""
    from wintestkit.engine.locator import Locator, WindowLocator

    try:
        if entry.kind == "window":
            text = WindowLocator.from_dict(entry.locator.get("window", {})).describe()
        else:
            text = Locator.from_dict(entry.locator).describe()
    except (ValueError, TypeError, KeyError):
        text = "<incomplete locator>"
    return f"{text} (dynamic)" if entry.dynamic else text


def format_human(result: DiscoveryResult) -> str:
    root = Path(result.root)

    def relative(path: str) -> str:
        try:
            return Path(path).relative_to(root).as_posix()
        except ValueError:
            return path

    lines = [f"Tests ({len(result.tests)})"]
    width = max((len(t.id) for t in result.tests), default=0)
    for test in result.tests:
        lines.append(f"  {test.id.ljust(width)}  (line {test.range.start.line + 1})")
    lines.append(f"Screens ({len(result.screens)})")
    for screen in result.screens:
        lines.append(f"  {screen.qualname}  {relative(screen.file)}:{screen.range.start.line + 1}")
        name_width = max((len(e.name) for e in screen.elements), default=0)
        lines.extend(
            f"    {element.name.ljust(name_width)}  {describe_element(element)}"
            for element in screen.elements
        )
    for error in result.errors:
        lines.append(f"error: {relative(error.file)}:{error.line + 1}: {error.message}")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    from wintestkit.discovery import discover

    root = common.resolve_root(args)
    paths = [Path(p) if Path(p).is_absolute() else Path.cwd() / p for p in args.paths] or None
    result = discover(root, paths=paths)
    if args.json or args.pretty or not common.is_tty():
        common.print_json(result.to_dict(), pretty=args.pretty)
    else:
        sys.stdout.write(format_human(result) + "\n")
    return common.EXIT_OK
