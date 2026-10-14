# pyright: basic
"""Environment checks: is this machine and session able to run UI tests?"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from wintestkit.config import WtkConfig
from wintestkit.errors import ConfigError

Status = Literal["ok", "warn", "fail", "skip"]

MIN_WINDOWS_BUILD = 17763  # Windows 10 1809
DESKTOP_SWITCHDESKTOP = 0x0100
UOI_NAME = 2
SM_REMOTESESSION = 0x1000
QUICK_CHECKS = ("interactive_session", "desktop_unlocked", "uia")


@dataclass(frozen=True)
class Check:
    """The outcome of one environment check."""

    id: str
    title: str
    status: Status
    detail: str
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
        }
        if self.hint is not None:
            data["hint"] = self.hint
        return data


# -- probes (module level so unit tests can replace them) ---------------------------------------


def _windows_build() -> int | None:
    if sys.platform != "win32":
        return None
    return int(sys.getwindowsversion().build)  # type: ignore[attr-defined]


def _session_id() -> int | None:
    from wintestkit.uia import win32

    session = wintypes.DWORD(0)
    if not win32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        return None
    return int(session.value)


def _input_desktop_name() -> str | None:
    """Name of the desktop receiving input, ``None`` when it cannot be opened (locked)."""
    from wintestkit.uia import win32

    desktop = win32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not desktop:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD(0)
        if not win32.GetUserObjectInformationW(
            desktop, UOI_NAME, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)
        ):
            return None
        return buffer.value
    finally:
        win32.CloseDesktop(desktop)


def _is_remote_session() -> bool:
    from wintestkit.uia import win32

    return bool(win32.GetSystemMetrics(SM_REMOTESESSION))


def _uia_error() -> str | None:
    """``None`` if UI Automation works, otherwise the reason it does not."""
    try:
        from wintestkit.uia import com

        com.get_uia().GetRootElement()
    except Exception as exc:
        return str(exc) or type(exc).__name__
    return None


def _monitor_scales() -> list[float]:
    """Scale factor (1.0 = 96 dpi) of every monitor."""
    scales: list[float] = []
    user32 = ctypes.WinDLL("user32")
    shcore = ctypes.WinDLL("shcore")
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
    )

    def callback(monitor: Any, hdc: Any, rect: Any, data: Any) -> bool:
        dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
        if shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
            scales.append(dpi_x.value / 96)
        return True

    user32.EnumDisplayMonitors(None, None, callback_type(callback), 0)
    return scales


def _comtypes_cache() -> tuple[str, bool]:
    """Directory where comtypes writes generated wrappers and whether it is writable."""
    import comtypes.gen

    directory = Path(next(iter(comtypes.gen.__path__)))
    return str(directory), os.access(directory, os.W_OK)


# -- the checks -----------------------------------------------------------------------------------


def _check_platform() -> Check:
    build = _windows_build()
    title = "Windows 10 1809 or later"
    if build is None:
        return Check(
            "platform",
            title,
            "fail",
            f"running on {sys.platform}",
            "WinTestKit only runs on Windows.",
        )
    if build < MIN_WINDOWS_BUILD:
        return Check(
            "platform",
            title,
            "fail",
            f"Windows build {build}",
            "Update to Windows 10 1809 or later.",
        )
    return Check("platform", title, "ok", f"Windows build {build}")


def _check_python() -> Check:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info < (3, 12):  # noqa: UP036 - the check exists for misconfigured installs
        return Check(
            "python", "Python 3.12 or later", "fail", f"Python {version}", "Install Python 3.12+."
        )
    return Check("python", "Python 3.12 or later", "ok", f"Python {version}")


def _check_interactive_session() -> Check:
    title = "Interactive desktop session"
    session = _session_id()
    if session == 0:
        return Check(
            "interactive_session",
            title,
            "fail",
            "running in session 0 (a service session without a desktop)",
            "Run the tests from a logged-in user session, not from a service or scheduled task "
            "that runs whether or not the user is logged on.",
        )
    return Check(
        "interactive_session",
        title,
        "ok",
        f"session {session}" if session is not None else "session unknown",
    )


def _check_desktop_unlocked() -> Check:
    title = "Desktop is unlocked"
    name = _input_desktop_name()
    if name is None:
        return Check(
            "desktop_unlocked",
            title,
            "fail",
            "the input desktop cannot be opened (the screen is locked or a secure prompt is open)",
            "Unlock the workstation, keep the screen on and dismiss any UAC prompt.",
        )
    if name.lower() != "default":
        return Check(
            "desktop_unlocked",
            title,
            "fail",
            f"the active desktop is {name!r}, not 'Default'",
            "Unlock the workstation and dismiss any UAC prompt.",
        )
    return Check("desktop_unlocked", title, "ok", "the Default desktop is active")


def _check_remote_session() -> Check:
    title = "Local session"
    if _is_remote_session():
        return Check(
            "remote_session",
            title,
            "warn",
            "running in a Remote Desktop session",
            "Minimizing or disconnecting the RDP window breaks UI tests; disconnect with "
            "`tscon <id> /dest:console` instead.",
        )
    return Check("remote_session", title, "ok", "not a remote session")


def _check_uia() -> Check:
    title = "UI Automation is available"
    error = _uia_error()
    if error is not None:
        return Check(
            "uia",
            title,
            "fail",
            f"could not create the UI Automation client: {error}",
            "Make sure comtypes is installed and the session is interactive and unlocked.",
        )
    return Check("uia", title, "ok", "the UI Automation client works")


def _check_dpi() -> Check:
    title = "Display scaling"
    try:
        scales = _monitor_scales()
    except OSError as exc:
        return Check("dpi", title, "warn", f"could not read monitor scaling: {exc}")
    if not scales:
        return Check("dpi", title, "warn", "no monitors found")
    primary = round(scales[0] * 100)
    if len({round(s * 100) for s in scales}) > 1:
        listed = ", ".join(f"{round(s * 100)}%" for s in scales)
        return Check(
            "dpi",
            title,
            "warn",
            f"{primary}% on the primary monitor; monitors differ ({listed})",
            "Mixed scaling is supported, but use one scale for the most reproducible screenshots.",
        )
    return Check("dpi", title, "ok", f"{primary}% on the primary monitor")


def _check_config(cfg: WtkConfig | None, error: ConfigError | None) -> Check:
    title = "WinTestKit configuration"
    if error is not None:
        return Check(
            "config", title, "fail", str(error), "Fix [tool.wintestkit] in pyproject.toml."
        )
    if cfg is None or not cfg.found:
        return Check(
            "config",
            title,
            "warn",
            "no [tool.wintestkit] table found",
            "Run `wtk init` or add a [tool.wintestkit] table to pyproject.toml.",
        )
    return Check("config", title, "ok", f"project root {cfg.root}")


def _check_app_path(cfg: WtkConfig | None) -> Check:
    title = "Application executable"
    if cfg is None or cfg.app is None or cfg.app.path is None:
        return Check("app_path", title, "skip", "no application path configured")
    if not cfg.app.path.is_file():
        return Check(
            "app_path",
            title,
            "fail",
            f"{cfg.app.path} does not exist",
            "Fix `path` in [tool.wintestkit.app] or build the application.",
        )
    return Check("app_path", title, "ok", str(cfg.app.path))


def _app_pids(cfg: WtkConfig | None) -> tuple[str | None, list[int]]:
    if cfg is None or cfg.app is None:
        return None, []
    try:
        name = cfg.app.process_name
    except ConfigError:
        return None, []
    from wintestkit.uia import win32

    return name, win32.pids_by_name(name)


def _check_app_running(cfg: WtkConfig | None) -> Check:
    title = "Application is running"
    name, pids = _app_pids(cfg)
    if name is None:
        return Check("app_running", title, "skip", "no application configured")
    if not pids:
        return Check(
            "app_running",
            title,
            "warn",
            f"{name} is not running",
            "WinTestKit starts it for `launch = per-session/per-test`; start it yourself to "
            "use `attach` or to highlight elements from the editor.",
        )
    return Check("app_running", title, "ok", f"{name} (pid {', '.join(str(p) for p in pids)})")


def _check_elevation(cfg: WtkConfig | None) -> Check:
    title = "Privilege level matches the application"
    name, pids = _app_pids(cfg)
    if name is None or not pids:
        return Check("elevation", title, "skip", "the application is not running")
    from wintestkit.uia import win32

    mine = win32.current_process_is_elevated()
    if mine:
        return Check("elevation", title, "ok", "WinTestKit runs elevated")
    for pid in pids:
        elevated = win32.process_is_elevated(pid)
        if elevated is None or elevated:
            reason = "access denied" if elevated is None else "elevated"
            return Check(
                "elevation",
                title,
                "fail",
                f"{name} (pid {pid}) is {reason} but WinTestKit is not",
                "Run your terminal or VS Code as administrator: Windows blocks input and UI "
                "Automation calls from a lower-privileged process.",
            )
    return Check("elevation", title, "ok", "neither WinTestKit nor the application is elevated")


def _check_comtypes_cache() -> Check:
    title = "comtypes cache is writable"
    try:
        directory, writable = _comtypes_cache()
    except ImportError as exc:
        return Check("comtypes_cache", title, "warn", f"comtypes is not importable: {exc}")
    if not writable:
        return Check(
            "comtypes_cache",
            title,
            "warn",
            f"{directory} is not writable",
            "comtypes generates wrappers there on first use; install into a writable "
            "environment or the first run may fail or be slow.",
        )
    return Check("comtypes_cache", title, "ok", directory)


def run_checks(
    cfg: WtkConfig | None,
    *,
    quick: bool = False,
    config_error: ConfigError | None = None,
) -> list[Check]:
    """Run the environment checks. ``quick`` runs only those needed before a test run."""
    checks: list[Check] = []
    runners = [
        ("platform", _check_platform),
        ("python", _check_python),
        ("interactive_session", _check_interactive_session),
        ("desktop_unlocked", _check_desktop_unlocked),
        ("remote_session", _check_remote_session),
        ("uia", _check_uia),
        ("dpi", _check_dpi),
        ("config", lambda: _check_config(cfg, config_error)),
        ("app_path", lambda: _check_app_path(cfg)),
        ("app_running", lambda: _check_app_running(cfg)),
        ("elevation", lambda: _check_elevation(cfg)),
        ("comtypes_cache", _check_comtypes_cache),
    ]
    for check_id, runner in runners:
        if quick and check_id not in QUICK_CHECKS:
            continue
        try:
            checks.append(runner())
        except Exception as exc:
            checks.append(Check(check_id, check_id, "fail", f"the check itself failed: {exc}"))
    return checks


def has_failures(checks: list[Check]) -> bool:
    return any(c.status == "fail" for c in checks)
