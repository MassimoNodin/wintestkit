from types import SimpleNamespace

import pytest

from wintestkit.engine.diagnose import Candidate, Diagnostic
from wintestkit.engine.locator import Locator
from wintestkit.errors import ElementNotFoundError, InspectorUnavailableError
from wintestkit.targets import resolve_bound
from wintestkit.uia.element import ElementInfo


def test_missing_has_part_and_three_candidates() -> None:
    candidates = tuple(
        Candidate(
            ElementInfo(
                name=f"Name{i}",
                automation_id=f"Id{i}",
                control_type="Button",
                class_name="",
                framework_id="",
                process_id=0,
                rect=None,
                is_enabled=True,
                is_offscreen=False,
                has_keyboard_focus=False,
                runtime_id=(),
            ),
            0,
            (),
        )
        for i in range(4)
    )
    diagnostic = Diagnostic("not_found", "nothing", "x", "window", 0, candidates)

    def fail(timeout: float) -> None:
        raise ElementNotFoundError(diagnostic)

    result = resolve_bound(SimpleNamespace(resolve=fail, locator=Locator(automation_id="Wrong")), 0)
    assert (
        result.message
        == "Not found: the window matched, but no descendant has automation_id 'Wrong'. Nearest: 'Id0' (Name0), 'Id1' (Name1), 'Id2' (Name2)."
    )


@pytest.mark.parametrize("code", ["inspectorDisabled", "alreadyAttached"])
def test_inspector_failure(code: str) -> None:
    def fail(timeout: float) -> None:
        raise InspectorUnavailableError("failure", code=code)

    result = resolve_bound(
        SimpleNamespace(resolve=fail, locator=Locator(where=(("clr:Name", "x"),))), 0
    )
    assert result.message and "`clr:Name`" in result.message
    assert result.hint and result.hint in result.message
    assert result.code == code
    if code == "inspectorDisabled":
        assert "which is disabled" in result.message
    else:
        assert "attach failed: alreadyAttached" in result.message
        print("ALREADY_ATTACHED:", result.message)
