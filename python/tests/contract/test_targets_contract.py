"""Actual serialized target results conform to the shared RPC contracts."""

from typing import Any

import pytest

from wintestkit.engine.diagnose import Diagnostic
from wintestkit.targets import CheckResult, ElementResult
from wintestkit.uia.element import ElementInfo, Rect


@pytest.mark.parametrize("status", ["found", "not_found", "ambiguous", "error"])
def test_target_result_contracts(validate: Any, status: str) -> None:
    info = ElementInfo(
        "", "OK", "Button", "Button", "WPF", 1, Rect(0, 0, 10, 10), True, False, False, "1.2"
    )
    diagnostic = Diagnostic("not_found", "missing", "Button", "Demo", 0)
    result = ElementResult(
        status,
        0.125,
        element=info if status == "found" else None,
        diagnostic=diagnostic if status in ("not_found", "ambiguous") else None,
        message="resolved",
    )
    validate("rpc.schema.json", "ElementResult", result.to_dict())
    validate("rpc.schema.json", "ElementCheckResult", result.to_dict())
    checked = CheckResult(
        status,
        result.duration_ms,
        element=result.element,
        diagnostic=result.diagnostic,
        message=result.message,
        qualname="Main.ok",
        locator="Button",
    )
    validate("rpc.schema.json", "CheckResult", checked.to_dict())
    validate("rpc.schema.json", "PageCheckResult", {"results": [checked.to_dict()]})
