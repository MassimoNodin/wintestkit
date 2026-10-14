"""Fake UI Automation tree and application for resolver / diagnostics unit tests."""

from __future__ import annotations

from typing import Any

from wintestkit.uia.constants import TreeScope
from wintestkit.uia.element import ElementInfo, Rect

_COUNTER = [0]
DEFAULT_RECT = Rect(0, 0, 10, 10)


class FakeElement:
    """Duck-typed stand-in for ``UIAElement`` backed by an in-memory tree."""

    def __init__(
        self,
        control_type: str,
        name: str = "",
        automation_id: str = "",
        class_name: str = "",
        children: list[FakeElement] | None = None,
        rect: Rect | None = DEFAULT_RECT,
    ) -> None:
        _COUNTER[0] += 1
        self.control_type = control_type
        self.name = name
        self.automation_id = automation_id
        self.class_name = class_name
        self.framework_id = "WPF"
        self.process_id = 1
        self.rect = rect
        self.is_enabled = True
        self.is_offscreen = False
        self.has_keyboard_focus = False
        self.runtime_id = f"1.{_COUNTER[0]}"
        self.native_window_handle = _COUNTER[0]
        self._parent: FakeElement | None = None
        self.children_list: list[FakeElement] = []
        for child in children or []:
            self.add(child)

    def add(self, child: FakeElement) -> FakeElement:
        child._parent = self
        self.children_list.append(child)
        return child

    # -- UIAElement surface -----------------------------------------------------------------

    def as_live(self) -> FakeElement:
        return self

    def info(self, with_patterns: bool = False) -> ElementInfo:
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
            runtime_id=self.runtime_id,
            patterns=None,
        )

    def parent(self) -> FakeElement | None:
        return self._parent

    def children(self) -> list[FakeElement]:
        return list(self.children_list)

    def same_as(self, other: Any) -> bool:
        return self is other

    def is_alive(self) -> bool:
        return True

    def find_all(
        self, scope: TreeScope, condition: Any | None = None, cached: bool = False
    ) -> list[FakeElement]:
        """``condition`` is the property dict produced by the patched condition factory."""
        if scope == TreeScope.Children:
            candidates = list(self.children_list)
        else:
            candidates = list(self._descendants())
        return [e for e in candidates if _matches(e, condition or {})]

    def _descendants(self) -> list[FakeElement]:
        found: list[FakeElement] = []
        for child in self.children_list:
            found.append(child)
            found.extend(child._descendants())
        return found

    def __repr__(self) -> str:
        return f"<Fake {self.control_type} {self.name!r}>"


_CONDITION_ATTRS = {
    "control_type": "control_type",
    "automation_id": "automation_id",
    "name": "name",
    "class_name": "class_name",
}


def _matches(element: FakeElement, props: dict[str, Any]) -> bool:
    from wintestkit.uia.constants import CONTROL_TYPE_NAMES

    for key, value in props.items():
        actual = getattr(element, _CONDITION_ATTRS[key])
        if key == "control_type":
            actual_id = next(i for i, n in CONTROL_TYPE_NAMES.items() if n == actual)
            if actual_id != value:
                return False
        elif actual != value:
            return False
    return True


class FakeApp:
    """Stand-in for ``App`` exposing the surface used by the resolver."""

    def __init__(self, windows: list[FakeElement], process_name: str = "DemoApp.exe") -> None:
        self.windows = windows
        self.process_name = process_name

    @property
    def pids(self) -> list[int]:
        return [1]

    def is_running(self) -> bool:
        return True

    def top_level_windows(self) -> list[FakeElement]:
        return list(self.windows)

    def main_window(self, timeout: float = 0.0) -> FakeElement:
        for window in self.windows:
            if window.control_type == "Window":
                return window
        raise AssertionError("no main window in fake app")
