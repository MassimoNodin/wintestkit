import ast
import tomllib
from pathlib import Path

import pytest

from wintestkit.cli import main


def test_init_creates_a_valid_starter_project(tmp_path: Path) -> None:
    root = tmp_path / "new project"
    assert main(["init", str(root), "--app", "C:/Apps/My App.exe"]) == 0
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["wintestkit"]["app"]["path"] == "C:/Apps/My App.exe"
    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
    for relative in ["pages/main.py", "tests/test_smoke.py"]:
        ast.parse((root / relative).read_text(encoding="utf-8"))
    assert 'Window(title="My App")' in (root / "pages/main.py").read_text(encoding="utf-8")
    assert (root / ".gitignore").read_text(encoding="utf-8") == "wtk-report/\n"


def test_init_preserves_existing_metadata_and_python_files(tmp_path: Path) -> None:
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text(
        '[project]\nname = "mine"\n[tool.pytest.ini_options]\naddopts = "-q"\n', encoding="utf-8"
    )
    page = tmp_path / "pages" / "main.py"
    page.parent.mkdir()
    page.write_text("custom = True\n", encoding="utf-8")
    assert main(["init", str(tmp_path)]) == 0
    assert main(["init", str(tmp_path)]) == 0
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config["project"]["name"] == "mine"
    assert config["tool"]["pytest"]["ini_options"]["addopts"] == "-q"
    assert page.read_text(encoding="utf-8") == "custom = True\n"
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8").count("wtk-report/") == 1


def test_force_replaces_only_starter_files(tmp_path: Path) -> None:
    assert main(["init", str(tmp_path), "--app", "C:/Original.exe"]) == 0
    page = tmp_path / "pages" / "main.py"
    page.write_text("custom = True\n", encoding="utf-8")
    assert main(["init", str(tmp_path), "--force", "--app", "C:/Replacement.exe"]) == 0
    assert 'Window(title="Replacement")' in page.read_text(encoding="utf-8")
    config = tomllib.loads((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["wintestkit"]["app"]["path"] == "C:/Original.exe"


def test_init_rejects_invalid_toml_without_modifying_it(tmp_path: Path) -> None:
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text("[broken", encoding="utf-8")
    assert main(["init", str(tmp_path)]) == 2
    assert config_path.read_text(encoding="utf-8") == "[broken"
    assert not (tmp_path / "pages").exists()


@pytest.mark.parametrize(
    "source",
    [
        'tool = "scalar"',
        "[tool]\npytest = 1",
        "[tool]\nwintestkit = false",
        "tool = { pytest = {} }",
    ],
)
def test_init_rejects_incompatible_tables_without_writes(tmp_path: Path, source: str) -> None:
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text(source, encoding="utf-8")
    assert main(["init", str(tmp_path)]) == 2
    assert config_path.read_text(encoding="utf-8") == source
    assert not (tmp_path / "pages").exists()
