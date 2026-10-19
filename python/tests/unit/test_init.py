import ast
import re
import tomllib
from pathlib import Path

import pytest

from wintestkit.cli import main
from wintestkit.commands.init import skill_files
from wintestkit.config import load_config


def test_init_creates_a_valid_starter_project(tmp_path: Path) -> None:
    root = tmp_path / "new project"
    assert main(["init", str(root), "--app", "C:/Apps/My App.exe"]) == 0
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert "wintestkit" not in config.get("tool", {})
    loaded = load_config(root)
    assert loaded.app is not None
    assert loaded.app.path == Path("C:/Apps/My App.exe")
    assert "My App.exe" not in (root / "wintestkit.yaml").read_text(encoding="utf-8")
    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
    for relative in ["pages/main.py", "flows/main.py", "tests/test_smoke.py"]:
        ast.parse((root / relative).read_text(encoding="utf-8"))
    assert 'Window(title="My App")' in (root / "pages/main.py").read_text(encoding="utf-8")
    assert (root / ".gitignore").read_text(encoding="utf-8").splitlines() == [
        "wintestkit.local.toml",
        "wintestkit.local.yaml",
        ".venv/",
        "__pycache__/",
        ".pytest_cache/",
        ".ruff_cache/",
        "wtk-report/",
        "wtk-results/",
    ]


@pytest.mark.parametrize("ending", ["", "\n"])
def test_init_extends_existing_gitignore_without_duplicates(tmp_path: Path, ending: str) -> None:
    ignore_path = tmp_path / ".gitignore"
    original = "# Keep my rules\ncustom-output/\nwintestkit.local.toml\nwtk-report/" + ending
    ignore_path.write_text(original, encoding="utf-8")
    assert main(["init", str(tmp_path)]) == 0
    updated = ignore_path.read_text(encoding="utf-8")
    assert updated.startswith(original + ("" if ending else "\n"))
    assert updated.splitlines().count("wintestkit.local.toml") == 1
    assert updated.splitlines().count("wtk-report/") == 1
    assert "wtk-results/" in updated.splitlines()
    assert main(["init", str(tmp_path), "--force"]) == 0
    assert ignore_path.read_text(encoding="utf-8") == updated


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
    config = load_config(tmp_path)
    assert config.app is not None
    assert config.app.path == Path("C:/Original.exe")


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


SKILL = ".claude/skills/wintestkit-tests"


def _tree(folder: Path) -> dict[str, str]:
    return {
        path.relative_to(folder).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(folder.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def test_init_writes_the_agent_skill(tmp_path: Path) -> None:
    assert main(["init", str(tmp_path)]) == 0
    written = _tree(tmp_path / SKILL)
    assert written == skill_files()
    assert "SKILL.md" in written
    assert written["SKILL.md"].startswith("---\nname: wintestkit-tests\ndescription: ")
    assert {"references/api.md", "references/fixing-breakages.md"} <= written.keys()
    assert "references/migration-from-testcomplete.md" in written


def test_skill_is_not_overwritten_unless_forced(tmp_path: Path) -> None:
    assert main(["init", str(tmp_path)]) == 0
    skill = tmp_path / SKILL / "SKILL.md"
    skill.write_text("my notes\n", encoding="utf-8")
    assert main(["init", str(tmp_path)]) == 0
    assert skill.read_text(encoding="utf-8") == "my notes\n"
    assert main(["init", str(tmp_path), "--force"]) == 0
    assert skill.read_text(encoding="utf-8") == skill_files()["SKILL.md"]


def test_every_shipped_copy_of_the_skill_is_identical() -> None:
    """``skills/wintestkit-tests`` is canonical; run ``python scripts/sync_skill.py`` to update."""
    repo = Path(__file__).resolve().parents[3]
    canonical = repo / "skills" / "wintestkit-tests"
    if not canonical.is_dir():
        pytest.skip("not running from a repository checkout")
    expected = _tree(canonical)
    assert expected == skill_files(), "packaged copy differs: run python scripts/sync_skill.py"
    example = repo / "examples" / "calculator-tests" / ".claude" / "skills" / "wintestkit-tests"
    assert _tree(example) == expected, "example copy differs: run python scripts/sync_skill.py"


def test_skill_links_resolve_and_sizes_are_reasonable() -> None:
    written = skill_files()
    body = written["SKILL.md"]
    assert len(body.splitlines()) < 300
    for target in re.findall(r"\]\((references/[^)#]+)", body):
        assert target in written
