"""Unit tests for the environment doctor with patched probes."""

from pathlib import Path

import pytest

from wintestkit import doctor
from wintestkit.config import load_config
from wintestkit.doctor import Check, has_failures, run_checks
from wintestkit.errors import ConfigError
from wintestkit.uia import win32


@pytest.fixture(autouse=True)
def healthy_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_windows_build", lambda: 26200)
    monkeypatch.setattr(doctor, "_session_id", lambda: 1)
    monkeypatch.setattr(doctor, "_input_desktop_name", lambda: "Default")
    monkeypatch.setattr(doctor, "_is_remote_session", lambda: False)
    monkeypatch.setattr(doctor, "_uia_error", lambda: None)
    monkeypatch.setattr(doctor, "_monitor_scales", lambda: [1.25])
    monkeypatch.setattr(doctor, "_comtypes_cache", lambda: ("C:/cache", True))
    monkeypatch.setattr(doctor, "_app_pids", lambda cfg: (None, []))


def by_id(checks: list[Check]) -> dict[str, Check]:
    return {c.id: c for c in checks}


def config_with_app(tmp_path: Path, app_exists: bool = True) -> doctor.WtkConfig:
    exe = tmp_path / "App.exe"
    if app_exists:
        exe.write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        f'[tool.wintestkit]\nlaunch = "attach"\n[tool.wintestkit.app]\npath = "{exe.as_posix()}"\n',
        encoding="utf-8",
    )
    return load_config(tmp_path)


def test_all_checks_ok_on_a_healthy_machine(tmp_path: Path) -> None:
    cfg = config_with_app(tmp_path)
    checks = by_id(run_checks(cfg))
    assert [c for c in checks.values() if c.status == "fail"] == []
    assert checks["platform"].status == "ok"
    assert checks["python"].status == "ok"
    assert checks["dpi"].detail == "125% on the primary monitor"
    assert checks["config"].status == "ok"
    assert checks["app_path"].status == "ok"
    assert checks["comtypes_cache"].status == "ok"
    assert list(checks) == [
        "platform",
        "python",
        "interactive_session",
        "desktop_unlocked",
        "remote_session",
        "uia",
        "dpi",
        "config",
        "app_path",
        "app_running",
        "elevation",
        "comtypes_cache",
    ]
    assert not has_failures(list(checks.values()))


def test_quick_runs_only_the_pre_run_checks(tmp_path: Path) -> None:
    assert [c.id for c in run_checks(None, quick=True)] == [
        "interactive_session",
        "desktop_unlocked",
        "uia",
    ]


@pytest.mark.parametrize(
    ("build", "status"), [(None, "fail"), (17134, "fail"), (17763, "ok"), (22631, "ok")]
)
def test_platform(monkeypatch: pytest.MonkeyPatch, build: int | None, status: str) -> None:
    monkeypatch.setattr(doctor, "_windows_build", lambda: build)
    assert by_id(run_checks(None))["platform"].status == status


def test_python_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.sys, "version_info", (3, 11, 9, "final", 0))
    check = by_id(run_checks(None))["python"]
    assert check.status == "fail"
    assert "3.11.9" in check.detail


def test_service_session_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_session_id", lambda: 0)
    check = by_id(run_checks(None))["interactive_session"]
    assert check.status == "fail"
    assert "session 0" in check.detail
    assert check.hint


def test_locked_or_secure_desktop_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_input_desktop_name", lambda: None)
    locked = by_id(run_checks(None))["desktop_unlocked"]
    assert locked.status == "fail"
    assert "locked" in locked.detail
    monkeypatch.setattr(doctor, "_input_desktop_name", lambda: "Winlogon")
    secure = by_id(run_checks(None))["desktop_unlocked"]
    assert secure.status == "fail"
    assert "Winlogon" in secure.detail
    monkeypatch.setattr(doctor, "_input_desktop_name", lambda: "default")
    assert by_id(run_checks(None))["desktop_unlocked"].status == "ok"


def test_remote_session_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_is_remote_session", lambda: True)
    check = by_id(run_checks(None))["remote_session"]
    assert check.status == "warn"
    assert "tscon" in (check.hint or "")


def test_uia_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_uia_error", lambda: "CoCreateInstance failed")
    check = by_id(run_checks(None))["uia"]
    assert check.status == "fail"
    assert "CoCreateInstance failed" in check.detail


def test_dpi_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_monitor_scales", lambda: [1.0, 1.5])
    mixed = by_id(run_checks(None))["dpi"]
    assert mixed.status == "warn"
    assert "100%, 150%" in mixed.detail
    monkeypatch.setattr(doctor, "_monitor_scales", lambda: [])
    assert by_id(run_checks(None))["dpi"].status == "warn"
    monkeypatch.setattr(doctor, "_monitor_scales", lambda: [1.0, 1.0])
    assert by_id(run_checks(None))["dpi"].status == "ok"

    def broken() -> list[float]:
        raise OSError("no shcore")

    monkeypatch.setattr(doctor, "_monitor_scales", broken)
    assert by_id(run_checks(None))["dpi"].status == "warn"


def test_config_variants(tmp_path: Path) -> None:
    missing = by_id(run_checks(load_config(tmp_path)))["config"]
    assert missing.status == "warn"
    assert "wtk init" in (missing.hint or "")
    broken = by_id(
        run_checks(None, config_error=ConfigError("tool.wintestkit.launch: bad", key="launch"))
    )["config"]
    assert broken.status == "fail"
    assert "tool.wintestkit.launch" in broken.detail
    assert by_id(run_checks(None))["config"].status == "warn"


def test_app_path_variants(tmp_path: Path) -> None:
    assert by_id(run_checks(None))["app_path"].status == "skip"
    assert by_id(run_checks(load_config(tmp_path)))["app_path"].status == "skip"
    missing = by_id(run_checks(config_with_app(tmp_path, app_exists=False)))["app_path"]
    assert missing.status == "fail"
    assert "does not exist" in missing.detail


def test_app_running_variants(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = config_with_app(tmp_path)
    monkeypatch.setattr(doctor, "_app_pids", lambda c: ("App.exe", []))
    stopped = by_id(run_checks(cfg))["app_running"]
    assert stopped.status == "warn"
    assert "not running" in stopped.detail
    monkeypatch.setattr(doctor, "_app_pids", lambda c: ("App.exe", [10, 20]))
    running = by_id(run_checks(cfg))["app_running"]
    assert running.status == "ok"
    assert running.detail == "App.exe (pid 10, 20)"
    assert by_id(run_checks(None))["app_running"].status in {"skip", "ok", "warn"}


def test_elevation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = config_with_app(tmp_path)
    monkeypatch.setattr(doctor, "_app_pids", lambda c: ("App.exe", [42]))
    monkeypatch.setattr(win32, "current_process_is_elevated", lambda: False)

    monkeypatch.setattr(win32, "process_is_elevated", lambda pid: True)
    elevated_app = by_id(run_checks(cfg))["elevation"]
    assert elevated_app.status == "fail"
    assert "administrator" in (elevated_app.hint or "")

    monkeypatch.setattr(win32, "process_is_elevated", lambda pid: None)
    denied = by_id(run_checks(cfg))["elevation"]
    assert denied.status == "fail"
    assert "access denied" in denied.detail

    monkeypatch.setattr(win32, "process_is_elevated", lambda pid: False)
    assert by_id(run_checks(cfg))["elevation"].status == "ok"

    monkeypatch.setattr(win32, "current_process_is_elevated", lambda: True)
    monkeypatch.setattr(win32, "process_is_elevated", lambda pid: True)
    assert by_id(run_checks(cfg))["elevation"].status == "ok"

    monkeypatch.setattr(doctor, "_app_pids", lambda c: ("App.exe", []))
    assert by_id(run_checks(cfg))["elevation"].status == "skip"


def test_comtypes_cache_not_writable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_comtypes_cache", lambda: ("C:/ro", False))
    check = by_id(run_checks(None))["comtypes_cache"]
    assert check.status == "warn"
    assert "C:/ro" in check.detail


def test_a_crashing_probe_becomes_a_failed_check(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode() -> int:
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(doctor, "_session_id", explode)
    checks = by_id(run_checks(None))
    assert checks["interactive_session"].status == "fail"
    assert "probe exploded" in checks["interactive_session"].detail
    assert checks["uia"].status == "ok"  # the others still ran


def test_to_dict_omits_missing_hints() -> None:
    assert Check("x", "X", "ok", "fine").to_dict() == {
        "id": "x",
        "title": "X",
        "status": "ok",
        "detail": "fine",
    }
    assert Check("x", "X", "fail", "bad", "fix it").to_dict()["hint"] == "fix it"


def test_real_probes_run_on_this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke test of the unpatched probes (they only read system state)."""
    monkeypatch.undo()  # drop the autouse patches: use the real probes
    results = run_checks(None, quick=False)
    assert {c.id for c in results} >= {"platform", "python", "dpi"}
    assert by_id(results)["platform"].status == "ok"
    assert by_id(results)["python"].status == "ok"
    assert by_id(results)["interactive_session"].status == "ok"
