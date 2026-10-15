"""Create a starter project while preserving existing user files."""

from __future__ import annotations

import argparse
import json
import tomllib
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any, cast

from wintestkit.commands import common


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("init", help="create a WinTestKit project")
    parser.add_argument("directory", nargs="?", metavar="DIR")
    parser.add_argument("--app", metavar="PATH")
    parser.add_argument(
        "--force", action="store_true", help="replace existing starter Python files"
    )
    parser.set_defaults(handler=run)


def _template(name: str, **values: str) -> str:
    source = files("wintestkit.scaffold").joinpath(name).read_text(encoding="utf-8")
    return Template(source).substitute(values)


def _write(path: Path, text: str, *, force: bool) -> None:
    if path.exists() and not force:
        print(f"Skipped existing {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"Created {path}")


def run(args: argparse.Namespace) -> int:
    root = Path(args.directory or args.root or ".").resolve()
    config_path = root / "pyproject.toml"
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    try:
        config = tomllib.loads(original)
    except tomllib.TOMLDecodeError as error:
        raise common.CommandError(
            f"cannot update invalid pyproject.toml: {error}", common.EXIT_USAGE
        ) from error
    app_path = Path(args.app or "C:/path/to/YourApp.exe")
    app_value = json.dumps(app_path.as_posix(), ensure_ascii=False)
    title = json.dumps(app_path.stem, ensure_ascii=False)
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
    if "wintestkit" not in tool:
        additions.append(_template("wintestkit.toml.tmpl", app_path=app_value))
    elif "app" not in tool["wintestkit"]:
        additions.append("[tool.wintestkit.app]\npath = " + app_value + "\n")
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
        print(f"Updated {config_path}")
    else:
        print("Skipped existing pyproject.toml configuration")
    for relative, content in {
        "pages/__init__.py": "",
        "pages/main.py": _template("main.py.tmpl", title=title),
        "tests/__init__.py": "",
        "tests/test_smoke.py": _template("test_smoke.py.tmpl"),
    }.items():
        _write(root / relative, content, force=args.force)
    ignore_path = root / ".gitignore"
    ignore = ignore_path.read_text(encoding="utf-8") if ignore_path.exists() else ""
    if "wtk-report/" not in ignore.splitlines():
        separator = "\n" if ignore and not ignore.endswith("\n") else ""
        ignore_path.write_text(ignore + separator + "wtk-report/\n", encoding="utf-8")
    print("\nNext: install wintestkit and pytest, select your app/window in pyproject.toml and")
    print("pages/main.py, then run wtk doctor and wtk run from the project directory.")
    return common.EXIT_OK
