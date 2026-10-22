# pyright: basic
"""Thin wrapper around ``IUIAutomationElement`` plus value objects describing elements."""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

import comtypes

from wintestkit.errors import UIAError
from wintestkit.uia import com
from wintestkit.uia.constants import (
    CONTROL_TYPE_NAMES,
    PATTERN_IDS,
    PROPERTY_IDS,
    TreeScope,
)

log = logging.getLogger("wintestkit.uia.element")


# Nesting shown for a property: a list of elements, each element, and the arrays inside it.
MAX_INSPECTION_DEPTH = 4
_MAX_INSPECTION_ITEMS = 32


def _uia_interfaces(value: Any) -> tuple[Any, Any] | None:
    """The element or element-array interface behind a COM pointer, or ``None``.

    Only genuine COM pointers are asked: any other object is never probed for members.
    """
    __tracebackhide__ = True
    if not isinstance(value, comtypes.IUnknown):
        return None
    module = com.uia_module()
    for interface, is_array in (
        (module.IUIAutomationElementArray, True),
        (module.IUIAutomationElement, False),
    ):
        try:
            return value.QueryInterface(interface), is_array
        except (comtypes.COMError, ValueError, TypeError):
            continue
    return None


def _describe_element(name: str, raw: Any, depth: int) -> dict[str, Any]:
    """A UIA element as a nested object: its identity and its place on screen."""
    __tracebackhide__ = True
    result: dict[str, Any] = {"name": name, "typeName": "UIAElement", "kind": "object"}
    element = UIAElement(raw)
    values: dict[str, Any] = {}
    try:
        rect = element.rect
        values.update(
            AutomationId=element.automation_id,
            BoundingRectangle=None
            if rect is None
            else [rect.left, rect.top, rect.width, rect.height],
            ClassName=element.class_name,
            ControlType=element.control_type,
            Name=element.name,
            RuntimeId=[int(part) for part in raw.GetRuntimeId()],
        )
    except (comtypes.COMError, UIAError):
        result["status"] = "The element is no longer available"
        return result
    result["children"] = [
        inspection_property(key, value, depth + 1) for key, value in sorted(values.items())
    ]
    return result


def _describe_uia_value(name: str, value: Any, depth: int) -> dict[str, Any] | None:
    """Expand an element or element array held in a property; ``None`` for other COM values."""
    __tracebackhide__ = True
    found = _uia_interfaces(value)
    if found is None:
        return None
    interface, is_array = found
    if not is_array:
        return _describe_element(name, interface, depth)
    result: dict[str, Any] = {"name": name, "typeName": "UIAElementArray", "kind": "array"}
    count = int(interface.Length)
    if count == 0:
        result["status"] = "Empty"
    elif depth >= MAX_INSPECTION_DEPTH:
        result["status"] = "Depth limit reached"
    else:
        result["children"] = [
            _describe_element(str(index), interface.GetElement(index), depth + 1)
            for index in range(min(count, _MAX_INSPECTION_ITEMS))
        ]
        if count > _MAX_INSPECTION_ITEMS:
            result["status"] = f"Truncated to {_MAX_INSPECTION_ITEMS} items"
    return result


def inspection_property(name: str, value: Any, depth: int = 0) -> dict[str, Any]:
    """Describe UIA values without invoking object members or arbitrary string conversions.

    Scalars, lists and the UIA elements and element arrays that properties such as
    ``ControllerFor`` hold are described, nested up to ``MAX_INSPECTION_DEPTH`` levels. Any other
    object is reported as opaque and its members are never read.
    """
    __tracebackhide__ = True
    result: dict[str, Any] = {"name": name, "typeName": type(value).__name__}
    if value is None or type(value) in (str, int, float, bool):
        result["kind"] = "scalar"
        if type(value) is float and not math.isfinite(value):
            result.update(kind="unavailable", status="Non-finite UIA value")
        else:
            result["value"] = value[:4096] if type(value) is str else value
            if type(value) is str and len(value) > 4096:
                result["status"] = "Truncated to 4096 characters"
    elif type(value) in (list, tuple):
        result["kind"] = "array"
        if depth >= MAX_INSPECTION_DEPTH:
            result["status"] = "Depth limit reached"
        else:
            result["children"] = [
                inspection_property(str(index), child, depth + 1)
                for index, child in enumerate(value[:_MAX_INSPECTION_ITEMS])
            ]
            if len(value) > _MAX_INSPECTION_ITEMS:
                result["status"] = f"Truncated to {_MAX_INSPECTION_ITEMS} items"
    elif (expanded := _describe_uia_value(name, value, depth)) is not None:
        return expanded
    else:
        result.update(kind="object", status="Opaque external UIA value; members are not read")
    return result


@dataclass(frozen=True, slots=True)
class Rect:
    """A rectangle in physical screen pixels."""

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        __tracebackhide__ = True
        return self.left + self.width

    @property
    def bottom(self) -> int:
        __tracebackhide__ = True
        return self.top + self.height

    @property
    def center(self) -> tuple[int, int]:
        __tracebackhide__ = True
        return (self.left + self.width // 2, self.top + self.height // 2)

    def is_empty(self) -> bool:
        __tracebackhide__ = True
        return self.width <= 0 or self.height <= 0

    def inflate(self, d: int) -> Rect:
        __tracebackhide__ = True
        return Rect(self.left - d, self.top - d, self.width + 2 * d, self.height + 2 * d)

    def to_dict(self) -> dict[str, int]:
        __tracebackhide__ = True
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


@dataclass(frozen=True, slots=True)
class ElementInfo:
    """Immutable snapshot of an element's properties (mirrors the protocol ``ElementInfo``)."""

    automation_id: str
    name: str
    control_type: str
    class_name: str
    framework_id: str
    process_id: int
    rect: Rect | None
    is_enabled: bool
    is_offscreen: bool
    has_keyboard_focus: bool
    runtime_id: str
    patterns: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        __tracebackhide__ = True
        data: dict[str, Any] = {
            "automationId": self.automation_id,
            "name": self.name,
            "controlType": self.control_type,
            "className": self.class_name,
            "frameworkId": self.framework_id,
            "processId": self.process_id,
            "rect": self.rect.to_dict() if self.rect is not None else None,
            "isEnabled": self.is_enabled,
            "isOffscreen": self.is_offscreen,
            "hasKeyboardFocus": self.has_keyboard_focus,
            "runtimeId": self.runtime_id,
        }
        if self.patterns is not None:
            data["patterns"] = list(self.patterns)
        return data

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ElementInfo:
        __tracebackhide__ = True
        rect = d.get("rect")
        patterns = d.get("patterns")
        return cls(
            automation_id=d["automationId"],
            name=d["name"],
            control_type=d["controlType"],
            class_name=d["className"],
            framework_id=d["frameworkId"],
            process_id=d["processId"],
            rect=Rect(rect["left"], rect["top"], rect["width"], rect["height"]) if rect else None,
            is_enabled=d["isEnabled"],
            is_offscreen=d["isOffscreen"],
            has_keyboard_focus=d["hasKeyboardFocus"],
            runtime_id=d["runtimeId"],
            patterns=tuple(patterns) if patterns is not None else None,
        )

    def short(self) -> str:
        """Compact label: ``Button "Sign in"``, ``Edit [TextBox]``, ``Text #StatusText "Ready"``."""
        __tracebackhide__ = True
        parts = [self.control_type]
        if self.automation_id:
            parts.append(f"#{self.automation_id}")
        if self.name:
            parts.append(f'"{self.name}"')
        if not self.automation_id and not self.name and self.class_name:
            parts.append(f"[{self.class_name}]")
        return " ".join(parts)


# Properties read by info(); also what a CacheRequest preloads.
_INFO_PROPERTIES = (
    "AutomationId",
    "Name",
    "ControlType",
    "ClassName",
    "FrameworkId",
    "ProcessId",
    "BoundingRectangle",
    "IsEnabled",
    "IsOffscreen",
    "HasKeyboardFocus",
    "NativeWindowHandle",
)

_cache_lock = threading.Lock()
_cache_request: Any = None


def _get_cache_request() -> Any:
    __tracebackhide__ = True
    global _cache_request
    if _cache_request is not None:
        return _cache_request
    with _cache_lock:
        if _cache_request is None:
            uia = com.get_uia()
            with com.wrap_com_errors:
                request = uia.CreateCacheRequest()
                for name in _INFO_PROPERTIES:
                    request.AddProperty(PROPERTY_IDS[name])
                request.TreeScope = int(TreeScope.Element)
            _cache_request = request
    return _cache_request


def _control_view_condition(condition: Any | None) -> Any:
    __tracebackhide__ = True
    uia = com.get_uia()
    view = uia.ControlViewCondition
    if condition is None:
        return view
    return uia.CreateAndCondition(view, condition)


class ElementEnumerationError(Exception):
    def __init__(self, elements: list[UIAElement | None], errors: list[dict[str, Any]]) -> None:
        __tracebackhide__ = True
        super().__init__("some UIA elements could not be enumerated")
        self.elements = elements
        self.errors = errors


def array_to_list(array: Any, cached: bool = False) -> list[UIAElement]:
    __tracebackhide__ = True
    if array is None:
        return []
    elements: list[UIAElement | None] = []
    errors: list[dict[str, Any]] = []
    for index in range(array.Length):
        try:
            elements.append(UIAElement(array.GetElement(index), cached=cached))
        except Exception as exc:
            elements.append(None)
            errors.append({"index": index, "message": str(exc)})
    if errors:
        raise ElementEnumerationError(elements, errors)
    return [element for element in elements if element is not None]


class UIAElement:
    """Wrapper around ``IUIAutomationElement``.

    Property reads are live unless the element was obtained through a cache request
    (``find_all(cached=True)``), in which case the cached values are read.
    """

    __slots__ = ("_cached", "raw")

    def __init__(self, raw: Any, cached: bool = False) -> None:
        __tracebackhide__ = True
        self.raw = raw
        self._cached = cached

    def _read(self, attribute: str) -> Any:
        __tracebackhide__ = True
        prefix = "Cached" if self._cached else "Current"
        with com.wrap_com_errors:
            return getattr(self.raw, prefix + attribute)

    def as_live(self) -> UIAElement:
        """The same element with live (uncached) property reads."""
        __tracebackhide__ = True
        return UIAElement(self.raw) if self._cached else self

    # -- properties ---------------------------------------------------------------------------

    @property
    def automation_id(self) -> str:
        __tracebackhide__ = True
        return self._read("AutomationId") or ""

    @property
    def name(self) -> str:
        __tracebackhide__ = True
        return self._read("Name") or ""

    @property
    def control_type_id(self) -> int:
        __tracebackhide__ = True
        return int(self._read("ControlType"))

    @property
    def control_type(self) -> str:
        __tracebackhide__ = True
        ident = self.control_type_id
        return CONTROL_TYPE_NAMES.get(ident, f"Unknown({ident})")

    @property
    def class_name(self) -> str:
        __tracebackhide__ = True
        return self._read("ClassName") or ""

    @property
    def framework_id(self) -> str:
        __tracebackhide__ = True
        return self._read("FrameworkId") or ""

    @property
    def process_id(self) -> int:
        __tracebackhide__ = True
        return int(self._read("ProcessId"))

    @property
    def native_window_handle(self) -> int:
        __tracebackhide__ = True
        return int(self._read("NativeWindowHandle") or 0)

    @property
    def rect(self) -> Rect | None:
        __tracebackhide__ = True
        raw_rect = self._read("BoundingRectangle")
        rect = Rect(
            raw_rect.left,
            raw_rect.top,
            raw_rect.right - raw_rect.left,
            raw_rect.bottom - raw_rect.top,
        )
        return None if rect.is_empty() else rect

    @property
    def is_enabled(self) -> bool:
        __tracebackhide__ = True
        return bool(self._read("IsEnabled"))

    @property
    def is_offscreen(self) -> bool:
        __tracebackhide__ = True
        return bool(self._read("IsOffscreen"))

    @property
    def has_keyboard_focus(self) -> bool:
        __tracebackhide__ = True
        return bool(self._read("HasKeyboardFocus"))

    @property
    def runtime_id(self) -> str:
        __tracebackhide__ = True
        with com.wrap_com_errors:
            ids = self.raw.GetRuntimeId()
        return ".".join(str(i) for i in ids)

    def get_property(self, name: str) -> Any:
        """Read a property by its ``PROPERTY_IDS`` name; returns a Python value."""
        __tracebackhide__ = True
        try:
            ident = PROPERTY_IDS[name]
        except KeyError:
            raise ValueError(f"unknown UIA property {name!r}") from None
        with com.wrap_com_errors:
            return self.raw.GetCurrentPropertyValue(ident)

    def supported_patterns(self) -> list[str]:
        """Names of the patterns the element supports."""
        __tracebackhide__ = True
        supported: list[str] = []
        for name, ident in PATTERN_IDS.items():
            try:
                pattern = self.raw.GetCurrentPattern(ident)
            except comtypes.COMError:
                continue
            if pattern:
                supported.append(name)
        return supported

    def info(self, with_patterns: bool = False) -> ElementInfo:
        __tracebackhide__ = True
        try:
            runtime_id = self.runtime_id
        except Exception:
            runtime_id = ""
        return ElementInfo(
            automation_id=self.automation_id,
            name=self.name,
            control_type=self.control_type,
            class_name=self.class_name,
            framework_id=self.framework_id,
            process_id=self.process_id,
            rect=self.rect,
            is_enabled=self.is_enabled,
            is_offscreen=self.is_offscreen,
            has_keyboard_focus=self.has_keyboard_focus,
            runtime_id=runtime_id,
            patterns=tuple(self.supported_patterns()) if with_patterns else None,
        )

    # -- tree navigation ----------------------------------------------------------------------

    def parent(self) -> UIAElement | None:
        __tracebackhide__ = True
        uia = com.get_uia()
        with com.wrap_com_errors:
            parent = uia.ControlViewWalker.GetParentElement(self.raw)
        return UIAElement(parent) if parent else None

    def children(self) -> list[UIAElement]:
        __tracebackhide__ = True
        return self.find_all(TreeScope.Children)

    def iter_children(self) -> Iterator[UIAElement]:
        """Lazily enumerate control-view children with cached description properties."""
        __tracebackhide__ = True
        with com.wrap_com_errors:
            walker = com.get_uia().ControlViewWalker
            request = _get_cache_request()
            child = walker.GetFirstChildElementBuildCache(self.raw, request)
        while child:
            yield UIAElement(child, cached=True)
            with com.wrap_com_errors:
                child = walker.GetNextSiblingElementBuildCache(child, request)

    def find_all(
        self, scope: TreeScope, condition: Any | None = None, cached: bool = False
    ) -> list[UIAElement]:
        """Find matching elements in the control view; ``cached`` preloads info() properties."""
        __tracebackhide__ = True
        with com.wrap_com_errors:
            cond = _control_view_condition(condition)
            if cached:
                array = self.raw.FindAllBuildCache(int(scope), cond, _get_cache_request())
            else:
                array = self.raw.FindAll(int(scope), cond)
            return array_to_list(array, cached=cached)

    def find_first(self, scope: TreeScope, condition: Any | None = None) -> UIAElement | None:
        __tracebackhide__ = True
        with com.wrap_com_errors:
            found = self.raw.FindFirst(int(scope), _control_view_condition(condition))
        return UIAElement(found) if found else None

    def set_focus(self) -> None:
        __tracebackhide__ = True
        with com.wrap_com_errors:
            self.raw.SetFocus()

    def same_as(self, other: UIAElement) -> bool:
        __tracebackhide__ = True
        with com.wrap_com_errors:
            return bool(com.get_uia().CompareElements(self.raw, other.raw))

    def is_alive(self) -> bool:
        __tracebackhide__ = True
        try:
            self.raw.CurrentProcessId  # noqa: B018 - the read itself is the liveness probe
        except comtypes.COMError:
            return False
        return True

    def __repr__(self) -> str:
        __tracebackhide__ = True
        try:
            return f"<UIAElement {self.control_type} {self.name!r}>"
        except Exception:
            return "<UIAElement (unavailable)>"


# -- entry points ----------------------------------------------------------------------------


def root() -> UIAElement:
    """The desktop root element."""
    __tracebackhide__ = True
    with com.wrap_com_errors:
        return UIAElement(com.get_uia().GetRootElement())


def from_point(x: int, y: int) -> UIAElement | None:
    __tracebackhide__ = True
    uia = com.get_uia()
    point = com.uia_module().tagPOINT(x, y)
    try:
        raw = uia.ElementFromPoint(point)
    except comtypes.COMError:
        return None
    return UIAElement(raw) if raw else None


def from_handle(hwnd: int) -> UIAElement:
    __tracebackhide__ = True
    with com.wrap_com_errors:
        return UIAElement(com.get_uia().ElementFromHandle(hwnd))


def focused() -> UIAElement | None:
    __tracebackhide__ = True
    try:
        raw = com.get_uia().GetFocusedElement()
    except comtypes.COMError:
        return None
    return UIAElement(raw) if raw else None
