from dataclasses import replace
from types import SimpleNamespace

import pytest

from wintestkit import doctor
from wintestkit.app import App
from wintestkit.config import AppConfig, load_config
from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector import probe, sessions
from wintestkit.inspector.hints import inspector_error_hint
from wintestkit.uia import win32


@pytest.fixture
def setup_agent(tmp_path, monkeypatch):
    cfg = replace(load_config(tmp_path), app=AppConfig(path=tmp_path / "app.exe"))
    cfg = replace(cfg, inspector=replace(cfg.inspector, enabled=True))
    monkeypatch.setattr(doctor, "_app_pids", lambda cfg: ("app.exe", [123]))
    facts = SimpleNamespace(
        wpf_loaded=True,
        winforms_loaded=False,
        identity=SimpleNamespace(pid=123),
        runtime="net10",
        architecture="x64",
    )
    monkeypatch.setattr(probe, "identify", lambda pid: facts)
    state = SimpleNamespace(agent_version="1.2", architecture="x64", features=("query", "state"))
    registry = SimpleNamespace(
        attach=lambda *args, **kwargs: SimpleNamespace(session=state), close_all=lambda: None
    )
    monkeypatch.setattr(sessions, "SessionRegistry", lambda **kwargs: registry)
    return cfg, facts, registry


def test_not_running(setup_agent, monkeypatch):
    cfg, _, _ = setup_agent
    monkeypatch.setattr(doctor, "_app_pids", lambda cfg: ("app.exe", []))
    check = doctor._check_wpf_agent(cfg)
    assert check.status == "skip" and "--agent" in check.hint


def test_non_wpf(setup_agent):
    cfg, facts, _ = setup_agent
    facts.wpf_loaded = False
    assert "not a WPF or WinForms application" in doctor._check_wpf_agent(cfg).detail


def test_ok_and_closed(setup_agent):
    cfg, _, registry = setup_agent
    closed = []
    registry.close_all = lambda: closed.append(True)
    check = doctor._check_wpf_agent(cfg)
    assert check.status == "ok"
    assert all(
        value in check.detail for value in ("1.2", "net10.0-windows", "x64", "query", "state")
    )
    assert closed == [True]


@pytest.mark.parametrize(
    "code,hint",
    [
        ("blockedByPolicy", "Allow-list"),
        ("unsupportedTarget", "x64 Python"),
        ("agentVersionMismatch", "version"),
        ("payloadMismatch", "payload"),
        ("timeout", "inspector request did not complete"),
        ("attachFailed", "permissions"),
    ],
)
def test_errors_close(setup_agent, code, hint):
    cfg, _, registry = setup_agent
    closed = []

    def fail(*args, **kwargs):
        raise InspectorUnavailableError("failure", code=code)

    registry.attach = fail
    registry.close_all = lambda: closed.append(True)
    check = doctor._check_wpf_agent(cfg)
    assert check.status == "fail" and code in check.detail and hint in check.hint
    assert closed == [True]


def test_config_skips(setup_agent):
    cfg, _, _ = setup_agent
    assert doctor._check_wpf_agent(replace(cfg, backend="uia")).detail == "backend is uia"
    assert (
        "disabled"
        in doctor._check_wpf_agent(
            replace(cfg, inspector=replace(cfg.inspector, enabled=False))
        ).detail
    )


def test_existing_agent_is_ok_without_detaching(setup_agent):
    cfg, _, registry = setup_agent
    closed = []

    def fail(*args, **kwargs):
        raise InspectorUnavailableError("An inspector is already attached", code="alreadyAttached")

    registry.attach = fail
    registry.close_all = lambda: closed.append(True)
    check = doctor._check_wpf_agent(cfg, launch=True)
    assert check.status == "ok"
    assert "agent already attached to PID 123" in check.detail
    assert "another WinTestKit session" in check.detail
    assert "runtime=net10" in check.detail and "architecture=x64" in check.detail
    assert closed == [True]  # Only the empty diagnostic registry is closed.


def test_already_attached_hint():
    hint = inspector_error_hint("alreadyAttached")
    assert "Another WinTestKit session owns the agent" in hint
    assert "close that session or restart the application" in hint


def test_quick_never_attaches(setup_agent, monkeypatch):
    cfg, _, _ = setup_agent
    monkeypatch.setattr(doctor, "_check_wpf_agent", lambda *args, **kwargs: pytest.fail("attached"))
    assert "wpf_agent" not in [check.id for check in doctor.run_checks(cfg, quick=True, agent=True)]


def test_launch_owned_and_close(setup_agent, monkeypatch):
    cfg, _, _ = setup_agent
    monkeypatch.setattr(doctor, "_app_pids", lambda cfg: ("app.exe", []))
    events = []
    process = SimpleNamespace(
        poll=lambda: None,
        terminate=lambda: events.append("terminate"),
        wait=lambda **kwargs: events.append("wait"),
    )
    app = SimpleNamespace(pids=[123], _popen=process)

    def launch(*args, **kwargs):
        assert kwargs["owned_only"] is True
        events.append("launch")
        return app

    monkeypatch.setattr(App, "launch", launch)
    monkeypatch.setattr(win32, "top_level_windows", lambda pids: [1])
    assert doctor._check_wpf_agent(cfg, launch=True).status == "ok"
    assert events == ["launch", "terminate", "wait"]


def test_launch_failure(setup_agent, monkeypatch):
    cfg, _, _ = setup_agent
    monkeypatch.setattr(doctor, "_app_pids", lambda cfg: ("app.exe", []))

    def fail(*args, **kwargs):
        raise RuntimeError("did not show a window")

    monkeypatch.setattr(App, "launch", fail)
    check = doctor._check_wpf_agent(cfg, launch=True)
    assert check.status == "fail" and "window" in check.detail


def test_launched_app_already_attached_fails(setup_agent, monkeypatch):
    cfg, _, registry = setup_agent
    monkeypatch.setattr(doctor, "_app_pids", lambda cfg: ("app.exe", []))
    process = SimpleNamespace(poll=lambda: None, terminate=lambda: None, wait=lambda **kwargs: None)
    monkeypatch.setattr(
        App, "launch", lambda *args, **kwargs: SimpleNamespace(pids=[123], _popen=process)
    )
    monkeypatch.setattr(win32, "top_level_windows", lambda pids: [1])

    def fail(*args, **kwargs):
        raise InspectorUnavailableError("An inspector is already attached", code="alreadyAttached")

    registry.attach = fail
    check = doctor._check_wpf_agent(cfg, launch=True)
    assert check.status == "fail" and "alreadyAttached" in check.detail
    assert check.hint == inspector_error_hint("alreadyAttached")
