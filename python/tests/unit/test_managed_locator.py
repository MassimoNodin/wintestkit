"""S8 locator semantics with an in-memory UIA tree and typed managed responses."""

import re
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import runtime
from wintestkit.backends.element import WpfElement
from wintestkit.config import load_config
from wintestkit.engine import query
from wintestkit.engine.locator import Locator, WindowLocator
from wintestkit.engine.managed import ManagedCondition
from wintestkit.engine.properties import resolve_where
from wintestkit.engine.resolve import Scope, resolve_all, resolve_window
from wintestkit.errors import (
    ConfigError,
    InvalidLocatorError,
    WindowNotFoundError,
)


@pytest.fixture(autouse=True)
def setup(tmp_path):
    runtime.reset()
    runtime.set_config(load_config(tmp_path))
    yield
    runtime.reset()


@pytest.mark.parametrize("backend,framework", [("uia", "WPF"), ("auto", "Win32")])
@pytest.mark.parametrize(
    "key", ["clr:Value", "type:Is", "field:Value", "type:FullName", "dp:Asm|Owner::Value"]
)
def test_managed_keys_rejected_by_uia(monkeypatch, tmp_path, backend, framework, key):
    root = FakeElement("Window")
    root.framework_id = framework
    runtime.set_config(replace(load_config(tmp_path), backend=backend))
    with pytest.raises(
        InvalidLocatorError,
        match=rf"{key}.*backend: {backend}.*{framework}.*backend: auto.*WPF window",
    ):
        query.query_all(root, Locator(where=((key, "Example"),)))


@pytest.mark.parametrize("backend,framework", [("uia", "WPF"), ("auto", "Win32")])
def test_resolution_rejects_managed_without_attaching(monkeypatch, tmp_path, backend, framework):
    window = FakeElement("Window")
    window.framework_id = framework
    runtime.set_config(replace(load_config(tmp_path), backend=backend))
    monkeypatch.setattr(
        runtime, "managed_client_for", lambda *args, **kwargs: pytest.fail("attached")
    )
    with pytest.raises(InvalidLocatorError, match=rf"clr:Value.*backend: {backend}.*{framework}"):
        resolve_all(Scope(FakeApp([window])), Locator(where=(("clr:Value", "Example"),)))


def test_managed_window_selector_filters_before_index(monkeypatch, tmp_path):
    from wintestkit.engine import resolve as resolver

    runtime.set_config(replace(load_config(tmp_path), backend="auto"))
    first = FakeElement("Window", name="first")
    other = FakeElement("Window", name="native")
    other.framework_id = "Win32"
    last = FakeElement("Window", name="last")
    roots = {}
    for window in (first, last):
        root = Mock(spec=WpfElement)
        root.ref = SimpleNamespace(type=SimpleNamespace(full_name=f"Demo.{window.name}"))
        roots[id(window)] = root
    monkeypatch.setattr(resolver, "route", lambda window: roots[id(window)])
    monkeypatch.setattr(resolver, "matches_root", lambda root, conditions: True)
    app = FakeApp([first, other, last])
    selector = WindowLocator(where=(("type:Is", "Demo.Base"),), index=1)
    assert resolve_window(app, selector) is last
    monkeypatch.setattr(resolver, "matches_root", lambda root, conditions: root is roots[id(last)])
    assert resolve_window(app, replace(selector, index=None)) is last
    with pytest.raises(WindowNotFoundError, match=r"Demo.first.*Demo.last"):
        resolve_window(app, replace(selector, index=1))
    monkeypatch.setattr(resolver, "matches_root", lambda root, conditions: False)
    with pytest.raises(WindowNotFoundError, match="open windows"):
        resolve_window(app, replace(selector, index=None))


def test_managed_window_selector_uia_rejected_even_without_candidates(tmp_path):
    runtime.set_config(replace(load_config(tmp_path), backend="uia"))
    with pytest.raises(InvalidLocatorError, match=r"clr:Value.*backend: uia.*backend: auto"):
        resolve_window(FakeApp([]), WindowLocator(where=(("clr:Value", "Example"),)))


def test_managed_aliases_are_explicit_and_uia_aliases_unchanged(tmp_path):
    cfg = load_config(
        tmp_path, {"property_aliases": {"ClrFullClassName": "type:FullName", "Hint": "HelpText"}}
    )
    with runtime.config_scope(cfg):
        managed, uia = resolve_where(
            (("ClrFullClassName", "Demo.Control"), ("Hint", "help")), "owner"
        )
        assert isinstance(managed, ManagedCondition)
        assert managed.key == "type:FullName" and managed.alias == "ClrFullClassName"
        assert uia.spec.uia_name == "HelpText"
        with pytest.raises(InvalidLocatorError, match="twice"):
            resolve_where((("ClrFullClassName", "A"), ("type:FullName", "A")), "owner")
    with pytest.raises(ConfigError):
        load_config(tmp_path, {"property_aliases": {"A": "B", "B": "type:FullName"}})


@pytest.mark.parametrize(
    "key",
    [
        "clr:",
        "clr:A..B",
        r"clr:A\q",
        "clr:A[0]",
        "clr:A()",
        "field:*",
        "field:0",
        "dp:Asm|Owner::P/",
        "dp:Asm|Owner::P/Q//R",
        "type:Missing",
    ],
)
def test_invalid_paths_fail_at_declaration(key):
    with pytest.raises(InvalidLocatorError):
        Locator(where=((key, "value"),))


@pytest.mark.parametrize("value", [None, [], {}, object()])
def test_object_and_null_literals_are_rejected(value):
    with pytest.raises(InvalidLocatorError):
        Locator(where=(("clr:Value", value),))


def test_locator_serialization_preserves_namespaces_and_escapes():
    locator = Locator(
        where=(
            (r"clr:DataContext.A\.B", re.compile("value$", re.I)),
            (r"dp:Asm|Demo.Owner::P/A\/B", 42),
            ("field:Value", True),
        ),
        window=WindowLocator(where=(("type:FullName", "Demo.Window"),)),
    )
    assert Locator.from_dict(locator.to_dict()) == locator
    assert Locator.from_dict(locator.to_dict()).to_dict() == locator.to_dict()
