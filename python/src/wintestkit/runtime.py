"""Process-wide runtime context: active configuration, current test and step events.

This is the only module with global mutable state.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Generator, Iterable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import PurePath
from types import TracebackType
from typing import Any, Literal, cast

from wintestkit.config import WtkConfig, load_config
from wintestkit.errors import ActionError

log = logging.getLogger("wintestkit.runtime")

REDACTED = "***"
_SECRET_NAME_PARTS = ("password", "secret", "token")

# Patched by unit tests.
_sleep: Callable[[float], None] = time.sleep


@dataclass
class StepRecord:
    """One action or assertion performed by a test (mirrors the protocol ``StepEvent``)."""

    seq: int
    action: str
    target: str
    locator: str
    args: dict[str, Any]
    start: float
    duration: float = 0.0
    status: Literal["passed", "failed"] = "passed"
    error: dict[str, Any] | None = None
    screenshot: str | None = None
    sensitive: bool = field(default=False, repr=False)

    def set_arguments(self, args: Mapping[str, Any], *, secret: bool) -> None:
        __tracebackhide__ = True
        self.sensitive = secret or any(
            part in key.lower() for key in args for part in _SECRET_NAME_PARTS
        )
        self.args = _redact(args, secret)

    def to_dict(self) -> dict[str, Any]:
        __tracebackhide__ = True
        data: dict[str, Any] = {
            "seq": self.seq,
            "action": self.action,
            "target": self.target,
            "locator": self.locator,
            "args": self.args,
            "start": self.start,
            "duration": self.duration,
            "status": self.status,
        }
        if self.error is not None:
            data["error"] = self.error
        if self.screenshot is not None:
            data["screenshot"] = self.screenshot
        return data


StepListener = Callable[[StepRecord], None]

_lock = threading.Lock()
_config: WtkConfig | None = None
_scoped_config: ContextVar[WtkConfig | None] = ContextVar("wtk_config", default=None)
_object_preview_context: ContextVar[bool] = ContextVar("wtk_object_preview_context", default=False)
_listeners: list[StepListener] = []
_current_test: str | None = None
_seq = 0


# -- configuration --------------------------------------------------------------------------------


def get_config() -> WtkConfig:
    """The active configuration (loaded from the working directory on first use)."""
    __tracebackhide__ = True
    scoped = _scoped_config.get()
    if scoped is not None:
        return scoped
    global _config
    with _lock:
        if _config is None:
            _config = load_config()
        return _config


def set_config(cfg: WtkConfig) -> None:
    __tracebackhide__ = True
    global _config
    with _lock:
        _config = cfg


@contextmanager
def config_scope(cfg: WtkConfig) -> Generator[None]:
    """Use a project's configuration for one CLI/editor operation without leaking it."""
    __tracebackhide__ = True
    token = _scoped_config.set(cfg)
    preview_token = _object_preview_context.set(False)
    try:
        yield
    finally:
        _object_preview_context.reset(preview_token)
        _scoped_config.reset(token)


@contextmanager
def object_preview_test_context() -> Generator[None]:
    """Permit synchronous object previews only inside an explicit test call scope."""
    __tracebackhide__ = True
    token = _object_preview_context.set(True)
    try:
        yield
    finally:
        _object_preview_context.reset(token)


def object_previews_active() -> bool:
    """Editor configuration scopes and ordinary resolution never authorize capture."""
    __tracebackhide__ = True
    return _object_preview_context.get() and get_config().object_previews


# -- listeners and test lifecycle -----------------------------------------------------------------


def add_step_listener(fn: StepListener) -> Callable[[], None]:
    """Register ``fn`` to receive every finished step; returns a function that removes it."""
    __tracebackhide__ = True
    with _lock:
        _listeners.append(fn)

    def remove() -> None:
        __tracebackhide__ = True
        with _lock:
            if fn in _listeners:
                _listeners.remove(fn)

    return remove


def begin_test(test_id: str) -> None:
    """Mark the start of a test and restart step numbering."""
    __tracebackhide__ = True
    global _current_test, _seq
    with _lock:
        _current_test = test_id
        _seq = 0


def end_test() -> None:
    __tracebackhide__ = True
    global _current_test
    with _lock:
        _current_test = None


def current_test() -> str | None:
    __tracebackhide__ = True
    with _lock:
        return _current_test


def reset() -> None:
    """Forget configuration, listeners and the current test (for tests of WinTestKit itself)."""
    __tracebackhide__ = True
    global _config, _current_test, _seq
    with _lock:
        _config = None
        _current_test = None
        _seq = 0
        _listeners.clear()


# -- steps ----------------------------------------------------------------------------------------


def _json_safe(value: Any) -> Any:
    __tracebackhide__ = True
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, re.Pattern):
        pattern = value  # type: ignore[assignment]
        flags = "".join(
            letter
            for bit, letter in ((re.IGNORECASE, "i"), (re.MULTILINE, "m"), (re.DOTALL, "s"))
            if pattern.flags & bit  # pyright: ignore[reportUnknownMemberType]
        )
        return f"/{pattern.pattern}/{flags}"  # pyright: ignore[reportUnknownMemberType]
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, list | tuple | set | frozenset):
        return [_json_safe(v) for v in cast("Iterable[Any]", value)]
    if isinstance(value, Mapping):
        mapping = cast("Mapping[Any, Any]", value)
        return {str(k): _json_safe(v) for k, v in mapping.items()}
    return repr(value)


def _redact(args: Mapping[str, Any] | None, secret: bool) -> dict[str, Any]:
    __tracebackhide__ = True
    safe: dict[str, Any] = {}
    for key, value in (args or {}).items():
        sensitive = secret or any(part in key.lower() for part in _SECRET_NAME_PARTS)
        safe[key] = REDACTED if sensitive else _json_safe(value)
    return safe


def _error_info(exc: BaseException) -> dict[str, Any]:
    __tracebackhide__ = True
    to_dict = getattr(exc, "to_dict", None)
    if callable(to_dict):
        try:
            info = to_dict()
            if isinstance(info, dict):
                return info  # pyright: ignore[reportUnknownVariableType]
        except Exception:
            log.debug("to_dict() of %r failed", exc, exc_info=True)
    return {"type": type(exc).__name__, "message": str(exc)}


def _notify(record: StepRecord) -> None:
    __tracebackhide__ = True
    with _lock:
        listeners = list(_listeners)
    for listener in listeners:
        try:
            listener(record)
        except Exception:
            log.exception("step listener %r failed", listener)


class _StepContext:
    """Context manager behind :func:`step`.

    A class rather than ``@contextmanager`` so that no ``contextlib`` frames appear in the
    tracebacks of failing tests (the frames of this module are hidden from pytest).
    """

    def __init__(self, record: StepRecord) -> None:
        __tracebackhide__ = True
        self._record = record
        self._started = 0.0

    def __enter__(self) -> StepRecord:
        __tracebackhide__ = True
        self._started = time.perf_counter()
        return self._record

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        __tracebackhide__ = True
        record = self._record
        record.duration = time.perf_counter() - self._started
        if exc is not None:
            record.status = "failed"
            if record.sensitive:
                record.args = _redact(record.args, True)
                safe_error = (
                    AssertionError("Sensitive assertion failed (details redacted)")
                    if isinstance(exc, AssertionError)
                    else ActionError("Sensitive action failed (details redacted)")
                )
                record.error = _error_info(safe_error)
                _notify(record)
                raise safe_error from None
            record.error = _error_info(exc)
            _notify(record)
            return
        _notify(record)
        slow_mo = get_config().slow_mo_ms
        if slow_mo > 0:
            _sleep(slow_mo / 1000)


def step(
    action: str,
    target: str,
    locator: str,
    args: Mapping[str, Any] | None = None,
    *,
    secret: bool = False,
) -> _StepContext:
    """Record one step. Arguments named like secrets (or all of them with ``secret=True``) are
    replaced by ``"***"`` before anything is stored or sent to listeners.
    Sensitive failures replace provider details with a safe action or assertion error.
    """
    __tracebackhide__ = True
    global _seq
    with _lock:
        _seq += 1
        seq = _seq
    return _StepContext(
        StepRecord(
            seq=seq,
            action=action,
            target=target,
            locator=locator,
            args=_redact(args, secret),
            start=time.time(),
            sensitive=secret
            or any(part in key.lower() for key in (args or {}) for part in _SECRET_NAME_PARTS),
        )
    )
