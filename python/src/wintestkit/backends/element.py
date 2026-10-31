"""Resolution-facing element interface and the inspector-backed implementation."""

from __future__ import annotations

import time
import weakref
from contextlib import suppress
from typing import Any, Protocol

from wintestkit.backends.mapping import map_runtime_ids, map_state_at_point
from wintestkit.errors import InspectorError, InspectorReadError, NoUiaPeerError
from wintestkit.inspector.client import InspectorClient
from wintestkit.inspector.models import ElementState, ObjectRef
from wintestkit.inspector.paths import PathSegment
from wintestkit.uia.constants import CONTROL_TYPES
from wintestkit.uia.element import ElementInfo, Rect, UIAElement


class TargetElement(Protocol):
    @property
    def automation_id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def control_type(self) -> str: ...
    @property
    def control_type_id(self) -> int: ...
    @property
    def class_name(self) -> str: ...
    @property
    def framework_id(self) -> str: ...
    @property
    def process_id(self) -> int: ...
    @property
    def native_window_handle(self) -> int: ...
    @property
    def rect(self) -> Rect | None: ...
    @property
    def is_enabled(self) -> bool: ...
    @property
    def is_offscreen(self) -> bool: ...
    @property
    def has_keyboard_focus(self) -> bool: ...
    @property
    def runtime_id(self) -> str: ...
    def info(self, with_patterns: bool = False) -> ElementInfo: ...
    def parent(self) -> UIAElement | None: ...
    def children(self) -> list[UIAElement]: ...
    def same_as(self, other: UIAElement) -> bool: ...
    def is_alive(self) -> bool: ...
    def as_live(self) -> TargetElement: ...
    def get_property(self, name: str) -> Any: ...


def check_uia_protocol(element: UIAElement) -> TargetElement:
    return element


class _Lease:
    def __init__(self, client: InspectorClient, ref: ObjectRef) -> None:
        self.finalizer = weakref.finalize(self, _release, client, ref.object_id)


def _release(client: InspectorClient, object_id: str) -> None:
    with suppress(Exception):
        client.release([object_id], deadline=time.monotonic() + 0.25)


_leases: weakref.WeakKeyDictionary[
    InspectorClient, weakref.WeakValueDictionary[tuple[str, str, int], _Lease]
] = weakref.WeakKeyDictionary()


class WpfElement:
    """Inspector snapshot; wrappers share a lease and release it when the last dies.

    The agent expires strong leases after inactivity but keeps weak entries for live
    objects. Explicit release prevents those entries accumulating across test runs.
    Callers must not independently release a handle while a wrapper owns it.
    """

    def __init__(self, client: InspectorClient, ref: ObjectRef, process_id: int) -> None:
        self.client, self.ref, self._process_id = client, ref, process_id
        key = (ref.session_id, ref.object_id, ref.generation)
        leases = _leases.setdefault(client, weakref.WeakValueDictionary())
        lease = leases.get(key)
        if lease is None:
            lease = _Lease(client, ref)
            leases[key] = lease
        self._lease = lease
        self._identity: dict[str, str] | None = None
        self._state: ElementState | None = None
        self._uia: UIAElement | None = None

    def _get_identity(self) -> dict[str, str]:
        if self._identity is None:
            names = ("automation_id", "name", "class_name", "control_type")
            paths = [(PathSegment("uia", name),) for name in names]
            values, _ = self.client.read(
                self.ref.object_id, self.ref.generation, paths, deadline=time.monotonic() + 2
            )
            identity: dict[str, str] = {}
            for name, item in zip(names, values, strict=True):
                value = item.value
                if value.status == "unavailable":
                    identity[name] = ""
                elif value.status == "ok" and isinstance(value.scalar, str):
                    identity[name] = value.scalar
                else:
                    raise InspectorReadError(
                        f"Cannot read UIA identity {name}: {value.status}", code="readFailed"
                    )
            self._identity = identity
        return self._identity

    def _get_state(self) -> ElementState:
        if self._state is None:
            self._state = self.client.state_get(
                self.ref, timeout_ms=2000, deadline=time.monotonic() + 2
            )
        return self._state

    @property
    def automation_id(self) -> str:
        return self._get_identity()["automation_id"]

    @property
    def name(self) -> str:
        return self._get_identity()["name"]

    @property
    def class_name(self) -> str:
        return self._get_identity()["class_name"]

    @property
    def control_type(self) -> str:
        return self._get_identity()["control_type"]

    @property
    def control_type_id(self) -> int:
        return CONTROL_TYPES.get(self.control_type, 0)

    @property
    def framework_id(self) -> str:
        return "WPF"

    @property
    def process_id(self) -> int:
        return self._process_id

    @property
    def rect(self) -> Rect | None:
        bounds = self._get_state().bounds
        if bounds is None:
            return None
        left, top = round(bounds.x), round(bounds.y)
        rect = Rect(
            left, top, round(bounds.x + bounds.width) - left, round(bounds.y + bounds.height) - top
        )
        return None if rect.is_empty() else rect

    @property
    def is_enabled(self) -> bool:
        return self._get_state().enabled

    @property
    def is_offscreen(self) -> bool:
        return self._get_state().offscreen

    @property
    def has_keyboard_focus(self) -> bool:
        return self._get_state().focused

    @property
    def runtime_id(self) -> str:
        rid = self._get_state().uia_runtime_id
        return (
            ".".join(map(str, rid))
            if rid
            else f"wpf:{self.ref.session_id}:{self.ref.object_id}:{self.ref.generation}"
        )

    @property
    def native_window_handle(self) -> int:
        """Only the HWND's UIA root owns the HWND, not its descendants."""
        from wintestkit.uia.element import from_handle

        state = self._get_state()
        if not state.window_handle or not state.uia_runtime_id:
            return 0
        return (
            state.window_handle
            if from_handle(state.window_handle).runtime_id == self.runtime_id
            else 0
        )

    def as_live(self) -> WpfElement:
        return WpfElement(self.client, self.ref, self.process_id)

    def is_alive(self) -> bool:
        try:
            self.client.state_get(self.ref, timeout_ms=2000, deadline=time.monotonic() + 2)
        except InspectorError as error:
            if error.code in ("objectStale", "mappingFailed"):
                return False
            raise
        return True

    def same_as(self, other: UIAElement | WpfElement) -> bool:
        if isinstance(other, WpfElement):
            return (self.ref.session_id, self.ref.object_id, self.ref.generation) == (
                other.ref.session_id,
                other.ref.object_id,
                other.ref.generation,
            )
        state = self._get_state()
        return bool(state.uia_runtime_id) and self.runtime_id == other.runtime_id

    def as_uia(self) -> UIAElement:
        """Map the agent handle to its peer for phase 2 UIA-only operations."""
        state = self._get_state()
        if state.window_handle and state.uia_runtime_id:
            if self._uia is not None:
                try:
                    if self._uia.is_alive() and self._uia.runtime_id == self.runtime_id:
                        return self._uia
                except Exception:
                    pass
                self._uia = None
            result = map_state_at_point(state)
            if result is not None:
                self._uia = result
                return result
            key = (state.window_handle, state.uia_runtime_id)
            result = map_runtime_ids({state.window_handle: [state.uia_runtime_id]}).get(key)
            if result is not None:
                self._uia = result
                return result
        raise NoUiaPeerError(
            f"{self.info().short()} has no UI Automation peer; "
            "this operation needs one until phase 3"
        )

    @property
    def raw(self) -> Any:
        """Expose the UIA peer for UIAElement.same_as without changing UIAElement."""
        return self.as_uia().raw

    def parent(self) -> UIAElement | None:
        """Delegate tree navigation to the UIA peer until the router slice."""
        return self.as_uia().parent()

    def children(self) -> list[UIAElement]:
        """Delegate tree navigation to the UIA peer until the router slice."""
        return self.as_uia().children()

    def get_property(self, name: str) -> Any:
        """Delegate arbitrary UIA property reads to the peer."""
        return self.as_uia().get_property(name)

    def info(self, with_patterns: bool = False) -> ElementInfo:
        """Use agent identity and geometry; delegate pattern enumeration to UIA."""
        return ElementInfo(
            self.automation_id,
            self.name,
            self.control_type,
            self.class_name,
            self.framework_id,
            self.process_id,
            self.rect,
            self.is_enabled,
            self.is_offscreen,
            self.has_keyboard_focus,
            self.runtime_id,
            tuple(self.as_uia().supported_patterns()) if with_patterns else None,
        )


def uia_of(element: TargetElement) -> UIAElement:
    from typing import cast

    return element.as_uia() if isinstance(element, WpfElement) else cast(UIAElement, element)
