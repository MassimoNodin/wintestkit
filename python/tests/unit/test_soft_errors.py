"""Soft errors: ``log.error``, soft checks and the plugin that fails the test when it ends."""

from collections.abc import Generator
from typing import Any

import pytest

from wintestkit import log, runtime, soft


@pytest.fixture(autouse=True)
def clean() -> Generator[None]:
    runtime.reset()
    soft.clear()
    yield
    soft.clear()
    runtime.reset()


# -- the collector --------------------------------------------------------------------------------


def test_errors_are_collected_in_order_and_drained() -> None:
    soft.record("first")
    soft.record("second", source="expect")
    assert [(e.message, e.source) for e in soft.errors()] == [
        ("first", "log.error"),
        ("second", "expect"),
    ]
    assert len(soft.errors()) == 2  # reading does not forget them
    assert [e.message for e in soft.drain()] == ["first", "second"]
    assert soft.errors() == []


def test_failure_message_lists_every_error_numbered() -> None:
    soft.record("Order 2 is missing")
    soft.record('expect(Orders.title).to_have_text("x") failed\n  Expected: x\n  Actual: y')
    message = soft.failure_message(soft.drain())
    assert message == (
        "2 errors recorded during the test:\n"
        "  1. Order 2 is missing\n"
        '  2. expect(Orders.title).to_have_text("x") failed\n'
        "       Expected: x\n"
        "       Actual: y"
    )
    assert soft.failure_message([soft.SoftError("only")]).startswith("1 error recorded")


def test_the_failure_carries_the_errors() -> None:
    soft.record("one")
    failure = soft.SoftErrorsFailure(soft.drain())
    assert isinstance(failure, AssertionError)
    assert [e.message for e in failure.errors] == ["one"]
    assert "1. one" in str(failure)


def test_continue_on_error_scopes_nest_and_restore() -> None:
    assert not soft.is_continuing()
    with soft.continue_on_error():
        assert soft.is_continuing()
        with soft.continue_on_error(False):
            assert not soft.is_continuing()
        assert soft.is_continuing()
    assert not soft.is_continuing()


def test_continue_on_error_restores_after_an_exception() -> None:
    with pytest.raises(RuntimeError), soft.continue_on_error():
        raise RuntimeError("x")
    assert not soft.is_continuing()


# -- log.error and log.checkpoint -----------------------------------------------------------------


def test_log_error_records_an_error_and_a_log_entry() -> None:
    runtime.begin_test("test_a")
    entries: list[dict[str, Any]] = []
    runtime.add_log_listener(entries.append)
    log.error("Order 2 is missing", order=2)
    log.message("carrying on")
    (error,) = soft.errors()
    assert (error.message, error.source) == ("Order 2 is missing", "log.error")
    assert [(e["level"], e["text"]) for e in entries] == [
        ("error", "Order 2 is missing"),
        ("info", "carrying on"),
    ]
    assert entries[0]["details"] == {"order": 2, "source": "log.error"}


def test_log_error_outside_a_test_is_still_remembered() -> None:
    log.error("no test yet")
    assert [e.message for e in soft.errors()] == ["no test yet"]


def test_log_error_does_not_raise() -> None:
    log.error("one")
    log.error("two")
    assert len(soft.errors()) == 2


def test_checkpoint_is_a_passed_step() -> None:
    steps: list[runtime.StepRecord] = []
    runtime.add_step_listener(steps.append)
    log.checkpoint("Order list verified", rows=3)
    (step,) = steps
    assert (step.action, step.target, step.status) == (
        "checkpoint",
        "Order list verified",
        "passed",
    )
    assert step.args == {"rows": 3}
    assert soft.errors() == []  # it is a pass, not an error


# -- the plugin -----------------------------------------------------------------------------------


def test_a_test_with_log_errors_fails_when_it_ends_listing_all_of_them(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(
        test_orders="""
        from wintestkit import log

        def test_orders():
            log.error("Order 2 is missing")
            print("still running after the first error")
            log.error("Order 3 has no total")

        def test_clean():
            pass
        """
    )
    result = pytester.runpytest("-s")
    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(
        [
            "*still running after the first error*",
            "*2 errors recorded during the test:*",
            "*1. Order 2 is missing*",
            "*2. Order 3 has no total*",
        ]
    )


def test_one_test_does_not_inherit_the_errors_of_the_previous_one(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(
        test_orders="""
        from wintestkit import log

        def test_a():
            log.error("only in a")

        def test_b():
            pass

        def test_c():
            log.error("only in c")
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1, failed=2)
    text = result.stdout.str()
    assert text.count("only in a") >= 1 and text.count("only in c") >= 1
    assert "1 error recorded" in text and "2 errors" not in text


def test_a_test_that_raises_keeps_its_exception_and_lists_the_soft_errors(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(
        test_orders="""
        from wintestkit import log

        def test_orders():
            log.error("Order 2 is missing")
            raise ValueError("the grid is gone")
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*ValueError: the grid is gone*", "*1. Order 2 is missing*"])


def test_errors_recorded_by_a_finalizer_fail_the_teardown(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        test_orders="""
        import pytest
        from wintestkit import log

        @pytest.fixture
        def orders():
            yield
            log.error("left an order open")

        def test_orders(orders):
            pass
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*1. left an order open*"])


def test_a_skipped_test_ignores_errors_recorded_before_the_skip(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        test_orders="""
        import pytest
        from wintestkit import log

        def test_orders():
            log.error("not a problem any more")
            pytest.skip("not today")
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(skipped=1)


def test_the_marker_makes_every_check_of_the_test_soft(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        test_orders="""
        import pytest
        from wintestkit import soft

        pytestmark = pytest.mark.wtk(soft=True)

        def test_soft():
            assert soft.is_continuing()

        @pytest.mark.wtk(soft=False)
        def test_hard():
            assert not soft.is_continuing()

        def test_after(request):
            assert soft.is_continuing()
        """
    )
    pytester.makepyprojecttoml("[tool.wintestkit]\n")
    result = pytester.runpytest()
    result.assert_outcomes(passed=3)


def test_checks_are_hard_without_the_marker(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        test_orders="""
        from wintestkit import soft

        def test_hard():
            assert not soft.is_continuing()
        """
    )
    pytester.runpytest().assert_outcomes(passed=1)


def test_soft_errors_appear_in_the_report_and_event_stream(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml("[tool.wintestkit]\ntimeout = 1\n")
    pytester.makepyfile(
        test_orders="""
        from wintestkit import log

        def test_orders():
            log.error("Order 2 is missing")
        """
    )
    result = pytester.runpytest("--wtk-no-html", "--wtk-screenshots=off", "--wtk-replay=off")
    result.assert_outcomes(failed=1)
    import json

    results = json.loads((pytester.path / "wtk-report" / "results.json").read_text("utf-8"))
    (test,) = results["tests"]
    assert test["outcome"] == "failed"
    assert [(e["level"], e["text"]) for e in test["log"]] == [("error", "Order 2 is missing")]
    assert "1. Order 2 is missing" in test["message"]
