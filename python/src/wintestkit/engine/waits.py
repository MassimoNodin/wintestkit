"""Polling waits with rich failure messages."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal

from wintestkit.errors import LocatorError, UIAError, WaitTimeoutError
from wintestkit.uia.element import UIAElement

POLL_INTERVAL = 0.1
STABLE_INTERVAL = 0.05

# Injectable for unit tests.
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep

State = Literal["attached", "detached", "visible", "hidden", "enabled", "disabled", "stable"]


def wait_until[T](
    fn: Callable[[], T | Literal[False] | None],
    timeout: float,
    *,
    description: str,
    interval: float = POLL_INTERVAL,
    retry_on: tuple[type[BaseException], ...] = (LocatorError, UIAError),
) -> T:
    """Call ``fn`` until it returns something other than ``None``/``False``.

    ``fn`` runs once immediately and then every ``interval`` seconds. Exceptions in ``retry_on``
    are remembered and retried; any other exception propagates. On timeout the last
    ``LocatorError`` is re-raised (with the wait time appended to its message) so the user sees
    the element diagnostic; otherwise ``WaitTimeoutError`` is raised. ``timeout == 0`` means a
    single attempt.
    """
    start = _clock()
    last_error: BaseException | None = None
    while True:
        try:
            result = fn()
        except retry_on as exc:
            last_error = exc
        else:
            if result is not None and result is not False:
                return result
            last_error = None
        waited = _clock() - start
        if waited >= timeout:
            break
        _sleep(min(interval, max(timeout - waited, 0.0)))
    if isinstance(last_error, LocatorError):
        suffix = f" (waited {timeout:.1f}s)"
        last_error.message += suffix
        last_error.args = (last_error.message,)
        raise last_error
    raise WaitTimeoutError(
        f"Timed out after {timeout:.1f}s waiting for {description}",
        last_error=last_error,
        waited=waited,
    )


def _attached(el: UIAElement | None) -> bool:
    if el is None:
        return False
    try:
        return el.is_alive()
    except UIAError:
        return False


def _visible(el: UIAElement | None) -> bool:
    if not _attached(el):
        return False
    assert el is not None
    try:
        rect = el.rect
        return not el.is_offscreen and rect is not None and not rect.is_empty()
    except UIAError:
        return False


def element_state_ok(el: UIAElement | None, state: State) -> bool:
    """Whether ``el`` is currently in ``state``."""
    if state == "attached":
        return _attached(el)
    if state == "detached":
        return not _attached(el)
    if state == "visible":
        return _visible(el)
    if state == "hidden":
        return not _visible(el)
    if not _attached(el):
        return False
    assert el is not None
    try:
        if state == "enabled":
            return el.is_enabled
        if state == "disabled":
            return not el.is_enabled
        first = el.rect
        _sleep(STABLE_INTERVAL)
        return first == el.rect
    except UIAError:
        return False


def wait_for_state(
    get: Callable[[], UIAElement | None],
    state: State,
    timeout: float,
    description: str,
) -> UIAElement | None:
    """Wait until the element returned by ``get`` is in ``state``; returns it (``None`` if gone).

    ``get`` normally resolves a locator. For ``detached`` and ``hidden`` a failed resolution counts
    as success, because a missing element is both.
    """
    missing_is_ok = state in ("detached", "hidden")

    def check() -> tuple[UIAElement | None] | None:
        try:
            el = get()
        except LocatorError:
            if not missing_is_ok:
                raise
            el = None
        return (el,) if element_state_ok(el, state) else None

    return wait_until(check, timeout, description=description)[0]
