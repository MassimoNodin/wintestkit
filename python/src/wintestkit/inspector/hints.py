"""Shared remediation hints for inspector failures."""

from __future__ import annotations

_HINTS = {
    "blockedByPolicy": "Allow-list the WinTestKit payload directory in your security policy.",
    "unsupportedTarget": "Use a supported WPF runtime and architecture with native x64 Python.",
    "agentVersionMismatch": "Match the agent payload version and restart the application.",
    "payloadMismatch": "Reinstall the matching inspector payload.",
    "timeout": "Check agent readiness and security policy, then increase "
    "inspector.attach_timeout if needed.",
}


def inspector_error_hint(code: str) -> str:
    return _HINTS.get(
        code, "Check the inspector payload, target permissions, and application compatibility."
    )
