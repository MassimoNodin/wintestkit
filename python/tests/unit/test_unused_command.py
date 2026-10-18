from __future__ import annotations

import json
from pathlib import Path

from wintestkit.cli import main


def _project(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        '[tool.wintestkit.app]\nprocess="app.exe"\n', encoding="utf-8"
    )
    (root / "pages").mkdir()
    (root / "pages" / "main.py").write_text(
        "from wintestkit import Element, Page\n"
        "class Base(Page):\n    base = Element(name='base')\n"
        "class Child(Base):\n    used = Element(name='used')\n    unused = Element(name='unused')\n"
        "class Mounted(Page):\n    child = Child()\n    own = Element(name='own')\n"
        "class Orphan(Page):\n    abandoned = Element(name='abandoned')\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_main.py").write_text(
        "def test_it(page):\n    page.used.click()\n", encoding="utf-8"
    )
    (root / "node_modules").mkdir()
    (root / "node_modules" / "ignored.py").write_text("bad syntax !!!", encoding="utf-8")


def test_cli_reports_only_static_unused_and_accounts_for_inheritance_mounts(tmp_path, capsys):
    _project(tmp_path)
    assert main(["--root", str(tmp_path), "unused", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    names = {entry["name"] for entry in result["unused"]}
    assert "abandoned" in names and "own" in names
    assert "base" not in names and "child" not in names and "used" not in names
    assert result["estimate"] is True
    assert not result["errors"]


def test_syntax_or_encoding_errors_suppress_markers_safely(tmp_path, capsys):
    _project(tmp_path)
    (tmp_path / "flows").mkdir()
    (tmp_path / "flows" / "broken.py").write_bytes(b"\xff\xfe")
    assert main(["--root", str(tmp_path), "unused", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["errors"]
    assert result["unused"] == []
