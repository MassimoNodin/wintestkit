"""The test-facing model: ``Page``, ``Window``, ``Element`` and their bound counterparts.

Users declare elements as class attributes of a ``Page`` subclass. Accessing an attribute on the
class returns the definition; accessing it on an instance returns a *bound* object that resolves
the locator lazily and auto-waits before every action.
"""

# Page objects and the module-level locator helpers cooperate on private state by design.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import copy
import dataclasses
import inspect
import os
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from types import FrameType
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    Literal,
    Self,
    TypedDict,
    TypeVar,
    Unpack,
    cast,
    get_args,
    get_origin,
    overload,
)

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.engine import actions, overlay, relocate, waits
from wintestkit.engine.diagnose import Relocation
from wintestkit.engine.locator import (
    ItemSelector,
    Locator,
    Matcher,
    WindowLocator,
    match_value,
)
from wintestkit.engine.properties import WhereValue, normalize_where
from wintestkit.engine.resolve import Scope, resolve, resolve_all, resolve_window
from wintestkit.engine.waits import State
from wintestkit.errors import (
    ActionError,
    AmbiguousElementError,
    ElementNotFoundError,
    ElementTypeError,
    LocatorError,
    UIAError,
    WaitTimeoutError,
    WindowNotFoundError,
    WtkError,
)
from wintestkit.uia import patterns
from wintestkit.uia.element import ElementInfo, UIAElement

__all__ = [
    "BoundControl",
    "BoundElement",
    "BoundElements",
    "BoundWindow",
    "Element",
    "Elements",
    "Page",
    "PageObject",
    "Window",
    "is_password_locator",
]

_T = TypeVar("_T")
if TYPE_CHECKING:
    # A defaulted type variable (PEP 696): a bare ``Element(...)`` means ``Element[BoundElement]``.
    from typing_extensions import TypeVar as _DefaultedTypeVar

    from wintestkit import controls as _controls

    B = _DefaultedTypeVar("B", bound="BoundControl", covariant=True, default="BoundElement")
else:
    B = TypeVar("B", bound="BoundControl", covariant=True)
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


class ChildOptions(TypedDict, total=False):
    """Options of ``parent.Element(...)`` and the typed child methods (``parent.Button(...)``).

    There is no ``within``, ``depth`` or ``window``: a child is always searched among the direct
    children of its parent, in the parent's window.
    """

    automation_id: Matcher
    name: Matcher
    control_type: str
    class_name: Matcher
    index: int
    timeout: float
    validate: bool
    where: Mapping[str, WhereValue]


class ChildGroupOptions(TypedDict, total=False):
    """Options of ``parent.Elements(...)``: like ``ChildOptions`` without ``index``/``validate``."""

    automation_id: Matcher
    name: Matcher
    control_type: str
    class_name: Matcher
    timeout: float
    where: Mapping[str, WhereValue]


_CHILD_FORBIDDEN = ("within", "depth", "window")


def _child_options(kind: str, options: Mapping[str, Any]) -> dict[str, Any]:
    """The options of a child declaration, refusing the ones a child cannot take."""
    __tracebackhide__ = True
    clash = [key for key in _CHILD_FORBIDDEN if key in options]
    if clash:
        raise TypeError(
            f"{kind}() on an element searches its direct children in its window: "
            f"drop {', '.join(key + '=' for key in clash)}"
        )
    return dict(options)


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
        where: Mapping[str, WhereValue] | None = None,
    ) -> None:
        __tracebackhide__ = True
        self.locator = WindowLocator(
            title=title,
            process=process,
            class_name=class_name,
            automation_id=automation_id,
            index=index,
            where=normalize_where(where, {}),
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


class PageObject:
    """A page (one window) or a reusable component (a box with a ``root``), lazily bound.

    A component is mounted on a parent with ``address = AddressBox()``; the mount may override the
    component's ``root`` and ``window`` for that one use: ``AddressBox(root=Element(...))``.
    """

    window: ClassVar[Window | None] = None
    root: ClassVar[_AnyElement | None] = None
    app: App

    def __init__(
        self,
        app: App | PageObject | None = None,
        *,
        root: _AnyElement | None = None,
        window: Window | None = None,
    ) -> None:
        __tracebackhide__ = True
        if root is not None and (
            not isinstance(root, Element)  # pyright: ignore[reportUnnecessaryIsInstance]
            or isinstance(root, Elements)
        ):
            raise TypeError("root= must be an Element, not Elements or another type")
        if window is not None and not isinstance(window, Window):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError("window= must be a Window")
        self._parent: PageObject | None = app if isinstance(app, PageObject) else None
        self._children: dict[str, PageObject] = {}
        self._attribute: str | None = None
        self._root_override = root
        self._window_override = window
        self._source = _caller_source()  # where the page or mount was written, for diagnostics
        if app is not None:
            self.app = app.app if isinstance(app, PageObject) else app
        self._bind_window_override()

    def _bind_window_override(self) -> None:
        """A mount's ``window=`` is the instance's ``window`` even if the class declares none."""
        __tracebackhide__ = True
        override = self._window_override
        if override is not None and type(self).window is None:
            self.__dict__["window"] = BoundWindow(self, override)

    def __set_name__(self, owner: type, name: str) -> None:
        __tracebackhide__ = True
        self._attribute = name
        override = self._root_override
        if override is not None and override.owner is None:
            override.owner = owner
            override.name = f"{name}.root"

    def __get__(self, obj: PageObject | None, owner: type | None = None) -> Self:
        __tracebackhide__ = True
        if obj is None:
            return self
        if self._attribute is None:
            raise TypeError("Child page objects must be declared as class attributes")
        if self._attribute not in obj._children:
            ancestor: PageObject | None = obj
            while ancestor is not None:
                if type(ancestor) is type(self):
                    raise TypeError("Cyclic page-object composition")
                ancestor = ancestor._parent
            # The class-level declaration is a template; every parent instance gets its own copy.
            child = copy.copy(self)
            child._parent = obj
            child.app = obj.app
            child._children = {}
            child._bind_window_override()
            obj._children[self._attribute] = child
        return cast("Self", obj._children[self._attribute])

    # -- declarations ---------------------------------------------------------------------------

    @classmethod
    def elements(cls) -> dict[str, _AnyElement]:
        """Declared ``Element``/``Elements`` attributes, base classes first."""
        __tracebackhide__ = True
        found: dict[str, _AnyElement] = {}
        for klass in reversed(cls.__mro__):
            for name, value in vars(klass).items():
                if isinstance(value, Element):
                    found[name] = value
        return found

    @classmethod
    def children(cls) -> dict[str, PageObject]:
        """Components mounted on this class (``address = AddressBox()``), base classes first."""
        __tracebackhide__ = True
        found: dict[str, PageObject] = {}
        for klass in reversed(cls.__mro__):
            for name, value in vars(klass).items():
                if isinstance(value, PageObject):
                    found[name] = value
                else:
                    found.pop(name, None)
        return found

    def _effective_root(self) -> _AnyElement | None:
        __tracebackhide__ = True
        return self._root_override if self._root_override is not None else type(self).root

    def _effective_window(self) -> Window | None:
        __tracebackhide__ = True
        return self._window_override if self._window_override is not None else type(self).window

    def _is_root(self, definition: _AnyElement) -> bool:
        __tracebackhide__ = True
        return definition is self._root_override or definition is type(self).root

    def _path(self) -> str | None:
        """``Home.address`` for a mounted component; ``None`` for a page without a parent."""
        __tracebackhide__ = True
        parts: list[str] = []
        node = self
        while node._parent is not None:
            parts.append(node._attribute or type(node).__name__)
            node = node._parent
        if not parts:
            return None
        parts.append(type(node).__qualname__)
        return ".".join(reversed(parts))

    def declared(self) -> dict[str, _AnyElement]:
        """Declared elements with the effective ``root`` (a mount may override it) first."""
        __tracebackhide__ = True
        found = type(self).elements()
        root = self._effective_root()
        if root is None:
            return found
        return {"root": root, **{k: v for k, v in found.items() if k != "root"}}

    def bound_at(self, path: str) -> Any:
        """The bound element or window at a dotted path such as ``address.street``.

        A component on its own means its ``root``, or its window when it declares no root. A
        window that is not declared falls back to the application's main window.
        """
        __tracebackhide__ = True
        owner: PageObject = self
        *components, last = path.split(".")
        for part in components:
            child = getattr(owner, part, None)
            if not isinstance(child, PageObject):
                raise AttributeError(f"{part!r} is not a component of {type(owner).__name__}")
            owner = child
        bound: Any = getattr(owner, last, None)
        if isinstance(bound, PageObject):
            owner = bound
            last = "root" if owner._effective_root() is not None else "window"
            bound = getattr(owner, last, None)
        if bound is None:
            return BoundWindow(owner, owner._effective_window() or Window())
        return bound

    def check(self) -> dict[str, BaseException | None]:
        """Resolve every element once without waiting; maps attribute path to its error.

        Mounted components are checked recursively under dotted paths (``address.street``,
        ``address.root``).
        """
        __tracebackhide__ = True
        return self._check("")

    def _check(self, prefix: str) -> dict[str, BaseException | None]:
        __tracebackhide__ = True
        results: dict[str, BaseException | None] = {}
        for name, definition in self.declared().items():
            try:
                if isinstance(definition, Elements):
                    resolve_all(_scope(self), _element_locator(self, definition))
                else:
                    definition.__get__(self, type(self)).resolve_once()
                results[prefix + name] = None
            except (LocatorError, UIAError, ActionError) as exc:
                if isinstance(exc, LocatorError) and not isinstance(definition, Elements):
                    _explain_relocation(definition.__get__(self, type(self)), exc)
                results[prefix + name] = exc
        for name in type(self).children():
            try:
                child = cast("PageObject", getattr(self, name))
            except TypeError as exc:  # cyclic composition
                results[prefix + name] = exc
                continue
            results.update(child._check(f"{prefix}{name}."))
        return results


Page = PageObject


def _scope(page: PageObject) -> Scope:
    """The window to search: the mount's, else the root's, else the class's, else an ancestor's."""
    __tracebackhide__ = True
    current: PageObject | None = page
    while current is not None:
        window = current._window_override
        root = current._effective_root()
        if window is None and root is not None:
            window = root.window
        if window is None:
            window = type(current).window
        if window is not None:
            return Scope(page.app, window.locator)
        current = current._parent
    return Scope(page.app)


def scope_window(page: PageObject) -> WindowLocator | None:
    """The window locator the page's elements are searched in (``None``: the main window)."""
    __tracebackhide__ = True
    return _scope(page).window


def _root_locator(page: PageObject, root: _AnyElement, *, windowed: bool) -> Locator:
    """The component's root: searched in its window, never beneath the parent's root.

    The ``within`` chain of a per-mount root override names elements of the mounting parent, so it
    is scoped by the parent's rules; a class-level root's chain is used as written.
    """
    __tracebackhide__ = True
    within: Locator | None = None
    if root.within is not None:
        if root is page._root_override and page._parent is not None:
            within = _component_locator(page._parent, root.within, windowed=False)
        else:
            within = root.within.locator(include_window=False)
    window = root.window.locator if windowed and root.window is not None else None
    return dataclasses.replace(root._own, within=within, window=window)


def _component_locator(page: PageObject, definition: _AnyElement, *, windowed: bool) -> Locator:
    """``definition`` as a locator: beneath the page's own ``root`` if it declares one."""
    __tracebackhide__ = True
    root = page._effective_root()
    if root is not None and page._is_root(definition):
        return _root_locator(page, root, windowed=windowed)
    if definition.within is not None:
        within = _component_locator(page, definition.within, windowed=False)
    elif root is not None:
        within = _root_locator(page, root, windowed=False)
    else:
        within = None
    window = definition.window.locator if windowed and definition.window is not None else None
    return dataclasses.replace(definition._own, within=within, window=window)


def _element_locator(page: PageObject, definition: _AnyElement) -> Locator:
    __tracebackhide__ = True
    if definition.window is not None and not page._is_root(definition):
        return definition.locator()  # an explicit window opts out of the page's root
    return _component_locator(page, definition, windowed=True)


def _qualified_name(page: Any, definition: _AnyElement | Window) -> str:
    """``Home.address.street`` for a mounted component's member, else the definition's own."""
    __tracebackhide__ = True
    path = page._path() if isinstance(page, PageObject) else None
    if path is None:
        return definition.qualname
    if isinstance(definition, Element) and page._is_root(definition):
        return f"{path}.root"
    return f"{path}.{definition.name or ('window' if isinstance(definition, Window) else '?')}"


def _display_location(source: tuple[str, int] | None) -> str | None:
    """``pages/home.py:12``: the path relative to the working directory when it is beneath it."""
    __tracebackhide__ = True
    if source is None:
        return None
    file, line = source
    try:
        relative = os.path.relpath(file)
    except ValueError:  # another drive
        relative = file
    shown = file if relative.startswith("..") else relative
    return f"{shown.replace(os.sep, '/')}:{line}"


_RELOCATABLE_KINDS = ("not_found", "window_not_found")


def _relocatable(exc: LocatorError) -> bool:
    """Only a plain "nothing matched" can mean the element moved (not ambiguity or bad indexes)."""
    __tracebackhide__ = True
    if not isinstance(exc, ElementNotFoundError | WindowNotFoundError):
        return False
    innermost = exc.diagnostic
    while innermost.within is not None:
        innermost = innermost.within
    return innermost.kind in _RELOCATABLE_KINDS


def _declared_window(page: PageObject) -> UIAElement | None:
    __tracebackhide__ = True
    try:
        return resolve_window(page.app, _scope(page).window)
    except (LocatorError, UIAError, WtkError):
        return None


def _hint(page: PageObject, box_moved: bool) -> str:
    __tracebackhide__ = True
    if not box_moved:
        return (
            "the element moved to another window — declare it on the page for that window, "
            "or set `window=` on it"
        )
    if page._parent is None:
        return "the page's root moved to another window — point the page's `window` at it"
    mount = f"{page._attribute} = {type(page).__name__}()"
    where = _display_location(page._source)
    shown = f"`{mount}` ({where})" if where else f"`{mount}`"
    return f"the box moved — move {shown} to the page for that window, or set its window"


def _same_window_hint(
    page: PageObject, definition: _AnyElement, root: _AnyElement | None, is_root: bool
) -> str:
    """The element is in the declared window, just not under the container its locator names."""
    __tracebackhide__ = True
    if root is not None and not is_root:
        where = _display_location(root.source)
        return (
            "the component root locator no longer matches the container of this element — "
            f"update `root`{f' at {where}' if where else ''}"
        )
    where = _display_location(definition.source)
    at = f" at {where}" if where else ""
    if is_root:
        return f"the root's `within=` chain no longer matches the container — update `root`{at}"
    return f"the container locator no longer matches — update the `within=` chain{at}"


def _explain_relocation(bound: BoundControl, exc: LocatorError) -> None:
    """Search the application's other windows for a not-found element and annotate ``exc``.

    Diagnosis only: nothing found here is ever used for an action. Runs at most once per error and
    within ``relocate.RELOCATE_BUDGET`` seconds.
    """
    __tracebackhide__ = True
    page, definition = bound.page, bound.definition
    if (
        exc.diagnostic.relocations
        or definition.ad_hoc
        or bound.locator.item is not None
        or not isinstance(page, PageObject)
        or not _relocatable(exc)
    ):
        return
    app = getattr(page, "app", None)
    if app is None:
        return
    deadline = relocate.new_deadline()
    root = page._effective_root()
    is_root = root is not None and page._is_root(definition)
    mounted = page._parent is not None
    kind: Literal["element", "component_root"] = (
        "component_root" if is_root and mounted else "element"
    )
    target = _qualified_name(page, definition)
    found: list[Relocation] = []
    declared_window = _declared_window(page)
    hits = relocate.find_elsewhere(
        app, definition._own, declared=declared_window, deadline=deadline
    )
    for hit in hits:
        shown = f"{target} ({type(page).__name__})" if kind == "component_root" else target
        found.append(Relocation(kind, shown, hit.window, hit.path, hit.same_window))
    other_window = any(not hit.same_window for hit in hits)
    box_moved = kind == "component_root" and other_window
    if root is not None and not is_root:
        root_name = _qualified_name(page, root)
        roots = relocate.find_elsewhere(app, root._own, exclude=declared_window, deadline=deadline)
        for hit in roots:
            shown = f"{root_name} ({type(page).__name__})"
            found.append(Relocation("component_root", shown, hit.window, hit.path))
        box_moved = box_moved or bool(roots)
        other_window = other_window or bool(roots)
    if not found:
        return
    if other_window:
        hint = _hint(page, box_moved)
    else:
        hint = _same_window_hint(page, definition, root, is_root)
    diagnostic = dataclasses.replace(
        exc.diagnostic,
        relocations=tuple(found[: relocate.MAX_MATCHES]),
        hint=hint,
        declared=_display_location(definition.source),
    )
    exc.diagnostic = diagnostic
    exc.message = "\n".join([exc.message, *diagnostic.relocation_lines()])
    exc.args = (exc.message,)


def _default_timeout(definition: _AnyElement | None, per_call: float | None) -> float:
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
        return _qualified_name(self.page, self.definition)

    def _description(self) -> str:
        __tracebackhide__ = True
        return self.qualname

    def explain_relocation(self, exc: LocatorError) -> None:
        """Annotate a not-found error with where the element was found instead (elements only)."""
        __tracebackhide__ = True

    def resolve(self, timeout: float | None = None) -> UIAElement:
        """Wait until the element exists (strictly one match) and return it."""
        __tracebackhide__ = True
        try:
            return waits.wait_until(
                self.resolve_once,
                self._timeout(timeout),
                description=f"{self._description()} to exist",
                retry_on=_RETRY_ON,
            )
        except LocatorError as exc:
            self.explain_relocation(exc)
            raise

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
        try:
            waits.wait_for_state(
                self.resolve_once,
                state,
                self._timeout(timeout),
                f"{self._description()} to be {state}",
                retry_on=_RETRY_ON,
            )
        except LocatorError as exc:
            self.explain_relocation(exc)
            raise
        return self

    def highlight(self, duration_ms: int = 1500, *, timeout: float | None = None) -> None:
        """Bring the owning window forward, then flash an outline (blocks for the duration)."""
        __tracebackhide__ = True
        element = self.resolve(timeout)
        actions.bring_to_front(element)
        rect = element.rect
        if rect is None:
            raise ActionError(f"{self._description()} has no on-screen rectangle to highlight")
        overlay.flash(
            rect,
            duration_ms,
            color=overlay.parse_color(runtime.get_config().highlight_color),
            block=True,
        )


class BoundWindow(_BoundBase):
    """A ``Window`` definition bound to a page's application."""

    def __init__(self, page: Any, definition: Window) -> None:
        __tracebackhide__ = True
        self.page = page
        self.definition = definition

    @property
    def locator(self) -> WindowLocator:
        __tracebackhide__ = True
        page = self.page
        if (
            isinstance(page, PageObject)
            and page._window_override is not None
            and self.definition is type(page).window
        ):
            return page._window_override.locator  # a mount may swap the component's window
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


class BoundControl(_BoundBase):
    """A declared element bound to a page: resolves lazily and auto-waits before every action.

    This is the common base of every typed element (``Button``, ``ComboBox`` ...) and of
    ``BoundElement``. It offers resolution, waiting, reading ``text`` and the actions every control
    has (``focus``, ``hover``, ``scroll_into_view``). Controls add their own actions on top.

    Subclass it to support a custom control, and write its actions with :meth:`perform` and
    :meth:`step` so they auto-wait and appear in the report like the built-in ones.
    """

    #: UIA patterns the matched element must support to count as this control. Every entry must
    #: be present; ``"A|B"`` accepts either pattern.
    required_patterns: ClassVar[tuple[str, ...]] = ()
    #: Control types that count as this control when it has no ``required_patterns``.
    accepted_control_types: ClassVar[tuple[str, ...]] = ()

    def __init__(
        self, page: Any, definition: _AnyElement, locator_override: Locator | None = None
    ) -> None:
        __tracebackhide__ = True
        self.page = page
        self.definition = definition
        self._override = locator_override

    # -- identity -------------------------------------------------------------------------------

    @property
    def locator(self) -> Locator:
        __tracebackhide__ = True
        return (
            self._override
            if self._override is not None
            else _element_locator(self.page, self.definition)
        )

    def _description(self) -> str:
        __tracebackhide__ = True
        return f"{self.qualname} {self.locator.describe()}"

    def explain_relocation(self, exc: LocatorError) -> None:
        __tracebackhide__ = True
        _explain_relocation(self, exc)

    def _derive(self, locator: Locator) -> Self:
        __tracebackhide__ = True
        return type(self)(self.page, self.definition, locator)

    def __repr__(self) -> str:
        __tracebackhide__ = True
        return f"<{type(self).__name__} {self.qualname} {self.locator.describe()}>"

    # -- type validation ------------------------------------------------------------------------

    def check_type(self, element: UIAElement) -> None:
        """Raise ``ElementTypeError`` when ``element`` cannot be this control.

        The default checks ``required_patterns`` (or ``accepted_control_types`` when there are no
        patterns). Override it for a custom rule. It runs on every resolution unless the
        declaration was made with ``validate=False``.
        """
        __tracebackhide__ = True
        if self.required_patterns:
            missing = [
                spec
                for spec in self.required_patterns
                if not any(patterns.has_pattern(element, name) for name in spec.split("|"))
            ]
            if missing:
                raise self.type_mismatch(
                    element, "does not support the " + " and ".join(missing) + " pattern"
                )
        elif (
            self.accepted_control_types and element.control_type not in self.accepted_control_types
        ):
            raise self.type_mismatch(
                element, "is not one of the control types " + ", ".join(self.accepted_control_types)
            )

    def type_mismatch(self, element: UIAElement, reason: str) -> ElementTypeError:
        """The error for an element that does not fit the declared type (for ``check_type``)."""
        __tracebackhide__ = True
        declared = type(self.definition).__name__
        return ElementTypeError(
            f"{self.qualname} is declared as {declared} but matched control type "
            f"{element.control_type!r} (class {element.class_name!r}, name {element.name!r}), "
            f"which {reason}. Fix the locator, declare it as the right type or as a plain "
            "Element, or pass validate=False"
        )

    # -- resolution and waiting -----------------------------------------------------------------

    def resolve_once(self) -> UIAElement:
        __tracebackhide__ = True
        element = resolve(_scope(self.page), self.locator)
        if self.definition.validate:
            self.check_type(element)
        try:
            if (
                runtime.object_previews_active()
                and not isinstance(self.definition, Elements)
                and self.locator.item is None
            ):
                from wintestkit.object_previews import capture_bound

                capture_bound(self, element)
        except Exception:
            pass
        return element

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
        except LocatorError as exc:
            self.explain_relocation(exc)
            raise
        except WaitTimeoutError as exc:
            raise WaitTimeoutError(
                f"Timed out after {budget:.1f}s waiting for {self._description()} {unmet[0]}",
                last_error=exc.last_error,
                waited=exc.waited,
            ) from None

    def perform(self, timeout: float | None, act: Callable[[UIAElement], _T]) -> _T:
        """Wait until the element is actionable, then run ``act`` on it and return its result.

        This is the hook for writing actions: it auto-waits (exists, enabled, visible), highlights
        when configured, and resolves and acts once more if the element vanishes mid-action.
        """
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
                overlay.flash(
                    rect,
                    400,
                    color=overlay.parse_color(runtime.get_config().highlight_color),
                    block=True,
                )

    def step(
        self, action: str, args: Mapping[str, Any] | None = None, *, secret: bool = False
    ) -> AbstractContextManager[runtime.StepRecord]:
        """Report an action as a step (``with self.step("pick", {"date": ...}): ...``).

        ``secret=True`` hides the arguments in logs and reports.
        """
        __tracebackhide__ = True
        return runtime.step(action, self.qualname, self.locator.describe(), args, secret=secret)

    # -- actions every control has --------------------------------------------------------------

    def hover(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("hover"):
            self.perform(timeout, actions.hover)

    def focus(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("focus"):
            self.perform(timeout, actions.focus)

    def scroll_into_view(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("scroll_into_view"):
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
        """The element's text: its value, document text or UIA name."""
        __tracebackhide__ = True
        return actions.get_text(self.resolve())

    def is_enabled(self) -> bool:
        __tracebackhide__ = True
        return self.resolve().is_enabled

    # -- derivation -----------------------------------------------------------------------------

    def nth(self, i: int) -> Self:
        """The ``i``-th match (0-based) of this locator."""
        __tracebackhide__ = True
        return self._derive(self.locator.with_index(i))

    # -- children: ``page.panel.Button(name="OK")`` searches the direct children of ``panel`` -----

    def _bind_child(self, kind: str, options: Mapping[str, Any]) -> Any:
        """A direct child of this element, bound on the fly (nothing is searched yet)."""
        __tracebackhide__ = True
        parent = self.locator
        if parent.item is not None:
            raise ActionError(
                f"{self.qualname} is a grid row or cell: it cannot be searched for children"
            )
        definition: _AnyElement = self.definition._declare_child(kind, options)
        definition.owner = self.definition.owner
        definition.name = f"{self.definition.name}.{kind}"
        definition.ad_hoc = True
        locator = dataclasses.replace(
            definition._own, within=dataclasses.replace(parent, window=None), window=parent.window
        )
        if isinstance(definition, Elements):
            return BoundElements(self.page, definition, locator)
        return type(definition)._bound(self.page, definition, locator)

    def Element(self, **options: Unpack[ChildOptions]) -> BoundElement:
        """A control that is a direct child of this element."""
        __tracebackhide__ = True
        return cast("BoundElement", self._bind_child("Element", options))

    def Elements(self, **options: Unpack[ChildGroupOptions]) -> BoundElements:
        """All the direct children of this element that match."""
        __tracebackhide__ = True
        return cast("BoundElements", self._bind_child("Elements", options))

    def Button(self, **options: Unpack[ChildOptions]) -> _controls.BoundButton:
        __tracebackhide__ = True
        return cast("_controls.BoundButton", self._bind_child("Button", options))

    def CheckBox(self, **options: Unpack[ChildOptions]) -> _controls.BoundCheckBox:
        __tracebackhide__ = True
        return cast("_controls.BoundCheckBox", self._bind_child("CheckBox", options))

    def ComboBox(self, **options: Unpack[ChildOptions]) -> _controls.BoundComboBox:
        __tracebackhide__ = True
        return cast("_controls.BoundComboBox", self._bind_child("ComboBox", options))

    def DataGrid(self, **options: Unpack[ChildOptions]) -> _controls.BoundDataGrid:
        __tracebackhide__ = True
        return cast("_controls.BoundDataGrid", self._bind_child("DataGrid", options))

    def ListBox(self, **options: Unpack[ChildOptions]) -> _controls.BoundListBox:
        __tracebackhide__ = True
        return cast("_controls.BoundListBox", self._bind_child("ListBox", options))

    def ListItem(self, **options: Unpack[ChildOptions]) -> _controls.BoundListItem:
        __tracebackhide__ = True
        return cast("_controls.BoundListItem", self._bind_child("ListItem", options))

    def RadioButton(self, **options: Unpack[ChildOptions]) -> _controls.BoundRadioButton:
        __tracebackhide__ = True
        return cast("_controls.BoundRadioButton", self._bind_child("RadioButton", options))

    def TabControl(self, **options: Unpack[ChildOptions]) -> _controls.BoundTabControl:
        __tracebackhide__ = True
        return cast("_controls.BoundTabControl", self._bind_child("TabControl", options))

    def Text(self, **options: Unpack[ChildOptions]) -> _controls.BoundText:
        __tracebackhide__ = True
        return cast("_controls.BoundText", self._bind_child("Text", options))

    def TextBox(self, **options: Unpack[ChildOptions]) -> _controls.BoundTextBox:
        __tracebackhide__ = True
        return cast("_controls.BoundTextBox", self._bind_child("TextBox", options))

    def TreeView(self, **options: Unpack[ChildOptions]) -> _controls.BoundTreeView:
        __tracebackhide__ = True
        return cast("_controls.BoundTreeView", self._bind_child("TreeView", options))


# Each mixin below holds the actions of one family of controls. ``BoundElement`` combines them all;
# the typed controls in ``wintestkit.controls`` pick only what applies.


class _Clickable(BoundControl):
    def click(self, *, mode: InputMode | None = None, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        effective = mode or runtime.get_config().input_mode
        with self.step("click", {"mode": effective}) as record:
            record.args["strategy"] = self.perform(
                timeout, lambda el: actions.click(el, mode=effective)
            )

    def double_click(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("double_click"):
            self.perform(timeout, actions.double_click)

    def right_click(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("right_click"):
            self.perform(timeout, actions.right_click)


class _Valued(BoundControl):
    @property
    def value(self) -> str:
        """The ValuePattern value (for a combo box, the text of its edit part)."""
        __tracebackhide__ = True
        return actions.get_value(self.resolve())


class _TextEntry(_Valued):
    def type(
        self,
        text: str,
        *,
        clear: bool = True,
        keys: bool = False,
        timeout: float | None = None,
        secret: bool = False,
    ) -> None:
        """Type text; password controls and explicit secrets hide input and failure details."""
        __tracebackhide__ = True
        secret = secret or is_password_locator(self.locator)
        args = {"text": text, "clear": clear, "keys": keys}
        with self.step("type", args, secret=True) as rec:

            def enter(el: UIAElement) -> str:
                __tracebackhide__ = True
                nonlocal secret
                rec.sensitive = True
                secret = secret or actions.is_password(el)
                rec.set_arguments(args, secret=secret)
                return actions.type_text(el, text, clear=clear, keys=keys)

            rec.args["strategy"] = self.perform(timeout, enter)

    def clear(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("clear"):
            self.perform(timeout, actions.clear)

    def press(self, keys: str, *, timeout: float | None = None, secret: bool = False) -> None:
        """Press keys; use secret=True to hide sensitive input on non-password controls."""
        __tracebackhide__ = True
        secret = secret or is_password_locator(self.locator)
        with self.step("press", {"keys": keys}, secret=True) as rec:

            def send(el: UIAElement) -> None:
                __tracebackhide__ = True
                nonlocal secret
                rec.sensitive = True
                secret = secret or actions.is_password(el)
                rec.set_arguments({"keys": keys}, secret=secret)
                actions.press(el, keys)

            self.perform(timeout, send)


class _Checkable(BoundControl):
    def check(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("check"):
            self.perform(timeout, lambda el: actions.set_checked(el, True))

    def uncheck(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("uncheck"):
            self.perform(timeout, lambda el: actions.set_checked(el, False))

    def is_checked(self) -> bool:
        __tracebackhide__ = True
        return actions.is_checked(self.resolve())


class _Selecting(BoundControl):
    def _choose(self, element: UIAElement, item: str | int | re.Pattern[str]) -> None:
        __tracebackhide__ = True
        actions.select(element, item)

    def select(self, item: str | int | re.Pattern[str], *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("select", {"item": item}):
            self.perform(timeout, lambda el: self._choose(el, item))

    def selected_items(self) -> list[str]:
        __tracebackhide__ = True
        return actions.selected_items(self.resolve())


class _Expandable(BoundControl):
    def expand(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("expand"):
            self.perform(timeout, actions.expand)

    def collapse(self, *, timeout: float | None = None) -> None:
        __tracebackhide__ = True
        with self.step("collapse"):
            self.perform(timeout, actions.collapse)


class _GridControl(BoundControl):
    def row(self, i: int) -> BoundElement:
        """Row ``i`` (0-based) of a grid element."""
        __tracebackhide__ = True
        locator = self.locator.with_item(ItemSelector("row", i))
        return BoundElement(self.page, self.definition, locator)

    def cell(self, row: int, column: int | str) -> BoundElement:
        """The cell at ``row`` and ``column`` (index or header name) of a grid element."""
        __tracebackhide__ = True
        locator = self.locator.with_item(ItemSelector("cell", row, column))
        return BoundElement(self.page, self.definition, locator)

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


class BoundElement(_Clickable, _TextEntry, _Checkable, _Selecting, _Expandable, _GridControl):
    """The generic bound element: every action, whatever the control (see ``Element``).

    Prefer a typed element (``Button``, ``ComboBox`` ...) where one fits: it offers only the
    actions that apply and checks that the matched element really is that kind of control.
    """


def _find_row_diagnostic(bound: BoundControl, column: int | str, shown: str, rows: int) -> Any:
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
        return (
            self._override
            if self._override is not None
            else _element_locator(self.page, self.definition)
        )

    @property
    def qualname(self) -> str:
        __tracebackhide__ = True
        return _qualified_name(self.page, self.definition)

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


class Element(Generic[B]):  # noqa: UP046  (a type-parameter default needs Python 3.13)
    """Describes one UI element by its UI Automation properties.

    A plain ``Element`` is the generic fallback: its bound element offers every action. A typed
    element (``Button``, ``ComboBox`` ... or your own: ``class DatePicker(Element[BoundX])``)
    binds to a class with only the actions of that control and checks the matched element fits,
    unless declared with ``validate=False``.
    """

    _bound: ClassVar[type[BoundControl]] = BoundElement
    validate: bool

    def __init_subclass__(cls, **kwargs: Any) -> None:
        __tracebackhide__ = True
        super().__init_subclass__(**kwargs)
        # ``class DatePicker(Element[BoundDatePicker])`` binds the element to ``BoundDatePicker``.
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if isinstance(origin, type) and issubclass(origin, Element):
                for argument in get_args(base):
                    if isinstance(argument, type) and issubclass(argument, BoundControl):
                        cls._bound = argument

    def __init__(
        self,
        *,
        automation_id: Matcher | None = None,
        name: Matcher | None = None,
        control_type: str | None = None,
        class_name: Matcher | None = None,
        index: int | None = None,
        depth: int | None = None,
        within: _AnyElement | None = None,
        window: Window | None = None,
        timeout: float | None = None,
        validate: bool = True,
        where: Mapping[str, WhereValue] | None = None,
    ) -> None:
        __tracebackhide__ = True
        self._init(
            automation_id,
            name,
            control_type,
            class_name,
            index,
            depth,
            within,
            window,
            timeout,
            validate,
            where,
        )

    def _init(
        self,
        automation_id: Matcher | None,
        name: Matcher | None,
        control_type: str | None,
        class_name: Matcher | None,
        index: int | None,
        depth: int | None,
        within: _AnyElement | None,
        window: Window | None,
        timeout: float | None,
        validate: bool = True,
        where: Mapping[str, WhereValue] | None = None,
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
        self.validate = validate
        # Validates control_type, index/depth and the "needs at least one property" rule now,
        # at definition time, rather than on first use.
        self._own = Locator(
            automation_id=automation_id,
            name=name,
            control_type=control_type,
            class_name=class_name,
            index=index,
            depth=depth,
            where=normalize_where(where, {}),
        )
        self.name: str | None = None
        self.owner: type | None = None
        self.source = _caller_source()
        #: Created on the fly by ``bound.Button(...)``: not a declared member of any page.
        self.ad_hoc = False

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

    # -- children: ``panel.Button(name="OK")`` is ``Button(name="OK", within=panel, depth=1)`` ----

    def _declare_child(self, kind: str, options: Mapping[str, Any]) -> Any:
        __tracebackhide__ = True
        from wintestkit import controls

        factory = {"Element": Element, "Elements": Elements}.get(kind) or getattr(controls, kind)
        return factory(**_child_options(kind, options), within=self, depth=1)

    def Element(self, **options: Unpack[ChildOptions]) -> _PlainElement:
        """A control that is a direct child of this element."""
        __tracebackhide__ = True
        return cast("_PlainElement", self._declare_child("Element", options))

    def Elements(self, **options: Unpack[ChildGroupOptions]) -> _ElementGroup:
        """All the direct children of this element that match."""
        __tracebackhide__ = True
        return cast("_ElementGroup", self._declare_child("Elements", options))

    def Button(self, **options: Unpack[ChildOptions]) -> _controls.Button:
        __tracebackhide__ = True
        return cast("_controls.Button", self._declare_child("Button", options))

    def CheckBox(self, **options: Unpack[ChildOptions]) -> _controls.CheckBox:
        __tracebackhide__ = True
        return cast("_controls.CheckBox", self._declare_child("CheckBox", options))

    def ComboBox(self, **options: Unpack[ChildOptions]) -> _controls.ComboBox:
        __tracebackhide__ = True
        return cast("_controls.ComboBox", self._declare_child("ComboBox", options))

    def DataGrid(self, **options: Unpack[ChildOptions]) -> _controls.DataGrid:
        __tracebackhide__ = True
        return cast("_controls.DataGrid", self._declare_child("DataGrid", options))

    def ListBox(self, **options: Unpack[ChildOptions]) -> _controls.ListBox:
        __tracebackhide__ = True
        return cast("_controls.ListBox", self._declare_child("ListBox", options))

    def ListItem(self, **options: Unpack[ChildOptions]) -> _controls.ListItem:
        __tracebackhide__ = True
        return cast("_controls.ListItem", self._declare_child("ListItem", options))

    def RadioButton(self, **options: Unpack[ChildOptions]) -> _controls.RadioButton:
        __tracebackhide__ = True
        return cast("_controls.RadioButton", self._declare_child("RadioButton", options))

    def TabControl(self, **options: Unpack[ChildOptions]) -> _controls.TabControl:
        __tracebackhide__ = True
        return cast("_controls.TabControl", self._declare_child("TabControl", options))

    def Text(self, **options: Unpack[ChildOptions]) -> _controls.Text:
        __tracebackhide__ = True
        return cast("_controls.Text", self._declare_child("Text", options))

    def TextBox(self, **options: Unpack[ChildOptions]) -> _controls.TextBox:
        __tracebackhide__ = True
        return cast("_controls.TextBox", self._declare_child("TextBox", options))

    def TreeView(self, **options: Unpack[ChildOptions]) -> _controls.TreeView:
        __tracebackhide__ = True
        return cast("_controls.TreeView", self._declare_child("TreeView", options))

    def locator(self, *, include_window: bool = True) -> Locator:
        """The locator for this element, including its ``within`` chain and window override."""
        __tracebackhide__ = True
        within = self.within.locator(include_window=False) if self.within is not None else None
        window = self.window.locator if include_window and self.window is not None else None
        return dataclasses.replace(self._own, within=within, window=window)

    @overload
    def __get__(self, obj: None, owner: type | None = None) -> Self: ...
    @overload
    def __get__(self, obj: object, owner: type | None = None) -> B: ...
    def __get__(self, obj: object | None, owner: type | None = None) -> Self | B:
        __tracebackhide__ = True
        if obj is None:
            return self
        return cast("B", type(self)._bound(obj, self))

    def __repr__(self) -> str:
        __tracebackhide__ = True
        return f"<{type(self).__name__} {self.qualname} {self.locator().describe()}>"


class Elements(Element[BoundElement]):
    """Describes a group of elements matching one locator (no ``index``)."""

    def __init__(
        self,
        *,
        automation_id: Matcher | None = None,
        name: Matcher | None = None,
        control_type: str | None = None,
        class_name: Matcher | None = None,
        depth: int | None = None,
        within: _AnyElement | None = None,
        window: Window | None = None,
        timeout: float | None = None,
        where: Mapping[str, WhereValue] | None = None,
    ) -> None:
        __tracebackhide__ = True
        self._init(
            automation_id,
            name,
            control_type,
            class_name,
            None,
            depth,
            within,
            window,
            timeout,
            where=where,
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


_AnyElement = Element[BoundControl]
_PlainElement = Element[BoundElement]
_ElementGroup = Elements
