# pyright: basic
"""COM bootstrap for UI Automation.

WinTestKit uses the COM multithreaded apartment (MTA) everywhere. ``sys.coinit_flags`` is set
before ``comtypes`` is imported because comtypes reads it at import time.
"""

from __future__ import annotations

import functools
import logging
import sys
import threading
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

# Must happen before the first ``import comtypes`` anywhere in the process.
if "comtypes" not in sys.modules:
    sys.coinit_flags = 0  # COINIT_MULTITHREADED  # type: ignore[attr-defined]

import comtypes
import comtypes.client

from wintestkit.errors import EnvironmentNotReadyError, UIAError
from wintestkit.uia.constants import CONTROL_TYPES, PROPERTY_IDS

__all__ = [
    "UIA_E_ELEMENTNOTAVAILABLE",
    "create_condition",
    "ensure_com_initialized",
    "get_uia",
    "uia_module",
    "wrap_com_errors",
]

log = logging.getLogger("wintestkit.uia.com")

COINIT_MULTITHREADED = 0
UIA_E_ELEMENTNOTAVAILABLE = -2147220991  # 0x80040201 as a signed 32-bit HRESULT

_P = ParamSpec("_P")
_T = TypeVar("_T")

_local = threading.local()
_uia_lock = threading.Lock()
_uia: Any = None
_warned_sta = False


def ensure_com_initialized() -> None:
    """Initialise COM for the calling thread as MTA (once per thread)."""
    __tracebackhide__ = True
    global _warned_sta
    if getattr(_local, "initialized", False):
        return
    if getattr(sys, "coinit_flags", COINIT_MULTITHREADED) != COINIT_MULTITHREADED:
        if not _warned_sta:
            _warned_sta = True
            log.warning("comtypes was imported with STA flags; UI Automation uses that apartment")
    else:
        try:
            comtypes.CoInitializeEx(COINIT_MULTITHREADED)
        except OSError as exc:
            # RPC_E_CHANGED_MODE: the thread already lives in another apartment; that is fine.
            log.debug("CoInitializeEx: %s", exc)
    _local.initialized = True


def uia_module() -> Any:
    """Return the generated ``comtypes.gen.UIAutomationClient`` module."""
    __tracebackhide__ = True
    ensure_com_initialized()
    try:
        return comtypes.client.GetModule("UIAutomationCore.dll")
    except (OSError, ImportError) as exc:
        raise EnvironmentNotReadyError(f"UI Automation is not available: {exc}") from exc


def get_uia() -> Any:
    """Return the shared ``IUIAutomation`` client object (created lazily)."""
    __tracebackhide__ = True
    global _uia
    ensure_com_initialized()
    if _uia is not None:
        return _uia
    with _uia_lock:
        if _uia is not None:
            return _uia
        module = uia_module()
        last_error: Exception | None = None
        for clsid_name in ("CUIAutomation8", "CUIAutomation"):
            clsid = getattr(module, clsid_name, None)
            if clsid is None:
                continue
            try:
                _uia = comtypes.client.CreateObject(clsid, interface=module.IUIAutomation)
            except (OSError, comtypes.COMError) as exc:
                last_error = exc
                log.debug("creating %s failed: %s", clsid_name, exc)
                continue
            return _uia
        raise EnvironmentNotReadyError(
            f"Could not create the UI Automation client object: {last_error}"
        )


def _convert(exc: comtypes.COMError) -> UIAError:
    __tracebackhide__ = True
    hresult = exc.hresult if isinstance(exc.hresult, int) else None
    if hresult == UIA_E_ELEMENTNOTAVAILABLE:
        return UIAError("The UI element is no longer available", hresult, element_gone=True)
    text = getattr(exc, "text", None) or "COM error"
    hex_value = f"0x{hresult & 0xFFFFFFFF:08X}" if hresult is not None else "unknown"
    return UIAError(f"UI Automation call failed ({hex_value}): {text}", hresult)


class _WrapComErrors:
    """Converts ``comtypes.COMError`` to ``UIAError``; usable as decorator or context manager."""

    def __call__(self, fn: Callable[_P, _T]) -> Callable[_P, _T]:
        __tracebackhide__ = True

        @functools.wraps(fn)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            __tracebackhide__ = True
            try:
                return fn(*args, **kwargs)
            except comtypes.COMError as exc:
                raise _convert(exc) from exc

        return wrapper

    def __enter__(self) -> None:
        __tracebackhide__ = True
        return None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        __tracebackhide__ = True
        if isinstance(exc, comtypes.COMError):
            raise _convert(exc) from exc


wrap_com_errors = _WrapComErrors()

_CONDITION_PROPS = {
    "control_type": "ControlType",
    "automation_id": "AutomationId",
    "name": "Name",
    "class_name": "ClassName",
    "process_id": "ProcessId",
    "framework_id": "FrameworkId",
}


def create_condition(**props: Any) -> Any:
    """Build a UIA condition matching all given exact property values.

    Accepted keys: ``control_type`` (int id), ``automation_id``, ``name``, ``class_name``,
    ``process_id``, ``framework_id``. No properties yields a true condition.
    """
    __tracebackhide__ = True
    for key in props:
        if key not in _CONDITION_PROPS:
            raise ValueError(f"unsupported condition property {key!r}")
    uia = get_uia()
    with wrap_com_errors:
        conditions = []
        for key, value in props.items():
            if key == "control_type" and isinstance(value, str):
                value = CONTROL_TYPES[value]
            conditions.append(
                uia.CreatePropertyCondition(PROPERTY_IDS[_CONDITION_PROPS[key]], value)
            )
        if not conditions:
            return uia.CreateTrueCondition()
        combined = conditions[0]
        for condition in conditions[1:]:
            combined = uia.CreateAndCondition(combined, condition)
        return combined
