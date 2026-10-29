"""S7 configuration layering and runtime attachment policy."""

import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from wintestkit import runtime
from wintestkit.config import load_config
from wintestkit.errors import ConfigError, InspectorUnavailableError
from wintestkit.inspector import probe, sessions
from wintestkit.inspector.models import ProcessIdentity

IDENTITY = ProcessIdentity(42, "2026-01-01T00:00:00Z")


def _identity(pid: int) -> ProcessIdentity:
    return IDENTITY


def _unexpected_probe(pid: int) -> Any:
    pytest.fail("unexpected probe")


def _unexpected_registry(**kwargs: Any) -> Any:
    pytest.fail("unexpected registry")


@pytest.fixture(autouse=True)
def reset_runtime() -> Any:
    runtime.reset()
    yield
    runtime.reset()


def test_configuration_layers_union_names_and_ignore_inspector_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.wintestkit.inspector]\nenabled = true\nattach = "manual"\n'
        'request_timeout = 1.5\nredact_names = ["account", "private"]\n',
        encoding="utf-8",
    )
    (tmp_path / "wintestkit.yaml").write_text(
        "inspector:\n  attach: on-demand\n  redact_names: [private, pin]\n", encoding="utf-8"
    )
    (tmp_path / "wintestkit.local.toml").write_text(
        '[tool.wintestkit.inspector]\nattach_timeout = 3\nredact_names = ["local"]\n',
        encoding="utf-8",
    )
    (tmp_path / "wintestkit.local.yaml").write_text(
        "inspector:\n  request_timeout: 0.5\n  redact_names: []\n", encoding="utf-8"
    )
    monkeypatch.setenv("WTK_INSPECTOR_ENABLED", "false")
    cfg = load_config(tmp_path, {"inspector.attach": "manual", "inspector.redact_names": ["cli"]})
    assert cfg.inspector.enabled and cfg.inspector.attach == "manual"
    assert cfg.inspector.attach_timeout == 3 and cfg.inspector.request_timeout == 0.5
    assert cfg.inspector.redact_names == ("account", "private", "pin", "local", "cli")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("enabled", 1),
        ("attach", "always"),
        ("attach_timeout", 10.1),
        ("attach_timeout", 0),
        ("request_timeout", 2.1),
        ("request_timeout", float("nan")),
        ("redact_names", [""]),
        ("redact_names", [1]),
        ("unknown", True),
    ],
)
def test_configuration_rejects_invalid_values(tmp_path: Path, key: str, value: Any) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path, {f"inspector.{key}": value})


def test_defaults_and_disabled_mode_never_probe_or_create_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = load_config(tmp_path)
    assert not cfg.inspector.enabled and cfg.inspector.attach == "manual"
    monkeypatch.setattr(probe, "current_identity", _unexpected_probe)
    monkeypatch.setattr(sessions, "SessionRegistry", _unexpected_registry)
    with (
        runtime.config_scope(cfg),
        pytest.raises(InspectorUnavailableError, match=r"inspector\.enabled"),
    ):
        runtime.managed_client_for(42, deadline=time.monotonic() + 1, target_hwnd=None)


def test_redaction_policy_change_replaces_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "SessionRegistry", FakeRegistry)
    cfg = load_config(tmp_path, {"inspector.enabled": True})
    with runtime.config_scope(cfg):
        original = runtime.inspector_sessions()
    cfg = replace(cfg, inspector=replace(cfg.inspector, redact_names=("account",)))
    with runtime.config_scope(cfg):
        runtime.require_managed()
        replacement = runtime.inspector_sessions()
        assert replacement is not original
        assert replacement.redact_names == ("account",)
        assert original.closed
        assert runtime.inspector_sessions() is replacement


@pytest.mark.parametrize("rules", ["private", [""], ["x" * 129], ["x"] * 33, [1], ["\ud800"]])
def test_invalid_redaction_config_does_not_echo_rules(tmp_path: Path, rules: object) -> None:
    with pytest.raises(ConfigError) as error:
        load_config(tmp_path, {"inspector.redact_names": rules})
    assert "private" not in str(error.value)


def test_additive_redaction_total_is_bounded(tmp_path: Path) -> None:
    (tmp_path / "wintestkit.yaml").write_text(
        "inspector:\n  redact_names: [" + ", ".join(f"rule{index}" for index in range(32)) + "]\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path, {"inspector.redact_names": ["one-more"]})


class FakeRegistry:
    instances: ClassVar[list["FakeRegistry"]] = []

    def __init__(self, *, request_timeout: float, redact_names: tuple[str, ...] = ()) -> None:
        self.timeout = request_timeout
        self.redact_names = redact_names
        self.attempts = 0
        self.fail = True
        self.client: Any = None
        self.closed = False
        self.__class__.instances.append(self)

    def get(self, identity: ProcessIdentity) -> Any:
        return self.client

    def attach(self, identity: ProcessIdentity, *, target_hwnd: int | None, deadline: float) -> Any:
        self.attempts += 1
        if self.fail:
            raise InspectorUnavailableError("injection failed", code="attachFailed")
        self.client = SimpleNamespace(session=SimpleNamespace(process=identity), close=lambda: None)
        return self.client

    def close_all(self) -> None:
        self.closed = True
        self.client = None


def test_manual_on_demand_failure_cache_explicit_retry_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeRegistry.instances.clear()
    monkeypatch.setattr(sessions, "SessionRegistry", FakeRegistry)
    monkeypatch.setattr(probe, "current_identity", _identity)
    cfg = load_config(tmp_path, {"inspector.enabled": True, "inspector.request_timeout": 0.25})
    with runtime.config_scope(cfg):
        with pytest.raises(InspectorUnavailableError, match="before using"):
            runtime.managed_client_for(42, deadline=time.monotonic() + 1, target_hwnd=None)
        registry = FakeRegistry.instances[-1]
        assert registry.timeout == 0.25 and registry.attempts == 0
    cfg = replace(cfg, inspector=replace(cfg.inspector, attach="on-demand"))
    with runtime.config_scope(cfg):
        for _ in range(2):
            with pytest.raises(InspectorUnavailableError, match="injection failed"):
                runtime.managed_client_for(42, deadline=time.monotonic() + 1, target_hwnd=None)
        assert registry.attempts == 1
        registry.fail = False
        client = runtime.attach_managed(IDENTITY, deadline=time.monotonic() + 1)
        assert runtime.inspector_attached_processes() == (IDENTITY,)
        assert (
            runtime.managed_client_for(42, deadline=time.monotonic() + 1, target_hwnd=None)
            is client
        )
        registry.client = None
        with pytest.raises(InspectorUnavailableError, match="explicitly attach"):
            runtime.managed_client_for(42, deadline=time.monotonic() + 1, target_hwnd=None)
        assert registry.attempts == 2
        runtime.close_inspector_sessions()
        assert registry.closed


def test_concurrent_on_demand_failure_is_attempted_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeRegistry.instances.clear()
    monkeypatch.setattr(sessions, "SessionRegistry", FakeRegistry)
    monkeypatch.setattr(probe, "current_identity", _identity)
    cfg = load_config(tmp_path, {"inspector.enabled": True, "inspector.attach": "on-demand"})
    runtime.set_config(cfg)
    barrier = threading.Barrier(5)
    failures: list[str] = []

    def worker() -> None:
        barrier.wait()
        try:
            runtime.managed_client_for(42, deadline=time.monotonic() + 2, target_hwnd=None)
        except InspectorUnavailableError as exc:
            failures.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert failures == ["attachFailed"] * 4
    assert FakeRegistry.instances[-1].attempts == 1


def test_timeout_change_does_not_clear_on_demand_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeRegistry.instances.clear()
    monkeypatch.setattr(sessions, "SessionRegistry", FakeRegistry)
    monkeypatch.setattr(probe, "current_identity", _identity)
    cfg = load_config(tmp_path, {"inspector.enabled": True, "inspector.attach": "on-demand"})
    with (
        runtime.config_scope(cfg),
        pytest.raises(InspectorUnavailableError, match="injection failed"),
    ):
        runtime.managed_client_for(42, deadline=time.monotonic() + 1, target_hwnd=None)
    old = FakeRegistry.instances[-1]
    cfg = replace(cfg, inspector=replace(cfg.inspector, request_timeout=0.25))
    with (
        runtime.config_scope(cfg),
        pytest.raises(InspectorUnavailableError, match="injection failed"),
    ):
        runtime.managed_client_for(42, deadline=time.monotonic() + 1, target_hwnd=None)
    assert old.closed and FakeRegistry.instances[-1].attempts == 0


def test_reset_cancels_an_inflight_attachment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, cancelled = threading.Event(), threading.Event()
    closed: list[bool] = []

    class BlockingRegistry(FakeRegistry):
        def attach(
            self, identity: ProcessIdentity, *, target_hwnd: int | None, deadline: float
        ) -> Any:
            started.set()
            assert cancelled.wait(5)
            return SimpleNamespace(close=lambda: closed.append(True))

        def close_all(self) -> None:
            cancelled.set()

    monkeypatch.setattr(sessions, "SessionRegistry", BlockingRegistry)
    monkeypatch.setattr(probe, "current_identity", _identity)
    cfg = load_config(tmp_path, {"inspector.enabled": True, "inspector.attach": "on-demand"})
    runtime.set_config(cfg)
    failures: list[str] = []

    def worker() -> None:
        try:
            runtime.managed_client_for(42, deadline=time.monotonic() + 5, target_hwnd=None)
        except InspectorUnavailableError as exc:
            failures.append(exc.code)

    thread = threading.Thread(target=worker)
    thread.start()
    assert started.wait(5)
    runtime.reset()
    thread.join(timeout=5)
    assert not thread.is_alive() and failures == ["cancelled"] and closed == [True]


def test_concurrent_wait_respects_its_own_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, finish = threading.Event(), threading.Event()

    class BlockingRegistry(FakeRegistry):
        def attach(
            self, identity: ProcessIdentity, *, target_hwnd: int | None, deadline: float
        ) -> Any:
            started.set()
            assert finish.wait(5)
            raise InspectorUnavailableError("failed", code="attachFailed")

    monkeypatch.setattr(sessions, "SessionRegistry", BlockingRegistry)
    monkeypatch.setattr(probe, "current_identity", _identity)
    runtime.set_config(
        load_config(tmp_path, {"inspector.enabled": True, "inspector.attach": "on-demand"})
    )

    def first() -> None:
        with pytest.raises(InspectorUnavailableError):
            runtime.managed_client_for(42, deadline=time.monotonic() + 5, target_hwnd=None)

    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert started.wait(5)
        start = time.monotonic()
        with pytest.raises(InspectorUnavailableError) as error:
            runtime.managed_client_for(42, deadline=start + 0.1, target_hwnd=None)
        assert error.value.code == "timeout" and time.monotonic() - start < 1
    finally:
        finish.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
