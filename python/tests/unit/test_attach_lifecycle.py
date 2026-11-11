"""Launch attachment policy and lifecycle with controlled process facts."""

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.config import load_config
from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector import probe
from wintestkit.inspector.models import ProcessIdentity


def test_launch_policy_and_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    identity = ProcessIdentity(42, "2026-01-01T00:00:00Z")
    window: Any = SimpleNamespace(process_id=42, native_window_handle=123)
    facts = SimpleNamespace(identity=identity, wpf_loaded=False)
    monkeypatch.setattr(probe, "identify", lambda pid: facts)
    calls: list[ProcessIdentity] = []

    def attach(identity: ProcessIdentity, **kwargs: Any) -> Any:
        calls.append(identity)
        return object()

    monkeypatch.setattr(runtime, "_attach_managed", attach)
    with runtime.config_scope(load_config(tmp_path)):
        assert runtime.attach_on_launch(window, deadline=time.monotonic() + 2) is None
        facts.wpf_loaded = True
        with runtime.step("app.start", "app", "app") as record:
            assert runtime.attach_on_launch(window, deadline=time.monotonic() + 2) == identity
        assert calls == [identity] and record.args["attach_seconds"] >= 0

        def blocked(identity: ProcessIdentity, **kwargs: Any) -> Any:
            raise InspectorUnavailableError("blocked", code="blockedByPolicy")

        monkeypatch.setattr(runtime, "_attach_managed", blocked)
        with pytest.raises(InspectorUnavailableError, match="wtk doctor --agent") as error:
            runtime.attach_on_launch(window, deadline=time.monotonic() + 2)
        assert error.value.code == "blockedByPolicy"
        assert "Allow-list" in str(error.value)

    for mode in ("manual", "on-demand"):
        with runtime.config_scope(load_config(tmp_path, {"inspector.attach": mode})):
            assert runtime.attach_on_launch(window, deadline=time.monotonic() + 2) is None


def test_replacement_and_close_release_identities(monkeypatch: pytest.MonkeyPatch) -> None:
    first = ProcessIdentity(42, "2026-01-01T00:00:00Z")
    second = ProcessIdentity(42, "2026-01-02T00:00:00Z")
    identities = iter((first, second))
    removed: list[ProcessIdentity] = []
    monkeypatch.setattr(runtime, "attach_on_launch", lambda *args, **kwargs: next(identities))
    monkeypatch.setattr(runtime, "detach_inspector", removed.append)
    monkeypatch.setattr(runtime, "detach_inspector_pids", lambda pids: None)
    app = App("fake", by_name=False)
    window: Any = object()
    app._attach_window(window, 1)  # pyright: ignore[reportPrivateUsage]
    app._attach_window(window, 1)  # pyright: ignore[reportPrivateUsage]
    assert removed == [first]
    app.close(timeout=0)
    assert removed == [first, second]
