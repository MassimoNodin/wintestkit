"""Resolve a page target, raise its window, and briefly outline its bounds."""

from __future__ import annotations

import argparse
import math
from typing import TYPE_CHECKING, Any

from wintestkit.commands import common

if TYPE_CHECKING:
    from wintestkit.targets import ElementResult


def nonnegative_seconds(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be a finite nonnegative number")
    return number


def nonnegative_milliseconds(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return number


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("highlight", help="find and outline a page or element")
    parser.add_argument("target", metavar="FILE::Page[.element]")
    parser.add_argument("--duration", type=nonnegative_milliseconds, default=1500, metavar="MS")
    parser.add_argument("--timeout", type=nonnegative_seconds, default=0.0, metavar="S")
    parser.add_argument("--launch", action="store_true", help="launch the app if it is not running")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.set_defaults(handler=run)


def format_result(result: ElementResult) -> str:
    if result.status == "found" and result.element is not None:
        info = result.element
        bounds = info.rect
        location = (
            f" at ({bounds.left},{bounds.top} {bounds.width}x{bounds.height})"
            if bounds is not None
            else " (no bounds)"
        )
        return f'\u2713 Found {info.control_type} "{info.name}"{location}'
    if result.diagnostic is not None:
        return result.diagnostic.format()
    return result.message or result.status


def run(args: argparse.Namespace) -> int:
    from wintestkit.engine import overlay
    from wintestkit.targets import ModuleLoader, parse_target, resolve_target

    cfg = common.load(args)
    target = parse_target(args.target, cfg.root, require_qualname=True)
    loader = ModuleLoader(cfg)
    loader.get_element(target)
    app = common.attach_app(cfg, launch=args.launch)
    try:
        result = resolve_target(app, loader, target, args.timeout)
        if result.status == "found":
            if result.uia is not None:
                from wintestkit.engine.actions import bring_to_front

                bring_to_front(result.uia)
                rect = result.uia.rect
            else:
                rect = result.element.rect if result.element is not None else None
            if rect is not None and not rect.is_empty():
                overlay.flash(rect, args.duration, block=True)
        if args.json:
            common.print_json(result.to_dict())
        else:
            print(format_result(result))
        return common.EXIT_OK if result.status == "found" else common.EXIT_FAILURE
    finally:
        if app.launched:
            app.close(timeout=cfg.app.close_timeout if cfg.app is not None else 10.0)
