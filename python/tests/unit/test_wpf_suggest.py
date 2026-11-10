"""WPF suggestion ordering and verification with a fake agent tree."""

from types import SimpleNamespace
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit.backends.element import WpfElement
from wintestkit.engine import resolve as resolver
from wintestkit.engine import suggest, wpf_resolve
from wintestkit.engine.locator import Locator
from wintestkit.uia import element as uia_element


def test_wpf_candidates_and_rendering() -> None:
    node = object.__new__(WpfElement)
    node._identity = {
        "automation_id": "Save",
        "name": "Save",
        "control_type": "Button",
        "class_name": "",
    }
    node.ref = SimpleNamespace(
        object_id="1", generation=1, type=SimpleNamespace(full_name="Demo.Button")
    )
    node.client = SimpleNamespace(
        read=lambda *args, **kwargs: (
            (SimpleNamespace(value=SimpleNamespace(status="ok", scalar="SaveName")),),
            "read",
        )
    )
    candidates = suggest._wpf_candidates(node)
    assert [strategy for strategy, _ in candidates] == ["automation_id", "x_name", "type_name"]
    assert candidates[1][1].where == (("clr:Name", "SaveName"),)
    assert candidates[2][1].where == (("type:Is", "Demo.Button"),)
    for _, locator in candidates:
        assert eval(suggest.render_element_code(locator), {"Element": Locator}) == locator


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("id", "automation_id"),
        ("name", "x_name"),
        ("type", "type_name"),
        ("scoped", "within"),
        ("index", "index"),
        ("mismatch", "automation_id"),
    ],
)
def test_wpf_selection(monkeypatch: pytest.MonkeyPatch, mode: str, expected: str) -> None:
    top = FakeElement("Window", "Demo")
    app = FakeApp([top])
    root, target, other, parent = (object.__new__(WpfElement) for _ in range(4))
    for index, node in enumerate((root, target, other, parent)):
        node.ref = SimpleNamespace(session_id="s", object_id=str(index), generation=1)
    info = FakeElement("Button", "Target").info()
    monkeypatch.setattr(WpfElement, "state", lambda self: SimpleNamespace(window_handle=1))
    monkeypatch.setattr(WpfElement, "info", lambda self: info)
    monkeypatch.setattr(uia_element, "from_handle", lambda hwnd: top)
    monkeypatch.setattr(wpf_resolve, "route", lambda *args, **kwargs: root)
    identifier = Locator(automation_id="id")
    name = Locator(where=(("clr:Name", "target"),))
    typed = Locator(name="label", where=(("type:FullName", "Demo.Button"),))
    parent_loc = Locator(automation_id="parent")
    monkeypatch.setattr(
        suggest,
        "_wpf_candidates",
        lambda node: (
            [("automation_id", parent_loc)]
            if node is parent
            else [("automation_id", identifier), ("x_name", name), ("type_name", typed)]
        ),
    )

    def query(scope: Any, locator: Locator, **kwargs: Any) -> Any:
        if locator.automation_id == "parent":
            values = [parent]
        elif (
            scope is parent
            or (mode == "id" and locator.automation_id == "id")
            or (mode == "name" and locator.where == name.where)
            or (mode == "type" and locator.where == typed.where)
        ):
            values = [target]
        else:
            values = [other, target]
        result = wpf_resolve.QueryMatches(values)
        return result

    monkeypatch.setattr(wpf_resolve, "query", query)
    monkeypatch.setattr(resolver, "resolve", lambda *args: other if mode == "mismatch" else target)
    result = suggest.suggest_locator(target, app, ancestors=(parent,) if mode == "scoped" else ())
    assert result.strategy == expected
    assert result.unique is (mode != "mismatch")
    if result.helpers:
        helper = result.helpers[-1]
        assert eval(result.code, {"Element": Locator, helper[0]: helper[2]}) == result.locator
    else:
        assert eval(result.code, {"Element": Locator}) == result.locator
