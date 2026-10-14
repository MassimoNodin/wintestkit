"""Serve editor requests over standard input/output."""

import argparse
import sys
from typing import Any


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("serve", help="start the editor JSON-RPC server")
    parser.add_argument("--stdio", action="store_true", required=True)
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    from wintestkit.server import Server

    return Server(sys.stdout.buffer).serve(sys.stdin.buffer)
