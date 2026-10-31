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
from typing import TYPE_CHECKING, Any, Literal, cast

from wintestkit.config import WtkConfig, load_config
from wintestkit.errors import ActionError

if TYPE_CHECKING:
    from wintestkit.inspector.client import InspectorClient
    from wintestkit.inspector.models import ProcessIdentity
    from wintestkit.inspector.sessions import SessionRegistry
    from wintestkit.uia.element import UIAElement

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
    backend: Literal["uia", "wpf"] | None = None
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
        if self.backend is not None:
            data["backend"] = self.backend
        if self.error is not None:
            data["error"] = self.error
        if self.screenshot is not None:
            data["screenshot"] = self.screenshot
        return data


_current_step: ContextVar[StepRecord | None] = ContextVar("wtk_step", default=None)


def record_backend(element: object) -> None:
    __tracebackhide__ = True
    from wintestkit.backends.element import WpfElement

    record = _current_step.get()
    if record is not None:
        record.backend = "wpf" if isinstance(element, WpfElement) else "uia"


StepListener = Callable[[StepRecord], None]

_lock = threading.Lock()
_config: WtkConfig | None = None
_scoped_config: ContextVar[WtkConfig | None] = ContextVar("wtk_config", default=None)
_listeners: list[StepListener] = []
_current_test: str | None = None
_seq = 0
_inspector_registry: SessionRegistry | None = None
_inspector_request_timeout: float | None = None
_inspector_redact_names: tuple[str, ...] | None = None
_inspector_failures: dict[ProcessIdentity, Exception] = {}
_inspector_attempted: set[ProcessIdentity] = set()
_inspector_attached: set[ProcessIdentity] = set()
_inspector_identity_locks: dict[ProcessIdentity, threading.Lock] = {}
_inspector_epoch = 0
_inspector_lock = threading.RLock()


def inspector_sessions() -> SessionRegistry:
    """Return the lazily constructed process-wide inspector registry."""
    __tracebackhide__ = True
    global \
        _inspector_registry, \
        _inspector_request_timeout, \
        _inspector_redact_names, \
        _inspector_epoch
    config = get_config().inspector
    timeout, names = config.request_timeout, config.redact_names
    old = None
    with _inspector_lock:
        if (
            _inspector_registry is None
            or _inspector_request_timeout != timeout
            or _inspector_redact_names != names
        ):
            from wintestkit.inspector.sessions import SessionRegistry

            old = _inspector_registry
            policy_changed = _inspector_redact_names != names
            _inspector_registry = SessionRegistry(request_timeout=timeout, redact_names=names)
            _inspector_request_timeout = timeout
            _inspector_redact_names = names
            _inspector_epoch += 1
            if policy_changed:
                _inspector_failures.clear()
                _inspector_attempted.clear()
        registry = _inspector_registry
    if old is not None:
        old.close_all()
    return registry


def require_managed(*, values: bool = True) -> None:
    """Check authorization before managed inspection."""
    __tracebackhide__ = True
    from wintestkit.errors import InspectorUnavailableError

    config = get_config().inspector
    if not config.enabled:
        raise InspectorUnavailableError(
            "Set inspector.enabled to true to use managed inspection", code="notAttached"
        )


def attach_managed(
    identity: ProcessIdentity, *, deadline: float, target_hwnd: int | None = None
) -> InspectorClient:
    """Explicitly attach or retry a process after a previous on-demand failure."""
    __tracebackhide__ = True
    return _attach_managed(identity, deadline=deadline, target_hwnd=target_hwnd, explicit=True)


def _attach_managed(
    identity: ProcessIdentity, *, deadline: float, target_hwnd: int | None, explicit: bool
) -> InspectorClient:
    __tracebackhide__ = True
    from wintestkit.errors import InspectorUnavailableError

    require_managed()
    config = get_config().inspector
    registry = inspector_sessions()
    with _inspector_lock:
        lock = _inspector_identity_locks.setdefault(identity, threading.Lock())
    if not lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
        raise InspectorUnavailableError("Inspector readiness deadline expired", code="timeout")
    try:
        if time.monotonic() >= deadline:
            raise InspectorUnavailableError("Inspector readiness deadline expired", code="timeout")
        with _inspector_lock:
            epoch = _inspector_epoch
            if registry is not _inspector_registry:
                raise InspectorUnavailableError("Inspector runtime was reset", code="cancelled")
            if explicit:
                _inspector_failures.pop(identity, None)
                _inspector_attempted.discard(identity)
        client = registry.get(identity)
        if client is not None:
            with _inspector_lock:
                if epoch != _inspector_epoch or registry is not _inspector_registry:
                    raise InspectorUnavailableError("Inspector runtime was reset", code="cancelled")
                return client
        with _inspector_lock:
            if not explicit and identity in _inspector_failures:
                raise _inspector_failures[identity]
            if not explicit and identity in _inspector_attempted:
                raise InspectorUnavailableError(
                    "Inspector session ended; explicitly attach again", code="notAttached"
                )
            _inspector_attempted.add(identity)
        try:
            client = registry.attach(
                identity,
                target_hwnd=target_hwnd,
                deadline=min(deadline, time.monotonic() + config.attach_timeout),
            )
        except Exception as exc:
            with _inspector_lock:
                if epoch == _inspector_epoch:
                    _inspector_failures[identity] = exc
            raise
        with _inspector_lock:
            valid = epoch == _inspector_epoch and registry is _inspector_registry
            if valid:
                _inspector_attached.add(identity)
                _inspector_failures.pop(identity, None)
        if not valid:
            client.close()
            raise InspectorUnavailableError("Inspector runtime was reset", code="cancelled")
        return client
    finally:
        lock.release()


def managed_client_for(pid: int, *, deadline: float, target_hwnd: int | None) -> InspectorClient:
    """Find an authorized session, attaching at most once per identity on demand."""
    __tracebackhide__ = True
    from wintestkit.errors import InspectorUnavailableError

    require_managed()
    config = get_config().inspector
    from wintestkit.inspector.probe import current_identity

    identity = current_identity(pid)
    registry = inspector_sessions()
    client = registry.get(identity)
    if client is not None:
        with _inspector_lock:
            if registry is not _inspector_registry:
                raise InspectorUnavailableError("Inspector runtime was reset", code="cancelled")
            return client
    if config.attach == "manual":
        raise InspectorUnavailableError(
            "Attach the inspector to this process before using managed locators",
            code="notAttached",
        )
    return _attach_managed(identity, deadline=deadline, target_hwnd=target_hwnd, explicit=False)


def managed_element_identity(element: UIAElement) -> tuple[tuple[int, ...], int | None]:
    """Use the actual UIA runtime ID and pass an HWND only for its own element."""
    __tracebackhide__ = True
    from wintestkit.errors import InspectorMappingError
    from wintestkit.inspector.models import runtime_id_value
    from wintestkit.uia.element import from_handle

    try:
        runtime_id = runtime_id_value([int(part) for part in element.runtime_id.split(".")])
        hwnd = element.native_window_handle
        own_hwnd = hwnd if hwnd and element.same_as(from_handle(hwnd)) else None
    except (ValueError, TypeError, OverflowError) as exc:
        raise InspectorMappingError(
            "Element has no valid UIA runtime ID", code="mappingFailed"
        ) from exc
    return runtime_id, own_hwnd


def inspector_attached_processes() -> tuple[ProcessIdentity, ...]:
    """Successful identities for this run, including sessions already detached."""
    __tracebackhide__ = True
    with _inspector_lock:
        return tuple(
            sorted(_inspector_attached, key=lambda item: (item.pid, item.creation_time_utc))
        )


def clear_inspector_history() -> None:
    """Start a new run's attachment history without creating a registry."""
    __tracebackhide__ = True
    with _inspector_lock:
        _inspector_attached.clear()


def close_inspector_sessions() -> None:
    """Cancel pending attaches and close sessions without touching target processes."""
    __tracebackhide__ = True
    global \
        _inspector_registry, \
        _inspector_request_timeout, \
        _inspector_redact_names, \
        _inspector_epoch
    with _inspector_lock:
        registry, _inspector_registry = _inspector_registry, None
        _inspector_request_timeout = None
        _inspector_redact_names = None
        _inspector_epoch += 1
        _inspector_failures.clear()
        _inspector_attempted.clear()
        _inspector_identity_locks.clear()
    if registry is not None:
        registry.close_all()


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
    try:
        yield
    finally:
        _scoped_config.reset(token)


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
    close_inspector_sessions()
    with _inspector_lock:
        _inspector_attached.clear()
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
        self._token = _current_step.set(self._record)
        return self._record

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        __tracebackhide__ = True
        _current_step.reset(self._token)
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
