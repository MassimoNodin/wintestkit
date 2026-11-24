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
        with pytest.raises(InvalidLocatorError, match="requires the WPF backend"):
            read_property(FakeElement("Button", "x"), "clr:Name")
    finally:
        runtime.reset()


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
