"""Generic property constraints across public declarations, queries and configuration."""

import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import Button, Element, Elements, Window, runtime
from wintestkit.config import load_config
from wintestkit.engine import query
from wintestkit.engine.locator import Locator, WindowLocator
from wintestkit.engine.properties import SUPPORTED, inspection_values, resolve_where
from wintestkit.engine.resolve import resolve_window
from wintestkit.errors import ConfigError, InvalidLocatorError
from wintestkit.uia import com
from wintestkit.uia.constants import PROPERTY_IDS


def test_check_uses_target_project_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from wintestkit.cli import main
    from wintestkit.commands import common

    (tmp_path / "pyproject.toml").write_text("[tool.wintestkit]\n", encoding="utf-8")
    (tmp_path / "wintestkit.yaml").write_text(
        "property_aliases: {ClrFullClassName: ItemStatus}\n", encoding="utf-8"
    )
    (tmp_path / "page.py").write_text(
        'from wintestkit import Page, Element\nclass Main(Page):\n    address = Element(where={"ClrFullClassName": "Company.AddressBox"})\n',
        encoding="utf-8",
    )
    previous = load_config(tmp_path, overrides={"property_aliases": {"Other": "HelpText"}})
    previous = replace(previous, property_aliases={})
    monkeypatch.setattr(runtime, "_config", previous)
    button = FakeElement("Button", properties={"ItemStatus": "Company.AddressBox"})
    monkeypatch.setattr(
        common, "attach_app", lambda config: FakeApp([FakeElement("Window", children=[button])])
    )
    assert main(["--root", str(tmp_path), "check", "page.py"]) == 0
    assert "1 found, 0 broken/moved" in capsys.readouterr().out
    assert runtime.get_config() is previous


def test_inspect_shows_properties_and_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from wintestkit.cli import main
    from wintestkit.commands import common

    (tmp_path / "pyproject.toml").write_text("[tool.wintestkit]\n", encoding="utf-8")
    (tmp_path / "wintestkit.yaml").write_text(
        "property_aliases: {ClrFullClassName: ItemStatus}\n", encoding="utf-8"
    )
    button = FakeElement(
        "Button", properties={"HelpText": "Save", "ItemStatus": "Company.AddressBox"}
    )
    monkeypatch.setattr(
        common, "attach_app", lambda config: FakeApp([FakeElement("Window", children=[button])])
    )
    assert main(["--root", str(tmp_path), "inspect", "--json"]) == 0
    values = json.loads(capsys.readouterr().out)["children"][0]["properties"]
    assert values["HelpText"] == "Save"
    assert values["ClrFullClassName"] == "Company.AddressBox"
    assert main(["--root", str(tmp_path), "inspect"]) == 0
    assert "ClrFullClassName: Company.AddressBox" in capsys.readouterr().out


@pytest.fixture(autouse=True)
def fake_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query, "make_condition", lambda **props: props)


@pytest.mark.parametrize("declaration", [Element, Button, Elements])
def test_public_declarations_freeze_where(declaration: type[Element]) -> None:
    values = {"HelpText": "Save"}
    definition = declaration(where=values)
    values["HelpText"] = "Changed"
    assert definition.locator().where == (("HelpText", "Save"),)
    assert hash(definition.locator())


def test_window_only_properties_are_not_empty() -> None:
    locator = Window(where={"FrameworkId": "WPF"}).locator
    assert not locator.is_empty()
    assert locator.describe() == 'Window[FrameworkId="WPF"]'


def test_exact_regex_and_builtin_constraints_combine() -> None:
    save = FakeElement(
        "Button",
        "Save",
        properties={"HelpText": "Save", "ItemStatus": "Company.AddressBox", "IsPassword": False},
    )
    other = FakeElement(
        "Button", "Save", properties={"HelpText": "Other", "ItemStatus": "Company.AddressBox"}
    )
    wrong_type = FakeElement("Edit", "Save", properties=save.properties)
    root = FakeElement("Window", children=[save, other, wrong_type])
    locator = Element(
        control_type="Button",
        where={"HelpText": "Save", "ItemStatus": re.compile(r"AddressBox$"), "IsPassword": False},
    ).locator()
    assert query.query_all(root, locator) == [save]


@pytest.mark.parametrize(
    ("property_name", "value"),
    [
        ("HasKeyboardFocus", True),
        ("GridRowCount", 4),
        ("AriaRole", "button"),
        ("RangeValueValue", 2.5),
        ("ControlType", "Button"),
        ("ValueValue", "hello"),
    ],
)
def test_additional_scalar_properties(property_name: str, value: object) -> None:
    actual = 50000 if property_name == "ControlType" else value
    button = FakeElement("Button", properties={property_name: actual})
    root = FakeElement("Window", children=[button])
    locator = Locator.from_dict({"where": {property_name: value}})
    assert query.query_all(root, locator) == [button]


def test_window_constraints_prevent_main_window_shortcut() -> None:
    first = FakeElement("Window", properties={"ItemStatus": "Main"})
    dialog = FakeElement("Window", properties={"ItemStatus": "Company.Dialog"})
    app = FakeApp([first, dialog])
    locator = Window(where={"ItemStatus": re.compile("Dialog$")}).locator
    assert resolve_window(app, locator) is dialog


def test_aliases_resolve_lazily_and_match(monkeypatch: pytest.MonkeyPatch) -> None:
    locator = Element(where={"ClrFullClassName": re.compile("AddressBox$")}).locator()
    monkeypatch.setattr(
        runtime,
        "get_config",
        lambda: SimpleNamespace(property_aliases={"ClrFullClassName": "ItemStatus"}),
    )
    button = FakeElement("Button", properties={"ItemStatus": "Company.AddressBox"})
    assert query.query_all(FakeElement("Window", children=[button]), locator) == [button]
    assert (
        inspection_values(button, {"ClrFullClassName": "ItemStatus"})["ClrFullClassName"]
        == "Company.AddressBox"
    )


@pytest.mark.parametrize(
    "values",
    [
        {"HelpText": 3},
        {"IsEnabled": 1},
        {"ProcessId": True},
        {"GridRowCount": "4"},
        {"HelpText": None},
        {"": "x"},
    ],
)
def test_invalid_property_types_fail_at_declaration(values: dict) -> None:
    with pytest.raises(TypeError):
        Element(where=values)


@pytest.mark.parametrize(
    "definition",
    [
        lambda: Element(name="Save", where={"Name": "Save"}),
        lambda: Window(title="Demo", where={"Name": "Demo"}),
    ],
)
def test_duplicate_builtin_fails_at_declaration(definition: object) -> None:
    with pytest.raises(TypeError, match="both"):
        definition()


@pytest.mark.parametrize(
    ("values", "aliases"),
    [
        ({"Typo": "x"}, {}),
        ({"Custom": 1}, {"Custom": "HelpText"}),
        ({"Custom": "x", "HelpText": "x"}, {"Custom": "HelpText"}),
        ({"Value": "x", "ValueValue": "x"}, {}),
    ],
)
def test_invalid_alias_or_duplicate_fails_without_search(
    monkeypatch: pytest.MonkeyPatch, values: dict, aliases: dict
) -> None:
    monkeypatch.setattr(runtime, "get_config", lambda: SimpleNamespace(property_aliases=aliases))
    locator = Element(where=values).locator()
    with pytest.raises(InvalidLocatorError):
        resolve_where(locator.where, locator.describe())


def test_alias_cannot_duplicate_builtin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime, "get_config", lambda: SimpleNamespace(property_aliases={"Caption": "Name"})
    )
    locator = Element(name="OK", where={"Caption": "OK"}).locator()
    with pytest.raises(InvalidLocatorError, match="twice"):
        query.query_all(FakeElement("Window"), locator)


@pytest.mark.parametrize("locator_class", [Locator, WindowLocator])
def test_protocol_round_trip(locator_class: type[Locator] | type[WindowLocator]) -> None:
    data = {
        "where": {"HelpText": {"regex": "save", "flags": "i"}, "IsEnabled": True, "ProcessId": 17}
    }
    locator = locator_class.from_dict(data)
    assert locator.to_dict() == data
    assert "HelpText=/save/i, IsEnabled=true, ProcessId=17" in locator.describe()


def test_alias_layers_merge(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.wintestkit.property_aliases]\nFirst = "Name"\n', encoding="utf-8"
    )
    (tmp_path / "wintestkit.yaml").write_text(
        "property_aliases: {ClrFullClassName: ItemStatus}", encoding="utf-8"
    )
    (tmp_path / "wintestkit.local.yaml").write_text(
        "property_aliases: {First: HelpText}", encoding="utf-8"
    )
    config = load_config(tmp_path, overrides={"property_aliases": {"Last": "ClassName"}})
    assert config.property_aliases == {
        "First": "HelpText",
        "ClrFullClassName": "ItemStatus",
        "Last": "ClassName",
    }


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"Name": "HelpText"},
        {"Custom": "NotAProperty"},
        {"": "Name"},
        {"Custom": 7},
        {"RuntimeId": "ItemStatus"},
        {"Custom": "BoundingRectangle"},
    ],
)
def test_invalid_config_aliases(tmp_path: Path, value: object) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path, overrides={"property_aliases": value})


def test_native_conditions_use_real_property_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, object]] = []
    native = SimpleNamespace(
        CreatePropertyCondition=lambda ident, value: calls.append((ident, value)) or (ident, value),
        CreateAndCondition=lambda first, second: (first, second),
    )
    monkeypatch.setattr(com, "get_uia", lambda: native)
    com.create_condition(help_text="Save", GridRowCount=4, is_enabled=True)
    assert calls == [
        (PROPERTY_IDS["HelpText"], "Save"),
        (PROPERTY_IDS["GridRowCount"], 4),
        (PROPERTY_IDS["IsEnabled"], True),
    ]
    assert all(spec.uia_name in PROPERTY_IDS for spec in SUPPORTED.values())


@pytest.mark.parametrize("full", [False, True])
def test_spy_properties_include_configured_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, full: bool
) -> None:
    from rpc_support import make_server, request

    server, output, button = make_server(tmp_path, monkeypatch)
    (tmp_path / "wintestkit.yaml").write_text(
        "property_aliases: {ClrFullClassName: ItemStatus, Contents: Value}\n", encoding="utf-8"
    )
    request(server, output, "initialize", {"root": str(tmp_path)})
    monkeypatch.setattr(
        button,
        "get_property",
        lambda name: {"ItemStatus": "Company.AddressBox", "ValueValue": "contents"}.get(name, ""),
    )
    node = server._register(button)
    result = request(
        server, output, "inspect.properties", {"nodeId": node["nodeId"], "full": full}
    )["result"]
    assert result["properties"]["ClrFullClassName"] == "Company.AddressBox"
    assert result["properties"]["Contents"] == "contents"


def test_terminal_spy_prints_properties(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from wintestkit.cli import main
    from wintestkit.engine import spy, suggest

    (tmp_path / "pyproject.toml").write_text("[tool.wintestkit]\n", encoding="utf-8")
    button = FakeElement(
        "Button", properties={"HelpText": "Save", "ItemStatus": "Company.AddressBox"}
    )

    class Session:
        def __init__(self, hover, pick, cancel, process_filter):
            self.pick, self.cancel = pick, cancel

        def start(self):
            self.pick(button)
            self.cancel()

        def stop(self):
            pass

    monkeypatch.setattr(spy, "SpySession", Session)
    monkeypatch.setattr(
        suggest,
        "suggest_locator",
        lambda *args: SimpleNamespace(
            window=None, helpers=[], attribute_name="save", code='Button(name="Save")'
        ),
    )
    assert main(["--root", str(tmp_path), "spy", "--all-processes"]) == 0
    text = capsys.readouterr().out
    assert "HelpText: Save" in text
    assert "ItemStatus: Company.AddressBox" in text


def test_editor_discovers_property_mappings_without_importing(tmp_path: Path) -> None:
    from wintestkit.discovery import discover

    source = """
import re
from wintestkit import Page, Window, Element, Elements
raise RuntimeError("discovery must not execute this module")
class Main(Page):
    window = Window(where={"FrameworkId": "WPF"})
    address = Element(where={"ClrFullClassName": re.compile("AddressBox$", re.I), "IsEnabled": True, "ProcessId": -1, "RangeValueValue": 2.5})
    children = Elements(where={"ControlType": "button"}, within=address)
    dynamic = Element(name="Save", where={"HelpText": EXPECTED})
    dynamic_window = Window(where=PROPERTIES)
"""
    (tmp_path / "page.py").write_text(source, encoding="utf-8")
    result = discover(tmp_path)
    assert not result.errors
    (page,) = result.pages
    elements = {entry.name: entry for entry in page.elements}
    assert elements["window"].locator == {"window": {"where": {"FrameworkId": "WPF"}}}
    assert not elements["window"].dynamic
    assert elements["address"].locator["where"] == {
        "ClrFullClassName": {"regex": "AddressBox$", "flags": "i"},
        "IsEnabled": True,
        "ProcessId": -1,
        "RangeValueValue": 2.5,
    }
    assert not elements["address"].dynamic
    assert elements["children"].locator["where"] == {"ControlType": "Button"}
    assert elements["children"].locator["within"]["where"] == elements["address"].locator["where"]
    assert elements["dynamic"].dynamic
    assert elements["dynamic"].locator == {"name": "Save"}
    assert elements["dynamic_window"].dynamic


def test_inspection_values_read_only_what_aliases_point_at_when_given_no_base() -> None:
    from wintestkit.engine.properties import inspection_values

    button = FakeElement(
        "Button",
        properties={"HelpText": "Save", "ItemStatus": "Company.AddressBox", "ItemType": "x"},
    )
    aliases = {"ClrFullClassName": "ItemStatus"}
    # the command line keeps its three defaults ...
    assert set(inspection_values(button, aliases)) == {
        "HelpText",
        "ItemStatus",
        "ItemType",
        "ClrFullClassName",
    }
    # ... Spy's list does not
    assert inspection_values(button, aliases, base=()) == {
        "ItemStatus": "Company.AddressBox",
        "ClrFullClassName": "Company.AddressBox",
    }
    assert inspection_values(button, {}, base=()) == {}
