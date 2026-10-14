"""Unit tests for the resolver and diagnostics, run against an in-memory element tree."""

import re
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit.engine import query
from wintestkit.engine.locator import Locator, WindowLocator
from wintestkit.engine.resolve import Scope, query_all, resolve, resolve_all, resolve_window
from wintestkit.errors import (
    AmbiguousElementError,
    ElementNotFoundError,
    WindowNotFoundError,
)


@pytest.fixture(autouse=True)
def fake_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query, "make_condition", lambda **props: props)


class Demo:
    """A small tree shaped like the WPF demo app."""

    def __init__(self) -> None:
        self.sign_in = FakeElement("Button", "Sign in", class_name="Button")
        self.username = FakeElement("Edit", class_name="TextBox")
        self.password = FakeElement("Edit", class_name="PasswordBox")
        self.credentials = FakeElement(
            "Group",
            "Credentials",
            class_name="GroupBox",
            children=[self.username, self.password, self.sign_in],
        )
        self.ok_a = FakeElement("Button", "OK", class_name="Button")
        self.ok_b = FakeElement("Button", "OK", class_name="Button")
        self.panel_a = FakeElement("Group", "Panel A", children=[self.ok_a])
        self.panel_b = FakeElement("Group", "Panel B", children=[self.ok_b])
        self.status = FakeElement(
            "Text", "Ready", automation_id="StatusText", class_name="TextBlock"
        )
        self.items = [FakeElement("ListItem", f"Item {i}") for i in range(1, 6)]
        self.list = FakeElement("List", class_name="ListBox", children=self.items)
        self.window = FakeElement(
            "Window",
            "WTK Demo",
            class_name="Window",
            children=[self.credentials, self.panel_a, self.panel_b, self.status, self.list],
        )
        self.dialog = FakeElement("Window", "WTK Demo - Dialog", class_name="Window")
        self.copy_item = FakeElement("MenuItem", "Copy")
        self.popup = FakeElement("Pane", class_name="Popup", children=[self.copy_item])
        self.app = FakeApp([self.window, self.dialog, self.popup])
        self.scope = Scope(self.app)  # type: ignore[arg-type]


@pytest.fixture
def demo() -> Demo:
    return Demo()


def test_unique_match(demo: Demo) -> None:
    assert resolve(demo.scope, Locator(control_type="Button", name="Sign in")) is demo.sign_in


def test_unique_match_by_automation_id(demo: Demo) -> None:
    assert resolve(demo.scope, Locator(automation_id="StatusText")) is demo.status


def test_ambiguous_message_and_candidates(demo: Demo) -> None:
    with pytest.raises(AmbiguousElementError) as exc_info:
        resolve(demo.scope, Locator(control_type="Button", name="OK"))
    diagnostic = exc_info.value.diagnostic
    assert diagnostic.kind == "ambiguous"
    assert str(exc_info.value) == (
        '2 elements match Button[name="OK"] in Window "WTK Demo"; add within= or index= to pick one'
    )
    assert diagnostic.match_count == 2
    assert diagnostic.locator == 'Button[name="OK"]'
    assert diagnostic.searched_in == 'Window "WTK Demo"'
    assert len(diagnostic.candidates) == 2
    assert diagnostic.candidates[0].mismatches == ()


def test_not_found_message_with_closest_candidate(demo: Demo) -> None:
    with pytest.raises(ElementNotFoundError) as exc_info:
        resolve(demo.scope, Locator(control_type="Button", name="Sign In"))
    diagnostic = exc_info.value.diagnostic
    assert diagnostic.kind == "not_found"
    assert str(exc_info.value) == (
        'No element matches Button[name="Sign In"] in Window "WTK Demo" '
        '(closest: Button "Sign in" — name differs)'
    )
    top = diagnostic.candidates[0]
    assert top.info.name == "Sign in"
    assert top.score == 1
    assert [(m.property, m.expected, m.actual) for m in top.mismatches] == [
        ("name", '"Sign In"', '"Sign in"')
    ]
    assert len(diagnostic.candidates) <= 5


def test_not_found_without_any_candidate(demo: Demo) -> None:
    with pytest.raises(ElementNotFoundError) as exc_info:
        resolve(demo.scope, Locator(automation_id="Nope"))
    assert str(exc_info.value) == 'No element matches *[id="Nope"] in Window "WTK Demo"'
    assert exc_info.value.diagnostic.candidates == ()


def test_not_found_names_two_mismatching_properties(demo: Demo) -> None:
    with pytest.raises(ElementNotFoundError) as exc_info:
        resolve(demo.scope, Locator(control_type="Button", name="Sign In", class_name="Btn"))
    assert str(exc_info.value).endswith('(closest: Button "Sign in" — name and class differ)')


def test_index_selects_among_matches(demo: Demo) -> None:
    assert resolve(demo.scope, Locator(control_type="Button", name="OK", index=0)) is demo.ok_a
    assert resolve(demo.scope, Locator(control_type="Button", name="OK", index=1)) is demo.ok_b


def test_index_out_of_range_message(demo: Demo) -> None:
    with pytest.raises(ElementNotFoundError) as exc_info:
        resolve(demo.scope, Locator(control_type="Button", name="OK", index=5))
    assert exc_info.value.diagnostic.kind == "index_out_of_range"
    assert str(exc_info.value) == (
        'index=5 is out of range: 2 elements match Button[name="OK"] in Window "WTK Demo"'
    )


def test_index_only_locator(demo: Demo) -> None:
    assert resolve(demo.scope, Locator(control_type="ListItem", index=2)) is demo.items[2]
    assert resolve(demo.scope, Locator(index=0)) is demo.credentials


def test_regex_filter(demo: Demo) -> None:
    assert resolve(demo.scope, Locator(control_type="Text", name=re.compile("^Rea"))) is demo.status
    matches = resolve_all(
        demo.scope, Locator(control_type="ListItem", name=re.compile(r"^Item [24]$"))
    )
    assert matches == [demo.items[1], demo.items[3]]
    with pytest.raises(ElementNotFoundError):
        resolve(demo.scope, Locator(control_type="Text", name=re.compile("^zzz")))


def test_regex_with_flags(demo: Demo) -> None:
    pattern = re.compile("ready", re.IGNORECASE)
    assert resolve(demo.scope, Locator(name=pattern, control_type="Text")) is demo.status


def test_within_chain(demo: Demo) -> None:
    panel_b = Locator(control_type="Group", name="Panel B")
    assert (
        resolve(demo.scope, Locator(control_type="Button", name="OK", within=panel_b)) is demo.ok_b
    )
    password = Locator(
        control_type="Edit",
        class_name="PasswordBox",
        within=Locator(control_type="Group", name="Credentials"),
    )
    assert resolve(demo.scope, password) is demo.password


def test_within_failure_wraps_inner_diagnostic(demo: Demo) -> None:
    locator = Locator(
        control_type="Button", name="OK", within=Locator(control_type="Group", name="Panel C")
    )
    with pytest.raises(ElementNotFoundError) as exc_info:
        resolve(demo.scope, locator)
    diagnostic = exc_info.value.diagnostic
    assert diagnostic.kind == "within_failed"
    assert str(exc_info.value) == (
        'Could not resolve Group[name="Panel C"] '
        '(needed by Group[name="Panel C"] > Button[name="OK"]): '
        'No element matches Group[name="Panel C"] in Window "WTK Demo" '
        '(closest: Group "Panel A" — name differs)'
    )
    assert diagnostic.within is not None
    assert diagnostic.within.kind == "not_found"
    assert diagnostic.locator == 'Group[name="Panel C"] > Button[name="OK"]'


def test_within_ambiguous_keeps_error_type(demo: Demo) -> None:
    locator = Locator(control_type="Edit", within=Locator(control_type="Group"))
    with pytest.raises(AmbiguousElementError) as exc_info:
        resolve(demo.scope, locator)
    assert exc_info.value.diagnostic.kind == "within_failed"


def test_searched_in_for_nested_failure(demo: Demo) -> None:
    locator = Locator(
        control_type="Button",
        name="Missing",
        within=Locator(control_type="Group", name="Panel A"),
    )
    with pytest.raises(ElementNotFoundError) as exc_info:
        resolve(demo.scope, locator)
    assert exc_info.value.diagnostic.searched_in == 'Group "Panel A" in Window "WTK Demo"'
    assert str(exc_info.value) == (
        'No element matches Button[name="Missing"] in Group "Panel A" in Window "WTK Demo" '
        '(closest: Button "OK" — name differs)'
    )


def test_depth_limits_the_search(demo: Demo) -> None:
    direct = Locator(control_type="Button", name="Sign in", depth=1)
    with pytest.raises(ElementNotFoundError):
        resolve(demo.scope, direct)
    assert (
        resolve(demo.scope, Locator(control_type="Button", name="Sign in", depth=2)) is demo.sign_in
    )
    assert (
        resolve(demo.scope, Locator(control_type="Group", name="Panel A", depth=1)) is demo.panel_a
    )


def test_query_all_document_order(demo: Demo) -> None:
    assert query_all(demo.window, Locator(control_type="Button")) == [
        demo.sign_in,
        demo.ok_a,
        demo.ok_b,
    ]


def test_resolve_all(demo: Demo) -> None:
    assert resolve_all(demo.scope, Locator(control_type="Button", name="OK")) == [
        demo.ok_a,
        demo.ok_b,
    ]
    assert resolve_all(demo.scope, Locator(automation_id="Nope")) == []
    within_missing = Locator(control_type="Button", within=Locator(control_type="Group", name="X"))
    with pytest.raises(ElementNotFoundError):
        resolve_all(demo.scope, within_missing)


def test_popup_fallback_finds_elements_outside_the_window(demo: Demo) -> None:
    assert resolve(demo.scope, Locator(control_type="MenuItem", name="Copy")) is demo.copy_item


def test_popup_fallback_skipped_for_explicit_window(demo: Demo) -> None:
    locator = Locator(
        control_type="MenuItem", name="Copy", window=WindowLocator(title="WTK Demo - Dialog")
    )
    with pytest.raises(ElementNotFoundError):
        resolve(demo.scope, locator)


def test_popup_fallback_skipped_for_later_links(demo: Demo) -> None:
    locator = Locator(
        control_type="MenuItem",
        name="Copy",
        within=Locator(control_type="Group", name="Panel A"),
    )
    with pytest.raises(ElementNotFoundError):
        resolve(demo.scope, locator)


def test_window_resolution(demo: Demo) -> None:
    assert resolve_window(demo.scope.app, None) is demo.window
    assert resolve_window(demo.scope.app, WindowLocator()) is demo.window
    assert resolve_window(demo.scope.app, WindowLocator(title="WTK Demo - Dialog")) is demo.dialog
    assert resolve_window(demo.scope.app, WindowLocator(title=re.compile("Dialog$"))) is demo.dialog
    assert (
        resolve_window(demo.scope.app, WindowLocator(class_name="Window", index=1)) is demo.dialog
    )


def test_window_not_found_message(demo: Demo) -> None:
    with pytest.raises(WindowNotFoundError) as exc_info:
        resolve_window(demo.scope.app, WindowLocator(title="Foo"))
    assert str(exc_info.value) == (
        'No window matches Window[title="Foo"] for DemoApp.exe '
        '(open windows: "WTK Demo", "WTK Demo - Dialog", <Popup>)'
    )
    assert exc_info.value.diagnostic.kind == "window_not_found"
    assert exc_info.value.diagnostic.searched_in == "Application DemoApp.exe"


def test_window_ambiguous(demo: Demo) -> None:
    with pytest.raises(AmbiguousElementError) as exc_info:
        resolve_window(demo.scope.app, WindowLocator(class_name="Window"))
    assert str(exc_info.value) == (
        '2 windows match Window[class="Window"] for DemoApp.exe; add index= to pick one'
    )


def test_window_index_out_of_range(demo: Demo) -> None:
    with pytest.raises(WindowNotFoundError):
        resolve_window(demo.scope.app, WindowLocator(class_name="Window", index=4))


def test_scope_window_and_locator_window_override(demo: Demo) -> None:
    scope = Scope(demo.app, WindowLocator(title="WTK Demo - Dialog"))  # type: ignore[arg-type]
    dialog_button = FakeElement("Button", "Save")
    demo.dialog.add(dialog_button)
    assert resolve(scope, Locator(control_type="Button", name="Save")) is dialog_button
    override = Locator(
        control_type="Button", name="OK", index=0, window=WindowLocator(title="WTK Demo")
    )
    assert resolve(scope, override) is demo.ok_a


def test_resolved_elements_are_live(demo: Demo) -> None:
    calls: list[str] = []

    class Tracking(FakeElement):
        def as_live(self) -> Any:
            calls.append(self.name)
            return self

    tracked = Tracking("Button", "Tracked")
    demo.window.add(tracked)
    assert resolve(demo.scope, Locator(control_type="Button", name="Tracked")) is tracked
    assert calls == ["Tracked"]


def test_elements_reached_twice_are_deduplicated(demo: Demo) -> None:
    class Twin(FakeElement):
        """A search that returns the same element twice, like WPF popup windows do."""

        def find_all(self, scope: Any, condition: Any = None, cached: bool = False) -> list[Any]:
            found = super().find_all(scope, condition, cached)
            return found + found

    twin_window = Twin("Window", "Twin", children=[FakeElement("Button", "Once")])
    scope = Scope(FakeApp([twin_window]))  # type: ignore[arg-type]
    assert len(resolve_all(scope, Locator(control_type="Button", name="Once"))) == 1
    assert resolve(scope, Locator(control_type="Button", name="Once")).name == "Once"
