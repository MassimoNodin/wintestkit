"""Nested property data: element arrays expand, nesting is bounded, pinned names are read."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rpc_support import make_server, request

from wintestkit.uia import element
from wintestkit.uia.constants import CONTROL_TYPES
from wintestkit.uia.element import MAX_INSPECTION_DEPTH, inspection_property


class FakeUiaElement:
    """The raw ``IUIAutomationElement`` surface that expansion reads."""

    def __init__(self, name: str, control_type: str = "Button", gone: bool = False) -> None:
        self.name, self.control_type, self.gone = name, control_type, gone

    def __getattr__(self, attribute: str) -> Any:
        if not attribute.startswith("Current"):
            raise AttributeError(attribute)
        if self.gone:
            import comtypes

            raise comtypes.COMError(-2147220991, "gone", (None, None, None, 0, None))
        values: dict[str, Any] = {
            "AutomationId": f"id_{self.name}",
            "Name": self.name,
            "ControlType": CONTROL_TYPES[self.control_type],
            "ClassName": "Cls",
            "BoundingRectangle": SimpleNamespace(left=1, top=2, right=11, bottom=22),
        }
        return values[attribute.removeprefix("Current")]

    def GetRuntimeId(self) -> list[int]:
        return [42, 7]


class FakeElementArray:
    def __init__(self, *elements: FakeUiaElement) -> None:
        self.elements = elements
        self.Length = len(elements)

    def GetElement(self, index: int) -> FakeUiaElement:
        return self.elements[index]


class ComPointer:
    """Stands in for a COM pointer; the interface lookup is patched per test."""


def expand(monkeypatch: pytest.MonkeyPatch, found: Any) -> None:
    monkeypatch.setattr(element, "_uia_interfaces", lambda value: found)


def named(children: list[dict[str, Any]]) -> dict[str, Any]:
    return {child["name"]: child for child in children}


def test_an_element_array_expands_into_nested_elements(monkeypatch: pytest.MonkeyPatch) -> None:
    expand(monkeypatch, (FakeElementArray(FakeUiaElement("Save"), FakeUiaElement("Open")), True))
    result = inspection_property("ControllerFor", ComPointer())
    assert (result["kind"], result["typeName"]) == ("array", "UIAElementArray")
    first, second = result["children"]
    assert [first["name"], second["name"]] == ["0", "1"]
    assert (first["kind"], first["typeName"]) == ("object", "UIAElement")
    fields = named(first["children"])
    # alphabetical, and the arrays inside the element are themselves nested one level further
    assert list(fields) == [
        "AutomationId",
        "BoundingRectangle",
        "ClassName",
        "ControlType",
        "Name",
        "RuntimeId",
    ]
    assert fields["Name"]["value"] == "Save"
    assert fields["ControlType"]["value"] == "Button"
    assert [child["value"] for child in fields["BoundingRectangle"]["children"]] == [1, 2, 10, 20]
    assert [child["value"] for child in fields["RuntimeId"]["children"]] == [42, 7]


def test_a_single_element_is_an_object(monkeypatch: pytest.MonkeyPatch) -> None:
    expand(monkeypatch, (FakeUiaElement("Label", "Text"), False))
    result = inspection_property("LabeledBy", ComPointer())
    assert result["kind"] == "object"
    assert named(result["children"])["ControlType"]["value"] == "Text"


def test_an_empty_element_array_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    expand(monkeypatch, (FakeElementArray(), True))
    result = inspection_property("ControllerFor", ComPointer())
    assert result["status"] == "Empty"
    assert "children" not in result


def test_a_large_element_array_is_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    expand(monkeypatch, (FakeElementArray(*(FakeUiaElement(str(i)) for i in range(40))), True))
    result = inspection_property("SelectionSelection", ComPointer())
    assert len(result["children"]) == 32
    assert result["status"] == "Truncated to 32 items"


def test_an_element_that_disappeared_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    expand(monkeypatch, (FakeElementArray(FakeUiaElement("Gone", gone=True)), True))
    [item] = inspection_property("ControllerFor", ComPointer())["children"]
    assert item["status"] == "The element is no longer available"
    assert "children" not in item


def test_other_com_values_stay_opaque(monkeypatch: pytest.MonkeyPatch) -> None:
    expand(monkeypatch, None)
    result = inspection_property("Unknown", ComPointer())
    assert result["kind"] == "object"
    assert "children" not in result


def test_nesting_stops_at_the_depth_limit() -> None:
    deep: Any = [1]
    for _ in range(MAX_INSPECTION_DEPTH + 2):
        deep = [deep]
    node = inspection_property("deep", deep)
    levels = 0
    while "children" in node:
        node = node["children"][0]
        levels += 1
    assert node["status"] == "Depth limit reached"
    assert levels == MAX_INSPECTION_DEPTH


def test_included_properties_are_read_without_the_full_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    node = server._register(button)
    reads: list[str] = []
    original = button.get_property

    def get_property(name: str) -> Any:
        reads.append(name)
        return original(name)

    monkeypatch.setattr(button, "get_property", get_property)
    result = request(
        server,
        output,
        "inspect.properties",
        {"nodeId": node["nodeId"], "include": ["Name", "Nonsense", "Name", "RuntimeId"]},
    )["result"]
    assert result["properties"]["Name"] == "OK"
    assert result["properties"]["RuntimeId"] == "1, 2"
    assert "Nonsense" not in result["properties"]
    assert reads.count("Name") == 1  # repeated names are read once
    assert {item["name"] for item in result["inspection"]} >= {"Name", "RuntimeId"}
    assert "AutomationId" not in reads  # still not the whole list


def test_included_names_are_validated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    node = server._register(button)
    for bad in ("Name", [1], [""], ["x" * 65], ["Name"] * 65):
        error = request(
            server, output, "inspect.properties", {"nodeId": node["nodeId"], "include": bad}
        )["error"]
        assert error["code"] == -32602


def test_the_flat_value_summarizes_nested_data(monkeypatch: pytest.MonkeyPatch) -> None:
    from wintestkit.server import _summarize

    assert _summarize(inspection_property("RuntimeId", [42, 7])) == "42, 7"
    expand(monkeypatch, (FakeElementArray(FakeUiaElement("A"), FakeUiaElement("B")), True))
    assert _summarize(inspection_property("ControllerFor", ComPointer())) == "2 items"
    expand(monkeypatch, (FakeUiaElement("Label", "Text"), False))
    assert _summarize(inspection_property("LabeledBy", ComPointer())) == 'Text "Label"'
    expand(monkeypatch, (FakeElementArray(), True))
    assert _summarize(inspection_property("ControllerFor", ComPointer())) == "Empty"
    assert _summarize(inspection_property("Name", "x")) == "x"
