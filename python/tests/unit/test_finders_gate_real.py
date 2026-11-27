"""Reviewable Suite migration samples against the owned WPF fixture."""

import os
from dataclasses import replace
from xml.sax.saxutils import escape

import pytest
from test_wpf_query_gate_real import config

from wintestkit import runtime
from wintestkit.engine.locator import Locator
from wintestkit.engine.resolve import resolve, resolve_all
from wintestkit.errors import InvalidLocatorError
from wintestkit.finders import find, find_all_children, find_child
from wintestkit.model import Element, Page
from wintestkit.name_mapping import convert

pytest_plugins = ["test_wpf_query_gate_real"]

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)


class FixturePage(Page):
    group = Element(automation_id="ParityGroup")


def _node(name, key, value, children="", *, extended=True):
    flag = ' ExtendedFind="True"' if extended else ""
    return (
        f'<Child Name="{name}" Key="{key}"{flag}><Properties><Property Name="WPFControlName">'
        f'<Value Value="{value}" /></Property></Properties>'
        + (f"<Children>{children}</Children>" if children else "")
        + "</Child>"
    )


def export_for(title):
    """A NameMapping export of the owned fixture: its window and boxes, as a real file is laid out."""
    window = (
        f'<Child Name="Main" Key="{{W}}"><Properties><Property Name="WndCaption">'
        f'<Value Value="{escape(title, {chr(34): "&quot;"})}" /></Property></Properties><Children>'
        + _node("group", "{G}", "ParityGroup", _node("nested", "{N}", "NestedButto?"))
        + _node("fancy", "{F}", "FancyAutomationId")
        + _node("missing", "{M}", "NestedButton", extended=False)
        + "</Children></Child>"
    )
    process = (
        '<Child Name="App" Key="{P}"><Properties><Property Name="ProcessName">'
        f'<Value Value="App" /></Property></Properties><Children>{window}</Children></Child>'
    )
    return (
        '<Root Signature="{X}" NameMappingVersion="7" SaveImages="0"><Nodes Name="NameMapping" '
        'Key="{N0}"><Children><Child Name="Sys" Key="{S}"><Properties><Property Name="Name">'
        f'<Value Value="Sys" /></Property></Properties><Children>{process}</Children></Child>'
        "</Children></Nodes></Root>"
    )


SAMPLES = [
    (
        'p.FindChild("WPFControlName", "FancyAutomationId", 20)',
        'find_child(page, "WPFControlName", "FancyAutomationId", 20)',
        "fancy",
    ),
    (
        'group.FindChild("ClrFullClassName", "System.Windows.Controls.Button", 20)',
        'find_child(page.group, "ClrFullClassName", "System.Windows.Controls.Button", 20)',
        "nested",
    ),
    (
        'p.FindChild(["WPFControlName", "ClrFullClassName"], ["FancyAutomationId", "*FancyButton"], 20)',
        'find_child(page, ["WPFControlName", "ClrFullClassName"], ["FancyAutomationId", "*FancyButton"], 20)',
        "fancy",
    ),
    (
        'p.FindChild("WPFControlName", "Fancy*Id", 20)',
        'find_child(page, "WPFControlName", "Fancy*Id", 20)',
        "fancy",
    ),
    (
        'p.FindChild("WPFControlName", "FancyAutomationI?", 20)',
        'find_child(page, "WPFControlName", "FancyAutomationI?", 20)',
        "fancy",
    ),
    (
        'p.FindChild("WPFControlName", "NestedButton", 1)',
        'find_child(page, "WPFControlName", "NestedButton", 1)',
        "missing",
    ),
    (
        'p.FindChild("WPFControlName", "NestedButton", 20)',
        'find_child(page, "WPFControlName", "NestedButton", 20)',
        "nested",
    ),
    (
        'p.FindAllChildren("WPFControlName", "Duplicate", 20).length',
        'find_all_children(page, "WPFControlName", "Duplicate", 20)',
        "duplicates",
    ),
    (
        'group.Find("WPFControlName", "ParityGroup", 1)',
        'find(page.group, "WPFControlName", "ParityGroup", 1)',
        "group",
    ),
    (
        'p.FindChild("WPFControlText", "Fancy action", 20)',
        'find_child(page, "WPFControlText", "Fancy action", 20)',
        "fancy",
    ),
    (
        'p.FindChild(["WPFControlName", "WPFControlOrdinalNo"], ["Duplicate", 2], 20)',
        'find_child(page, ["WPFControlName", "WPFControlOrdinalNo"], ["Duplicate", 2], 20)',
        "second",
    ),
    (
        'p.FindChild(["WPFControlName", "Visible", "Enabled"], ["FancyAutomationId", true, true], 20)',
        'find_child(page, ["WPFControlName", "Visible", "Enabled"], ["FancyAutomationId", True, True], 20)',
        "fancy",
    ),
    (
        'p.FindChild(["WPFControlName", "DataContext.Label"], ["FancyAutomationId", "fixture"], 20)',
        'find_child(page, ["WPFControlName", "DataContext.Label"], ["FancyAutomationId", "fixture"], 20)',
        "fancy",
    ),
    (
        'p.FindChild("ClrFullClassName", "WinTestKit.Fixture.PeerlessMarker", 20)',
        'find_child(page, "ClrFullClassName", "WinTestKit.Fixture.PeerlessMarker", 20)',
        "peerless",
    ),
]


@pytest.mark.parametrize("backend", ["auto", "uia"])
def test_migration_samples(owned, backend, record_property):
    scope, path = owned
    page = FixturePage(scope.app)
    with runtime.config_scope(replace(config(path, "agent"), backend=backend)):
        expected = {
            "fancy": resolve(scope, Locator(automation_id="FancyAutomationId")),
            "nested": resolve(scope, Locator(automation_id="NestedButton")),
            "group": resolve(scope, Locator(automation_id="ParityGroup")),
            "duplicates": resolve_all(scope, Locator(automation_id="Duplicate")),
        }
        expected["second"] = expected["duplicates"][1]
        if backend == "auto":
            expected["peerless"] = resolve(
                scope, Locator(where=(("type:Is", "WinTestKit.Fixture.PeerlessMarker"),))
            )
        for original, expression, target in SAMPLES:
            if backend == "uia" and (
                any(
                    key in expression
                    for key in ("ClrFullClassName", "DataContext.Label", '"Visible"')
                )
            ):
                with pytest.raises(InvalidLocatorError, match="requires the WPF backend"):
                    eval(
                        expression,
                        {
                            "find_child": find_child,
                            "find_all_children": find_all_children,
                            "find": find,
                            "page": page,
                        },
                    ).resolve_once()
                record_property(original, "expected D8 error: managed key requires WPF")
                continue
            result = eval(
                expression,
                {
                    "find_child": find_child,
                    "find_all_children": find_all_children,
                    "find": find,
                    "page": page,
                },
            )
            if target == "missing":
                assert not result.exists(timeout=1)
                record_property(original, "pass")
            elif target == "duplicates":
                assert len(result) == 2
                assert all(
                    item.resolve_once().same_as(reference)
                    for item, reference in zip(result, expected[target], strict=True)
                )
                record_property(original, "pass")
            else:
                assert result.resolve_once().same_as(expected[target]), original
                record_property(original, "pass")


def test_namemapping_round_trip(owned, tmp_path):
    scope, path = owned
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        title = scope.app.main_window().name
        source = tmp_path / "NameMapping.xml"
        source.write_text(export_for(title), encoding="utf-8")
        namespace = {}
        exec(compile(convert(source), str(source), "exec"), namespace)
        page = namespace["Main"](scope.app)
        for alias, automation_id in (
            ("group", "ParityGroup"),
            ("nested", "NestedButton"),
            ("fancy", "FancyAutomationId"),
        ):
            assert (
                getattr(page, alias)
                .resolve_once()
                .same_as(resolve(scope, Locator(automation_id=automation_id)))
            )
        assert not page.missing.exists(timeout=1)


@pytest.mark.integration
def test_app_finder_managed_and_visibility(owned):
    scope, path = owned
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        main = scope.app.main_window()
        assert find_child(scope.app, "WndCaption", main.name, 1).resolve_once().same_as(main)
        match = find_child(
            scope.app, ["ClrClassName", "VisibleOnScreen"], ["FancyButton", True], 20
        )
        assert match.resolve_once().same_as(
            resolve(scope, Locator(automation_id="FancyAutomationId"))
        )


def test_object_tree_depth_text_and_ordinal(owned):
    """The migration object tree on the owned fixture: levels, window nodes, text and ordinals."""
    scope, path = owned
    page = FixturePage(scope.app)
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        main = scope.app.main_window()
        nested = resolve(scope, Locator(automation_id="NestedButton"))
        # The group box's template parts are hidden: its content is a direct child.
        direct = find_child(page.group, "WPFControlName", "NestedButton", 1)
        assert direct.resolve_once().same_as(nested)
        # The text is the T3 text (the button's content), not the peer name.
        by_text = find_child(page.group, "WPFControlText", "Nested", 1)
        assert by_text.resolve_once().same_as(nested)
        assert by_text.get("wpf:Text") == "Nested"
        # Ordinals are same-type positions among siblings, not global indexes.
        duplicates = [
            find_child(
                page, ["WPFControlName", "WPFControlOrdinalNo"], ["Duplicate", ordinal], None
            )
            for ordinal in (1, 2)
        ]
        references = resolve_all(scope, Locator(automation_id="Duplicate"))
        for found, reference in zip(duplicates, references, strict=True):
            assert found.resolve_once().same_as(reference)
        assert [item.get("wpf:Ordinal") for item in duplicates] == [1, 2]
        # From an application: depth 1 is the window node, depth 2 its root visual, then children.
        assert find_child(scope.app, "WPFControlText", main.name, 1).resolve_once().same_as(main)
        assert not find_child(scope.app, "WPFControlName", "ParityGroup", 2).exists(timeout=1)
        assert (
            find_child(scope.app, "WPFControlName", "ParityGroup", None)
            .resolve_once()
            .same_as(resolve(scope, Locator(automation_id="ParityGroup")))
        )
        # From a window the root visual itself is depth 1.
        assert find_child(scope, "WPFControlText", main.name, 1).resolve_once().same_as(main)
        assert not find_child(scope, "WPFControlName", "NestedButton", 1).exists(timeout=1)


def test_object_tree_keys_as_locator_options(owned):
    scope, path = owned
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):

        class Tree(Page):
            fancy = Element(
                automation_id="FancyAutomationId",
                tree="objects",
                where={"wpf:Text": "Fancy action"},
            )
            second = Element(automation_id="Duplicate", tree="objects", where={"wpf:Ordinal": 2})

        page = Tree(scope.app)
        assert page.fancy.resolve_once().same_as(
            resolve(scope, Locator(automation_id="FancyAutomationId"))
        )
        assert page.second.resolve_once().same_as(
            resolve_all(scope, Locator(automation_id="Duplicate"))[1]
        )
        assert page.second.get("wpf:Ordinal") == 2
