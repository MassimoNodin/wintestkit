"""Soft errors: failures that mark the test failed but let it carry on.

A suite that runs "on error: continue" wants to see every problem of a test, not only the first.
``log.error(...)`` records one, a soft check records one instead of raising, and
``continue_on_error()`` turns every ``expect`` assertion inside it into a soft one. The pytest
plugin fails the test when it ends, with all the errors listed (and in the report, one log entry
each)::

    from wintestkit import log, soft

    def test_orders(app):
        with soft.continue_on_error():
            expect(page.title).to_have_text("Orders")      # a wrong title does not stop the test
            expect(page.count).to_have_text("3")
        log.error("order 2 is missing")                      # the same, by hand

The marker ``@pytest.mark.wtk(soft=True)`` does that for a whole test or module.
"""

from __future__ import annotations

import threading
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

__all__ = [
    "SoftError",
    "SoftErrorsFailure",
    "clear",
    "continue_on_error",
    "drain",
    "errors",
    "failure_message",
    "is_continuing",
    "record",
]


@dataclass(frozen=True)
class SoftError:
    """One recorded error: its text and what recorded it (``log.error``, ``expect``, ``check``)."""

    message: str
    source: str = "log.error"


class SoftErrorsFailure(AssertionError):
    """Raised at the end of a test that recorded soft errors; ``errors`` lists them all."""

    def __init__(self, errors: Sequence[SoftError]) -> None:
        super().__init__(failure_message(errors))
        self.errors = tuple(errors)


_lock = threading.Lock()
_errors: list[SoftError] = []
_continuing: ContextVar[bool] = ContextVar("wtk_soft_continue", default=False)


def record(
    message: str, *, source: str = "log.error", details: Mapping[str, Any] | None = None
) -> SoftError:
    """Record an error that fails the test at its end and let the test continue.

    The error is also a log entry of the test, shown as an error in the report.
    """
    from wintestkit import log

    error = SoftError(message, source)
    with _lock:
        _errors.append(error)
    log.report_error(message, source, dict(details or {}))
    return error


def errors() -> list[SoftError]:
    """The errors recorded so far in this test."""
    with _lock:
        return list(_errors)


def drain() -> list[SoftError]:
    """Return the recorded errors and forget them."""
    with _lock:
        taken = list(_errors)
        _errors.clear()
    return taken


def clear() -> None:
    with _lock:
        _errors.clear()


def is_continuing() -> bool:
    """Whether ``expect`` assertions are soft here (inside ``continue_on_error()``)."""
    return _continuing.get()


@contextmanager
def continue_on_error(enabled: bool = True) -> Generator[None]:
    """Make the ``expect`` assertions and migration checks inside the block record their
    failure instead of raising, so the test continues and fails at its end."""
    token = _continuing.set(enabled)
    try:
        yield
    finally:
        _continuing.reset(token)


def failure_message(found: Sequence[SoftError]) -> str:
    """The text of the failure of a test with soft errors: every error, numbered."""
    count = len(found)
    lines = [f"{count} error{'s' if count != 1 else ''} recorded during the test:"]
    for number, error in enumerate(found, start=1):
        first, *rest = error.message.splitlines() or [""]
        lines.append(f"  {number}. {first}")
        lines.extend(f"     {line}" for line in rest)
    return "\n".join(lines)
