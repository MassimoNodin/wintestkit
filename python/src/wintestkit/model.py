"""The test-facing model: ``Page``, ``Window``, ``Element`` and their bound counterparts.

Users declare elements as class attributes of a ``Page`` subclass. Accessing an attribute on the
class returns the definition; accessing it on an instance returns a *bound* object that resolves
the locator lazily and auto-waits before every action.
"""

from __future__ import annotations

import dataclasses
import inspect
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from types import FrameType
from typing import Any, ClassVar, Literal, TypeVar, overload

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.engine import actions, overlay, waits
from wintestkit.engine.locator import (
    ItemSelector,
    Locator,
    Matcher,
    WindowLocator,
    match_value,
)
from wintestkit.engine.resolve import Scope, resolve, resolve_all, resolve_window
from wintestkit.engine.waits import State
from wintestkit.errors import (
    ActionError,
    AmbiguousElementError,
    ElementNotFoundError,
    LocatorError,
    UIAError,
    WaitTimeoutError,
    WindowNotFoundError,
)
from wintestkit.uia import patterns
from wintestkit.uia.element import ElementInfo, UIAElement

__all__ = [
    "BoundElement",
    "BoundElements",
    "BoundWindow",
    "Element",
    "Elements",
    "Page",
    "Window",
    "is_password_locator",
]

_T = TypeVar("_T")
InputMode = Literal["pattern", "mouse"]
_MAX_FIND_ROW_ROWS = 10_000
_PASSWORD_CLASS = "PasswordBox"
# An ambiguous locator is a mistake in the test, not a transient state: fail immediately instead
# of retrying it until the timeout.
_RETRY_ON = (ElementNotFoundError, WindowNotFoundError, UIAError)


def _caller_source() -> tuple[str, int] | None:
    """``(file, 1-based line)`` of the first frame outside this module (the user's definition)."""
    __tracebackhide__ = True
    frame: FrameType | None = inspect.currentframe()
    while frame is not None and frame.f_globals.get("__name__") == __name__:
        frame = frame.f_back
    if frame is None:
        return None
    return (frame.f_code.co_filename, frame.f_lineno)


# -- definitions ----------------------------------------------------------------------------------


class Window:
    """Describes a top-level window of the application under test."""

    def __init__(
        self,
        *,
        title: Matcher | None = None,
        process: str | None = None,
        class_name: Matcher | None = None,
        automation_id: Matcher | None = None,
        index: int | None = None,
    ) -> None:
        __tracebackhide__ = True
        self.locator = WindowLocator(
            title=title,
            process=process,
            class_name=class_name,
            automation_id=automation_id,
            index=index,
        )
        self.timeout: float | None = None  # windows use the configured default timeout
        self.name: str | None = None
        self.owner: type | None = None
        self.source = _caller_source()

    def __set_name__(self, owner: type, name: str) -> None:
        __tracebackhide__ = True
        self.owner = owner
        self.name = name

    @property
    def qualname(self) -> str:
        __tracebackhide__ = True
        if self.owner is None or self.name is None:
            return "<anonymous>"
        return f"{self.owner.__qualname__}.{self.name}"

    @overload
    def __get__(self, obj: None, owner: type | None = None) -> Window: ...
    @overload
    def __get__(self, obj: object, owner: type | None = None) -> BoundWindow: ...
    def __get__(self, obj: object | None, owner: type | None = None) -> Window | BoundWindow:
        __tracebackhide__ = True
        if obj is None:
            return self
        return BoundWindow(obj, self)

    def __repr__(self) -> str:
        __tracebackhide__ = True
        return f"<Window {self.qualname} {self.locator.describe()}>"


class Element:
    """Describes one UI element by its UI Automation properties."""

    def __init__(
        self,
        *,
        automation_id: Matcher | None = None,
        name: Matcher | None = None,
        control_type: str | None = None,
        class_name: Matcher | None = None,
        index: int | None = None,
        depth: int | None = None,
        within: Element | None = None,
        window: Window | None = None,
        timeout: float | None = None,
    ) -> None:
        __tracebackhide__ = True
        self._init(
            automation_id, name, control_type, class_name, index, depth, within, window, timeout
        )

    def _init(
        self,
        automation_id: Matcher | None,
        name: Matcher | None,
        control_type: str | None,
        class_name: Matcher | None,
        index: int | None,
        depth: int | None,
        within: Element | None,
        window: Window | None,
        timeout: float | None,
    ) -> None:
        __tracebackhide__ = True
        if within is not None and (
            not isinstance(within, Element)  # pyright: ignore[reportUnnecessaryIsInstance]
            or isinstance(within, Elements)
        ):
            raise TypeError("within= must be an Element, not Elements or another type")
        if window is not None and not isinstance(window, Window):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError("window= must be a Window")
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must not be negative")
        self.within = within
        self.window = window
        self.timeout = timeout
        # Validates control_type, index/depth and the "needs at least one property" rule now,
        # at definition time, rather than on first use.
        self._own = Locator(
            automation_id=automation_id,
            name=name,
            control_type=control_type,
            class_name=class_name,
            index=index,
            depth=depth,
        )
        self.name: str | None = None
        self.owner: type | None = None
        self.source = _caller_source()

    def __set_name__(self, owner: type, name: str) -> None:
        __tracebackhide__ = True
        self.owner = owner
        self.name = name

    @property
    def qualname(self) -> str:
        __tracebackhide__ = True
        if self.owner is None or self.name is None:
            return "<anonymous>"
        return f"{self.owner.__qualname__}.{self.name}"

    def locator(self, *, include_window: bool = True) -> Locator:
        """The locator for this element, including its ``within`` chain and window override."""
        __tracebackhide__ = True
        within = self.within.locator(include_window=False) if self.within is not None else None
        window = self.window.locator if include_window and self.window is not None else None
        return dataclasses.replace(self._own, within=within, window=window)

    @overload
    def __get__(self, obj: None, owner: type | None = None) -> Element: ...
    @overload
    def __get__(self, obj: object, owner: type | None = None) -> BoundElement: ...
    def __get__(self, obj: object | None, owner: type | None = None) -> Element | BoundElement:
        __tracebackhide__ = True
        if obj is None:
            return self
        return BoundElement(obj, self)

    def __repr__(self) -> str:
        __tracebackhide__ = True
        return f"<{type(self).__name__} {self.qualname} {self.locator().describe()}>"


class Elements(Element):
    """Describes a group of elements matching one locator (no ``index``)."""

    def __init__(
        self,
        *,
        automation_id: Matcher | None = None,
        name: Matcher | None = None,
        control_type: str | None = None,
        class_name: Matcher | None = None,
        depth: int | None = None,
        within: Element | None = None,
        window: Window | None = None,
        timeout: float | None = None,
    ) -> None:
        __tracebackhide__ = True
        self._init(
            automation_id, name, control_type, class_name, None, depth, within, window, timeout
        )

    @overload  # type: ignore[override]
    def __get__(self, obj: None, owner: type | None = None) -> Elements: ...
    @overload
    def __get__(self, obj: object, owner: type | None = None) -> BoundElements: ...
    def __get__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, obj: object | None, owner: type | None = None
    ) -> Elements | BoundElements:
        __tracebackhide__ = True
        if obj is None:
            return self
        return BoundElements(obj, self)


class Page:
    """A page or dialog of the application: a collection of window and element definitions."""

    window: ClassVar[Window | None] = None

    def __init__(self, app: App) -> None:
        __tracebackhide__ = True
        self.app = app

    @classmethod
    def elements(cls) -> dict[str, Element]:
        """Declared ``Element``/``Elements`` attributes, base classes first."""
        __tracebackhide__ = True
        found: dict[str, Element] = {}
        for klass in reversed(cls.__mro__):
            for name, value in vars(klass).items():
                if isinstance(value, Element):
                    found[name] = value
        return found

    def check(self) -> dict[str, BaseException | None]:
        """Resolve every element once without waiting; maps attribute name to its error."""
        __tracebackhide__ = True
        results: dict[str, BaseException | None] = {}
        for name, definition in type(self).elements().items():
            try:
                if isinstance(definition, Elements):
                    resolve_all(_scope(self), definition.locator())
                else:
                    resolve(_scope(self), definition.locator())
                results[name] = None
            except (LocatorError, UIAError, ActionError) as exc:
                results[name] = exc
        return results


def _scope(page: Any) -> Scope:
    __tracebackhide__ = True
    app: App = page.app
    window: Any = getattr(type(page), "window", None)  # pyright: ignore[reportUnknownArgumentType]
    locator = window.locator if isinstance(window, Window) else None
    return Scope(app, locator)


def _default_timeout(definition: Element | None, per_call: float | None) -> float:
    __tracebackhide__ = True
    if per_call is not None:
        return per_call
    if definition is not None and definition.timeout is not None:
        return definition.timeout
    return runtime.get_config().timeout


def _matches_password(matcher: Matcher | None) -> bool:
    __tracebackhide__ = True
    if matcher is None:
        return False
    if isinstance(matcher, str):
        return matcher == _PASSWORD_CLASS
    return matcher.search(_PASSWORD_CLASS) is not None


def is_password_locator(locator: Locator) -> bool:
    """Whether any link of the locator targets a ``PasswordBox`` (its input is never logged)."""
    __tracebackhide__ = True
    return any(_matches_password(link.class_name) for link in locator.chain())


# -- bound elements -------------------------------------------------------------------------------


class _BoundBase:
    """Shared resolution logic of bound single elements and windows."""

    page: Any
    definition: Any

    def _timeout(self, per_call: float | None) -> float:
        __tracebackhide__ = True
        return _default_timeout(self.definition, per_call)

    def resolve_once(self) -> UIAElement:
        __tracebackhide__ = True
        raise NotImplementedError

    @property
    def qualname(self) -> str:
        __tracebackhide__ = True
        return str(self.definition.qualname)

    def _description(self) -> str:
        __tracebackhide__ = True
        return self.qualname

    def resolve(self, timeout: float | None = None) -> UIAElement:
        """Wait until the element exists (strictly one match) and return it."""
        __tracebackhide__ = True
        return waits.wait_until(
            self.resolve_once,
            self._timeout(timeout),
            description=f"{self._description()} to exist",
            retry_on=_RETRY_ON,
        )

    def exists(self, timeout: float = 0) -> bool:
        """Whether the element is found (``timeout`` > 0 waits for it to appear)."""
        __tracebackhide__ = True
        try:
            waits.wait_until(
                self.resolve_once,
                timeout,
                description=f"{self._description()} to exist",
                retry_on=_RETRY_ON,
            )
        except (ElementNotFoundError, WindowNotFoundError, WaitTimeoutError):
            return False
        except AmbiguousElementError:
            return True
        return True

    def is_visible(self) -> bool:
        """Whether the element exists and is on screen (a single attempt, no waiting)."""
        __tracebackhide__ = True
        try:
            return waits.element_state_ok(self.resolve_once(), "visible")
        except (LocatorError, UIAError):
            return False

    def info(self) -> ElementInfo:
        __tracebackhide__ = True
        return self.resolve().info(with_patterns=True)

    def wait_for(self, state: State = "visible", *, timeout: float | None = None) -> Any:
        """Wait until the element reaches ``state`` and return ``self``."""
        __tracebackhide__ = True
        waits.wait_for_state(
            self.resolve_once,
            state,
            self._timeout(timeout),
            f"{self._description()} to be {state}",
            retry_on=_RETRY_ON,
        )
        return self

    def highlight(self, duration_ms: int = 1500, *, timeout: float | None = None) -> None:
        """Flash an outline around the element (blocks for the duration)."""
        __tracebackhide__ = True
        element = self.resolve(timeout)
        rect = element.rect
        if rect is None:
            raise ActionError(f"{self._description()} has no on-screen rectangle to highlight")
        overlay.flash(rect, duration_ms, block=True)


class BoundWindow(_BoundBase):
    """A ``Window`` definition bound to a page's application."""

    def __init__(self, page: Any, definition: Window) -> None:
        __tracebackhide__ = True
        self.page = page
        self.definition = definition

    @property
    def locator(self) -> WindowLocator:
        __tracebackhide__ = True
        return self.definition.locator  # type: ignore[no-any-return]

    def _description(self) -> str:
        __tracebackhide__ = True
        return f"{self.qualname} {self.locator.describe()}"

    def resolve_once(self) -> UIAElement:
        __tracebackhide__ = True
        return resolve_window(self.page.app, self.locator)

    @property
    def title(self) -> str:
        __tracebackhide__ = True
        return self.resolve().name

    def close(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with runtime.step("window.close", self.qualname, self.locator.describe()):
            patterns.window_close(self.resolve(timeout))

    def maximize(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with runtime.step("window.maximize", self.qualname, self.locator.describe()):
            patterns.window_set_state(self.resolve(timeout), "maximized")

    def minimize(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with runtime.step("window.minimize", self.qualname, self.locator.describe()):
            patterns.window_set_state(self.resolve(timeout), "minimized")

    def restore(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with runtime.step("window.restore", self.qualname, self.locator.describe()):
            patterns.window_set_state(self.resolve(timeout), "normal")

    def __repr__(self) -> str:
        __tracebackhide__ = True
        return f"<BoundWindow {self.qualname} {self.locator.describe()}>"


class BoundElement(_BoundBase):
    """An ``Element`` definition bound to a page: resolves lazily and auto-waits."""

    def __init__(
        self, page: Any, definition: Element, locator_override: Locator | None = None
    ) -> None:
        __tracebackhide__ = True
        self.page = page
        self.definition = definition
        self._override = locator_override

    # -- identity -------------------------------------------------------------------------------

    @property
    def locator(self) -> Locator:
        __tracebackhide__ = True
        return self._override if self._override is not None else self.definition.locator()

    def _description(self) -> str:
        __tracebackhide__ = True
        return f"{self.qualname} {self.locator.describe()}"

    def _derive(self, locator: Locator) -> BoundElement:
        __tracebackhide__ = True
        return BoundElement(self.page, self.definition, locator)

    def __repr__(self) -> str:
        __tracebackhide__ = True
        return f"<BoundElement {self.qualname} {self.locator.describe()}>"

    # -- resolution and waiting -----------------------------------------------------------------

    def resolve_once(self) -> UIAElement:
        __tracebackhide__ = True
        return resolve(_scope(self.page), self.locator)

    def _actionable(self, timeout: float | None) -> UIAElement:
        """Wait until the element is attached and enabled (and visible unless it can scroll)."""
        __tracebackhide__ = True
        budget = self._timeout(timeout)
        unmet = ["to exist"]

        def poll() -> UIAElement | None:
            __tracebackhide__ = True
            element = self.resolve_once()
            if not element.is_enabled:
                unmet[0] = "to be enabled"
                return None
            if element.is_offscreen and not (
                patterns.has_pattern(element, "ScrollItem")
                or patterns.has_pattern(element, "VirtualizedItem")
            ):
                unmet[0] = "to be visible"
                return None
            return element

        try:
            return waits.wait_until(
                poll, budget, description=f"{self._description()} to exist", retry_on=_RETRY_ON
            )
        except WaitTimeoutError as exc:
            raise WaitTimeoutError(
                f"Timed out after {budget:.1f}s waiting for {self._description()} {unmet[0]}",
                last_error=exc.last_error,
                waited=exc.waited,
            ) from None

    def _perform(self, timeout: float | None, act: Callable[[UIAElement], _T]) -> _T:
        """Resolve and act; if the element vanishes mid-action, resolve and act once more."""
        __tracebackhide__ = True
        for attempt in range(2):
            element = self._actionable(timeout)
            self._maybe_highlight(element)
            try:
                return act(element)
            except UIAError as exc:
                if not exc.element_gone or attempt == 1:
                    raise
        raise AssertionError("unreachable")  # pragma: no cover

    def _maybe_highlight(self, element: UIAElement) -> None:
        __tracebackhide__ = True
        if runtime.get_config().highlight_actions:
            rect = element.rect
            if rect is not None:
                overlay.flash(rect, 400, block=True)

    def _step(
        self, action: str, args: Mapping[str, Any] | None = None, *, secret: bool = False
    ) -> AbstractContextManager[runtime.StepRecord]:
        __tracebackhide__ = True
        return runtime.step(action, self.qualname, self.locator.describe(), args, secret=secret)

    # -- actions --------------------------------------------------------------------------------

    def click(self, *, mode: InputMode | None = None, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        effective = mode or runtime.get_config().input_mode
        with self._step("click", {"mode": effective}) as record:
            record.args["strategy"] = self._perform(
                timeout, lambda el: actions.click(el, mode=effective)
            )

    def double_click(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self._step("double_click"):
            self._perform(timeout, actions.double_click)

    def right_click(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self._step("right_click"):
            self._perform(timeout, actions.right_click)

    def hover(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self._step("hover"):
            self._perform(timeout, actions.hover)

    def type(
        self, text: str, *, clear: bool = True, keys: bool = False, timeout: float | None = None
    ) -> None:
        __tracebackhide__ = True
        secret = is_password_locator(self.locator)
        with self._step("type", {"text": text, "clear": clear, "keys": keys}, secret=secret) as rec:
            rec.args["strategy"] = self._perform(
                timeout, lambda el: actions.type_text(el, text, clear=clear, keys=keys)
            )

    def clear(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self._step("clear"):
            self._perform(timeout, actions.clear)

    def press(self, keys: str, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self._step("press", {"keys": keys}):
            self._perform(timeout, lambda el: actions.press(el, keys))

    def select(self, item: str | int | re.Pattern[str], *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self._step("select", {"item": item}):
            self._perform(timeout, lambda el: actions.select(el, item))

    def check(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self._step("check"):
            self._perform(timeout, lambda el: actions.set_checked(el, True))

    def uncheck(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self._step("uncheck"):
            self._perform(timeout, lambda el: actions.set_checked(el, False))

    def expand(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self._step("expand"):
            self._perform(timeout, actions.expand)

    def collapse(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self._step("collapse"):
            self._perform(timeout, actions.collapse)

    def focus(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self._step("focus"):
            self._perform(timeout, actions.focus)

    def scroll_into_view(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self._step("scroll_into_view"):
            element = self.resolve(timeout)
            if patterns.has_pattern(element, "VirtualizedItem"):
                patterns.realize(element)
            if patterns.has_pattern(element, "ScrollItem"):
                patterns.scroll_into_view(element)
            else:
                actions.ensure_visible(element)

    # -- reads (wait for the element to exist only) ---------------------------------------------

    @property
    def text(self) -> str:
        __tracebackhide__ = True
        return actions.get_text(self.resolve())

    @property
    def value(self) -> str:
        __tracebackhide__ = True
        return actions.get_value(self.resolve())

    def is_enabled(self) -> bool:
        __tracebackhide__ = True
        return self.resolve().is_enabled

    def is_checked(self) -> bool:
        __tracebackhide__ = True
        return actions.is_checked(self.resolve())

    def selected_items(self) -> list[str]:
        __tracebackhide__ = True
        return actions.selected_items(self.resolve())

    # -- derivation -----------------------------------------------------------------------------

    def nth(self, i: int) -> BoundElement:
        """The ``i``-th match (0-based) of this locator."""
        __tracebackhide__ = True
        return self._derive(self.locator.with_index(i))

    def row(self, i: int) -> BoundElement:
        """Row ``i`` (0-based) of a grid element."""
        __tracebackhide__ = True
        return self._derive(self.locator.with_item(ItemSelector("row", i)))

    def cell(self, row: int, column: int | str) -> BoundElement:
        """The cell at ``row`` and ``column`` (index or header name) of a grid element."""
        __tracebackhide__ = True
        return self._derive(self.locator.with_item(ItemSelector("cell", row, column)))

    def row_count(self) -> int:
        __tracebackhide__ = True
        return patterns.grid_size(self.resolve())[0]

    def column_count(self) -> int:
        __tracebackhide__ = True
        return patterns.grid_size(self.resolve())[1]

    def find_row(
        self, column: int | str, value: Matcher, *, timeout: float | None = None
    ) -> BoundElement:
        """The first row whose ``column`` cell equals (or matches) ``value``."""
        __tracebackhide__ = True
        grid = self.resolve(timeout)
        rows, columns = patterns.grid_size(grid)
        if rows > _MAX_FIND_ROW_ROWS:
            raise ActionError(
                f"find_row() refuses to scan {rows} rows (limit {_MAX_FIND_ROW_ROWS}); "
                "narrow the grid or use row(i)"
            )
        if isinstance(column, str):
            names = [header.name for header in patterns.column_headers(grid)]
            if column not in names:
                raise ActionError(f"{self.qualname} has no column {column!r} (columns: {names})")
            column_index = names.index(column)
        else:
            column_index = column
        if not 0 <= column_index < columns:
            raise ActionError(f"column {column!r} is out of range (grid has {columns} columns)")
        for index in range(rows):
            cell = patterns.grid_item(grid, index, column_index)
            if match_value(value, actions.get_text(cell)):
                return self.row(index)
        shown = value if isinstance(value, str) else f"/{value.pattern}/"
        raise ElementNotFoundError(_find_row_diagnostic(self, column, shown, rows))


def _find_row_diagnostic(bound: BoundElement, column: int | str, shown: str, rows: int) -> Any:
    __tracebackhide__ = True
    from wintestkit.engine.diagnose import Diagnostic

    description = bound.locator.describe()
    return Diagnostic(
        kind="not_found",
        message=f"No row with {column!r} = {shown!r} in {bound.qualname} ({rows} rows scanned)",
        locator=description,
        searched_in=bound.qualname,
        match_count=0,
    )


class BoundElements:
    """An ``Elements`` definition bound to a page: all matches of one locator."""

    def __init__(
        self, page: Any, definition: Elements, locator_override: Locator | None = None
    ) -> None:
        __tracebackhide__ = True
        self.page = page
        self.definition = definition
        self._override = locator_override

    @property
    def locator(self) -> Locator:
        __tracebackhide__ = True
        return self._override if self._override is not None else self.definition.locator()

    @property
    def qualname(self) -> str:
        __tracebackhide__ = True
        return self.definition.qualname

    def _description(self) -> str:
        __tracebackhide__ = True
        return f"{self.qualname} {self.locator.describe()}"

    def __repr__(self) -> str:
        __tracebackhide__ = True
        return f"<BoundElements {self.qualname} {self.locator.describe()}>"

    def resolve_all(self) -> list[UIAElement]:
        __tracebackhide__ = True
        return resolve_all(_scope(self.page), self.locator)

    def count(self, *, timeout: float = 0) -> int:
        """Number of matches; waits up to ``timeout`` seconds for at least one.

        For virtualized lists this counts only the items that are currently realized.
        """
        __tracebackhide__ = True
        try:
            return len(
                waits.wait_until(
                    lambda: self.resolve_all() or None,
                    timeout,
                    description=f"{self._description()} to exist",
                )
            )
        except (WaitTimeoutError, ElementNotFoundError, WindowNotFoundError):
            return 0

    def nth(self, i: int) -> BoundElement:
        __tracebackhide__ = True
        return BoundElement(self.page, self.definition, self.locator.with_index(i))

    def first(self) -> BoundElement:
        __tracebackhide__ = True
        return self.nth(0)

    def last(self) -> BoundElement:
        __tracebackhide__ = True
        total = self.count()
        if total == 0:
            raise ActionError(f"{self.qualname} matches no elements, so it has no last()")
        return self.nth(total - 1)

    def all(self) -> list[BoundElement]:
        __tracebackhide__ = True
        return [self.nth(i) for i in range(self.count())]

    def texts(self) -> list[str]:
        __tracebackhide__ = True
        return [actions.get_text(element) for element in self.resolve_all()]

    def filter(
        self,
        *,
        name: Matcher | None = None,
        class_name: Matcher | None = None,
        automation_id: Matcher | None = None,
    ) -> BoundElements:
        """A copy of this collection narrowed by additional properties of the final link."""
        __tracebackhide__ = True
        changes = {
            key: value
            for key, value in (
                ("name", name),
                ("class_name", class_name),
                ("automation_id", automation_id),
            )
            if value is not None
        }
        return BoundElements(
            self.page, self.definition, dataclasses.replace(self.locator, **changes)
        )

    def __iter__(self) -> Iterator[BoundElement]:
        __tracebackhide__ = True
        return iter(self.all())

    def __len__(self) -> int:
        __tracebackhide__ = True
        return self.count()
