"""Reviewable TestComplete migration samples against the owned WPF fixture."""

import os
from dataclasses import replace

import pytest
from test_wpf_query_gate_real import config

from wintestkit import runtime
from wintestkit.engine.locator import Locator
from wintestkit.engine.resolve import resolve, resolve_all
from wintestkit.errors import InvalidLocatorError
from wintestkit.model import Element, Page
from wintestkit.name_mapping import convert
from wintestkit.testcomplete import find, find_all_children, find_child

pytest_plugins = ["test_wpf_query_gate_real"]

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
    reason="requires explicitly enabled owned Windows fixture",
)


class FixturePage(Page):
    group = Element(automation_id="ParityGroup")


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
    source = tmp_path / "NameMapping.xml"
    source.write_text(
        """<Root><Item alias="group" extendedFind="True"><Properties>
      <Property name="WPFControlName" value="ParityGroup" /></Properties>
      <Item alias="nested" extendedFind="True"><Properties>
      <Property name="WPFControlName" value="NestedButto?" /></Properties></Item>
      </Item><Item alias="fancy" extendedFind="True"><Properties>
      <Property name="WPFControlName" value="FancyAutomationId" /></Properties></Item>
      <Item alias="missing"><Properties><Property name="WPFControlName" value="NestedButton" /></Properties></Item>
      </Root>""",
        encoding="utf-8",
    )
    namespace = {}
    exec(compile(convert(source), str(source), "exec"), namespace)
    page = namespace["ImportedPage"](scope.app)
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
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
