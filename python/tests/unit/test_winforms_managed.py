"""Managed reads and locators on WinForms controls, with fakes for the agent and the UIA tree.

A WinForms window (or a WinForms control hosted in WPF) is found through UI Automation; its native
members are read, and managed ``where`` keys are matched, by the agent on the control's own thread.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import finders, runtime
from wintestkit.backends.element import WpfElement
from wintestkit.config import load_config
from wintestkit.engine import query, wpf_resolve
from wintestkit.engine import resolve as resolver
from wintestkit.engine.locator import Locator, WindowLocator
from wintestkit.engine.property_read import read_property
from wintestkit.engine.resolve import Scope, resolve, resolve_all, resolve_window
from wintestkit.errors import InspectorUnavailableError, InvalidLocatorError
from wintestkit.inspector.models import ObjectRef, PathValue, TypeInfo, Value

CONTROL = "System.Windows.Forms.Control"
HOSTED_CLASS = "WindowsForms10.window.8.app.0.141b42a_r8"


def winforms_ref(name: str, full_name: str = "Demo.SeriesChart") -> ObjectRef:
    return ObjectRef(
        "session", name, 1, TypeInfo(full_name, full_name, "A", "T, A", (CONTROL,)), "d"
    )


def wpf_ref(name: str) -> ObjectRef:
    return ObjectRef("session", name, 1, TypeInfo("W", "Demo.W", "A", "T, A", ()), "d")


class Client:
    """An agent that answers reads from a table and records the queries it receives."""

    def __init__(self, values: dict[tuple[str, ...], Value] | None = None) -> None:
        self.session = SimpleNamespace(features=["query", "geometry", "exactUiaMapping"])
        self.values = values or {}
        self.queries: list[Any] = []
        self.matches: tuple[ObjectRef, ...] = ()
        self.read_paths: list[Any] = []

    def read(self, object_id: str, generation: int, paths: Any, *, deadline: float) -> Any:
        self.read_paths.extend(paths)
        found = []
        for path in paths:
            key = tuple(segment.name for segment in path)
            found.append(PathValue(tuple(path), self.values[key]))
        return tuple(found), "read"

    def query_find_all(self, locator: Any, *, timeout_ms: int, deadline: float) -> Any:
        self.queries.append(locator)
        return SimpleNamespace(matches=self.matches, complete=True, unreadable=None)

    def query_find(self, locator: Any, *, timeout_ms: int, deadline: float) -> Any:
        self.queries.append(locator)
        return SimpleNamespace(match=self.matches[0])

    def release(self, ids: Any, *, deadline: float) -> None:
        pass

    def defer_release(self, object_id: str) -> None:
        pass


def winforms_element(name: str = "chart1", framework: str = "WinForm") -> FakeElement:
    element = FakeElement("Pane", name, automation_id=name, class_name=HOSTED_CLASS)
    element.framework_id = framework
    return element


@pytest.fixture(autouse=True)
def setup(tmp_path: Path) -> Generator[None]:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"backend": "auto", "timeout": 1.0}))
    yield
    runtime.reset()


# -- who may be mapped ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("framework", "class_name", "winforms"),
    [
        ("WinForm", "", True),
        ("WinForms", "", True),
        ("Win32", HOSTED_CLASS, True),  # a hosted control whose provider reports a plain window
        ("Win32", "Edit", False),
        ("WPF", "", False),
        ("Win32", "", False),
    ],
)
def test_winforms_elements_are_told_by_framework_or_class(
    framework: str, class_name: str, winforms: bool
) -> None:
    element = FakeElement("Pane", class_name=class_name)
    element.framework_id = framework
    assert wpf_resolve.is_winforms_element(element) is winforms
    assert wpf_resolve.managed_capable(element) is (winforms or framework == "WPF")
    assert wpf_resolve.wpf_capable(element) is (framework == "WPF")


def test_agent_objects_are_told_by_their_type() -> None:
    assert wpf_resolve.is_winforms_element(WpfElement(Client(), winforms_ref("a"), 1))
    assert not wpf_resolve.is_winforms_element(WpfElement(Client(), wpf_ref("a"), 1))
    assert not wpf_resolve.managed_capable(WpfElement(Client(), winforms_ref("a"), 1))


def test_nothing_is_mapped_without_the_auto_backend(tmp_path: Path) -> None:
    runtime.set_config(load_config(tmp_path, {"backend": "uia"}))
    assert not wpf_resolve.managed_capable(winforms_element())


# -- el.get("clr:...") ------------------------------------------------------------------------------


def int_value(number: int) -> Value:
    return Value("ok", "integer", "System.Int32", "System.Int32", scalar=str(number))


def string_value(text: str) -> Value:
    return Value("ok", "string", "System.String", "System.String", scalar=text)


@pytest.mark.parametrize("framework", ["WinForm", "Win32"])
def test_get_reads_native_members_of_a_winforms_control(
    monkeypatch: pytest.MonkeyPatch, framework: str
) -> None:
    client = Client(
        {
            ("SeriesCount",): int_value(3),
            ("Footer", "Text"): string_value("Page 1 of 2"),
            ("Series[1]", "Title"): string_value("Beta"),
            ("Name",): string_value("SeriesChart"),
        }
    )
    mapped = WpfElement(client, winforms_ref("chart"), 1)
    seen: list[Any] = []

    def to_managed(element: Any) -> WpfElement:
        seen.append(element)
        return mapped

    monkeypatch.setattr("wintestkit.engine.property_read.to_managed", to_managed)
    control = winforms_element(framework=framework)
    assert read_property(control, "clr:SeriesCount") == 3
    assert read_property(control, "clr:Footer.Text") == "Page 1 of 2"
    assert read_property(control, "clr:Series[1].Title") == "Beta"
    assert read_property(control, "type:Name") == "SeriesChart"
    assert seen == [control] * 4
    assert [(s.kind, s.name) for s in client.read_paths[1]] == [
        ("property", "Footer"),
        ("property", "Text"),
    ]


def test_get_of_a_redacted_or_failing_native_member_reports_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client(
        {
            ("ApiKey",): Value("redacted", "unavailable", "T", "T"),
            ("Broken",): Value(
                "exception", "unavailable", "T", "T", message="System.InvalidOperationException"
            ),
        }
    )
    monkeypatch.setattr(
        "wintestkit.engine.property_read.to_managed",
        lambda element: WpfElement(client, winforms_ref("c"), 1),
    )
    from wintestkit.errors import ActionError

    with pytest.raises(ActionError, match="redacted"):
        read_property(winforms_element(), "clr:ApiKey")
    with pytest.raises(ActionError, match="InvalidOperationException"):
        read_property(winforms_element(), "clr:Broken")


def test_get_without_the_inspector_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: Any, **kwargs: Any) -> Any:
        raise InspectorUnavailableError("blocked", code="notAttached")

    monkeypatch.setattr(wpf_resolve.runtime, "managed_client_for", blocked)
    monkeypatch.setattr(wpf_resolve.runtime, "managed_element_identity", lambda e: ((1,), 5))
    monkeypatch.setattr(wpf_resolve, "root_handle", lambda e: 5)
    with pytest.raises(InspectorUnavailableError, match=r"WinForms inspector \(notAttached\)"):
        read_property(winforms_element(), "clr:SeriesCount")


def test_get_on_a_plain_window_or_the_uia_backend_is_still_refused(tmp_path: Path) -> None:
    plain = FakeElement("Pane")
    plain.framework_id = "Win32"
    with pytest.raises(InvalidLocatorError, match=r"requires the WPF backend.*WinForms window"):
        read_property(plain, "clr:SeriesCount")
    runtime.set_config(load_config(tmp_path, {"backend": "uia"}))
    with pytest.raises(InvalidLocatorError, match="requires the WPF backend"):
        read_property(winforms_element(), "clr:SeriesCount")


# -- where= on WinForms windows ---------------------------------------------------------------------


@pytest.fixture
def form() -> tuple[FakeElement, FakeApp]:
    window = FakeElement("Window", "Charts", automation_id="chartForm")
    window.framework_id = "WinForm"
    return window, FakeApp([window])


def agent_for(monkeypatch: pytest.MonkeyPatch, *matches: ObjectRef) -> Client:
    client = Client()
    client.matches = matches
    root = WpfElement(client, winforms_ref("form", "Demo.MainForm"), 1)
    monkeypatch.setattr(resolver, "to_managed", lambda element: root)
    return client


def predicates(client: Client) -> list[tuple[str, str, Any]]:
    result = []
    for predicate in client.queries[0].predicates:
        path = predicate.path or ()
        result.append((predicate.kind, ".".join(s.name for s in path), predicate.value))
    return result


def test_a_where_on_a_winforms_window_is_matched_by_the_agent(
    monkeypatch: pytest.MonkeyPatch, form: tuple[FakeElement, FakeApp]
) -> None:
    _, app = form
    client = agent_for(monkeypatch, winforms_ref("chart"))
    locator = Locator(where=(("clr:SeriesCount", 3), ("clr:Footer.Text", "Page 1 of 2")))
    (found,) = resolve_all(Scope(app), locator)  # type: ignore[arg-type]
    assert isinstance(found, WpfElement) and found.ref.object_id == "chart"
    (wire,) = client.queries
    assert wire.scope.handle.object_id == "form" and wire.tree == "combined"
    assert predicates(client) == [
        ("equals", "SeriesCount", 3),
        ("equals", "Footer.Text", "Page 1 of 2"),
    ]


def test_migrated_properties_on_a_winforms_window_use_the_uia_forms(
    monkeypatch: pytest.MonkeyPatch, form: tuple[FakeElement, FakeApp]
) -> None:
    """Class names are ``type:`` predicates; the control name is its AutomationId, which the agent
    reads as the control's Name; text and ordinal keep their UIA meanings (name, zero-based index)."""
    _, app = form
    client = agent_for(monkeypatch, winforms_ref("chart"))
    locator = finders.to_locator(
        ["WinFormsControlName", "ClrClassName", "SeriesCount", "WPFControlText"],
        ["chart1", "SeriesChart", "3", "Revenue"],
    )
    assert resolve(Scope(app), locator).ref.object_id == "chart"  # type: ignore[arg-type,union-attr]
    wire = {
        (p.path[0].kind, p.path[0].name): p.kind for p in client.queries[0].predicates if p.path
    }
    assert wire == {
        ("uia", "automation_id"): "equals",  # the agent reads it as the control's Name
        ("type", "Name"): "equals",
        ("property", "SeriesCount"): "equalsText",  # migrated suites pass numbers as text
        ("uia", "name"): "equals",
    }
    assert client.queries[0].tree == "combined"


def test_an_ordinal_picks_among_the_agent_matches_by_its_uia_index(
    monkeypatch: pytest.MonkeyPatch, form: tuple[FakeElement, FakeApp]
) -> None:
    _, app = form
    client = agent_for(monkeypatch, winforms_ref("first"), winforms_ref("second"))
    locator = finders.to_locator(["ClrClassName", "WPFControlOrdinalNo"], ["SeriesChart", 2])
    assert resolve(Scope(app), locator).ref.object_id == "second"  # type: ignore[arg-type,union-attr]
    assert client.queries


def test_a_link_without_managed_keys_stays_in_the_uia_tree(
    monkeypatch: pytest.MonkeyPatch, form: tuple[FakeElement, FakeApp]
) -> None:
    window, app = form
    window.add(winforms_element("chart1"))
    monkeypatch.setattr(query, "make_condition", lambda **props: props)
    monkeypatch.setattr(
        resolver, "to_managed", lambda element: pytest.fail("a plain lookup must not attach")
    )
    monkeypatch.setattr(wpf_resolve.runtime, "managed_client_for", lambda *a, **k: pytest.fail())
    locator = finders.to_locator("WinFormsControlName", "chart1")
    assert resolve(Scope(app), locator).automation_id == "chart1"  # type: ignore[arg-type]


def test_a_managed_where_on_a_winforms_window_is_not_matched_without_the_auto_backend(
    tmp_path: Path, form: tuple[FakeElement, FakeApp]
) -> None:
    _, app = form
    runtime.set_config(replace(load_config(tmp_path), backend="uia"))
    with pytest.raises(InvalidLocatorError, match=r"clr:SeriesCount.*backend: uia"):
        resolve_all(Scope(app), Locator(where=(("clr:SeriesCount", 3),)))  # type: ignore[arg-type]


def test_a_winforms_window_selector_with_a_managed_key_asks_the_agent(
    monkeypatch: pytest.MonkeyPatch, form: tuple[FakeElement, FakeApp]
) -> None:
    window, app = form
    other = FakeElement("Window", "Other")
    other.framework_id = "Win32"
    app.windows.append(other)
    routed: list[tuple[Any, bool]] = []
    root = WpfElement(Client(), winforms_ref("form", "Demo.MainForm"), 1)

    def route(candidate: Any, *, force: bool = False) -> Any:
        routed.append((candidate, force))
        return root

    monkeypatch.setattr(resolver, "route", route)
    monkeypatch.setattr(resolver, "matches_root", lambda element, conditions: True)
    selector = WindowLocator(where=(("type:Name", "MainForm"),))
    assert resolve_window(app, selector) is window  # type: ignore[arg-type]
    assert routed == [(window, True)]


def test_an_application_wide_search_reaches_winforms_windows_with_managed_keys(
    monkeypatch: pytest.MonkeyPatch, form: tuple[FakeElement, FakeApp]
) -> None:
    window, app = form
    client = Client()
    client.matches = (winforms_ref("chart"),)
    root = WpfElement(client, winforms_ref("form", "Demo.MainForm"), 1)
    monkeypatch.setattr(resolver, "route", lambda candidate, *, force=False: root)
    monkeypatch.setattr(resolver, "matches_root", lambda element, conditions: False)
    locator = replace(finders.to_locator("SeriesCount", "3"), app_scope=True)
    (found,) = resolve_all(Scope(app), locator)  # type: ignore[arg-type]
    assert found.ref.object_id == "chart"  # type: ignore[union-attr]
    assert window is not None


# -- the query below an agent object ------------------------------------------------------------------


def test_below_a_winforms_object_a_migrated_link_is_searched_in_its_uia_form() -> None:
    client = Client()
    client.matches = (winforms_ref("label"),)
    wired = finders.to_locator("WPFControlText", "Revenue")
    below_winforms = wpf_resolve.query(
        WpfElement(client, winforms_ref("form"), 1), wired, root_level=True
    )
    assert [(p.path[0].kind, p.path[0].name) for p in client.queries[0].predicates] == [
        ("uia", "name")
    ]
    assert client.queries[0].tree == "combined" and len(below_winforms) == 1
    below_wpf = wpf_resolve.query(WpfElement(client, wpf_ref("root"), 1), wired, root_level=True)
    assert [(p.path[0].kind, p.path[0].name) for p in client.queries[1].predicates] == [
        ("object", "Text")
    ]
    assert client.queries[1].tree == "objects" and len(below_wpf) == 1


# -- writes -------------------------------------------------------------------------------------------


def test_a_write_to_a_winforms_control_found_by_uia_goes_through_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wintestkit.model import BoundControl

    mapped = WpfElement(Client(), winforms_ref("chart"), 1)
    control = winforms_element()
    monkeypatch.setattr(BoundControl, "resolve", lambda self: control)
    monkeypatch.setattr("wintestkit.engine.wpf_resolve.to_managed", lambda element: mapped)
    bound = object.__new__(BoundControl)
    assert bound._write_target() is mapped  # pyright: ignore[reportPrivateUsage]


def test_a_declared_object_tree_link_below_a_winforms_object_drops_the_tree() -> None:
    """``Element(tree="objects")`` has no UIA form; the agent walks a control's children whatever the tree."""
    client = Client()
    client.matches = (winforms_ref("chart"),)
    link = Locator(where=(("clr:SeriesCount", 3),), tree="objects", depth=1)
    found = wpf_resolve.query(WpfElement(client, winforms_ref("form"), 1), link, root_level=True)
    assert len(found) == 1
    wire = client.queries[0]
    assert wire.tree == "combined" and wire.depth == 1
    plain = Locator(depth=2, allow_empty=True)
    assert wpf_resolve.winforms_form(plain) is plain
