"""Shared remediation hints for inspector failures."""

from __future__ import annotations

_BUSY_HINT = "The application's UI thread is busy; values load automatically when it responds."

_HINTS = {
    "inspectorDisabled": "Set [tool.wintestkit.inspector] enabled = true in the project config.",
    "injectionFailed": "See %APPDATA%\\Snoop\\SnoopLog.txt and run `wtk doctor --agent`.",
    "injectionStalled": "Retry; if it keeps failing, restart the application. "
    "Security software may block injection.",
    "bootstrapRejected": "Retry the attachment; restart the application if it continues to fail.",
    "agentNotStarted": "Restart the application and retry; "
    "run `wtk doctor --agent` if it continues to fail.",
    "alreadyAttached": "Another WinTestKit session owns the agent for this process; "
    "close that session or restart the application.",
    "blockedByPolicy": "Allow-list the WinTestKit payload directory in your security policy.",
    "unsupportedTarget": "Use a supported WPF or WinForms runtime and architecture with "
    "native x64 Python.",
    "agentVersionMismatch": "Match the agent payload version and restart the application.",
    "payloadMismatch": "Reinstall the matching inspector payload.",
    "timeout": _BUSY_HINT,
    "dispatcherUnavailable": _BUSY_HINT,
    "busy": _BUSY_HINT,
}


def inspector_error_hint(code: str) -> str:
    return _HINTS.get(
        code, "Check the inspector payload, target permissions, and application compatibility."
    )
