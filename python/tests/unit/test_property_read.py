"""Managed property reader coverage without a running WPF application."""

from types import SimpleNamespace
from typing import Any

import pytest
from fakes import FakeElement

from wintestkit import runtime
from wintestkit.backends.element import WpfElement
from wintestkit.config import load_config
from wintestkit.engine.property_read import read_property, to_python
from wintestkit.errors import ActionError, InvalidLocatorError
from wintestkit.inspector.models import ObjectRef, PathValue, TypeInfo, Value


class FakeClient:
    def __init__(self, value: Value) -> None:
        self.value = value
        self.paths: Any = None

    def read(self, object_id: str, generation: int, paths: Any, *, deadline: float) -> Any:
        self.paths = paths
        return (PathValue(tuple(paths[0]), self.value),), "read"


@pytest.mark.parametrize(
    ("kind", "scalar", "expected"),
    [
        ("string", "fixture", "fixture"),
        ("integer", "123", 123),
        ("number", "1.5", 1.5),
        ("boolean", True, True),
        ("null", None, None),
        ("enum", "Ready", "Ready"),
    ],
)
def test_managed_scalar_and_alias(tmp_path: Any, kind: str, scalar: Any, expected: Any) -> None:
    runtime.reset()
    runtime.set_config(
        load_config(tmp_path, {"property_aliases": {"Alias": "clr:DataContext.Label"}})
    )
    value = Value("ok", kind, "T", "T", scalar=scalar)
    client = FakeClient(value)
    element = object.__new__(WpfElement)
    element.client = client
    element.ref = ObjectRef(
        "session", "object", 1, TypeInfo("T", "T", "A", "T, A", ()), "dispatcher"
    )
    try:
        assert read_property(element, "Alias") == expected
        assert [segment.name for segment in client.paths[0]] == ["DataContext", "Label"]
    finally:
        runtime.reset()


def test_redacted_and_non_wpf(tmp_path: Any) -> None:
    runtime.reset()
    runtime.set_config(load_config(tmp_path))
    element = object.__new__(WpfElement)
    element.client = FakeClient(Value("redacted", "unavailable", "T", "T"))
    element.ref = SimpleNamespace(object_id="object", generation=1)
    try:
        with pytest.raises(ActionError, match="redacted"):
            read_property(element, "clr:Secret")
        win32 = FakeElement("Button", "x")
        win32.framework_id = "Win32"
        with pytest.raises(InvalidLocatorError, match="requires the WPF backend"):
            read_property(win32, "clr:Name")
        runtime.set_config(load_config(tmp_path, {"backend": "uia"}))
        with pytest.raises(InvalidLocatorError, match="requires the WPF backend"):
            read_property(FakeElement("Button", "x"), "clr:Name")
    finally:
        runtime.reset()


def test_managed_read_of_a_grid_helper_element_goes_through_its_wpf_object(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cell or row comes from UI Automation; on a WPF window it reads like any WPF element."""
    runtime.reset()
    runtime.set_config(load_config(tmp_path))
    client = FakeClient(Value("ok", "string", "T", "T", scalar="Row 4"))
    mapped = object.__new__(WpfElement)
    mapped.client = client
    mapped.ref = ObjectRef(
        "session", "object", 1, TypeInfo("T", "T", "A", "T, A", ()), "dispatcher"
    )
    seen: list[Any] = []

    def to_managed(element: Any) -> WpfElement:
        seen.append(element)
        return mapped

    monkeypatch.setattr("wintestkit.engine.property_read.to_managed", to_managed)
    cell = FakeElement("DataItem", "cell")
    try:
        assert read_property(cell, "clr:DataContext.Label") == "Row 4"
        assert type_facet_path(client) is None
        assert seen == [cell]
        client.value = Value("ok", "string", "T", "T", scalar="OrderViewModel")
        assert read_property(cell, "type:Name@DataContext") == "OrderViewModel"
        assert [(s.kind, s.name) for s in client.paths[0]] == [
            ("property", "DataContext"),
            ("type", "Name"),
        ]
    finally:
        runtime.reset()


def type_facet_path(client: FakeClient) -> None:
    assert [(s.kind, s.name) for s in client.paths[0]] == [
        ("property", "DataContext"),
        ("property", "Label"),
    ]


def test_getter_error_includes_type_and_message() -> None:
    value = Value(
        "exception",
        "unavailable",
        "T",
        "",
        message="System.InvalidOperationException",
        error_message="broken",
    )
    with pytest.raises(ActionError, match=r"System\.InvalidOperationException: broken"):
        to_python(value)
