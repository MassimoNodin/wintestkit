"""Helpers shared by the sub-commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from wintestkit.app import App
    from wintestkit.config import WtkConfig

EXIT_OK = 0
EXIT_FAILURE = 1  # test failures, element not found, check failures
EXIT_USAGE = 2  # usage or configuration error
EXIT_ENVIRONMENT = 3  # environment not ready / application not running
EXIT_INTERNAL = 4
EXIT_NO_TESTS = 5


class CommandError(Exception):
    """A user-facing failure with a chosen exit code (message printed without traceback)."""

    def __init__(self, message: str, code: int = EXIT_FAILURE) -> None:
        super().__init__(message)
        self.code = code


def resolve_root(args: argparse.Namespace) -> Path:
    """The project root: ``--root`` or the nearest ``[tool.wintestkit]`` project or the cwd."""
    from wintestkit.config import find_project_root

    explicit: str | None = getattr(args, "root", None)
    if explicit:
        return Path(explicit).resolve()
    cwd = Path.cwd()
    return find_project_root(cwd) or cwd


def load(args: argparse.Namespace) -> WtkConfig:
    from wintestkit.config import load_config

    return load_config(resolve_root(args))


def print_json(data: Any, *, pretty: bool = False, stream: TextIO | None = None) -> None:
    out = stream or sys.stdout
    if pretty:
        out.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    else:
        out.write(json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n")
    out.flush()


def is_tty(stream: TextIO | None = None) -> bool:
    out = stream or sys.stdout
    return bool(getattr(out, "isatty", lambda: False)())


def attach_app(cfg: WtkConfig, *, launch: bool = False) -> App:
    """Attach to the configured application, optionally launching it when it is not running."""
    from wintestkit.app import App
    from wintestkit.errors import AppNotRunningError, ConfigError

    if cfg.app is None:
        raise ConfigError(
            "no application configured: set [tool.wintestkit.app] in pyproject.toml", key="app"
        )
    try:
        return App.attach(process=cfg.app.process_name)
    except AppNotRunningError:
        if not launch:
            raise CommandError(
                "App is not running. Start it or pass --launch.", EXIT_ENVIRONMENT
            ) from None
    from wintestkit.pytest_plugin import launch_app

    return launch_app(cfg)
