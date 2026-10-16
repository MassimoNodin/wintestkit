"""Page objects composed into pages: mounted components, their roots, scoping and checks."""

from collections.abc import Iterator
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import model, targets
from wintestkit.config import load_config
from wintestkit.discovery import discover
from wintestkit.engine.diagnose import Diagnostic
from wintestkit.engine.locator import Locator, WindowLocator
from wintestkit.errors import ElementNotFoundError
from wintestkit.model import BoundWindow, Element, Elements, Page, PageObject, Window
from wintestkit.targets import ModuleLoader, Target, TargetError

APP: Any = SimpleNamespace()


class AddressBox(Page):
    """A reusable box with a root: it can move between windows."""

    root = Element(automation_id="AddressBox")
    street = Element(automation_id="Street")
    city = Element(automation_id="City", within=root)
    lines = Elements(control_type="Edit")


class Home(Page):
    window = Window(title="Home")

    title = Element(automation_id="Title")
    address = AddressBox()


class Billing(Page):
    window = Window(title="Billing")

    shipping_panel = Element(control_type="Group", name="Shipping")
    billing_panel = Element(control_type="Group", name="Billing")
    address = AddressBox()
    shipping = AddressBox(root=Element(automation_id="Address", within=shipping_panel))
    billing = AddressBox(root=Element(automation_id="Address", within=billing_panel))


class Shell(Page):
    """A page that has a root of its own: components are still not placed beneath it."""

    window = Window(title="Shell")

    root = Element(automation_id="Shell")
    title = Element(automation_id="Title")
    address = AddressBox()
    pane = Element(control_type="Group", name="Pane")
    moved = AddressBox(root=Element(automation_id="Address", within=pane))


class OwnWindowBox(Page):
    window = Window(title="Dialog")

    root = Element(automation_id="Box")
    field = Element(automation_id="Field")


class Mixed(Page):
    window = Window(title="Mixed")

    box = OwnWindowBox()
    moved = AddressBox(window=Window(title="Elsewhere"))


class Scopes:
    """Patches the resolver and records the scope and locator of every resolution."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[Any, Locator]] = []
        self.errors: dict[str, BaseException] = {}
        monkeypatch.setattr(model, "resolve", self._resolve)
        monkeypatch.setattr(model, "resolve_all", self._resolve_all)

    def _resolve(self, scope: Any, locator: Locator) -> FakeElement:
        self.calls.append((scope, locator))
        for key, error in self.errors.items():
            if locator.automation_id == key:
                raise error
        return FakeElement("Edit")

    def _resolve_all(self, scope: Any, locator: Locator) -> list[FakeElement]:
        self.calls.append((scope, locator))
        return []


@pytest.fixture
def scopes(monkeypatch: pytest.MonkeyPatch) -> Scopes:
    return Scopes(monkeypatch)


def not_found() -> ElementNotFoundError:
    return ElementNotFoundError(Diagnostic("not_found", "nothing", "Edit", "Window", 0))


def locator(automation_id: str, **kwargs: Any) -> Locator:
    return Locator(automation_id=automation_id, **kwargs)


# -- plain pages are unchanged --------------------------------------------------------------------


def test_plain_page_locators_are_the_definition_locators() -> None:
    class Plain(Page):
        window = Window(title="Plain")
        group = Element(control_type="Group", name="G")
        ok = Element(control_type="Button", name="OK", within=group)
        other = Element(automation_id="X", window=Window(title="Other"))
        many = Elements(control_type="Button")

    page = Plain(APP)
    for name in ("group", "ok", "other", "many"):
        assert getattr(page, name).locator == getattr(Plain, name).locator()
    assert page.ok.qualname == Plain.ok.qualname
    assert page.window.locator == WindowLocator(title="Plain")


def test_plain_page_scope_without_window_is_none(scopes: Scopes) -> None:
    class Plain(Page):
        ok = Element(automation_id="OK")

    Plain(APP).ok.resolve_once()
    assert scopes.calls[-1][0].window is None


# -- component root and window --------------------------------------------------------------------


def test_component_root_is_searched_in_the_window(scopes: Scopes) -> None:
    home = Home(APP)
    assert home.address.root.locator == locator("AddressBox")
    home.address.root.resolve_once()
    scope, found = scopes.calls[-1]
    assert scope.window == WindowLocator(title="Home")
    assert found == locator("AddressBox")


def test_component_elements_are_beneath_the_component_root() -> None:
    address = Home(APP).address
    assert address.street.locator == locator("Street", within=locator("AddressBox"))
    assert address.lines.locator == Locator(control_type="Edit", within=locator("AddressBox"))
    # within=root names the root explicitly: it is not added twice
    assert address.city.locator == locator("City", within=locator("AddressBox"))


def test_parent_elements_are_not_affected_by_the_component() -> None:
    assert Home(APP).title.locator == locator("Title")


def test_component_root_is_not_chained_beneath_the_parent_root() -> None:
    shell = Shell(APP)
    assert shell.title.locator == locator("Title", within=locator("Shell"))
    assert shell.address.root.locator == locator("AddressBox")
    assert shell.address.street.locator == locator("Street", within=locator("AddressBox"))


def test_moving_a_component_only_moves_the_mount() -> None:
    assert Home(APP).address.street.locator == Billing(APP).address.street.locator


def test_component_without_window_uses_the_parents_window(scopes: Scopes) -> None:
    Billing(APP).address.street.resolve_once()
    assert scopes.calls[-1][0].window == WindowLocator(title="Billing")


def test_component_with_its_own_window_uses_it(scopes: Scopes) -> None:
    box = Mixed(APP).box
    box.field.resolve_once()
    assert scopes.calls[-1][0].window == WindowLocator(title="Dialog")
    assert box.field.locator == locator("Field", within=locator("Box"))
    assert box.window.locator == WindowLocator(title="Dialog")


def test_mount_can_override_the_window(scopes: Scopes) -> None:
    moved = Mixed(APP).moved
    moved.street.resolve_once()
    assert scopes.calls[-1][0].window == WindowLocator(title="Elsewhere")
    assert moved.street.locator == locator("Street", within=locator("AddressBox"))


def test_mount_window_overrides_a_class_window() -> None:
    class Boxed(OwnWindowBox):
        pass

    class Holder(Page):
        window = Window(title="Holder")
        box = Boxed(window=Window(title="Swapped"))

    bound = Holder(APP).box.window
    assert isinstance(bound, BoundWindow)
    assert bound.locator == WindowLocator(title="Swapped")


def test_standalone_component_is_searched_in_its_window(scopes: Scopes) -> None:
    box = AddressBox(APP)
    assert box.street.locator == locator("Street", within=locator("AddressBox"))
    box.street.resolve_once()
    assert scopes.calls[-1][0].window is None
    OwnWindowBox(APP).field.resolve_once()
    assert scopes.calls[-1][0].window == WindowLocator(title="Dialog")


# -- per-mount root overrides ---------------------------------------------------------------------


def test_mount_root_replaces_the_class_root() -> None:
    billing = Billing(APP)
    assert billing.address.root.locator == locator("AddressBox")
    assert billing.shipping.street.locator == locator(
        "Street",
        within=locator("Address", within=Locator(control_type="Group", name="Shipping")),
    )


def test_two_instances_in_one_window_are_told_apart_by_within() -> None:
    billing = Billing(APP)
    shipping = billing.shipping.root.locator
    billing_root = billing.billing.root.locator
    assert shipping != billing_root
    assert shipping.automation_id == billing_root.automation_id == "Address"
    assert shipping.within == Locator(control_type="Group", name="Shipping")
    assert billing_root.within == Locator(control_type="Group", name="Billing")


def test_mount_root_within_follows_the_parents_own_scoping() -> None:
    moved = Shell(APP).moved
    assert moved.root.locator == locator(
        "Address", within=Locator(control_type="Group", name="Pane", within=locator("Shell"))
    )
    assert moved.street.locator.chain()[0] == locator("Shell")


def test_mount_root_without_within_is_searched_in_the_window() -> None:
    class Parent(Page):
        window = Window(title="P")
        root = Element(automation_id="ParentRoot")
        box = AddressBox(root=Element(automation_id="Solo"))

    assert Parent(APP).box.root.locator == locator("Solo")
    assert Parent(APP).box.street.locator == locator("Street", within=locator("Solo"))


def test_mount_root_gives_a_component_without_root_one() -> None:
    class Loose(Page):
        field = Element(automation_id="Field")

    class Parent(Page):
        box = Loose(root=Element(automation_id="Group"))

    assert Parent(APP).box.field.locator == locator("Field", within=locator("Group"))
    assert list(Parent(APP).box.declared()) == ["root", "field"]


def test_mount_arguments_are_validated() -> None:
    with pytest.raises(TypeError, match="root="):
        AddressBox(root=Elements(automation_id="x"))
    with pytest.raises(TypeError, match="root="):
        AddressBox(root="x")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="window="):
        AddressBox(window="x")  # type: ignore[arg-type]


# -- instances ------------------------------------------------------------------------------------


def test_class_access_returns_the_template_and_instances_get_their_own() -> None:
    first, second = Home(APP), Home(APP)
    assert isinstance(Home.address, PageObject)
    assert first.address is first.address
    assert first.address is not second.address
    assert first.address is not Home.address
    assert first.address._parent is first
    assert second.address._parent is second
    assert first.address.street.page is first.address
    assert first.address.app is APP


def test_children_do_not_share_state_between_parents() -> None:
    first, second = Billing(APP), Billing(APP)
    first.address._children["x"] = Home(APP)
    assert "x" not in second.address._children
    assert Billing.address._children == {}


def test_a_component_cannot_contain_itself() -> None:
    class Node(Page):
        pass

    node = Node()
    Node.child = node  # type: ignore[attr-defined]
    node.__set_name__(Node, "child")
    with pytest.raises(TypeError, match="Cyclic"):
        Node(APP).child  # noqa: B018


def test_a_mount_must_be_a_class_attribute() -> None:
    with pytest.raises(TypeError, match="class attributes"):
        AddressBox().__get__(Home(APP))


# -- names ----------------------------------------------------------------------------------------


def test_qualnames_show_where_a_component_is_mounted() -> None:
    home = Home(APP)
    assert home.address.street.qualname == "Home.address.street"
    assert home.address.root.qualname == "Home.address.root"
    assert home.address.lines.qualname == "Home.address.lines"
    assert Billing(APP).shipping.root.qualname == "Billing.shipping.root"
    assert Billing(APP).shipping.street.qualname == "Billing.shipping.street"
    assert Mixed(APP).box.window.qualname == "Mixed.box.window"
    assert Home(APP).title.qualname == "Home.title"
    assert AddressBox(APP).street.qualname == "AddressBox.street"
    assert "Home.address.street" in repr(home.address.street)
    assert "Home.address.street" in home.address.street._description()


def test_a_failure_names_the_mount(scopes: Scopes) -> None:
    scopes.errors["Street"] = not_found()
    with pytest.raises(ElementNotFoundError):
        Billing(APP).shipping.street.resolve_once()
    assert "Billing.shipping.street" in Billing(APP).shipping.street._description()


# -- check ----------------------------------------------------------------------------------------


def test_check_walks_components_recursively(scopes: Scopes) -> None:
    scopes.errors["Street"] = not_found()
    results = Home(FakeApp([])).check()  # no other windows to search
    assert list(results) == [
        "title",
        "address.root",
        "address.street",
        "address.city",
        "address.lines",
    ]
    assert isinstance(results["address.street"], ElementNotFoundError)
    assert results["address.root"] is None
    assert results["title"] is None


def test_check_includes_the_mounts_root_override(scopes: Scopes) -> None:
    results = Billing(APP).check()
    assert {"shipping.root", "shipping.street", "billing.root", "address.root"} <= set(results)
    assert results["shipping.root"] is None
    shipping = [loc for _, loc in scopes.calls if loc.automation_id == "Address"]
    assert {loc.within.name for loc in shipping if loc.within is not None} == {
        "Shipping",
        "Billing",
    }


def test_check_reports_a_cycle_instead_of_recursing(scopes: Scopes) -> None:
    class First(Page):
        pass

    class Second(Page):
        pass

    for owner, name, kind in ((First, "second", Second), (Second, "first", First)):
        mount = kind()
        setattr(owner, name, mount)
        mount.__set_name__(owner, name)
    results = First(APP).check()
    assert isinstance(results["second.first"], TypeError)


# -- targets --------------------------------------------------------------------------------------

PAGES = dedent(
    """
    from wintestkit import Page, Window, Element

    class Box(Page):
        root = Element(automation_id="Box")
        field = Element(automation_id="Field")

    class Host(Page):
        window = Window(title="Host")
        panel = Element(name="Panel")
        box = Box()
        second = Box(root=Element(automation_id="Box", within=panel))

    class Loose(Page):
        field = Element(automation_id="Field")

    class Plain(Page):
        window = Window(title="Plain")
        loose = Loose(root=Element(automation_id="Grp"))
    """
)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[ModuleLoader, Path]]:
    monkeypatch.syspath_prepend(str(tmp_path))
    package = tmp_path / "component_pages"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    file = package / "main.py"
    file.write_text(PAGES, encoding="utf-8")
    loader = ModuleLoader(load_config(tmp_path))
    yield loader, file
    loader._purge_project_modules()


def test_element_names_include_components(project: tuple[ModuleLoader, Path]) -> None:
    loader, file = project
    assert loader.element_names(loader.get_page(Target(file, "Host"))) == [
        "window",
        "panel",
        "box.root",
        "box.field",
        "second.root",
        "second.field",
    ]
    assert loader.element_names(loader.get_page(Target(file, "Plain"))) == [
        "window",
        "loose.root",
        "loose.field",
    ]


def test_get_element_accepts_component_paths(project: tuple[ModuleLoader, Path]) -> None:
    loader, file = project
    host = loader.get_page(Target(file, "Host"))
    assert loader.get_element(Target(file, "Host.box.field")) == (host, "box.field")
    assert loader.get_element(Target(file, "Host.box")) == (host, "box")
    with pytest.raises(TargetError, match="no element"):
        loader.get_element(Target(file, "Host.box.nope"))
    with pytest.raises(TargetError, match="not a page attribute"):
        loader.get_element(Target(file, "Host.panel.field"))


def test_check_page_reports_dotted_qualnames(
    project: tuple[ModuleLoader, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    loader, file = project
    monkeypatch.setattr(model.BoundElement, "resolve", lambda self, timeout: FakeElement("Edit"))
    monkeypatch.setattr(model.BoundWindow, "resolve", lambda self, timeout: FakeElement("Window"))
    results = targets.check_page(APP, loader, file, "Host")
    assert [r.qualname for r in results] == [
        "Host.window",
        "Host.panel",
        "Host.box.root",
        "Host.box.field",
        "Host.second.root",
        "Host.second.field",
    ]
    assert "Box" in results[2].locator
    assert "Panel" in results[4].locator
    plain = targets.check_page(APP, loader, file, "Plain")
    assert [r.qualname for r in plain][-2:] == ["Plain.loose.root", "Plain.loose.field"]


def test_bound_at_resolves_paths(project: tuple[ModuleLoader, Path]) -> None:
    loader, file = project
    host = loader.get_page(Target(file, "Host"))(APP)
    assert host.bound_at("box.field").locator.automation_id == "Field"
    assert host.bound_at("box").locator == locator("Box")  # a component means its root
    assert host.bound_at("window").locator == WindowLocator(title="Host")
    with pytest.raises(AttributeError):
        host.bound_at("panel.field")


# -- discovery ------------------------------------------------------------------------------------


def test_discovery_reports_children_including_mount_keywords(tmp_path: Path) -> None:
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pages" / "boxes.py").write_text(
        dedent(
            """
            from wintestkit import Page, Element

            class AddressBox(Page):
                root = Element(automation_id="AddressBox")
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "pages" / "home.py").write_text(
        dedent(
            """
            from wintestkit import Page, Element, Window
            from pages.boxes import AddressBox

            class Home(Page):
                panel = Element(name="Panel")
                address = AddressBox()
                shipping = AddressBox(root=Element(automation_id="S", within=panel))
                moved = AddressBox(window=Window(title="W"))
                skipped = AddressBox(1)
                unknown = AddressBox(other=1)
                not_a_page = dict(root=1)
            """
        ),
        encoding="utf-8",
    )
    pages = {page.name: page for page in discover(tmp_path).pages}
    home = pages["Home"]
    assert [(c.name, c.page_id) for c in home.children] == [
        ("address", "pages/boxes.py::AddressBox"),
        ("shipping", "pages/boxes.py::AddressBox"),
        ("moved", "pages/boxes.py::AddressBox"),
    ]
    assert home.to_dict()["children"][1]["name"] == "shipping"
    assert pages["AddressBox"].children == ()
