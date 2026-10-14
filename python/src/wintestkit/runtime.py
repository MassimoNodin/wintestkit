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
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Literal, cast

from wintestkit.config import WtkConfig, load_config

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

    def to_dict(self) -> dict[str, Any]:
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
_listeners: list[StepListener] = []
_current_test: str | None = None
_seq = 0


# -- configuration --------------------------------------------------------------------------------


def get_config() -> WtkConfig:
    """The active configuration (loaded from the working directory on first use)."""
    global _config
    with _lock:
        if _config is None:
            _config = load_config()
        return _config


def set_config(cfg: WtkConfig) -> None:
    global _config
    with _lock:
        _config = cfg


# -- listeners and test lifecycle -----------------------------------------------------------------


def add_step_listener(fn: StepListener) -> Callable[[], None]:
    """Register ``fn`` to receive every finished step; returns a function that removes it."""
    with _lock:
        _listeners.append(fn)

    def remove() -> None:
        with _lock:
            if fn in _listeners:
                _listeners.remove(fn)

    return remove


def begin_test(test_id: str) -> None:
    """Mark the start of a test and restart step numbering."""
    global _current_test, _seq
    with _lock:
        _current_test = test_id
        _seq = 0


def end_test() -> None:
    global _current_test
    with _lock:
        _current_test = None


def current_test() -> str | None:
    with _lock:
        return _current_test


def reset() -> None:
    """Forget configuration, listeners and the current test (for tests of WinTestKit itself)."""
    global _config, _current_test, _seq
    with _lock:
        _config = None
        _current_test = None
        _seq = 0
        _listeners.clear()


# -- steps ----------------------------------------------------------------------------------------


def _json_safe(value: Any) -> Any:
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
    safe: dict[str, Any] = {}
    for key, value in (args or {}).items():
        sensitive = secret or any(part in key.lower() for part in _SECRET_NAME_PARTS)
        safe[key] = REDACTED if sensitive else _json_safe(value)
    return safe


def _error_info(exc: BaseException) -> dict[str, Any]:
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
    with _lock:
        listeners = list(_listeners)
    for listener in listeners:
        try:
            listener(record)
        except Exception:
            log.exception("step listener %r failed", listener)


@contextmanager
def step(
    action: str,
    target: str,
    locator: str,
    args: Mapping[str, Any] | None = None,
    *,
    secret: bool = False,
) -> Generator[StepRecord]:
    """Record one step. Arguments named like secrets (or all of them with ``secret=True``) are
    replaced by ``"***"`` before anything is stored or sent to listeners."""
    global _seq
    with _lock:
        _seq += 1
        seq = _seq
    record = StepRecord(
        seq=seq,
        action=action,
        target=target,
        locator=locator,
        args=_redact(args, secret),
        start=time.time(),
    )
    started = time.perf_counter()
    try:
        yield record
    except BaseException as exc:
        record.status = "failed"
        record.error = _error_info(exc)
        record.duration = time.perf_counter() - started
        _notify(record)
        raise
    record.duration = time.perf_counter() - started
    _notify(record)
    slow_mo = get_config().slow_mo_ms
    if slow_mo > 0:
        _sleep(slow_mo / 1000)
