"""Whether the current thread has already changed something in the application under test.

An action that fails because its element went away may be run again on a freshly resolved element,
but only if nothing it did before failing had an effect: typing the text twice or clicking twice is
worse than the failure. Code that causes an effect (user input, a UI Automation pattern call, an
inspector action or write that the agent may have run) calls :func:`mark`; a retry is safe only
while :func:`count` is what it was when the attempt started.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable

_state = threading.local()


def count() -> int:
    """How many effects this thread has caused so far."""
    return int(getattr(_state, "count", 0))


def mark() -> None:
    """Record that an effect may have happened."""
    _state.count = count() + 1


def unmark() -> None:
    """Take back a mark for a request the agent refused before it began (an ``objectStale``)."""
    _state.count = max(0, count() - 1)


def effect[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """Mark an effect after ``function`` returns: one that raised did not take effect."""

    @functools.wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        result = function(*args, **kwargs)
        mark()
        return result

    return wrapper
