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
        else "UI Automation call failed (0x80131505): The operation timed out"
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
