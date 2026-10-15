from pathlib import Path
from textwrap import dedent

from wintestkit.discovery import discover


def write(root: Path, relative: str, source: str) -> Path:
    file = root / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(dedent(source).lstrip(), encoding="utf-8")
    return file


def test_discovers_public_module_functions_without_importing(tmp_path: Path) -> None:
    file = write(
        tmp_path,
        "flows/navigation.py",
        """
        raise RuntimeError("must not execute")

        @decorate
        def open_page():
            def nested(): pass

        async def tour(): pass
        def _private(): pass
        class Helper:
            def method(self): pass
    """,
    )
    result = discover(tmp_path)
    assert result.errors == ()
    assert [flow.id for flow in result.flows] == [
        "flows/navigation.py::open_page",
        "flows/navigation.py::tour",
    ]
    assert result.flows[0].file == file.as_posix()
    assert result.flows[0].name_range.start.line == 3
    assert result.flows[0].to_dict()["nameRange"]["start"] == {"line": 3, "character": 4}


def test_flow_directories_can_be_nested_and_respect_selection(tmp_path: Path) -> None:
    selected = write(tmp_path, "src/project/flows/account/login.py", "def login(): pass")
    write(tmp_path, "flows/navigation.py", "def navigate(): pass")
    write(tmp_path, "helpers.py", "def helper(): pass")
    write(tmp_path, ".venv/flows/ignored.py", "def ignored(): pass")
    result = discover(tmp_path, paths=[selected])
    assert [flow.name for flow in result.flows] == ["login"]
    assert len(discover(tmp_path).flows) == 2


def test_unsaved_flow_edits_and_syntax_errors(tmp_path: Path) -> None:
    file = write(tmp_path, "flows/navigation.py", "def original(): pass")
    edited = discover(tmp_path, overrides={file: "async def renamed(): pass"})
    assert [flow.name for flow in edited.flows] == ["renamed"]
    broken = discover(tmp_path, overrides={file: "def broken(:"})
    assert broken.flows == ()
    assert len(broken.errors) == 1
