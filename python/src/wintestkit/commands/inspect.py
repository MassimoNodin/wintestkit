"""Inspect application windows and elements at physical screen coordinates."""

from __future__ import annotations

import argparse
import re
import time
from typing import TYPE_CHECKING, Any

from wintestkit.commands import common

if TYPE_CHECKING:
    from wintestkit.config import WtkConfig
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
    parser.add_argument(
        "--managed", action="store_true", help="attach temporarily and list managed metadata"
    )
    parser.add_argument(
        "--read-managed",
        action="append",
        default=[],
        metavar="QUALIFIED_PATH",
        help="explicitly read a managed path (repeatable; requires --managed)",
    )
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


def _managed(elements: list[UIAElement], cfg: WtkConfig, keys: list[str]) -> list[dict[str, Any]]:
    """Own a short-lived registry, even when attach, reads, or the caller are interrupted."""
    from wintestkit import runtime
    from wintestkit.errors import InspectorLimitError, InspectorMappingError
    from wintestkit.inspector.paths import parse_managed_key
    from wintestkit.inspector.probe import current_identity
    from wintestkit.inspector.sessions import SessionRegistry

    paths = [parse_managed_key(key) for key in keys]
    if len(paths) > 32:
        raise common.CommandError(
            "At most 32 managed paths can be read at once.", common.EXIT_USAGE
        )
    with runtime.config_scope(cfg):
        runtime.require_managed()
        registry = SessionRegistry(request_timeout=cfg.inspector.request_timeout)
        try:
            results: list[dict[str, Any]] = []
            for element in elements:
                identity = current_identity(element.process_id)
                client = registry.attach(
                    identity,
                    target_hwnd=None,
                    deadline=time.monotonic() + cfg.inspector.attach_timeout,
                )
                runtime_id, hwnd = runtime.managed_element_identity(element)
                mapping = client.resolve(
                    runtime_id, hwnd, deadline=time.monotonic() + cfg.inspector.request_timeout
                )
                if mapping.status != "exact" or mapping.object_ref is None:
                    raise InspectorMappingError(
                        f"Managed mapping is unavailable: {mapping.status}", code="mappingFailed"
                    )
                reference = mapping.object_ref
                members = client.members(
                    reference.object_id,
                    reference.generation,
                    deadline=time.monotonic() + cfg.inspector.request_timeout,
                )
                member_pages = [members.to_json()]
                seen_tokens: set[str] = set()
                while members.next_token is not None:
                    token = members.next_token
                    if token in seen_tokens or len(member_pages) >= 256:
                        raise InspectorLimitError(
                            "Managed metadata pagination did not finish", code="limitExceeded"
                        )
                    seen_tokens.add(token)
                    members = client.members(
                        reference.object_id,
                        reference.generation,
                        page_token=token,
                        deadline=time.monotonic() + cfg.inspector.request_timeout,
                    )
                    member_pages.append(members.to_json())
                result: dict[str, Any] = {
                    "process": identity.to_json(),
                    "session": client.session.to_json(),
                    "mapping": mapping.to_json(),
                    "members": member_pages[0],
                }
                if len(member_pages) > 1:
                    result["memberPages"] = member_pages
                if paths:
                    values, read_id = client.read(
                        reference.object_id,
                        reference.generation,
                        [path.segments for path in paths],
                        deadline=time.monotonic() + cfg.inspector.request_timeout,
                    )
                    result["read"] = {
                        "values": [value.to_json() for value in values],
                        "readId": read_id,
                    }
                results.append(result)
            return results
        finally:
            registry.close_all()


def run(args: argparse.Namespace) -> int:
    from wintestkit.engine import treedump
    from wintestkit.engine.locator import match_value
    from wintestkit.engine.properties import inspection_values
    from wintestkit.uia.element import from_point

    cfg = common.load(args)
    if args.read_managed and not args.managed:
        raise common.CommandError("--read-managed requires --managed.", common.EXIT_USAGE)
    if args.managed:
        from wintestkit import runtime

        with runtime.config_scope(cfg):
            runtime.require_managed()
    app = common.attach_app(cfg)
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
        managed = _managed([element], cfg, args.read_managed) if args.managed else None
        if args.json:
            data = {
                "element": info.to_dict(),
                "ancestors": [parent.to_dict() for parent in ancestors],
                "properties": inspection_values(element, cfg.property_aliases),
            }
            if managed is not None:
                data["managed"] = managed[0]
            common.print_json(data)
        else:
            print(treedump.format_node(info))
            print("Patterns: " + (", ".join(info.patterns or ()) or "none"))
            for key, value in inspection_values(element, cfg.property_aliases).items():
                print(f"{key}: {value}")
            for depth, parent in enumerate(ancestors, start=1):
                print("  " * depth + treedump.format_node(parent))
            if managed is not None:
                print("Managed metadata:")
                common.print_json(managed[0], pretty=True)
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
    managed = _managed(windows, cfg, args.read_managed) if args.managed else None
    if args.json:
        trees = [
            treedump.dump_json(window, max_depth=args.depth, property_aliases=cfg.property_aliases)
            for window in windows
        ]
        tree_data: dict[str, Any] = {"windows": trees} if args.all_windows else trees[0]
        if managed is not None:
            tree_data["managed"] = managed if args.all_windows else managed[0]
        common.print_json(tree_data)
    else:
        print(
            "\n\n".join(
                treedump.dump(window, max_depth=args.depth, property_aliases=cfg.property_aliases)
                for window in windows
            )
        )
        if managed is not None:
            print("Managed metadata:")
            common.print_json(managed if args.all_windows else managed[0], pretty=True)
    return common.EXIT_OK
