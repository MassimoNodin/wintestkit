"""The NameMapping importer reads the real export structure and generates a page per window."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from name_mapping_support import alias, export, node, run, write

from wintestkit.cli import main
from wintestkit.engine.locator import WindowLocator
from wintestkit.engine.properties import AsText
from wintestkit.finders import to_locator
from wintestkit.model import Element, Page, PageObject, Window
from wintestkit.name_mapping import MAX_XML_BYTES, Conversion, convert, convert_detailed

SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "name_mapping_sample.xml"


def declared(locator: Any, managed: bool) -> Any:
    """What a declaration holds: the object-tree form with the inspector, else the UIA form."""
    if managed:
        return replace(locator, uia_form=None)
    form = replace(locator.uia_form, depth=locator.depth)
    return replace(
        form,
        where=tuple(
            ({"type:FullName": "ClrFullClassName", "type:Name": "ClrClassName"}.get(k, k), v)
            for k, v in form.where
        ),
    )


def elements_of(page: type[Page]) -> dict[str, Element[Any]]:
    return {name: value for name, value in vars(page).items() if isinstance(value, Element)}


# -- the sample: every node kind in the real structure -------------------------------------------


def test_the_sample_fixture_keeps_the_real_line_endings_and_tabs() -> None:
    data = SAMPLE.read_bytes()
    assert data.count(b"\r\n") == data.count(b"\n") > 100
    assert b"\t" in data


@pytest.mark.parametrize("managed", [False, True])
def test_sample_generates_a_page_per_window_that_compiles(tmp_path: Path, managed: bool) -> None:
    result = convert_detailed(SAMPLE, managed_class_names=managed)
    assert isinstance(result, Conversion)
    ast.parse(result.code)
    assert result.warnings == ()
    # Two windows and four elements; the grid's two identifiers have no equivalent.
    assert result.declared == 6
    assert result.todos == 2
    assert convert(SAMPLE, managed_class_names=managed) == result.code
    target = tmp_path / "page.py"
    target.write_text(result.code, encoding="utf-8")
    subprocess.run([sys.executable, "-m", "ruff", "format", "--check", str(target)], check=True)
    namespace = run(result.code, tmp_path)
    assert issubclass(namespace["MainWindow"], Page)
    assert issubclass(namespace["OrdersDialog"], Page)
    assert ('tree="objects"' in result.code) is managed


@pytest.mark.parametrize("managed", [False, True])
def test_sample_windows_and_process(tmp_path: Path, managed: bool) -> None:
    code = convert(SAMPLE, managed_class_names=managed)
    namespace = run(code, tmp_path)
    # The process node maps to the application, not to an element.
    assert "Processes: App." in code
    assert "ProcessName" not in code
    # A WinForms window: its control name is its automation id.
    assert isinstance(namespace["MainWindow"].window, Window)
    assert namespace["MainWindow"].window.locator == WindowLocator(automation_id="MainWindow")
    # A Win32 window: caption and class.
    assert namespace["OrdersDialog"].window.locator == WindowLocator(
        title="Orders", class_name="#32770"
    )


@pytest.mark.parametrize("managed", [False, True])
def test_sample_elements_are_named_by_alias_and_nested_through_unaliased_nodes(
    tmp_path: Path, managed: bool
) -> None:
    namespace = run(convert(SAMPLE, managed_class_names=managed), tmp_path)
    elements = elements_of(namespace["MainWindow"])
    # MainView has no alias and keeps its mapped name; the aliases of its children skip it.
    assert list(elements) == ["MainView", "SaveButton", "NameBox"]
    assert elements["MainView"].within is None
    assert elements["SaveButton"].within is elements["MainView"]
    assert elements["NameBox"].within is elements["MainView"]
    # ExtendedFind="True" searches all descendants; without it the node is a direct child.
    assert elements["MainView"]._own.depth is None
    assert elements["SaveButton"]._own.depth is None
    assert elements_of(namespace["OrdersDialog"])["OrdersGrid"]._own.depth == 1


@pytest.mark.parametrize("managed", [False, True])
def test_sample_typed_and_wildcard_values(tmp_path: Path, managed: bool) -> None:
    page = elements_of(run(convert(SAMPLE, managed_class_names=managed), tmp_path)["MainWindow"])
    # Three properties: two strings and an integer (Type="0") ordinal.
    save = to_locator(
        ["ClrFullClassName", "WPFControlText", "WPFControlOrdinalNo"],
        ["System.Windows.Controls.Button", "Save", 1],
    )
    assert page["SaveButton"]._own == declared(save, managed)
    # A string and a boolean (Type="6").
    name_box = to_locator(["WPFControlName", "Visible"], ["NameBox", True])
    assert page["NameBox"]._own == declared(name_box, managed)
    assert dict(page["NameBox"]._own.where)["clr:IsVisible"] is True
    # A wildcard becomes a whole-value pattern.
    pattern = page["MainView"]._own.name
    assert isinstance(pattern, re.Pattern) and pattern.fullmatch("anything at all")
    key = "type:Name" if managed else "ClrClassName"
    assert dict(page["MainView"]._own.where) == {key: "MainWindow"}
    ordinal = dict(page["SaveButton"]._own.where).get("wpf:Ordinal")
    assert (ordinal == 1) if managed else (page["SaveButton"]._own.index == 0)


def test_sample_uia_node_properties_and_todos(tmp_path: Path) -> None:
    result = convert_detailed(SAMPLE)
    grid = elements_of(run(result.code, tmp_path)["OrdersDialog"])["OrdersGrid"]
    # FrameworkId, ClassName and LocalizedControlType are UIA properties.
    assert grid._own.class_name == "Company.Controls.OrdersGrid"
    assert dict(grid._own.where) == {"FrameworkId": "WPF", "LocalizedControlType": "table"}
    # ObjectIdentifier and ObjectGroupIndex have no equivalent: a TODO with the value, nothing made up.
    assert (
        "# TODO OrdersGrid: 'ObjectIdentifier' = 'OrdersGrid' (no equivalent; compare by hand)"
        in result.code
    )
    assert "# TODO OrdersGrid: 'ObjectGroupIndex' = 1 (no equivalent; compare by hand)" in (
        result.code
    )
    assert result.code.count("# TODO") == result.todos == 2


def test_sample_golden_output() -> None:
    expected = '''"""Generated from NameMapping; review locators before use.

Processes: App. Attach or launch the application, then use these pages.

ClrFullClassName and ClrClassName require verified application-specific UIA property aliases.
"""

import re

from wintestkit import Element, Page, Window


class MainWindow(Page):
    window = Window(automation_id="MainWindow")

    MainView = Element(
        name=re.compile("^.*\\\\Z", re.DOTALL),
        where={
            "ClrClassName": "MainWindow",
        },
    )
    SaveButton = Element(
        name="Save",
        index=0,
        where={
            "ClrFullClassName": "System.Windows.Controls.Button",
        },
        within=MainView,
    )
    NameBox = Element(
        automation_id="NameBox",
        where={
            "clr:IsVisible": True,
        },
        within=MainView,
    )


class OrdersDialog(Page):
    window = Window(
        title="Orders",
        class_name="#32770",
    )

    # TODO OrdersGrid: 'ObjectIdentifier' = 'OrdersGrid' (no equivalent; compare by hand)
    # TODO OrdersGrid: 'ObjectGroupIndex' = 1 (no equivalent; compare by hand)
    OrdersGrid = Element(
        class_name="Company.Controls.OrdersGrid",
        where={
            "FrameworkId": "WPF",
            "LocalizedControlType": "table",
        },
        depth=1,
    )
'''
    assert convert(SAMPLE) == expected
    managed = convert(SAMPLE, managed_class_names=True)
    assert 'tree="objects"' in managed and '"wpf:Text": "Save"' in managed
    assert '"wpf:Ordinal": 1,' in managed and '"type:FullName"' in managed
    assert "require the WPF inspector" in managed


# -- structure ------------------------------------------------------------------------------------


def test_aliases_can_skip_levels_and_one_node_can_have_several(tmp_path: Path) -> None:
    deep = node("Deep", "{C}", ("WPFControlName", "Deep"), extended=True)
    box = node("Box", "{B}", ("WPFControlName", "Box"), children=deep)
    panel = node("Panel", "{A}", ("WPFControlName", "Panel"), extended=True, children=box)
    windows = node("Main", "{W}", ("WinFormsControlName", "Main"), children=panel)
    # Deepest is listed straight below the window; the unaliased Panel is skipped. Box has two names.
    names = alias("Deepest", "{C}") + alias("Cell", "{B}") + alias("Other", "{B}")
    aliases = alias("App", "{P}", alias("Shell", "{W}", names))
    result = convert_detailed(write(tmp_path, export(windows, aliases)))
    page = run(result.code, tmp_path)["Shell"]
    elements = elements_of(page)
    assert list(elements) == ["Panel", "Cell", "Deepest"]
    assert page.Cell.within is page.Panel and page.Deepest.within is page.Cell
    assert elements["Deepest"]._own.depth is None and elements["Cell"]._own.depth == 1
    assert "Other" not in result.code  # the first alias names the node
    assert result.warnings == ()


def test_unaliased_nodes_keep_their_mapped_name(tmp_path: Path) -> None:
    child = node("Save Button", "{A}", ("WPFControlName", "Save"))
    windows = node("Main", "{W}", ("WndCaption", "Main"), children=child)
    code = convert(write(tmp_path, export(windows)))
    assert "class Main(Page):" in code and "Save_Button = Element(" in code


def test_an_alias_whose_owner_matches_no_node_is_a_warning(tmp_path: Path) -> None:
    child = node("Ok", "{A}", ("WPFControlName", "Ok"))
    windows = node("Main", "{W}", ("WndCaption", "Main"), children=child)
    aliases = alias("Lost", "{MISSING}") + alias("Main", "{W}")
    result = convert_detailed(write(tmp_path, export(windows, aliases)))
    assert result.warnings == ("alias 'Lost': owner {MISSING} matches no mapped node; skipped",)
    assert "Lost" not in result.code


def test_several_processes_name_the_process_of_each_window(tmp_path: Path) -> None:
    second = node(
        "Second",
        "{P2}",
        ("ProcessName", "Other"),
        children=node("Two", "{W2}", ("WndCaption", "Two")),
    )
    text = export(node("One", "{W1}", ("WndCaption", "One"))).replace(
        "</Children></Child></Children></Nodes>", f"</Children></Child>{second}</Children></Nodes>"
    )
    code = convert(write(tmp_path, text))
    assert "Processes: App, Other." in code
    assert 'process="App"' in code and 'process="Other"' in code
    run(code, tmp_path)


@pytest.mark.parametrize(("managed", "key"), [(False, "ClrClassName"), (True, "type:Name")])
def test_a_wpf_window_maps_its_root_visual(tmp_path: Path, managed: bool, key: str) -> None:
    windows = node(
        "Shell",
        "{W}",
        ("WndClass", "HwndWrapper*"),
        ("WndCaption", "Shell"),
        ("RootVisual.ClrClassName", "ShellWindow"),
        ("RootVisual.Name", "RootShell"),
    )
    code = convert(write(tmp_path, export(windows)), managed_class_names=managed)
    window = run(code, tmp_path)["Shell"].window.locator
    assert window.title == "Shell"
    assert window.automation_id == "RootShell"
    assert isinstance(window.class_name, re.Pattern)
    assert window.class_name.fullmatch("HwndWrapper[1]")
    assert dict(window.where) == {key: "ShellWindow"}


def test_unmappable_windows_and_parents_are_todos(tmp_path: Path) -> None:
    bad = node("Bad", "{A}", ("Name", "x"), children=node("Child", "{B}", ("WPFControlName", "c")))
    windows = node("Main", "{W}", ("ObjectIdentifier", "main"), children=bad)
    result = convert_detailed(write(tmp_path, export(windows)))
    assert "# TODO Main: the window has no mapped properties; it is the main window" in result.code
    assert "# TODO Bad: cannot declare element without mapped properties" in result.code
    assert "# TODO Child: cannot declare element because its parent is unmappable" in result.code
    assert result.todos == 5 and result.declared == 1
    run(result.code, tmp_path)


# -- values ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["True", "true", "TRUE", "tRuE"])
def test_booleans_parse_case_insensitively(tmp_path: Path, flag: str) -> None:
    box = node("Box", "{A}", ("WPFControlName", "Box"), ("Enabled", flag, "6"))
    windows = node("Main", "{W}", ("WndCaption", "Main"), children=box)
    result = convert_detailed(write(tmp_path, export(windows)))
    assert '"clr:IsEnabled": True,' in result.code and result.warnings == ()


def test_integer_and_string_values_and_the_empty_string(tmp_path: Path) -> None:
    box = node(
        "Box",
        "{A}",
        ("WPFControlName", ""),
        ("WPFControlText", ""),
        ("Count", "15", "0"),
        ("Label", "15"),
        ("Title", "a*b?"),
    )
    windows = node("Main", "{W}", ("WndCaption", "Main"), children=box)
    code = convert(write(tmp_path, export(windows)), managed_class_names=True)
    element = elements_of(run(code, tmp_path)["Main"])["Box"]._own
    assert element.automation_id == ""  # an empty value is a test for empty text
    where = dict(element.where)
    assert where["wpf:Text"] == ""
    assert where["clr:Count"] == 15 and where["clr:Label"] == AsText("15")
    pattern = where["clr:Title"]
    assert isinstance(pattern, re.Pattern)
    assert pattern.fullmatch("aXbY") and not pattern.fullmatch("ab")


def test_bad_typed_values_stay_text_with_a_warning(tmp_path: Path) -> None:
    box = node("Box", "{A}", ("Count", "many", "0"), ("Flag", "maybe", "6"), ("Odd", "1", "9"))
    windows = node("Main", "{W}", ("WndCaption", "Main"), children=box)
    result = convert_detailed(write(tmp_path, export(windows)))
    assert len(result.warnings) == 3
    assert any("is not an integer" in warning for warning in result.warnings)
    assert any("is not a boolean" in warning for warning in result.warnings)
    assert any("unknown value type '9'" in warning for warning in result.warnings)


# -- tolerance ------------------------------------------------------------------------------------


def test_unknown_elements_and_attributes_are_warnings_not_failures(tmp_path: Path) -> None:
    child = node("Ok", "{A}", ("WPFControlName", "Ok"))
    windows = node(
        "Main", "{W}", ("WndCaption", "Main"), extra="<Mystery />", children=child
    ).replace('Name="Main"', 'Name="Main" Colour="red"')
    text = export(windows, root_extra="<Extra />").replace(
        'SaveImages="0"', 'SaveImages="0" Flavour="x"'
    )
    result = convert_detailed(write(tmp_path, text))
    assert "Ok = Element(" in result.code
    joined = "\n".join(result.warnings)
    for fragment in ("<Mystery>", "<Extra>", "'Colour'", "'Flavour'"):
        assert fragment in joined
    assert "Storages" not in joined  # ignored without a word


def test_the_old_guessed_shapes_are_not_read(tmp_path: Path) -> None:
    guessed = (
        '<Root><Item><Properties><Property name="WPFControlName" value="x" />'
        "</Properties></Item></Root>"
    )
    with pytest.raises(ValueError, match="no NameMapping nodes were found"):
        convert(write(tmp_path, guessed))
    with pytest.raises(ValueError, match="expected <Root>"):
        convert(write(tmp_path, "<Mapping />"))


def test_a_process_without_windows_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no NameMapping windows"):
        convert(write(tmp_path, export("")))


@pytest.mark.parametrize(
    "payload",
    [
        b'<!DOCTYPE x [<!ENTITY e "boom">]><Root/>',
        b'<!DOCTYPE x SYSTEM "file:///secret"><Root/>',
        '<!DOCTYPE x [<!ENTITY e "boom">]><Root/>'.encode("utf-16"),
        '<!DOCTYPE x SYSTEM "file:///secret"><Root/>'.encode("utf-16-be"),
    ],
)
def test_import_rejects_dtd_and_entities(tmp_path: Path, payload: bytes) -> None:
    source = tmp_path / "mapping.xml"
    source.write_bytes(payload)
    with pytest.raises(ValueError, match="DTD"):
        convert(source)


def test_import_is_bounded_and_rejects_malformed_xml(tmp_path: Path) -> None:
    source = tmp_path / "mapping.xml"
    source.write_bytes(b" " * (MAX_XML_BYTES + 1))
    with pytest.raises(ValueError, match="byte import limit"):
        convert(source)
    with pytest.raises(ValueError, match="invalid NameMapping XML"):
        convert(write(tmp_path, "<Root><Nodes>"))


def test_deeply_nested_nodes_are_rejected(tmp_path: Path) -> None:
    inner = node("Leaf", "{L}", ("WPFControlName", "Leaf"))
    for level in range(210):
        inner = node(f"N{level}", f"{{K{level}}}", ("WPFControlName", f"N{level}"), children=inner)
    windows = node("Main", "{W}", ("WndCaption", "Main"), children=inner)
    with pytest.raises(ValueError, match="nested deeper"):
        convert(write(tmp_path, export(windows)))


# -- names ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["window", "root", "app", "check", "elements", "²", "Ⅳ", "class"])
def test_names_are_valid_and_do_not_shadow_the_page_api(tmp_path: Path, name: str) -> None:
    child = node(name, "{A}", ("WPFControlName", "x"))
    windows = node("Main", "{W}", ("WndCaption", "Main"), children=child)
    code = convert(write(tmp_path, export(windows)))
    page = next(n for n in ast.parse(code).body if isinstance(n, ast.ClassDef))
    targets = [
        target.id
        for statement in page.body
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Name)
    ]
    assert targets[0] == "window"
    assert targets[1] not in (set(dir(PageObject)) | set(PageObject.__annotations__))
    run(code, tmp_path)


def test_names_that_collide_get_suffixes(tmp_path: Path) -> None:
    children = "".join(
        node(name, f"{{K{i}}}", ("WPFControlName", f"n{i}"))
        for i, name in enumerate(["K", chr(0x212A), "Save", "Element", "Page", "Window"])
    )
    windows = node("Main", "{W}", ("WndCaption", "Main"), children=children)
    page = run(convert(write(tmp_path, export(windows))), tmp_path)["Main"]
    names = list(elements_of(page))
    assert names[:3] == ["K", "K_2", "Save"]
    assert len(names) == len(set(names)) == 6


# -- command --------------------------------------------------------------------------------------


def test_cli_reports_todos_and_warnings_and_refuses_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "page.py"
    target.write_text("keep me", encoding="utf-8")
    assert main(["import-namemapping", str(SAMPLE), str(target)]) == 2
    assert target.read_text(encoding="utf-8") == "keep me"
    capsys.readouterr()
    assert main(["import-namemapping", str(SAMPLE), str(target), "--force"]) == 0
    out = capsys.readouterr()
    assert "6 windows and elements, 2 TODO comments" in out.out
    assert out.err == ""
    assert "class MainWindow(Page):" in target.read_text(encoding="utf-8")
    odd = export(node("Main", "{W}", ("WndCaption", "Main")), root_extra="<Extra />")
    other = tmp_path / "other.py"
    assert main(["import-namemapping", str(write(tmp_path, odd)), str(other)]) == 0
    out = capsys.readouterr()
    assert "warning: unknown element <Extra> in the export ignored" in out.err
    assert "0 TODO comments" in out.out
    empty = write(tmp_path, "<Root />", "empty.xml")
    assert main(["import-namemapping", str(empty), str(tmp_path / "z.py")]) == 2


# -- typed non-string values for a type or a name -----------------------------------------------


@pytest.mark.parametrize("managed", [False, True])
def test_an_integer_class_name_is_a_todo_with_the_raw_value(tmp_path: Path, managed: bool) -> None:
    windows = node(
        "Popup",
        "{W}",
        ("WndCaption", "Popup"),
        ("RootVisual.ClrClassName", "0", "0"),
        ("RootVisual.ClrFullClassName", "0", "0"),
        ("WndClass", "7", "0"),
        children=node(
            "Box",
            "{B}",
            ("WPFControlName", "Box"),
            ("ClrClassName", "0", "0"),
            ("DataContext.ClrClassName", "0", "0"),
        ),
    )
    result = convert_detailed(write(tmp_path, export(windows)), managed_class_names=managed)
    assert "# TODO Popup: 'RootVisual.ClrClassName' = 0 (a type or name holds" in result.code
    assert "# TODO Popup: 'RootVisual.ClrFullClassName' = 0" in result.code
    assert "# TODO Popup: 'WndClass' = 7" in result.code
    assert "# TODO Box: 'ClrClassName' = 0" in result.code
    assert "# TODO Box: 'DataContext.ClrClassName' = 0" in result.code
    assert result.todos == 5
    # Nothing is emitted that can never match.
    assert ": 0," not in result.code and 'ClrClassName": 0' not in result.code
    namespace = run(result.code, tmp_path)
    window = namespace["Popup"].window.locator
    assert window.title == "Popup" and window.where == ()
    assert 'automation_id="Box"' in result.code


def test_a_string_class_name_and_a_typed_non_name_property_are_unchanged(tmp_path: Path) -> None:
    box = node(
        "Box",
        "{B}",
        ("WPFControlName", "Box"),
        ("ClrClassName", "Button"),
        ("WPFControlOrdinalNo", "2", "0"),
    )
    windows = node("Main", "{W}", ("WndCaption", "Main"), children=box)
    result = convert_detailed(write(tmp_path, export(windows)))
    assert result.todos == 0
    assert '"ClrClassName": "Button"' in result.code
