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
    try:
        comtypes.CoInitializeEx(COINIT_MULTITHREADED)
    except OSError as exc:
        if getattr(exc, "winerror", None) not in (-2147417850, 2147549446):
            raise
        if not _warned_sta:
            _warned_sta = True
            log.warning("calling thread already uses another COM apartment; using that apartment")
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
    "help_text": "HelpText",
    "item_status": "ItemStatus",
    "item_type": "ItemType",
    "accelerator_key": "AcceleratorKey",
    "access_key": "AccessKey",
    "localized_control_type": "LocalizedControlType",
    "value": "ValueValue",
    "is_enabled": "IsEnabled",
    "is_offscreen": "IsOffscreen",
    "is_password": "IsPassword",
    "is_keyboard_focusable": "IsKeyboardFocusable",
}


def create_condition(**props: Any) -> Any:
    """Build a UIA condition matching all given exact property values.

    Accepts UIA property names and the locator's snake-case shorthand names.
    No properties yields a true condition.
    """
    __tracebackhide__ = True
    for key in props:
        if key not in _CONDITION_PROPS and key not in PROPERTY_IDS:
            raise ValueError(f"unsupported condition property {key!r}")
    uia = get_uia()
    with wrap_com_errors:
        conditions = []
        for key, value in props.items():
            if key == "control_type" and isinstance(value, str):
                value = CONTROL_TYPES[value]
            conditions.append(
                uia.CreatePropertyCondition(PROPERTY_IDS[_CONDITION_PROPS.get(key, key)], value)
            )
        if not conditions:
            return uia.CreateTrueCondition()
        combined = conditions[0]
        for condition in conditions[1:]:
            combined = uia.CreateAndCondition(combined, condition)
        return combined


def create_runtime_ids_condition(runtime_ids: list[tuple[int, ...]]) -> Any:
    """Match any runtime ID using UIA's integer SAFEARRAY property value."""
    __tracebackhide__ = True
    from array import array

    if not runtime_ids:
        raise ValueError("At least one runtime ID is required")
    uia = get_uia()
    with wrap_com_errors:
        conditions = [uia.CreatePropertyCondition(30000, array("i", rid)) for rid in runtime_ids]
        result = conditions[0]
        for condition in conditions[1:]:
            result = uia.CreateOrCondition(result, condition)
        return result
