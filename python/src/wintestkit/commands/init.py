"""Create a starter project while preserving existing user files."""

from __future__ import annotations

import argparse
import json
import shlex
import tomllib
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PureWindowsPath
from typing import Any, cast

from wintestkit.commands import common
from wintestkit.config import ensure_local_ignores, load_config
from wintestkit.errors import ConfigError


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("init", help="create a WinTestKit project")
    parser.add_argument("directory", nargs="?", metavar="DIR")
    parser.add_argument("--app", metavar="PATH")
    parser.add_argument("--args", default="", metavar="ARGS", help="application launch arguments")
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace existing starter Python files and the agent skill",
    )
    parser.set_defaults(handler=run)


def _template(name: str) -> str:
    return files("wintestkit.scaffold").joinpath(name).read_text(encoding="utf-8")


def skill_files(source: Traversable | None = None, prefix: str = "") -> dict[str, str]:
    """The packaged agent skill as ``{relative path: text}`` (written to ``.claude/skills``)."""
    folder = source or files("wintestkit.scaffold").joinpath("skills", "wintestkit-tests")
    found: dict[str, str] = {}
    for entry in sorted(folder.iterdir(), key=lambda item: item.name):
        if entry.is_dir():
            if entry.name != "__pycache__":
                found.update(skill_files(entry, f"{prefix}{entry.name}/"))
        else:
            found[prefix + entry.name] = entry.read_text(encoding="utf-8")
    return found


def _write(path: Path, text: str, *, force: bool) -> None:
    if path.exists() and not force:
        print(f"Skipped existing {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"Created {path}")


def _starter_process(root: Path, app_path: Path | None) -> str:
    """The process name the starter page targets: the configured app, else the ``--app`` file.

    Returns an empty string when no usable ``.exe`` name is known.
    """
    try:
        configured = load_config(root).app
    except ConfigError:
        configured = None
    path = configured.path if configured and configured.path else app_path
    process = (
        configured.process
        if configured and configured.process
        else (PureWindowsPath(str(path)).name if path else "")
    )
    return process if process.lower().endswith(".exe") and len(process) > len(".exe") else ""


def run(args: argparse.Namespace) -> int:
    root = Path(args.directory or args.root or ".").resolve()
    config_path = root / "pyproject.toml"
    config_exists = config_path.exists()
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    try:
        config = tomllib.loads(original)
    except tomllib.TOMLDecodeError as error:
        raise common.CommandError(
            f"cannot update invalid pyproject.toml: {error}", common.EXIT_USAGE
        ) from error
    if args.args and not args.app:
        raise common.CommandError("--args needs --app", common.EXIT_USAGE)
    app_path = Path(args.app) if args.app else None
    additions: list[str] = []
    tool_value: object = config.get("tool", {})
    tool = cast(dict[str, Any], tool_value)
    if not isinstance(tool_value, dict) or any(
        not isinstance(tool.get(section, {}), dict) for section in ("pytest", "wintestkit")
    ):
        raise common.CommandError(
            "tool, tool.pytest and tool.wintestkit must be TOML tables",
            common.EXIT_USAGE,
        )
    if "ini_options" not in tool.get("pytest", {}):
        additions.append(_template("pytest.toml.tmpl"))
    if additions:
        combined = original + ("\n" if original and not original.endswith("\n") else "")
        combined += "\n".join(additions)
        try:
            tomllib.loads(combined)
        except tomllib.TOMLDecodeError as error:
            raise common.CommandError(
                f"cannot extend pyproject.toml tables: {error}", common.EXIT_USAGE
            ) from error
        root.mkdir(parents=True, exist_ok=True)
        config_path.write_text(combined, encoding="utf-8")
        print(f"{'Updated' if config_exists else 'Created'} {config_path}")
    else:
        print("Skipped existing pyproject.toml configuration")
    process = _starter_process(root, app_path)
    page = _template("main.py.tmpl").replace(
        "__PROCESS__", json.dumps(process or "TODO: set your app process", ensure_ascii=False)
    )
    note = (
        ""
        if process
        else "    # TODO: set the process name of your app (for example Orders.exe).\n"
    )
    page = page.replace("__NOTE__", note)
    smoke = _template("test_smoke.py.tmpl" if process else "test_smoke_todo.py.tmpl")
    for relative, content in {
        "pages/__init__.py": "",
        "pages/main.py": page,
        "flows/__init__.py": "",
        "flows/main.py": _template("flow_main.py.tmpl"),
        "tests/__init__.py": "",
        "tests/test_smoke.py": smoke,
    }.items():
        _write(root / relative, content, force=args.force)
    for relative, text in skill_files().items():
        _write(root / ".claude/skills/wintestkit-tests" / relative, text, force=args.force)
    ignore_path = root / ".gitignore"
    old_ignore = ignore_path.read_bytes() if ignore_path.exists() else None
    ensure_local_ignores(root)
    if ignore_path.read_bytes() != old_ignore:
        print(f"{'Updated' if old_ignore is not None else 'Created'} {ignore_path}")
    _write(
        root / "wintestkit.yaml",
        "# Shared project settings. Machine paths belong in wintestkit.local.yaml.\n{}\n",
        force=False,
    )
    local = "# Machine-specific settings. Do not commit this file.\n" + (
        "app:\n  path: " + json.dumps(app_path.as_posix(), ensure_ascii=False) + "\n"
        if app_path
        else "{}\n"
    )
    if app_path and args.args:
        launch_args = [part.strip('"') for part in shlex.split(args.args, posix=False)]
        local += "  args: " + json.dumps(launch_args, ensure_ascii=False) + "\n"
    if args.app or "wintestkit" not in tool:
        _write(root / "wintestkit.local.yaml", local, force=False)
    if process or app_path:
        print(
            "\nNext: install wintestkit and pytest, then run wtk doctor and wtk run "
            "from the project directory."
        )
    else:
        print("\nNext: install wintestkit and pytest, select your app in wintestkit.local.yaml and")
        print("pages/main.py, then run wtk doctor and wtk run from the project directory.")
    print("AI coding tools find the wintestkit-tests skill in .claude/skills/wintestkit-tests.")
    return common.EXIT_OK
