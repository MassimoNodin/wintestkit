"""Pytest reports attach mode and identities without starting an inspector itself."""

import pytest


def test_pytest_header_and_attachment_summary(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(
        '[tool.wintestkit.inspector]\nenabled = true\nattach = "on-demand"\n'
    )
    pytester.makepyfile(
        """
        from wintestkit import runtime
        from wintestkit.inspector.models import ProcessIdentity
        def test_recorded_identity():
            identity = ProcessIdentity(1234, '2026-01-01T00:00:00Z')
            runtime._inspector_attached.add(identity)
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider", "--wtk-no-report")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(
        [
            "*WinTestKit managed inspector: on-demand*",
            "*WinTestKit inspector attached: PID 1234 (2026-01-01T00:00:00.0000000Z)*",
        ]
    )


def test_pytest_disabled_does_not_print_inspector_report(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml("[tool.wintestkit]\n")
    pytester.makepyfile("def test_x(): pass")
    result = pytester.runpytest("-p", "no:cacheprovider", "--wtk-no-report")
    result.assert_outcomes(passed=1)
    assert "WinTestKit managed inspector:" not in result.stdout.str()
    assert "WinTestKit inspector attached:" not in result.stdout.str()
