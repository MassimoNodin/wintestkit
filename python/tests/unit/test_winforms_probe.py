"""WinForms processes are recognised and accepted wherever a WPF process is."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from wintestkit import runtime
from wintestkit.config import load_config
from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector import probe, sessions
from wintestkit.inspector.models import ProcessFacts, ProcessIdentity

IDENTITY = ProcessIdentity(42, "2026-01-01T00:00:00Z")
CORE = r"C:\Program Files\dotnet\shared\Microsoft.NETCore.App\8.0.5\coreclr.dll"
FORMS = (
    r"C:\Program Files\dotnet\shared\Microsoft.WindowsDesktop.App\8.0.5\System.Windows.Forms.dll"
)
WPF = r"C:\Program Files\dotnet\shared\Microsoft.WindowsDesktop.App\8.0.5\PresentationFramework.dll"


@pytest.mark.parametrize(
    ("modules", "expected"),
    [
        ((CORE, FORMS), True),
        ((CORE, FORMS.lower()), True),
        ((CORE, FORMS.replace("Forms.dll", "Forms.ni.dll")), True),
        ((CORE, WPF), False),
        ((CORE, r"C:\app\System.Windows.Forms.Design.dll"), False),
        ((CORE,), False),
    ],
)
def test_winforms_flag_follows_the_loaded_modules(modules: tuple[str, ...], expected: bool) -> None:
    assert probe._winforms(modules) is expected  # pyright: ignore[reportPrivateUsage]


def test_the_wpf_flag_is_unchanged_by_winforms() -> None:
    assert probe._runtime((CORE, FORMS)) == ("net8", False)  # pyright: ignore[reportPrivateUsage]
    assert probe._runtime((CORE, FORMS, WPF)) == ("net8", True)  # pyright: ignore[reportPrivateUsage]


def test_identify_reports_both_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    modules = (CORE, FORMS)
    monkeypatch.setattr(probe, "_modules", lambda pid: modules)
    monkeypatch.setattr(probe, "_runtime", lambda found: ("net8", False))
    monkeypatch.setattr(probe, "_identity", lambda handle, pid: IDENTITY)
    monkeypatch.setattr(probe, "_security", lambda handle, pid: ("sid", "medium", 1))
    monkeypatch.setattr(probe, "_open", lambda pid: 1)
    kernel = SimpleNamespace(
        QueryFullProcessImageNameW=lambda handle, flags, buffer, size: _fill(buffer),
        IsWow64Process2=lambda handle, process, native: _machine(process, native),
        CloseHandle=lambda handle: 1,
    )
    monkeypatch.setattr(probe, "_libraries", lambda: (kernel, None))
    facts = probe.identify(42)
    assert facts.winforms_loaded is True and facts.wpf_loaded is False
    assert facts.runtime == "net8" and facts.architecture == "x64"


def _fill(buffer: Any) -> int:
    buffer.value = "app.exe"
    return 1


def _machine(process: Any, native: Any) -> int:
    process._obj.value = 0
    native._obj.value = 0x8664
    return 1


@pytest.mark.parametrize(
    ("wpf", "winforms", "accepted"),
    [(True, False, True), (False, True, True), (True, True, True), (False, False, False)],
)
def test_attach_accepts_a_process_with_either_ui(
    monkeypatch: pytest.MonkeyPatch, wpf: bool, winforms: bool, accepted: bool
) -> None:
    monkeypatch.setattr(probe, "current_security", lambda: ("sid", "medium", 1))
    monkeypatch.setattr(probe, "controller_supported", lambda: True)
    facts = ProcessFacts(IDENTITY, "app.exe", "x64", "net10", wpf, 1, "sid", "medium", winforms)
    if accepted:
        sessions._validate_facts(facts, IDENTITY)  # pyright: ignore[reportPrivateUsage]
    else:
        with pytest.raises(InspectorUnavailableError, match="WPF/WinForms"):
            sessions._validate_facts(facts, IDENTITY)  # pyright: ignore[reportPrivateUsage]


def test_a_winforms_process_defaults_to_no_winforms_for_older_callers() -> None:
    facts = ProcessFacts(IDENTITY, "app.exe", "x64", "net10", True, 1, "sid", "medium")
    assert facts.winforms_loaded is False


@pytest.mark.parametrize(
    ("wpf", "winforms", "attaches"),
    [(True, True, True), (False, True, False), (False, False, False)],
)
def test_launch_attaches_to_wpf_applications_only(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, wpf: bool, winforms: bool, attaches: bool
) -> None:
    import time

    facts = SimpleNamespace(identity=IDENTITY, wpf_loaded=wpf, winforms_loaded=winforms)
    monkeypatch.setattr(probe, "identify", lambda pid: facts)
    calls: list[ProcessIdentity] = []
    monkeypatch.setattr(runtime, "_attach_managed", lambda identity, **kw: calls.append(identity))  # pyright: ignore[reportPrivateUsage]
    window: Any = SimpleNamespace(process_id=42, native_window_handle=123)
    with runtime.config_scope(load_config(tmp_path)):
        result = runtime.attach_on_launch(window, deadline=time.monotonic() + 2)
    assert (result == IDENTITY) is attaches
    assert bool(calls) is attaches
