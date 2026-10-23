"""``panel.Button(...)``: searching only the direct children of another element."""

from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from typing import Any

import pytest

from wintestkit import Page, Window, controls
from wintestkit.discovery import discover
from wintestkit.engine.locator import ItemSelector, Locator
from wintestkit.errors import ActionError
from wintestkit.model import BoundElement, BoundElements, Element, Elements

APP: Any = SimpleNamespace()

PANEL = Locator(control_type="Group", name="Shipping")


def child(**kwargs: Any) -> Locator:
    return Locator(depth=1, within=PANEL, **kwargs)


class Checkout(Page):
    window = Window(title="Checkout")

    panel = Element(control_type="Group", name="Shipping")
    ok = panel.Button(name="OK")
    street = panel.TextBox(automation_id="Street")
    rows = panel.Elements(control_type="ListItem")
    anything = panel.Element(name="Anything", index=1)
    zip_code = panel.Element(name="Address").TextBox(name="Zip")


class AddressBox(Page):
    root = Element(class_name="AddressBox")
    street = root.TextBox(automation_id="Street")


class Home(Page):
    window = Window(title="Home")

    address = AddressBox()


# -- declarations ---------------------------------------------------------------------------------


def test_a_child_declaration_is_within_depth_one() -> None:
    assert Checkout.ok.locator(include_window=False) == child(control_type=None, name="OK")
    assert Checkout.ok.locator() == Checkout.ok.locator(include_window=False)
    assert Checkout.street.locator() == child(automation_id="Street")
    assert Checkout.anything.locator() == child(name="Anything", index=1)


def test_child_methods_return_the_matching_declaration_types() -> None:
    assert type(Checkout.ok) is controls.Button
    assert type(Checkout.street) is controls.TextBox
    assert type(Checkout.anything) is Element
    assert type(Checkout.rows) is Elements
    assert Checkout.rows.locator() == child(control_type="ListItem")


def test_child_declarations_chain() -> None:
    assert Checkout.zip_code.locator() == Locator(name="Zip", depth=1, within=child(name="Address"))


def test_a_child_keeps_the_options_of_its_type() -> None:
    assert Checkout.ok.validate is True
    unvalidated = Checkout.panel.Button(name="X", validate=False, timeout=3)
    assert unvalidated.validate is False
    assert unvalidated.timeout == 3


@pytest.mark.parametrize("option", ["within", "depth", "window"])
def test_a_child_cannot_take_within_depth_or_window(option: str) -> None:
    value: Any = Window(title="W") if option == "window" else 1
    with pytest.raises(TypeError, match=r"direct children .* drop"):
        Checkout.panel.Button(name="X", **{option: value})


def test_a_group_of_elements_cannot_contain_children() -> None:
    with pytest.raises(TypeError, match="within= must be an Element"):
        Checkout.rows.Button(name="X")


def test_a_component_root_can_have_direct_children() -> None:
    assert Home(APP).address.street.locator == Locator(
        automation_id="Street", depth=1, within=Locator(class_name="AddressBox")
    )


# -- bound elements -------------------------------------------------------------------------------


def test_a_bound_element_searches_its_direct_children() -> None:
    page = Checkout(APP)
    button = page.panel.Button(name="Save")
    assert isinstance(button, controls.BoundButton)
    assert button.locator == child(name="Save")
    assert button.qualname == "Checkout.panel.Button"


def test_a_bound_child_of_a_declared_child_chains() -> None:
    page = Checkout(APP)
    field = page.ok.Element(name="Label")
    assert isinstance(field, BoundElement)
    assert field.locator == Locator(name="Label", depth=1, within=child(name="OK"))


def test_bound_children_of_a_group_are_a_collection() -> None:
    items = Checkout(APP).panel.Elements(control_type="ListItem")
    assert isinstance(items, BoundElements)
    assert items.locator == child(control_type="ListItem")


def test_a_bound_child_follows_nth() -> None:
    second = Checkout(APP).panel.nth(1).Button(name="OK")
    assert second.locator == Locator(
        name="OK", depth=1, within=Locator(control_type="Group", name="Shipping", index=1)
    )


def test_a_grid_row_cannot_be_searched_for_children() -> None:
    page = Checkout(APP)
    row = page.panel._derive(Locator(control_type="Group", item=ItemSelector("row", 2)))  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(ActionError, match="grid row or cell"):
        row.Button(name="OK")


def test_an_ad_hoc_child_is_not_a_declared_member() -> None:
    button = Checkout(APP).panel.Button(name="Save")
    assert button.definition.ad_hoc is True
    assert Checkout.ok.ad_hoc is False


# -- static discovery -----------------------------------------------------------------------------


def write(root: Path, name: str, source: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(source), encoding="utf-8")


def test_discovery_reads_child_declarations(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/checkout.py",
        """
        from wintestkit import Element, Page

        class Checkout(Page):
            panel = Element(control_type="Group", name="Shipping")
            ok = panel.Button(name="OK")
            rows = panel.Elements(control_type="ListItem")
            zip_code = panel.Element(name="Address").TextBox(name="Zip")
        """,
    )
    (page,) = discover(tmp_path).pages
    entries = {e.name: e for e in page.elements}
    panel = {"controlType": "Group", "name": "Shipping"}
    assert entries["ok"].locator == {"name": "OK", "depth": 1, "within": panel}
    assert entries["ok"].kind == "element"
    assert entries["ok"].element_type == "Button"
    assert entries["ok"].within_name == "panel"
    assert entries["ok"].dynamic is False
    assert entries["rows"].kind == "elements"
    assert entries["rows"].locator == {"controlType": "ListItem", "depth": 1, "within": panel}
    assert entries["zip_code"].locator == {
        "name": "Zip",
        "depth": 1,
        "within": {"name": "Address", "depth": 1, "within": panel},
    }
    assert entries["zip_code"].within_name == "panel"
    assert entries["zip_code"].dynamic is False


def test_discovery_reads_children_of_a_component_root(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/box.py",
        """
        from wintestkit import Element, Page

        class AddressBox(Page):
            root = Element(class_name="AddressBox")
            street = root.TextBox(automation_id="Street")
        """,
    )
    (page,) = discover(tmp_path).pages
    street = {e.name: e for e in page.elements}["street"]
    assert street.locator == {
        "automationId": "Street",
        "depth": 1,
        "within": {"className": "AddressBox"},
    }
    assert street.within_name == "root"


def test_discovery_does_not_mistake_a_module_call_for_a_child(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/qualified.py",
        """
        import wintestkit as wtk
        from wintestkit import Page

        class Qualified(Page):
            save = wtk.Button(name="Save")
        """,
    )
    (page,) = discover(tmp_path).pages
    (save,) = page.elements
    assert save.locator == {"name": "Save"}
    assert save.within_name is None


def test_discovery_flags_options_a_child_cannot_take(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pages/bad.py",
        """
        from wintestkit import Element, Page

        class Bad(Page):
            panel = Element(name="P")
            ok = panel.Button(name="OK", depth=2)
            unknown = missing.Button(name="X")
        """,
    )
    (page,) = discover(tmp_path).pages
    entries = {e.name: e for e in page.elements}
    assert entries["ok"].dynamic is True
    assert entries["unknown"].within_name is None
