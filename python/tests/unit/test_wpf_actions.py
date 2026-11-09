from types import SimpleNamespace

import pytest

from wintestkit.backends import WpfElement
from wintestkit.engine import actions
from wintestkit.errors import ActionError, InspectorError, UIAError
from wintestkit.inspector.models import ObjectRef, TypeInfo


class Client:
    def __init__(self):
        self.calls = []
        self.values = {
            "FullName": "T",
            "supported_patterns": "",
            "is_password": False,
            "toggle_state": "Off",
            "is_selected": True,
            "expand_state": "Collapsed",
            "is_read_only": False,
            "value": "before",
            "document_text": "document",
        }
        self.error = None

    def read(self, object_id, generation, paths, *, deadline):
        return tuple(
            SimpleNamespace(value=SimpleNamespace(status="ok", scalar=self.values[p[0].name]))
            for p in paths
        ), "read"

    def release(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        if name.startswith("act_"):

            def action(ref, *args, **kwargs):
                if self.error:
                    raise self.error
                self.calls.append((name, *args))
                if name == "act_toggle":
                    self.values["toggle_state"] = (
                        "On" if self.values["toggle_state"] == "Off" else "Off"
                    )

            return action
        raise AttributeError(name)


@pytest.fixture
def target(monkeypatch):
    client = Client()
    ref = ObjectRef("s", "o", 1, TypeInfo("T", "T", "A", "T, A", ()), "d")
    el = WpfElement(client, ref, 42)
    monkeypatch.setattr(el, "as_uia", lambda: pytest.fail("unexpected UIA mapping"))
    return client, el


@pytest.mark.parametrize(
    ("pattern", "state", "expected", "verb"),
    [
        ("Invoke,Toggle", "Collapsed", "invoke", "act_invoke"),
        ("Toggle", "Collapsed", "toggle", "act_toggle"),
        ("SelectionItem", "Collapsed", "select", "act_select"),
        ("ExpandCollapse", "Collapsed", "expand_collapse", "act_expand"),
        ("ExpandCollapse", "Expanded", "expand_collapse", "act_collapse"),
    ],
)
def test_click_pattern_order(target, pattern, state, expected, verb):
    client, el = target
    client.values.update(supported_patterns=pattern, expand_state=state)
    assert actions.click(el) == expected
    assert client.calls == [(verb,)]


def test_grid_pattern_validation_uses_agent(target):
    from wintestkit.uia import patterns

    client, el = target
    client.values["supported_patterns"] = "Grid,Selection"
    assert patterns.has_pattern(el, "Grid")


def test_states_and_actions(target):
    client, el = target
    actions.set_checked(el, True)
    assert actions.is_checked(el)
    actions.toggle(el)
    assert not actions.is_checked(el)
    actions.select_self(el)
    assert actions.is_selected(el)
    actions.expand(el)
    actions.collapse(el)
    assert [call[0] for call in client.calls] == [
        "act_toggle",
        "act_toggle",
        "act_select",
        "act_expand",
        "act_collapse",
    ]


def test_value_and_document_reads(target):
    client, el = target
    client.values["supported_patterns"] = "Value,Text"
    assert actions.type_text(el, "new", clear=False) == "value"
    actions.clear(el)
    assert client.calls == [("act_set_value", "beforenew"), ("act_set_value", "")]
    assert actions.get_text(el) == "before"
    assert actions.get_value(el) == "before"
    client.values["supported_patterns"] = "Text"
    assert actions.get_text(el) == "document"


@pytest.mark.parametrize("status", ["unavailable", "redacted"])
def test_password_classification_unavailable_fails_closed(target, monkeypatch, status):
    client, el = target
    monkeypatch.setattr(
        client,
        "read",
        lambda *args, **kwargs: ([SimpleNamespace(value=SimpleNamespace(status=status))], "read"),
    )
    assert actions.is_password(el) is True


def test_password_classifier_caches_per_wpf_identity(target, monkeypatch):
    client, el = target
    classifier = actions.PasswordClassifier()
    assert classifier.is_password(el) is False
    monkeypatch.setattr(client, "read", lambda *args, **kwargs: pytest.fail("unexpected reread"))
    other_wrapper = WpfElement(client, el.ref, 42)
    assert classifier.is_password(other_wrapper) is False


def test_password_uses_keys_without_sending_value(target, monkeypatch, caplog):
    client, el = target
    client.values.update(supported_patterns="Value", is_password=True)
    keys = []
    monkeypatch.setattr(actions, "focus", lambda el: keys.append("focus"))
    monkeypatch.setattr(actions, "_wpf_keyboard_target", lambda el: None)
    monkeypatch.setattr(actions.input, "press", lambda text: keys.append(text))
    monkeypatch.setattr(actions.input, "type_text", lambda text: keys.append("typed"))
    assert actions.type_text(el, "private") == "keys"
    assert keys == ["focus", "Ctrl+A Delete", "typed"]
    assert client.calls == []
    assert "private" not in caplog.text


def test_selection_names_are_individual_reads(target):
    client, el = target
    client.values.update(supported_patterns="Selection", selection_count=2)
    client.values["selection_name_0"] = "a,b"
    client.values["selection_name_1"] = "c\nd"
    assert actions.selected_items(el) == ["a,b", "c\nd"]


@pytest.mark.parametrize("code", ["timeout", "objectStale"])
@pytest.mark.parametrize("read", [False, True])
def test_action_errors_map_consistently(target, code, read):
    client, el = target
    error = InspectorError("failure", code=code)
    if read:

        def fail(*args, **kwargs):
            raise error

        client.read = fail
    else:
        client.error = error
    with pytest.raises(UIAError) as exc:
        actions.is_checked(el) if read else actions.toggle(el)
    assert exc.value.element_gone == (code == "objectStale")
    assert str(exc.value) == (
        "The UI element is no longer available"
        if code == "objectStale"
        else (
            "The WPF inspector did not complete reading toggle_state within its deadline"
            if read
            else "The WPF inspector did not complete toggle within its deadline"
        )
    )


def test_deadline_propagates_in_polling_budget(target):
    from wintestkit.engine.managed import query_budget
    from wintestkit.errors import InspectorDeadlineError

    client, el = target
    error = InspectorDeadlineError("deadline", code="limitExceeded")
    client.error = error
    with query_budget(), pytest.raises(InspectorDeadlineError) as exc:
        actions.toggle(el)
    assert exc.value is error


@pytest.mark.parametrize("budgeted", [False, True])
@pytest.mark.parametrize("fail_on_check", [1, 2])
def test_ensure_visible_translates_state_deadlines(target, monkeypatch, budgeted, fail_on_check):
    from contextlib import nullcontext

    from wintestkit.engine.managed import query_budget
    from wintestkit.errors import InspectorDeadlineError

    _client, el = target
    error = InspectorDeadlineError("deadline", code="timeout")
    checks = 0

    def state():
        nonlocal checks
        checks += 1
        if checks == fail_on_check:
            raise error
        return SimpleNamespace(is_offscreen=True)

    monkeypatch.setattr(el, "as_live", state)
    context = query_budget() if budgeted else nullcontext()
    with context, pytest.raises(InspectorDeadlineError if budgeted else UIAError) as raised:
        actions.ensure_visible(el)
    if budgeted:
        assert raised.value is error
    else:
        assert "checking visibility" in str(raised.value)


def test_agent_errors_are_not_retried_via_uia(target, monkeypatch):
    client, el = target
    monkeypatch.setattr(actions, "_short", lambda el: "target")
    client.error = InspectorError("unsupported", code="actionUnsupported")
    with pytest.raises(ActionError, match="target does not support the Toggle pattern"):
        actions.toggle(el)
    client.error = InspectorError("stale", code="objectStale")
    with pytest.raises(UIAError) as exc:
        actions.toggle(el)
    assert exc.value.element_gone


@pytest.fixture
def mouse(target, monkeypatch):
    from wintestkit.inspector.models import Dpi, ElementState, Point, Rect

    client, el = target
    state = ElementState(
        el.ref,
        123,
        Rect(10, 20, 100, 40),
        Dpi(96, 96),
        True,
        False,
        False,
        True,
        False,
        True,
        (),
        click_point=Point(60, 40),
    )
    client.state_get = lambda *args, **kwargs: state
    monkeypatch.setattr(actions, "_short", lambda el: "target")
    monkeypatch.setattr(actions.time, "sleep", lambda _: None)
    monkeypatch.setattr(actions.win32, "bring_to_foreground", lambda hwnd: True)
    monkeypatch.setattr(actions.win32, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(actions.win32, "window_pid", lambda hwnd: 42)
    monkeypatch.setattr(actions.win32, "GetForegroundWindow", lambda: 123)
    monkeypatch.setattr(actions.win32, "WindowFromPoint", lambda point: 123)
    monkeypatch.setattr(actions.win32, "root_window", lambda hwnd: hwnd)
    events = []
    monkeypatch.setattr(actions.input, "click", lambda x, y, **kw: events.append((x, y, kw)))
    monkeypatch.setattr(actions.input, "move_mouse", lambda x, y: events.append((x, y)))
    return client, el, state, events


@pytest.mark.parametrize(
    "case", ["owner", "popup", "foreign", "activate", "denied", "hit", "popup_on_activate"]
)
def test_popup_mouse_safety(mouse, monkeypatch, case):
    _client, el, _state, events = mouse
    foreground = [200 if case != "popup" else 123]
    if case in ("activate", "denied", "popup_on_activate"):
        foreground[0] = 300
    activated = []

    def activate(hwnd):
        activated.append(hwnd)
        if case == "denied":
            return False
        if case == "popup_on_activate":
            foreground[0] = 123
            return False
        foreground[0] = hwnd
        return True

    monkeypatch.setattr(actions.win32, "window_owner", lambda hwnd: 200 if hwnd == 123 else 0)
    monkeypatch.setattr(
        actions.win32, "window_pid", lambda hwnd: 999 if case == "foreign" and hwnd == 123 else 42
    )
    monkeypatch.setattr(actions.win32, "GetForegroundWindow", lambda: foreground[0])
    monkeypatch.setattr(actions.win32, "bring_to_foreground", activate)
    monkeypatch.setattr(actions.win32, "root_window", lambda hwnd: 300 if case == "hit" else 123)
    if case in ("foreign", "denied", "hit"):
        with pytest.raises(ActionError, match="refusing global input"):
            actions._wpf_mouse_click(el)
        assert events == []
    else:
        actions._wpf_mouse_click(el)
        assert len(events) == 1
    assert activated == ([200] if case in ("activate", "denied", "popup_on_activate") else [])


def test_mouse_entry_points_and_pattern_fallback(mouse):
    _client, el, state, events = mouse
    assert actions.click(el, mode="mouse") == "mouse"
    assert actions.click(el, button="right") == "mouse"
    assert actions.click(el) == "mouse"
    actions.double_click(el)
    actions.right_click(el)
    actions.hover(el)
    assert events == [
        (60, 40, {"button": "left", "count": 1}),
        (60, 40, {"button": "right", "count": 1}),
        (60, 40, {"button": "left", "count": 1}),
        (60, 40, {"button": "left", "count": 2}),
        (60, 40, {"button": "right", "count": 1}),
        (60, 40),
    ]
    assert state.uia_runtime_id is None


@pytest.mark.parametrize("field", ["visible", "offscreen", "click_point", "bounds"])
def test_mouse_rejects_unsafe_state(mouse, field):
    from dataclasses import replace

    client, el, state, events = mouse
    value = {"visible": False, "offscreen": True, "click_point": None, "bounds": None}[field]
    client.state_get = lambda *a, **k: replace(state, **{field: value})
    with pytest.raises(ActionError):
        actions.click(el, mode="mouse")
    assert not events


def test_mouse_part_and_missing_part(mouse):
    from dataclasses import replace

    from wintestkit.inspector.models import PartGeometry, Rect

    client, el, state, events = mouse
    state = replace(state, parts=(PartGeometry("toggle", "expanderToggle", Rect(20, 25, 20, 10)),))
    client.state_get = lambda *a, **k: state
    actions._wpf_mouse_click(el, role="expanderToggle")
    assert events[0][:2] == (30, 30)
    with pytest.raises(ActionError):
        actions._wpf_mouse_click(el, role="comboDropDown")


def test_mouse_rejects_foreground_change(mouse, monkeypatch):
    _client, el, _state, events = mouse
    monkeypatch.setattr(actions.win32, "GetForegroundWindow", lambda: 999)
    with pytest.raises(ActionError, match="foreground"):
        actions.click(el, mode="mouse")
    assert not events


def test_mouse_rejects_unstable_bounds(mouse, monkeypatch):
    from dataclasses import replace

    from wintestkit.inspector.models import Rect

    client, el, state, events = mouse
    states = iter([state, state, state, replace(state, bounds=Rect(11, 20, 100, 40))])
    client.state_get = lambda *a, **k: next(states)

    def fail_wait(fn, *a, **k):
        assert fn() is None
        raise actions.waits.WaitTimeoutError("unstable")

    monkeypatch.setattr(actions.waits, "wait_until", fail_wait)
    with pytest.raises(ActionError, match="unstable"):
        actions.click(el, mode="mouse")
    assert not events


@pytest.mark.parametrize(
    "read_only,keys,password", [(True, False, False), (False, True, False), (False, False, True)]
)
def test_keyboard_entry_and_clear(target, monkeypatch, read_only, keys, password):
    client, el = target
    client.values.update(supported_patterns="Value", is_read_only=read_only, is_password=password)
    events = []
    monkeypatch.setattr(actions, "focus", lambda el: events.append("focus"))
    monkeypatch.setattr(actions, "_wpf_keyboard_target", lambda el: events.append("guard"))
    monkeypatch.setattr(actions.input, "press", lambda key: events.append(key))
    monkeypatch.setattr(actions.input, "type_text", lambda value: events.append(value))
    assert actions.type_text(el, "hello", clear=False, keys=keys) == "keys"
    assert events == ["focus", "guard", "Ctrl+End", "guard", "hello"]
    events.clear()
    if read_only or password:
        actions.clear(el)
        assert events == ["focus", "guard", "Ctrl+A Delete"]
    actions.press(el, "Enter")
    assert events[-3:] == ["focus", "guard", "Enter"]


def test_checked_does_not_converge(target, monkeypatch):
    _client, el = target
    monkeypatch.setattr(actions, "_short", lambda el: "target")
    monkeypatch.setattr(actions, "_wpf_act", lambda *args: None)
    with pytest.raises(ActionError, match="did not reach the On state"):
        actions.set_checked(el, True)


def test_get_text_name_and_password(target, monkeypatch):
    client, el = target
    monkeypatch.setattr(type(el), "name", property(lambda self: "label"))
    client.values.update(supported_patterns="Value,Text", is_password=True)
    assert actions.get_text(el) == "label"
    client.values.update(supported_patterns="", is_password=False)
    assert actions.get_text(el) == "label"


@pytest.mark.parametrize(
    "patterns,verb", [("ScrollItem", "act_scroll_into_view"), ("", "act_bring_into_view")]
)
def test_ensure_visible_uses_agent(target, monkeypatch, patterns, verb):
    client, el = target
    client.values["supported_patterns"] = patterns
    states = iter([True, False])
    monkeypatch.setattr(el, "as_live", lambda: SimpleNamespace(is_offscreen=next(states)))
    actions.ensure_visible(el)
    assert client.calls == [(verb,)]


@pytest.mark.parametrize(
    ("control_type", "role"),
    [("ComboBox", "comboDropDown"), ("TreeItem", "treeItemExpander"), ("Group", "expanderToggle")],
)
def test_expand_collapse_mouse_uses_part(target, monkeypatch, control_type, role):
    client, el = target
    monkeypatch.setattr(type(el), "control_type", property(lambda self: control_type))
    calls = []
    monkeypatch.setattr(actions, "_wpf_mouse_click", lambda el, **kw: calls.append(kw["role"]))
    actions.expand(el, mode="mouse")
    client.values["expand_state"] = "Expanded"
    actions.collapse(el, mode="mouse")
    assert calls == [role, role]


def test_mouse_uses_agent_point_for_clipped_element(mouse):
    from dataclasses import replace

    from wintestkit.inspector.models import Point

    client, el, state, events = mouse
    client.state_get = lambda *args, **kwargs: replace(
        state, clipped=True, click_point=Point(25, 35)
    )
    actions.click(el, mode="mouse")
    assert events[0][:2] == (25, 35)


def test_mouse_scrolls_offscreen_before_click(mouse):
    from dataclasses import replace

    client, el, state, events = mouse
    from itertools import chain, repeat

    states = chain([replace(state, offscreen=True)], repeat(state))
    client.state_get = lambda *args, **kwargs: next(states)
    actions.click(el, mode="mouse")
    assert client.calls == [("act_bring_into_view",)]
    assert events[0][:2] == (60, 40)


@pytest.mark.parametrize("failure", ["owner", "point_window", "point_owner"])
def test_mouse_rejects_foreign_window(mouse, monkeypatch, failure):
    _client, el, _state, events = mouse
    if failure == "owner":
        monkeypatch.setattr(actions.win32, "window_pid", lambda hwnd: 99)
    elif failure == "point_window":
        monkeypatch.setattr(actions.win32, "root_window", lambda hwnd: 999)
    else:
        monkeypatch.setattr(actions.win32, "WindowFromPoint", lambda point: 124)
        monkeypatch.setattr(actions.win32, "root_window", lambda hwnd: 123)
        monkeypatch.setattr(actions.win32, "window_pid", lambda hwnd: 99 if hwnd == 124 else 42)
    with pytest.raises(ActionError, match="refusing global input"):
        actions.click(el, mode="mouse")
    assert not events


def test_mouse_rejects_unstable_click_point(mouse, monkeypatch):
    from dataclasses import replace
    from itertools import chain, repeat

    from wintestkit.inspector.models import Point

    client, el, state, events = mouse
    changed = replace(state, click_point=Point(61, 40))
    states = chain([state, state, state, changed], repeat(changed))
    client.state_get = lambda *args, **kwargs: next(states)

    def fail_wait(fn, *args, **kwargs):
        assert fn() is None
        raise actions.waits.WaitTimeoutError("unstable")

    monkeypatch.setattr(actions.waits, "wait_until", fail_wait)
    with pytest.raises(ActionError, match="unstable"):
        actions.click(el, mode="mouse")
    assert not events


def test_deadline_outside_query_budget_is_honest(target):
    from wintestkit.errors import InspectorDeadlineError

    client, el = target
    client.error = InspectorDeadlineError("deadline", code="limitExceeded")
    with pytest.raises(UIAError, match="did not complete toggle within its deadline"):
        actions.toggle(el)


@pytest.fixture
def item_target(target, monkeypatch):
    from wintestkit.inspector.models import RealizeResult

    client, el = target
    client.values.update(
        control_type="List", supported_patterns="Selection,ScrollItem", item_count=2
    )
    client.values.update(item_name_0="Alpha", item_name_1="Beta")
    monkeypatch.setattr(actions, "_short", lambda el: "target")
    monkeypatch.setattr(
        actions, "_wpf_mouse_click", lambda el, **kw: client.calls.append(("click", kw.get("role")))
    )

    monkeypatch.setattr(actions, "_wpf_mouse_target", lambda el, role: (10, 20))
    monkeypatch.setattr(
        actions.input,
        "click",
        lambda *args, **kwargs: client.calls.append(("click", "gridRowHeader")),
    )

    def realize(ref, match, **kwargs):
        client.calls.append(("realize", match))
        if client.error:
            raise client.error
        return RealizeResult("performed", ref)

    client.act_realize_item = realize
    client.state_get = lambda *args, **kwargs: SimpleNamespace(
        visible=True, offscreen=False, click_point=object()
    )

    def action(name):
        def call(ref, **kwargs):
            client.calls.append((name,))
            if name == "act_expand":
                client.values["expand_state"] = "Expanded"
            elif name == "act_collapse":
                client.values["expand_state"] = "Collapsed"

        return call

    client.act_expand = action("act_expand")
    client.act_collapse = action("act_collapse")
    return client, el


@pytest.mark.parametrize("kind", ["List", "ComboBox", "DataGrid"])
@pytest.mark.parametrize("mode", ["pattern", "mouse"])
@pytest.mark.parametrize(
    "item", ["Alpha", __import__("re").compile("lPh", __import__("re").IGNORECASE), 1]
)
def test_wpf_select_items(item_target, monkeypatch, kind, mode, item):
    client, el = item_target
    client.values["control_type"] = kind
    if mode == "mouse" and kind == "ComboBox":

        def expand_mouse(el, *, expanded):
            client.calls.append(("part", "comboDropDown", expanded))
            client.values["expand_state"] = "Expanded" if expanded else "Collapsed"

        monkeypatch.setattr(actions, "_wpf_expand_collapse_mouse", expand_mouse)
    actions.select(el, item, mode=mode)
    calls = client.calls
    if mode == "mouse":
        assert ("click", "gridRowHeader" if kind == "DataGrid" else None) in calls
    match = next(call[1] for call in calls if call[0] == "realize")
    if isinstance(item, str):
        assert match.kind == "equals" and match.value == item
    elif isinstance(item, int):
        assert match.kind == "index" and match.index == item
    else:
        assert match.kind == "regex" and match.pattern == "lPh" and match.flags == ("ignoreCase",)
    assert [c[0] for c in calls] == (
        (
            ["act_expand"]
            if kind == "ComboBox" and mode == "pattern"
            else ["part"]
            if kind == "ComboBox"
            else []
        )
        + ["realize"]
        + (["act_scroll_into_view", "act_select"] if mode == "pattern" else ["click"])
        + (
            ["act_collapse"]
            if kind == "ComboBox" and mode == "pattern"
            else ["part"]
            if kind == "ComboBox"
            else []
        )
    )


def test_wpf_grid_mouse_falls_back_when_header_unsafe(item_target, monkeypatch):
    client, el = item_target
    client.values["control_type"] = "DataGrid"

    def unsafe(el, role):
        raise actions.ActionError("no safe row header")

    monkeypatch.setattr(actions, "_wpf_mouse_target", unsafe)
    actions.select(el, "Alpha", mode="mouse")
    assert [call[0] for call in client.calls] == ["realize", "act_select"]


def test_wpf_combo_mouse_waits_for_item_geometry(item_target, monkeypatch):
    client, el = item_target
    client.values["control_type"] = "ComboBox"
    states = iter(
        [
            SimpleNamespace(visible=False, offscreen=True, click_point=None),
            SimpleNamespace(visible=True, offscreen=False, click_point=object()),
        ]
    )
    client.state_get = lambda *args, **kwargs: next(states)

    def expand_mouse(el, *, expanded):
        client.values["expand_state"] = "Expanded" if expanded else "Collapsed"

    monkeypatch.setattr(actions, "_wpf_expand_collapse_mouse", expand_mouse)
    actions.select(el, "Alpha", mode="mouse")
    assert ("click", None) in client.calls


@pytest.mark.parametrize("mode", ["pattern", "mouse"])
def test_wpf_combo_failure_collapses(item_target, monkeypatch, mode):
    client, el = item_target
    client.values.update(control_type="ComboBox", item_count=7)
    for i in range(7):
        client.values[f"item_name_{i}"] = f"item{i}"
    client.error = InspectorError("missing", code="notFound")
    if mode == "mouse":

        def expand_mouse(el, *, expanded):
            client.calls.append(("part", expanded))
            client.values["expand_state"] = "Expanded" if expanded else "Collapsed"

        monkeypatch.setattr(actions, "_wpf_expand_collapse_mouse", expand_mouse)
    from wintestkit.errors import ElementNotFoundError

    with pytest.raises(ElementNotFoundError) as exc:
        actions.select(el, "missing", mode=mode)
    assert str(exc.value).startswith(
        'No item "missing" in target (available: "item0", "item1", "item2", "item3", "item4")'
    )
    assert client.values["expand_state"] == "Collapsed"
    assert client.calls[-1][0] == ("act_collapse" if mode == "pattern" else "part")


def test_wpf_negative_and_unsupported_regex(item_target):
    import re

    from wintestkit.errors import ElementNotFoundError, InvalidLocatorError

    client, el = item_target
    with pytest.raises(ElementNotFoundError):
        actions.select(el, -1)
    assert not client.calls
    with pytest.raises(InvalidLocatorError, match="Unsupported WPF item locator"):
        actions.select(el, re.compile("x", re.ASCII))


def test_wpf_item_name_reads_and_query(item_target, monkeypatch):
    from wintestkit.engine import wpf_resolve

    client, el = item_target
    assert actions.combo_item_names(el) == ["Alpha", "Beta"]
    calls = []

    def query(root, locator):
        calls.append(locator.control_type)
        return [el] if locator.control_type in ("ListItem", "TreeItem") else []

    monkeypatch.setattr(wpf_resolve, "query", query)
    client.values["name"] = "Realized"
    assert actions.listed_item_names(el) == ["Realized", "Realized"]
    assert calls == list(actions._ITEM_TYPES)
