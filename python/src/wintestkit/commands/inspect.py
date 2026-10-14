"""Inspect application windows and elements at physical screen coordinates."""

from __future__ import annotations

import argparse
import re
from typing import TYPE_CHECKING, Any

from wintestkit.commands import common

if TYPE_CHECKING:
    from wintestkit.uia.element import UIAElement


def _depth(value: str) -> int:
    try:
        depth = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("depth must be an integer") from exc
    if not 0 <= depth <= 50:
        raise argparse.ArgumentTypeError("depth must be between 0 and 50")
    return depth


def _point(value: str) -> tuple[int, int]:
    parts = value.split(",")
    try:
        if len(parts) != 2:
            raise ValueError
        point = (int(parts[0]), int(parts[1]))
        if any(not -(2**31) <= coordinate < 2**31 for coordinate in point):
            raise ValueError
        return point
    except ValueError as exc:
        raise argparse.ArgumentTypeError("point must be X,Y with signed 32-bit integers") from exc


def _title(value: str) -> str | re.Pattern[str]:
    if len(value) >= 2 and value.startswith("/") and value.endswith("/"):
        try:
            return re.compile(value[1:-1])
        except re.error as exc:
            raise argparse.ArgumentTypeError(f"invalid window regex: {exc}") from exc
    return value


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("inspect", help="inspect the application UI Automation tree")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--window", type=_title, metavar="TITLE|/REGEX/")
    selection.add_argument("--all-windows", action="store_true")
    selection.add_argument("--at", type=_point, metavar="X,Y")
    parser.add_argument("--depth", type=_depth, default=12, metavar="N")
    parser.add_argument("--json", action="store_true", help="print inspection data as JSON")
    parser.set_defaults(handler=run)


def _ancestors(element: UIAElement) -> list[UIAElement]:
    ancestors: list[UIAElement] = []
    parent = element.parent()
    while parent is not None and len(ancestors) < 50:
        if parent.same_as(element) or any(parent.same_as(prior) for prior in ancestors):
            break
        ancestors.append(parent)
        parent = parent.parent()
    return ancestors


def run(args: argparse.Namespace) -> int:
    from wintestkit.engine import treedump
    from wintestkit.engine.locator import match_value
    from wintestkit.uia.element import from_point

    app = common.attach_app(common.load(args))
    if args.at is not None:
        element = from_point(*args.at)
        if element is None or element.process_id not in app.pids:
            raise common.CommandError("No element of the configured app at that point.")
        if element.control_type == "Text":
            parent = element.parent()
            if parent is not None and parent.control_type == "Button":
                element = parent
        info = element.info(with_patterns=True)
        ancestors = [parent.info(with_patterns=True) for parent in _ancestors(element)]
        if args.json:
            common.print_json(
                {"element": info.to_dict(), "ancestors": [parent.to_dict() for parent in ancestors]}
            )
        else:
            print(treedump.format_node(info))
            print("Patterns: " + (", ".join(info.patterns or ()) or "none"))
            for depth, parent in enumerate(ancestors, start=1):
                print("  " * depth + treedump.format_node(parent))
        return common.EXIT_OK
    if args.all_windows or args.window is not None:
        windows = app.top_level_windows()
        if args.window is not None:
            windows = [window for window in windows if match_value(args.window, window.name)]
        if not windows:
            raise common.CommandError("No matching application window.")
        if not args.all_windows and len(windows) > 1:
            raise common.CommandError(f"Ambiguous window title: {len(windows)} windows match.")
    else:
        windows = [app.main_window()]
    if args.json:
        trees = [treedump.dump_json(window, max_depth=args.depth) for window in windows]
        common.print_json({"windows": trees} if args.all_windows else trees[0])
    else:
        print("\n\n".join(treedump.dump(window, max_depth=args.depth) for window in windows))
    return common.EXIT_OK
