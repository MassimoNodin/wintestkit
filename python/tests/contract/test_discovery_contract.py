"""Discovery output must validate against discovery.schema.json."""

from collections.abc import Callable
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from wintestkit.discovery import discover

Validate = Callable[[str, str, Any], None]
EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "calculator-tests"


def test_the_examples_project_validates(validate: Validate) -> None:
    result = discover(EXAMPLES)
    validate("discovery.schema.json", "DiscoveryResult", result.to_dict())
    assert result.errors == ()
    assert len(result.tests) == 4
    assert {flow.name for flow in result.flows} == {"open_page", "tour_calculator"}
    names = {s.name for s in result.pages}
    assert {"CalculatorWindow", "StandardPage", "ScientificPage", "ProgrammerPage"} <= names
    assert {"NavigationPane", "NumberPad", "StandardOperators", "DisplayControls"} <= names
    main = next(s for s in result.pages if s.name == "CalculatorWindow")
    window = next(e for e in main.elements if e.name == "window")
    assert window.locator == {}
    assert {e.name: e.element_type for e in main.elements if e.name != "window"} == {
        "heading": "Text",
        "result": "Text",
    }
    assert [child.name for child in main.children] == ["navigation"]
    pane = next(s for s in result.pages if s.name == "NavigationPane")
    assert {c.page_id for c in main.children} == {pane.id}
    toggle = next(e for e in pane.elements if e.name == "toggle")
    assert toggle.element_type == "Button"
    assert toggle.locator == {"automationId": "TogglePaneButton"}
    assert next(e for e in pane.elements if e.name == "standard").element_type == "ListItem"
    programmer = next(s for s in result.pages if s.name == "ProgrammerPage")
    assert {child.name for child in programmer.children} >= {"navigation", "number_pad", "radix"}
    assert not any(e.dynamic for s in result.pages for e in s.elements)


def test_every_feature_validates(tmp_path: Path, validate: Validate) -> None:
    files = {
        "pyproject.toml": "",
        "tests/test_all.py": """
            import pytest

            @pytest.mark.parametrize("x", [1])
            def test_p(x): pass

            async def test_async(): pass

            class TestK:
                def test_m(self): pass
                class TestInner:
                    def test_i(self): pass
            """,
        "tests/test_syntax.py": "def broken(:\n",
        "pages/s.py": """
            import re
            from wintestkit import Element, Elements, Page, Window

            class S(Page):
                window = Window(title=re.compile("^W", re.I), process="App.exe")
                g = Element(control_type="Group", name="G")
                b: Element = Element(control_type="Button", name=dynamic(), within=g, window=window)
                items = Elements(control_type="ListItem", index=None, depth=2)
            """,
    }
    for rel, source in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(source).lstrip("\n"), encoding="utf-8")
    result = discover(tmp_path)
    payload = result.to_dict()
    validate("discovery.schema.json", "DiscoveryResult", payload)
    assert payload["errors"] and payload["pages"] and payload["tests"]
    (page,) = payload["pages"]
    button = next(e for e in page["elements"] if e["name"] == "b")
    assert button["dynamic"] is True
    assert button["withinName"] == "g"
    assert button["windowName"] == "window"
    assert button["elementType"] == "Element"
    assert next(e for e in page["elements"] if e["name"] == "items")["elementType"] == "Elements"
    assert "elementType" not in next(e for e in page["elements"] if e["name"] == "window")


@pytest.mark.parametrize("source", ["", "# nothing here\n", "x = 1\n"])
def test_empty_results_validate(tmp_path: Path, validate: Validate, source: str) -> None:
    (tmp_path / "test_empty.py").write_text(source, encoding="utf-8")
    validate("discovery.schema.json", "DiscoveryResult", discover(tmp_path).to_dict())
