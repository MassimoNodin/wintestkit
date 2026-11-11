"""Tests for the test-facing WPF write API."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from wintestkit import runtime
from wintestkit.backends.element import WpfElement
from wintestkit.errors import ActionError, WriteDeniedError
from wintestkit.inspector.models import WriteAudit
from wintestkit.model import BoundControl


@pytest.fixture
def setup_write(monkeypatch):
    audit = WriteAudit(
        "setProperty", "Shop.Views.OrderView", "key", "performed", "2026-11-11T00:00:00Z"
    )
    calls = []

    class Client:
        def members(self, object_id, generation, **kwargs):
            token = kwargs.get("page_token")
            calls.append(("members", token))
            if token is None:
                return SimpleNamespace(
                    items=[
                        SimpleNamespace(name="IsChecked", category="clrProperty", member_key="clr")
                    ],
                    next_token="next",
                )
            return SimpleNamespace(
                items=[
                    SimpleNamespace(
                        name="IsChecked", category="dependencyProperty", member_key="dp"
                    )
                ],
                next_token=None,
            )

        def write_set_property(self, ref, key, value, **kwargs):
            calls.append(("property", key, value))
            return audit

        def write_call(self, ref, key, arguments, **kwargs):
            calls.append(("call", key, arguments))
            return audit

    target = object.__new__(WpfElement)
    target.client = Client()
    target.ref = SimpleNamespace(
        object_id="id", generation=1, type=SimpleNamespace(full_name="Shop.Views.OrderView")
    )
    bound = object.__new__(BoundControl)
    monkeypatch.setattr(BoundControl, "resolve", lambda self: target)
    monkeypatch.setattr(
        runtime,
        "get_config",
        lambda: SimpleNamespace(
            backend="auto", inspector=SimpleNamespace(request_timeout=2), slow_mo_ms=0
        ),
    )

    @contextmanager
    def step(self, action):
        with runtime.step(action, "target", "locator") as record:
            yield record

    monkeypatch.setattr(BoundControl, "step", step)
    records = []
    unsubscribe = runtime.add_step_listener(records.append)
    yield bound, target, calls, records, audit
    unsubscribe()


def test_property_prefers_dependency_property_and_records_audit(setup_write):
    bound, _, calls, records, audit = setup_write
    bound.set_property("IsChecked", True)
    assert calls == [("members", None), ("members", "next"), ("property", "dp", True)]
    assert records[-1].to_dict()["audits"] == [audit.to_json()]


def test_method_overload_and_arguments(setup_write):
    bound, _, calls, records, _ = setup_write
    bound.call("Submit", "secret", True, 3, 1.5)
    assert calls[-1] == (
        "call",
        "Submit(System.String,System.Boolean,System.Int64,System.Double)",
        ("secret", True, 3, 1.5),
    )
    assert "secret" not in str(records[-1].to_dict())


def test_non_wpf_and_uia_rejected(setup_write, monkeypatch):
    bound, _, _, _, _ = setup_write
    monkeypatch.setattr(BoundControl, "resolve", lambda self: object())
    with pytest.raises(ActionError, match="WPF backend"):
        bound.call("Reset")
    monkeypatch.setattr(runtime, "get_config", lambda: SimpleNamespace(backend="uia"))
    with pytest.raises(ActionError, match="WPF backend"):
        bound.call("Reset")


def test_denial_records_audit_and_suggests_entry(setup_write, monkeypatch):
    bound, target, _, records, audit = setup_write

    def denied(*args, **kwargs):
        raise WriteDeniedError("denied", code="writeDenied", audit=audit)

    monkeypatch.setattr(target.client, "write_call", denied)
    with pytest.raises(WriteDeniedError, match=r"Shop.Views.OrderView.Submit\(System.String\)"):
        bound.call("Submit", "private")
    assert records[-1].audits == [audit.to_json()]
    assert "private" not in str(records[-1].to_dict())
