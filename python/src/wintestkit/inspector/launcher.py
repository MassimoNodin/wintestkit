"""Invoke the fixed, matching-bitness loader without exposing bootstrap secrets."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector.models import ProcessIdentity

_POLICY_ERRORS = {225, 577, 1260, 1655}
_POLICY_EXITS = {0xC0000428, 0xC0000603, 0xC0000361, 1260, 577}


def log_tail() -> str:
    """Read only the end of the launcher log; diagnostics must never mask failure."""
    try:
        root = os.environ.get("APPDATA")
        if not root:
            return ""
        with (Path(root) / "Snoop" / "SnoopLog.txt").open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 65536))
            lines = stream.read().decode("utf-8", errors="replace").splitlines()
        return next((line.strip()[:300] for line in reversed(lines) if line.strip()), "")
    except OSError:
        return ""


def launch(
    launcher: Path, agent: Path, identity: ProcessIdentity, settings_file: Path
) -> subprocess.Popen[Any]:
    arguments = [
        str(launcher),
        "--targetPID",
        str(identity.pid),
        "--assembly",
        str(agent),
        "--className",
        "WinTestKit.Inspector.Agent.EntryPoint",
        "--methodName",
        "Start",
        "--settingsFile",
        str(settings_file),
    ]
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    try:
        return subprocess.Popen(
            arguments,
            cwd=str(launcher.parent),
            shell=False,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startup,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError as error:
        code = "blockedByPolicy" if error.winerror in _POLICY_ERRORS else "attachFailed"
        message = f"Inspector launcher {launcher.name} could not be started"
        raise InspectorUnavailableError(message, code=code) from error


def policy_failure(process: subprocess.Popen[Any], launcher: Path) -> None:
    result = process.poll()
    if result is not None and result & 0xFFFFFFFF in _POLICY_EXITS:
        raise InspectorUnavailableError(
            f"Windows policy blocked {launcher.name}", code="blockedByPolicy"
        )


def close_launcher(process: subprocess.Popen[Any]) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
