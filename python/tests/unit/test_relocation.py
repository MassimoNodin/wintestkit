"""Relocation diagnostics: a not-found element is looked for in the app's other windows."""

from collections.abc import Iterator
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import model, targets
from wintestkit.commands.check import format_results
from wintestkit.config import load_config
from wintestkit.engine import query, relocate
from wintestkit.engine.diagnose import Diagnostic
from wintestkit.engine.locator import Locator
from wintestkit.errors import AmbiguousElementError, ElementNotFoundError
from wintestkit.expect import expect
from wintestkit.model import BoundWindow, Element, Page, Window
from wintestkit.targets import ModuleLoader, Target

ARROW = "→"
CHEVRON = "\u203a"
PATH = (
    f'Window "Edit Customer" {CHEVRON} Group #AddressBox "Address" {CHEVRON} Edit #Street "Street"'
)


@pytest.fixture(autouse=True)
def fake_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query, "make_condition", lambda **props: props)


class AddressBox(Page):
    root = Element(automation_id="AddressBox")
    street = Element(automation_id="Street")


class Home(Page):
    window = Window(title="Customer")

    name = Element(automation_id="Street")
    address = AddressBox()


def build_app(*, moved: bool = True) -> FakeApp:
    customer = FakeElement("Window", "Customer", class_name="Window")
    edit = FakeElement("Window", "Edit Customer", class_name="Window")
    if moved:
        street = FakeElement("Edit", "Street", automation_id="Street")
        box = FakeElement("Group", "Address", automation_id="AddressBox", children=[street])
        edit.add(box)
    return FakeApp([customer, edit])


def fail(bound: Any) -> ElementNotFoundError:
    with pytest.raises(ElementNotFoundError) as info:
        bound.resolve(0)
    return info.value


# -- the leaf moved -------------------------------------------------------------------------------


def test_leaf_found_in_another_window() -> None:
    error = fail(Home(build_app()).name)
    assert f'  {ARROW} found in another window: Window "Edit Customer" {CHEVRON}' in str(error)
    assert str(error).count("found in another window") == 1
    assert "  hint: the element moved to another window" in str(error)
    assert f"test_relocation.py:{Home.name.source[1]}" in str(error)
    found = error.diagnostic.relocations
    assert len(found) == 1
    assert found[0].kind == "element"
    assert found[0].target == "Home.name"
    assert found[0].window == 'Window "Edit Customer"'
    assert found[0].path.endswith('Edit #Street "Street"')


def test_leaf_in_another_window_exact_lines() -> None:
    lines = str(fail(Home(build_app()).name)).splitlines()
    assert f"  {ARROW} found in another window: {PATH}" in lines
    assert any(line.startswith("  hint: the element moved to another window") for line in lines)


def test_leaf_in_the_same_window_under_a_different_container() -> None:
    street = FakeElement("Edit", "Street", automation_id="Street")
    other = FakeElement("Group", "Box", automation_id="Other", children=[street])
    customer = FakeElement("Window", "Customer", class_name="Window", children=[other])
    error = fail(Home(FakeApp([customer])).address.street)
    text = str(error)
    lines = text.splitlines()
    assert (
        f'  {ARROW} found in the same window under a different container: Group #Other "Box" '
        f'{CHEVRON} Edit #Street "Street"'
    ) in lines
    assert "found in another window" not in text
    assert "moved to another window" not in text
    root_at = model._display_location(AddressBox.root.source)
    assert (
        "  hint: the component root locator no longer matches the container of this element — "
        f"update `root` at {root_at}"
    ) in lines
    found = error.diagnostic.relocations
    assert len(found) == 1
    assert found[0].same_window
    assert found[0].window == 'Window "Customer"'
    assert error.diagnostic.to_dict()["relocations"][0]["sameWindow"] is True
    assert Diagnostic.from_dict(error.to_dict()["diagnostic"]) == error.diagnostic


def test_nested_window_with_the_same_title_is_not_repeated_in_the_path() -> None:
    street = FakeElement("Edit", "Street", automation_id="Street")
    inner = FakeElement("Window", "Edit Customer", class_name="Window", children=[street])
    edit = FakeElement("Window", "Edit Customer", class_name="Window", children=[inner])
    app = FakeApp([FakeElement("Window", "Customer", class_name="Window"), edit])
    error = fail(Home(app).name)
    assert f'  {ARROW} found in another window: Window "Edit Customer" {CHEVRON} Edit' in str(error)
    assert f'Window "Edit Customer" {CHEVRON} Window' not in str(error)


def test_the_found_element_is_never_used() -> None:
    page = Home(build_app())
    with pytest.raises(ElementNotFoundError):
        page.name.click(timeout=0)
    assert not page.name.exists()


def test_component_root_found_elsewhere_means_the_box_moved() -> None:
    error = fail(Home(build_app()).address.street)
    text = str(error)
    assert f"  {ARROW} found in another window: {PATH}" in text
    assert (
        f"  {ARROW} the component root Home.address.root (AddressBox) was found in: "
        'Window "Edit Customer"'
    ) in text
    mount = model._display_location(Home.address._source)
    declared = model._display_location(AddressBox.street.source)
    assert mount is not None
    assert mount.endswith("test_relocation.py:" + str(Home.address._source[1]))  # type: ignore[index]
    assert (
        f"  hint: the box moved — move `address = AddressBox()` ({mount}) "
        "to the page for that window, or set its window"
    ) in text
    assert f"  declared: {declared}" in text
    kinds = [r.kind for r in error.diagnostic.relocations]
    assert kinds == ["element", "component_root"]


def test_mounted_root_itself_not_found_reports_the_root() -> None:
    error = fail(Home(build_app()).address.root)
    assert [r.kind for r in error.diagnostic.relocations] == ["component_root"]
    assert "the component root Home.address.root (AddressBox) was found in:" in str(error)
    assert "the box moved" in str(error)


def test_root_in_the_declared_window_is_not_a_moved_box() -> None:
    customer = FakeElement("Window", "Customer", class_name="Window")
    customer.add(FakeElement("Group", "Address", automation_id="AddressBox"))
    app = FakeApp([customer])
    error = fail(Home(app).address.street)
    assert error.diagnostic.relocations == ()
    assert ARROW not in str(error)


def test_nothing_found_elsewhere_leaves_the_message_alone() -> None:
    error = fail(Home(build_app(moved=False)).address.street)
    assert error.diagnostic.relocations == ()
    assert error.diagnostic.hint is None
    assert str(error) == error.diagnostic.message + " (waited 0.0s)"
    assert ARROW not in str(error)
    assert "relocations" not in error.diagnostic.to_dict()


def test_ambiguous_failures_do_not_search(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> list[Any]:
        raise AssertionError("searched")

    monkeypatch.setattr(relocate, "find_elsewhere", boom)
    window = FakeElement("Window", "Customer", class_name="Window")
    window.add(FakeElement("Button", "OK"))
    window.add(FakeElement("Button", "OK"))

    class Ambiguous(Page):
        window = Window(title="Customer")
        ok = Element(control_type="Button", name="OK")
        grid_cell = Element(control_type="Button", name="OK", index=5)

    page = Ambiguous(FakeApp([window]))
    with pytest.raises(AmbiguousElementError):
        page.ok.resolve(0)
    with pytest.raises(ElementNotFoundError):
        page.grid_cell.resolve(0)  # index out of range: the element exists


def test_check_explains_relocations() -> None:
    results = Home(build_app()).check()
    street = results["address.street"]
    assert isinstance(street, ElementNotFoundError)
    assert "the box moved" in str(street)
    assert results["name"] is not None


# -- surfaces -------------------------------------------------------------------------------------


def test_diagnostic_dict_carries_relocations() -> None:
    error = fail(Home(build_app()).address.street)
    data = error.to_dict()["diagnostic"]
    assert data["relocations"][0] == {
        "kind": "element",
        "target": "Home.address.street",
        "window": 'Window "Edit Customer"',
        "path": PATH,
    }
    assert data["relocations"][1]["kind"] == "component_root"
    assert data["hint"].startswith("the box moved")
    assert data["declared"].endswith(f"test_relocation.py:{AddressBox.street.source[1]}")
    again = Diagnostic.from_dict(data)
    assert again == error.diagnostic
    assert "found in another window" in again.format()


def test_expect_failure_shows_relocations() -> None:
    page = Home(build_app())
    with pytest.raises(AssertionError) as info:
        expect(page.address.street, timeout=0).to_exist()
    assert f"{ARROW} found in another window: {PATH}" in str(info.value)


def test_wtk_check_output_indents_relocations() -> None:
    error = fail(Home(build_app()).address.street)
    result = targets.CheckResult(
        status="not_found",
        duration_ms=1.0,
        message=str(error),
        diagnostic=error.diagnostic,
        qualname="Home.address.street",
    )
    text = format_results([result])
    assert text.startswith("✗ Home.address.street  ")
    assert f"\n      {ARROW} found in another window: {PATH}" in text
    assert result.to_dict()["diagnostic"]["relocations"]


# -- bounds ---------------------------------------------------------------------------------------


def many_windows(count: int) -> FakeApp:
    windows = []
    for i in range(count):
        window = FakeElement("Window", f"W{i}", class_name="Window")
        window.add(FakeElement("Edit", "Street", automation_id="Street"))
        windows.append(window)
    return FakeApp(windows)


def test_matches_are_capped() -> None:
    found = relocate.find_elsewhere(many_windows(12), Locator(automation_id="Street"))  # type: ignore[arg-type]
    assert len(found) == relocate.MAX_MATCHES


def test_expired_budget_searches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    monkeypatch.setattr(relocate, "_clock", lambda: now[0])
    app = many_windows(3)
    assert relocate.find_elsewhere(app, Locator(automation_id="Street"), deadline=99.0) == []  # type: ignore[arg-type]


def test_search_stops_when_the_budget_runs_out(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = [0.0]

    def clock() -> float:
        ticks[0] += 0.5
        return ticks[0]

    monkeypatch.setattr(relocate, "_clock", clock)
    app = many_windows(30)
    found = relocate.find_elsewhere(app, Locator(automation_id="Street"), limit=30)  # type: ignore[arg-type]
    assert 0 < len(found) < 30
    assert ticks[0] <= relocate.RELOCATE_BUDGET + 3  # a few more reads after the deadline


def test_only_a_bounded_number_of_windows_is_visited() -> None:
    found = relocate.find_elsewhere(
        many_windows(relocate.MAX_WINDOWS + 10),  # type: ignore[arg-type]
        Locator(automation_id="Street"),
        limit=1000,
    )
    assert len(found) == relocate.MAX_WINDOWS


def test_leaf_only_ignores_scope_and_position() -> None:
    chain = Locator(
        automation_id="X",
        index=2,
        depth=1,
        within=Locator(name="Outer"),
    )
    assert relocate.leaf_only(chain) == Locator(automation_id="X")


# -- loose ends -----------------------------------------------------------------------------------

PAGES = dedent(
    """
    from wintestkit import Page, Window, Element

    class Box(Page):
        root = Element(automation_id="Box")
        field = Element(automation_id="Field")

    class Host(Page):
        window = Window(title="Host")
        box = Box()
    """
)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[ModuleLoader, Path]]:
    monkeypatch.syspath_prepend(str(tmp_path))
    package = tmp_path / "reloc_pages"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    file = package / "main.py"
    file.write_text(PAGES, encoding="utf-8")
    loader = ModuleLoader(load_config(tmp_path))
    yield loader, file
    loader._purge_project_modules()


def test_whole_file_check_skips_mounted_components(
    project: tuple[ModuleLoader, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    loader, file = project
    monkeypatch.setattr(model.BoundElement, "resolve", lambda self, timeout: FakeElement("Edit"))
    monkeypatch.setattr(model.BoundWindow, "resolve", lambda self, timeout: FakeElement("Window"))
    app: Any = object()
    whole = targets.check_page(app, loader, file)
    assert [r.qualname for r in whole] == [
        "Host.window",
        "Host.box.root",
        "Host.box.field",
    ]
    explicit = targets.check_page(app, loader, file, "Box")
    assert [r.qualname for r in explicit] == ["Box.root", "Box.field"]
    assert loader.get_page(Target(file, "Box")) in loader.mounted_components()


# -- window on a component instance ---------------------------------------------------------------


def test_instance_window_reflects_the_mount_override() -> None:
    class NoWindow(Page):
        root = Element(automation_id="Box")

    class Holder(Page):
        window = Window(title="Holder")
        swapped = NoWindow(window=Window(title="Swapped"))
        plain = NoWindow()

    app: Any = object()
    first, second = Holder(app), Holder(app)
    swapped = first.swapped.window
    assert isinstance(swapped, BoundWindow)
    assert swapped.locator.title == "Swapped"
    assert swapped.page is first.swapped
    assert swapped.qualname.endswith("Holder.swapped.window")
    assert second.swapped.window.page is second.swapped  # type: ignore[attr-defined]
    assert first.plain.window is None
    standalone = NoWindow(app, window=Window(title="Own"))
    assert standalone.window.locator.title == "Own"  # type: ignore[attr-defined]
