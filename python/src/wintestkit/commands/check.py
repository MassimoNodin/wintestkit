"""Check every declared element of a page or a Python module."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from wintestkit.commands import common

if TYPE_CHECKING:
    from wintestkit.targets import CheckResult


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("check", help="resolve every element in a page or file")
    parser.add_argument("target", metavar="FILE[::Page]")
    parser.add_argument("--json", action="store_true", help="print the results as JSON")
    parser.set_defaults(handler=run)


def format_results(results: list[CheckResult]) -> str:
    icons = {"found": "\u2713", "ambiguous": "\u26a0", "not_found": "\u2717", "error": "\u2717"}
    return "\n".join(
        f"{icons[result.status]} {result.qualname}  "
        + (
            result.locator
            if result.status == "found"
            else (result.message or result.status).replace("\n", "\n    ")
        )
        for result in results
    )


def run(args: argparse.Namespace) -> int:
    from wintestkit.targets import ModuleLoader, TargetError, check_page, parse_target

    cfg = common.load(args)
    target = parse_target(args.target, cfg.root)
    loader = ModuleLoader(cfg)
    if target.qualname:
        loader.get_page(target)
    elif not loader.pages_in(target.file):
        raise TargetError(f"{target.file.name} defines no pages")
    app = common.attach_app(cfg)
    results = check_page(app, loader, target.file, target.qualname or None)
    if args.json:
        common.print_json({"results": [result.to_dict() for result in results]})
    else:
        print(format_results(results))
    passed = all(result.status == "found" for result in results)
    return common.EXIT_OK if passed else common.EXIT_FAILURE
