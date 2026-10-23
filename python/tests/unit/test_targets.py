"""Target loading, project reloads and structured resolution results."""

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fakes import FakeElement

from wintestkit import model, object_previews, targets
from wintestkit.config import load_config
from wintestkit.engine.diagnose import Diagnostic
from wintestkit.errors import AmbiguousElementError, ElementNotFoundError, UIAError
from wintestkit.targets import ModuleLoader, Target, TargetError, parse_target

SOURCE = (
    "from wintestkit import Page, Window, Element, Elements\n"
    "class Main(Page):\n"
    "    window = Window(title='Demo')\n"
    "    ok = Element(name='OK')\n"
    "    many = Elements(name='OK')\n"
    "class Child(Main):\n"
    "    ok = None\n"
    "    extra = Element(name='Extra')\n"
    "class Bare(Page):\n"
    "    button = Element(name='Button')\n"
)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[ModuleLoader, Path]]:
    monkeypatch.syspath_prepend(str(tmp_path))
    package = tmp_path / "target_pages"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    file = package / "main.py"
    file.write_text(SOURCE, encoding="utf-8")
    loader = ModuleLoader(load_config(tmp_path))
    yield loader, file
    loader._purge_project_modules()


def test_parse_relative_absolute_and_windows_paths(tmp_path: Path) -> None:
    target = parse_target("pages/main.py::Main.ok", tmp_path)
    assert target == Target((tmp_path / "pages/main.py").resolve(), "Main.ok")
    assert target.display(tmp_path) == "pages/main.py::Main.ok"
    assert parse_target(f"{target.file}::Main", tmp_path).file == target.file
    assert parse_target("pages/main.py", tmp_path).qualname == ""
    if os.name == "nt":
        assert parse_target(r"C:\wtk\pages\main.py::Main.ok", tmp_path).file == Path(
            r"C:\wtk\pages\main.py"
        )


def test_reload_scan_ignores_dot_prefixed_directories(tmp_path: Path) -> None:
    root = tmp_path / ".workspace" / "project"
    root.mkdir(parents=True)
    visible = root / "pages.py"
    visible.write_text(SOURCE, encoding="utf-8")
    for relative in (".custom/pages.py", "pkg/.cache/pages.py"):
        hidden = root / relative
        hidden.parent.mkdir(parents=True)
        hidden.write_text(SOURCE, encoding="utf-8")
    loader = ModuleLoader(load_config(root))
    assert set(loader._scan()) == {visible}


@pytest.mark.parametrize(
    "text", ["", "::Main", "main.py::", "main.py:: ", "main.py::Main..ok", "main.py::Main.1ok"]
)
def test_bad_target_syntax(tmp_path: Path, text: str) -> None:
    with pytest.raises(TargetError):
        parse_target(text, tmp_path)


def test_highlight_requires_page_name(tmp_path: Path) -> None:
    with pytest.raises(TargetError):
        parse_target("main.py", tmp_path, require_qualname=True)


def test_module_names_and_lookup(project: tuple[ModuleLoader, Path]) -> None:
    loader, file = project
    assert loader.module_name(file) == "target_pages.main"
    assert loader.module_name(file.parent / "__init__.py") == "target_pages"
    assert loader.load(file).__file__ == str(file)
    page = loader.get_page(Target(file, "Main"))
    assert loader.get_element(Target(file, "Main.ok")) == (page, "ok")
    assert loader.get_element(Target(file, "Main")) == (page, "window")
    assert loader.element_names(loader.get_page(Target(file, "Child"))) == [
        "window",
        "many",
        "extra",
    ]
    assert set(loader.pages_in(file)) == {"Main", "Child", "Bare"}


@pytest.mark.parametrize("qualname", ["Missing", "Main.missing", "Main.ok.extra"])
def test_bad_element_name(project: tuple[ModuleLoader, Path], qualname: str) -> None:
    loader, file = project
    with pytest.raises(TargetError):
        loader.get_element(Target(file, qualname))


def test_element_is_not_a_page(project: tuple[ModuleLoader, Path]) -> None:
    loader, file = project
    with pytest.raises(TargetError, match="not a page"):
        loader.get_page(Target(file, "Main.ok"))


def test_reload_same_size_within_one_timestamp_second(project: tuple[ModuleLoader, Path]) -> None:
    loader, file = project
    first = loader.load(file)
    original_time = file.stat().st_mtime_ns
    file.write_text(SOURCE.replace("Extra", "Other"), encoding="utf-8")
    os.utime(file, ns=(original_time + 100_000, original_time + 100_000))
    assert loader.refresh(force=True)
    second = loader.load(file)
    assert second is not first
    assert second.Child.extra._own.name == "Other"
    assert not loader.refresh(force=True)


def test_reload_dependency(project: tuple[ModuleLoader, Path]) -> None:
    loader, file = project
    dependency = file.parent / "labels.py"
    dependency.write_text("NAME = 'One'\n", encoding="utf-8")
    file.write_text("from .labels import NAME\n" + SOURCE, encoding="utf-8")
    loader.refresh(force=True)
    assert loader.load(file).NAME == "One"
    stamp = dependency.stat().st_mtime_ns
    dependency.write_text("NAME = 'Two'\n", encoding="utf-8")
    os.utime(dependency, ns=(stamp + 100_000, stamp + 100_000))
    loader.refresh(force=True)
    assert loader.load(file).NAME == "Two"


def test_namespace_and_conflicting_project_modules(
    project: tuple[ModuleLoader, Path], tmp_path: Path
) -> None:
    loader, file = project
    loader.load(file)
    other = tmp_path / "other"
    package = other / "target_pages"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    other_file = package / "second.py"
    other_file.write_text("VALUE = 42\n", encoding="utf-8")
    other_loader = ModuleLoader(load_config(other))
    assert other_loader.load(other_file).VALUE == 42
    assert Path(sys.modules["target_pages"].__file__).parent == package
    namespace = other / "namespace"
    namespace.mkdir()
    namespace_file = namespace / "main.py"
    namespace_file.write_text("VALUE = 43\n", encoding="utf-8")
    assert other_loader.load(namespace_file).VALUE == 43


@pytest.mark.parametrize(
    "source,expected",
    [
        ("this is invalid python\n", "SyntaxError"),
        ("raise ValueError('broken')\n", "ValueError: broken"),
    ],
)
def test_import_errors_have_source_location(
    project: tuple[ModuleLoader, Path], source: str, expected: str
) -> None:
    loader, file = project
    file.write_text(source, encoding="utf-8")
    with pytest.raises(TargetError) as failure:
        loader.load(file)
    assert expected in str(failure.value)
    assert f"{file.as_posix()}:1" in str(failure.value)


def test_missing_file(project: tuple[ModuleLoader, Path]) -> None:
    loader, file = project
    with pytest.raises(TargetError, match="file not found"):
        loader.load(file.with_name("missing.py"))


def test_bound_resolution_and_checks(
    project: tuple[ModuleLoader, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    loader, file = project
    element = FakeElement("Button", "OK")
    window = FakeElement("Window", "Demo")
    monkeypatch.setattr(model.BoundElement, "resolve", lambda self, timeout: element)
    monkeypatch.setattr(model.BoundWindow, "resolve", lambda self, timeout: window)
    app: Any = SimpleNamespace()
    result = targets.resolve_target(app, loader, Target(file, "Main.ok"))
    assert result.status == "found" and result.uia is element
    assert "uia" not in result.to_dict()
    assert targets.resolve_target(app, loader, Target(file, "Main.many")).status == "found"
    assert targets.resolve_target(app, loader, Target(file, "Bare")).element.name == "Demo"
    results = targets.check_page(app, loader, file, "Main")
    assert [result.qualname for result in results] == ["Main.window", "Main.ok", "Main.many"]
    assert all(result.status == "found" for result in results)
    assert results[1].to_dict()["qualname"] == "Main.ok"


@pytest.mark.parametrize(
    "error_type,status",
    [
        (ElementNotFoundError, "not_found"),
        (AmbiguousElementError, "ambiguous"),
        (UIAError, "error"),
    ],
)
def test_resolution_errors(error_type: type[Exception], status: str) -> None:
    diagnostic = Diagnostic("not_found", "missing", "Button", "Demo", 0)
    error = error_type("COM failed") if error_type is UIAError else error_type(diagnostic)

    def fail(timeout: float) -> None:
        raise error

    result = targets.resolve_bound(SimpleNamespace(resolve=fail), 0)
    assert result.status == status
    assert result.duration_ms >= 0
    assert result.message


@pytest.mark.parametrize(
    "qualname,member", [("Main.ok", "ok"), ("Mounted.address.street", "street")]
)
def test_explicit_check_resolves_only_requested_member_once(
    project: tuple[ModuleLoader, Path], monkeypatch: pytest.MonkeyPatch, qualname: str, member: str
) -> None:
    loader, file = project
    file.write_text(
        SOURCE + "class Address(Page):\n    street = Element(name='Street')\n"
        "class Mounted(Page):\n    address = Address()\n",
        encoding="utf-8",
    )
    element = FakeElement("Button", "OK")
    resolved = []
    captured = []

    def resolve(bound, timeout):
        resolved.append(bound.definition.name)
        return element

    monkeypatch.setattr(model.BoundElement, "resolve", resolve)
    monkeypatch.setattr(
        object_previews, "capture_bound", lambda bound, actual: captured.append((bound, actual))
    )
    result = targets.resolve_target(SimpleNamespace(), loader, Target(file, qualname), capture=True)
    assert result.status == "found" and result.uia is element
    assert resolved == [member]
    assert len(captured) == 1 and captured[0][1] is element
    assert captured[0][0].definition.name == member


def test_explicit_collection_check_resolves_first_without_capture(
    project: tuple[ModuleLoader, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    loader, file = project
    element = FakeElement("Button", "OK")
    resolved = []

    def resolve(bound, timeout):
        resolved.append(bound.definition.name)
        return element

    monkeypatch.setattr(model.BoundElement, "resolve", resolve)
    monkeypatch.setattr(
        object_previews, "capture_bound", lambda *args: pytest.fail("collection must not capture")
    )
    result = targets.resolve_target(
        SimpleNamespace(), loader, Target(file, "Main.many"), capture=True
    )
    assert result.status == "found" and result.uia is element
    assert resolved == ["many"]


def test_normal_resolution_page_checks_and_flows_never_capture(
    project: tuple[ModuleLoader, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    loader, file = project
    file.write_text(SOURCE + "def probe(app):\n    Main(app).ok.resolve(0)\n", encoding="utf-8")
    element = FakeElement("Button", "OK")
    monkeypatch.setattr(model.BoundElement, "resolve", lambda *args: element)
    monkeypatch.setattr(model.BoundWindow, "resolve", lambda *args: element)
    monkeypatch.setattr(
        object_previews, "capture_bound", lambda *args: pytest.fail("automatic capture")
    )
    app = SimpleNamespace()
    assert targets.resolve_target(app, loader, Target(file, "Main.ok")).status == "found"
    assert targets.check_page(app, loader, file, "Main")
    assert targets.run_flow(app, loader, file, "probe").status == "passed"


def test_page_check_captures_each_single_element_when_asked(
    project: tuple[ModuleLoader, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    loader, file = project
    element = FakeElement("Button", "OK")
    captured = []
    monkeypatch.setattr(model.BoundElement, "resolve", lambda *args: element)
    monkeypatch.setattr(model.BoundWindow, "resolve", lambda *args: element)
    monkeypatch.setattr(
        object_previews, "capture_bound", lambda bound, actual: captured.append(bound.qualname)
    )
    results = targets.check_page(SimpleNamespace(), loader, file, "Main", capture=True)
    assert [result.qualname for result in results] == ["Main.window", "Main.ok", "Main.many"]
    # The collection resolves its first member but is never captured.
    assert captured == ["Main.window", "Main.ok"]


def test_check_rejects_no_pages(project: tuple[ModuleLoader, Path]) -> None:
    loader, file = project
    file.write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(TargetError, match="no pages"):
        targets.check_page(SimpleNamespace(), loader, file)
