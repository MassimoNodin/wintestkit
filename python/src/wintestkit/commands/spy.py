"""Terminal locator picker."""

from __future__ import annotations

import argparse
import threading
from typing import Any

from wintestkit.commands import common


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("spy", help="pick locators with Ctrl+Click; Esc exits")
    parser.add_argument("--all-processes", action="store_true")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    from wintestkit.engine.spy import SpySession
    from wintestkit.engine.suggest import suggest_locator
    from wintestkit.uia.element import UIAElement

    app = None if args.all_processes else common.attach_app(common.load(args))
    pids = frozenset(app.pids) if app is not None else None
    finished = threading.Event()

    def hover(element: UIAElement) -> None:
        if common.is_tty():
            print("\r" + element.info().short() + "\x1b[K", end="", flush=True)

    def pick(element: UIAElement) -> None:
        suggestion = suggest_locator(element, app)
        print("\nPicked: " + element.info().short())
        if suggestion.window is not None:
            print("  window = " + suggestion.window[0])
        for name, code, _ in suggestion.helpers:
            print(f"  {name} = {code}")
        print(f"  {suggestion.attribute_name} = {suggestion.code}", flush=True)

    session = SpySession(hover, pick, finished.set, None if pids is None else pids.__contains__)
    try:
        session.start()
        print("Spy: Ctrl+Click to pick; Esc or Ctrl+C to exit.", flush=True)
        while not finished.wait(0.1):
            if not session.running:
                raise common.CommandError(
                    "Spy session stopped unexpectedly.", common.EXIT_ENVIRONMENT
                )
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()
        print()
    return common.EXIT_OK
