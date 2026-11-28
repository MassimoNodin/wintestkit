"""Translate property lists into WinTestKit locators.

The search helpers use the same lazy locators as page objects.
"""

from __future__ import annotations

import re
import time
import warnings
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, cast

from wintestkit import labels, log, model, runtime
from wintestkit.app import App
from wintestkit.backends.element import TargetElement, WpfElement, uia_of
from wintestkit.engine import actions, conditions, objects, pseudo, waits
from wintestkit.engine.diagnose import diagnostics_are_quiet
from wintestkit.engine.locator import Locator, is_window_node
from wintestkit.engine.managed import diagnostic_query_budget
from wintestkit.engine.properties import AsText
from wintestkit.engine.resolve import Scope, resolve_all, resolve_window
from wintestkit.engine.wpf_resolve import route, wpf_capable
from wintestkit.errors import (
    AmbiguousElementError,
    AmbiguousMatchWarning,
    AppNotRunningError,
    ElementNotFoundError,
    LocatorError,
    UIAError,
    WaitTimeoutError,
    WtkError,
)
from wintestkit.expect import Expectation
from wintestkit.keystrings import KeySegment as KeySegment  # the key grammar lives in keystrings
from wintestkit.keystrings import parse_keys as parse_keys
from wintestkit.keystrings import play_keys
from wintestkit.keystrings import to_keys as to_keys
from wintestkit.model import (
    BoundControl,
    BoundElement,
    BoundElements,
    BoundWindow,
    Elements,
    PageObject,
)
from wintestkit.uia import input as keyboard  # noqa: F401  # pyright: ignore[reportUnusedImport]
from wintestkit.uia.constants import PROPERTY_IDS

# property (lowercase) -> locator field or qualified where key.
#
# Text and ordinal are keys of the object tree (see ``to_locator``). On a window that is not a
# WPF window they have no object tree to read, so the same properties map to the UIA name and a
# global index there (``_UIA_MAP``).
PROPERTY_MAP = {
    "wpfcontrolname": "automation_id",
    "clrfullclassname": "type:FullName",
    "clrclassname": "type:Name",
    "wndclass": "class_name",
    "wndcaption": "name",
    "controlid": "automation_id",
    "winformscontrolname": "automation_id",
    "classname": "class_name",
    "frameworkid": "FrameworkId",
    "localizedcontroltype": "LocalizedControlType",
    "visibleonscreen": "VisibleOnScreen",
    "wpfcontroltext": "wpf:Text",
    "wpfcontrolordinalno": "wpf:Ordinal",
    "visible": "clr:IsVisible",
    "enabled": "clr:IsEnabled",
}


_UIA_MAP = {"wpfcontroltext": "name", "wpfcontrolordinalno": "index"}


def _matcher(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    pattern = labels.wildcard_regex(value)
    return value if pattern is None else pattern


_INDEX_SUFFIX = re.compile(r"-?[0-9]{1,9}\]")


def _name_part(part: str) -> bool:
    """A property name, optionally indexed: ``Items``, ``Rows[3]`` or ``Item[0]``."""
    name, bracket, index = part.partition("[")
    return name.isidentifier() and (not bracket or _INDEX_SUFFIX.fullmatch(index) is not None)


def to_locator(props: str | Sequence[str], values: Any, *, depth: int | None = None) -> Locator:
    """Convert a name/value pair or parallel sequences to a locator.

    Property names are case-insensitive; values are case-sensitive. Wildcards
    ``*`` and ``?`` match any run and one character, respectively. A plain
    string remains exact. WPFControlName uses AutomationId, whose WPF peer
    normally falls back to x:Name; an explicitly assigned AutomationId can
    differ. ClrClassName is the managed short type name. ClassName is the peer's
    short class name. Visible and Enabled read managed WPF properties.

    On a WPF window the locator searches the object tree of the migration model
    (``tree="objects"``): the visual tree without template parts and items-panel
    elements. Depth counts its levels (1 means direct children; from an application,
    1 is the window nodes), the first match is the pre-order one, WPFControlText
    matches ``wpf:Text`` (the element's text, which is not the peer name) and
    WPFControlOrdinalNo matches ``wpf:Ordinal`` (1-based among siblings of the same
    runtime type). Windows that are not WPF windows keep the UIA tree: there WPFControlText
    is the UIA Name and ordinals become zero-based indexes into all results in
    tree order. None leaves the library default depth in place.

    Wildcard regexes use strict whole-value matching, including for Unicode text.
    """
    if isinstance(props, str):
        names = [props]
        items = [values]
    else:
        names: list[Any] = list(props)
        if isinstance(values, str | bytes) or not isinstance(values, Sequence):
            raise ValueError("property names and values must be parallel sequences")
        items = list(cast("Sequence[Any]", values))
        if len(names) != len(items):
            raise ValueError("property names and values must have equal length")

    # The same properties twice: for the object tree of a WPF window, and for the UIA tree.
    fields: dict[str, Any] = {}
    where: dict[str, Any] = {}
    uia_fields: dict[str, Any] = {}
    uia_where: dict[str, Any] = {}
    seen: set[str] = set()
    from_name: set[str] = set()  # keys the Name label step set; no other property may set them
    for prop, value in zip(names, items, strict=True):
        if not isinstance(prop, str):
            raise ValueError(f"invalid property name: {prop!r}")
        qualified = ":" in prop
        if qualified:
            from wintestkit.inspector.paths import parse_managed_key

            parse_managed_key(prop)
        elif not all(_name_part(part) for part in prop.split(".")):
            raise ValueError(f"invalid property name: {prop!r}")
        if not qualified and prop.casefold() == "olevalue":
            raise ValueError("OleValue must follow a property path")
        if not qualified and prop.casefold().endswith(".olevalue"):
            prop = prop[: -len(".OleValue")]
        key = prop.casefold()
        if key in seen:
            raise ValueError(f"duplicate property: {prop!r}")
        seen.add(key)
        if key == "name":
            # The object's own label step, e.g. WPFObject("Button", "OK", 2): its conditions.
            object_where, step_where, step_fields = _name_conditions(value)
            for destination, extra in (
                (where, object_where),
                (uia_where, step_where),
                (uia_fields, step_fields),
            ):
                for condition, expected in extra.items():
                    if condition in destination:
                        raise ValueError(f"Name and another property both set {condition}")
                    destination[condition] = expected
                    from_name.add(condition)
            continue
        target = prop if qualified else PROPERTY_MAP.get(key, f"clr:{prop}")
        uia_target = _UIA_MAP.get(key, target)
        for suffix, facet in ((".clrclassname", "Name"), (".clrfullclassname", "FullName")):
            if key.endswith(suffix):
                target = uia_target = f"type:{facet}@{prop[: -len(suffix)]}"
                break
        uia_value: Any
        if key in {"visible", "enabled", "visibleonscreen", "exists"}:
            if isinstance(value, str) and value.casefold() in {"true", "false"}:
                value = value.casefold() == "true"
            if not isinstance(value, bool):
                raise ValueError(f"{prop} must be True or False")
            uia_value = value
        elif key == "wpfcontrolordinalno":
            if isinstance(value, str) and value.isascii() and value.isdecimal():
                value = int(value)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{prop} must be a positive integer")
            uia_value = value - 1  # a zero-based index into all UIA results
        elif key == "controlid":
            if isinstance(value, bool) or not (
                isinstance(value, int)
                or (isinstance(value, str) and value.isascii() and value.isdecimal())
            ):
                raise ValueError("ControlId must be an integer or numeric string")
            value = uia_value = str(int(value))
        else:
            if key == "wndcaption" and isinstance(value, str):
                value = labels.strip_mnemonic(value)
            value = uia_value = _matcher(value)
            if not qualified and isinstance(value, str) and target.startswith("clr:"):
                # Migrated suites pass numbers and booleans as strings; compare by text.
                value = uia_value = AsText(value)
        if key == "exists":
            if not value:
                raise ValueError("Exists=False cannot be used to find an absent element")
            continue
        for destination_fields, destination_where, destination_target, destination_value in (
            (fields, where, target, value),
            (uia_fields, uia_where, uia_target, uia_value),
        ):
            if destination_target in from_name:
                raise ValueError(f"Name and {prop} both set {destination_target}")
            if ":" in destination_target or destination_target in {
                "FrameworkId",
                "LocalizedControlType",
                "VisibleOnScreen",
            }:
                destination_where[destination_target] = destination_value
            else:
                destination_fields[destination_target] = destination_value
    uia = Locator(
        **uia_fields,
        where=tuple(uia_where.items()),
        allow_empty=not uia_where and not uia_fields,
    )
    return Locator(
        **fields,
        depth=depth,
        where=tuple(where.items()),
        tree="objects",
        uia_form=uia,
        allow_empty=not where and not fields,
    )


def _name_conditions(value: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """What a ``Name`` label step adds: ``where`` entries of the object-tree form, ``where``
    entries of the UIA form and its locator fields."""
    if not isinstance(value, str):
        raise ValueError('Name takes a label step such as \'WPFObject("Button", "OK", 2)\'')
    spec = labels.step_spec(labels.parse_step(value))
    if not isinstance(spec, labels.ObjectSpec):
        raise ValueError("Name takes a WPFObject step; use window() to find a Window step")
    if spec.name is not None:
        both = {"clr:Name": _matcher(spec.name)}
        return both, dict(both), {}
    where: dict[str, Any] = {"type:Name": spec.cls}
    uia_fields: dict[str, Any] = {}
    if spec.index is not None:
        where["wpf:Ordinal"] = spec.index
        uia_fields["index"] = spec.index - 1  # a zero-based index into all UIA results
    if spec.text is not None:
        where["wpf:Text"] = _matcher(spec.text)
        uia_fields["name"] = _matcher(spec.text)
    return where, {"type:Name": spec.cls}, uia_fields


Parent = BoundControl | BoundWindow | PageObject | Scope | App


def _search(parent: Parent, locator: Locator) -> BoundElements:
    if isinstance(parent, App):
        page = PageObject(parent)
        root = None
        locator = replace(locator, app_scope=True)
    elif isinstance(parent, BoundWindow):
        page = parent.page
        root = None
        locator = replace(locator, window=parent.locator)
    elif isinstance(parent, BoundControl):
        page = parent.page
        root = parent.locator
    elif isinstance(parent, PageObject):
        page = parent
        definition = cast(Any, parent)._effective_root()
        root = (
            cast(Any, model)._element_locator(parent, definition)
            if definition is not None
            else None
        )
    else:
        page = PageObject(parent.app)
        root = None
        locator = replace(locator, window=parent.window)
    if root is not None:
        locator = replace(locator, within=replace(root, window=None), window=root.window)
    definition = Elements(automation_id="__finders_search__")
    return BoundElements(page, definition, locator)


def _explicit_ordinal(locator: Locator) -> bool:
    """Whether the properties name an ordinal, which already picks one of several matches."""
    return (
        locator.index is not None
        or any(key == "wpf:Ordinal" for key, _ in locator.where)
        or (locator.uia_form is not None and locator.uia_form.index is not None)
    )


def _first(locator: Locator) -> Locator:
    """The locator with index 0 unless the ordinal already chose, in both of its forms."""
    first = replace(locator, index=0) if locator.index is None else locator
    uia = first.uia_form
    if uia is not None and uia.index is None:
        first = replace(first, uia_form=replace(uia, index=0))
    return first


class _FirstElement(BoundElement):
    def __init__(self, page: Any, definition: Any, locator: Locator, *, warn: bool) -> None:
        super().__init__(page, definition, locator)
        self._warn_ambiguity = warn
        self._warned_tests: set[str | None] = set()

    def _warn(self, count: int) -> None:
        test_id = runtime.current_test()
        if self._warn_ambiguity and count > 1 and test_id not in self._warned_tests:
            self._warned_tests.add(test_id)
            message = (
                f"find_child matched {count} elements for {self.locator.describe()}; using the "
                "first. Use a more robust mapping: add identifying properties, scope it with "
                "within=, or pass strict=True."
            )
            log.warning(message)
            warnings.warn(message, AmbiguousMatchWarning, stacklevel=3)

    def resolve_once(self) -> Any:
        if self._warn_ambiguity and runtime.current_test() not in self._warned_tests:
            candidates = resolve_all(cast(Any, model)._scope(self.page), self.locator)
            if candidates:
                element = candidates[0]
                runtime.record_backend(element)
                if self.definition.validate:
                    self.check_type(element)
                self._warn(len(candidates))
                return element
        return super().resolve_once()


def find_child(
    parent: BoundControl | PageObject | Scope | App,
    props: str | Sequence[str],
    values: Any,
    depth: int | None = 1,
    *,
    strict: bool = False,
) -> BoundElement:
    """Find a descendant lazily; depth 1 means direct children, None unlimited.

    On WPF windows the search runs in the object tree (see ``to_locator``): depth counts its
    levels, and from an application depth 1 is the window nodes and depth 2 the root visuals.
    From a window or a page without a root element, depth 1 is the window's root visual itself.
    By default the first match in pre-order wins; strict requires one match. An explicit
    WPFControlOrdinalNo is a same-type position among siblings, not a global index; matches that
    share it are still ordered, so the first of them wins.
    """
    locator = to_locator(props, values, depth=depth)
    result = _search(parent, locator)
    searched = result.locator
    if not strict:
        searched = _first(searched)
    return _FirstElement(
        result.page,
        result.definition,
        searched,
        warn=not strict and not _explicit_ordinal(result.locator),
    )


def find_all_children(
    parent: BoundControl | PageObject | Scope | App,
    props: str | Sequence[str],
    values: Any,
    depth: int | None = 1,
) -> list[BoundElement]:
    """Snapshot matching descendants as indexed, re-resolving bound elements.

    Changes in tree order after this call can change what an index identifies.
    """
    result = _search(parent, to_locator(props, values, depth=depth))
    return [result.nth(index) for index in range(len(result.resolve_all()))]


class _FindElement(_FirstElement):
    def __init__(self, parent: BoundControl, descendant: BoundElement, locator: Locator) -> None:
        super().__init__(
            descendant.page,
            descendant.definition,
            descendant.locator,
            warn=not _explicit_ordinal(locator),
        )
        self.container = parent
        self.match_locator = locator

    def resolve_once(self) -> Any:
        target = self.container.resolve_once()
        # A parent found at application level may be in any window: search where it was found.
        locator = replace(
            self.match_locator,
            depth=None,
            index=None,
            window=self.container.locator.window,
            app_scope=self.container.locator.app_scope,
        )
        candidates = resolve_all(cast(Any, model)._scope(self.container.page), locator)
        if any(cast(Any, target).same_as(candidate) for candidate in candidates):
            descendants = resolve_all(cast(Any, model)._scope(self.page), self.locator)
            self._warn(1 + len(descendants))
            return target
        return super().resolve_once()


def find(
    parent: BoundControl | PageObject | Scope | App,
    props: str | Sequence[str],
    values: Any,
    depth: int | None = 1,
) -> BoundElement:
    """Find the parent or its descendants, defaulting to a depth of 1.

    A bound parent is included. A Page or Scope without an element root starts at its window; on a
    WPF window the root visual is depth 1 of the object tree, so it can match; elsewhere the
    window itself cannot be included by the descendant resolver.
    """
    child = find_child(parent, props, values, depth)
    if isinstance(parent, PageObject):
        root = cast(Any, parent)._effective_root()
        if root is not None:
            parent = BoundElement(parent, root, cast(Any, model)._element_locator(parent, root))
    if isinstance(parent, BoundControl):
        return _FindElement(parent, child, to_locator(props, values, depth=depth))
    return child


# -- label steps: WPFObject(...) and Window(...) -------------------------------------------------
#
# The grammar and its semantics are defined in ``wintestkit.labels``; this section turns a step
# into a lazy, re-resolving element and walks the tree for ``parent``, ``children`` and labels.

#: How many siblings a not-found message lists.
_LISTED = 10


def _app_of(parent: Parent) -> App:
    if isinstance(parent, App):
        return parent
    if isinstance(parent, Scope | PageObject):
        return parent.app
    return cast(App, parent.page.app)


def _quoted(text: str | None) -> str:
    return labels.quote(text) if text is not None else "(unreadable)"


def _ordinals(names: list[str]) -> list[int]:
    seen: dict[str, int] = {}
    result: list[int] = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        result.append(seen[name])
    return result


class _StepElement(BoundElement):
    """The element a ``WPFObject`` or ``Window`` step selects below its parent.

    It resolves like any bound element; when the step finds nothing the error also lists the
    parent's children of the same type with their texts and ordinals, which is what a label is
    written from.
    """

    def __init__(
        self,
        page: Any,
        definition: Any,
        locator: Locator,
        *,
        origin: Parent | BoundControl | None = None,
        spec: labels.ObjectSpec | labels.WindowSpec | None = None,
    ) -> None:
        super().__init__(page, definition, locator)
        self.origin = origin
        self.spec = spec

    def resolve_once(self) -> Any:
        __tracebackhide__ = True
        try:
            return super().resolve_once()
        except ElementNotFoundError as error:
            listing = self._siblings_text()
            if listing:
                diagnostic = replace(
                    error.diagnostic, message=f"{error.diagnostic.message}; {listing}"
                )
                raise ElementNotFoundError(diagnostic) from None
            raise

    def _siblings_text(self) -> str | None:
        if self.origin is None or self.spec is None or diagnostics_are_quiet():
            return None
        try:
            with diagnostic_query_budget():
                children = _children_of_parent(self.origin)
        except WtkError:
            return None
        nodes = [child.node for child in children]
        spec = self.spec
        same: list[str]
        if isinstance(spec, labels.WindowSpec):
            windows = [n for n in nodes if isinstance(n, labels.WindowNode)]
            ordinals = _ordinals([n.class_name for n in windows])
            same = [
                f"#{ordinals[i]} {_quoted(n.caption)}"
                for i, n in enumerate(windows)
                if n.class_name == spec.cls
            ]
            kind = f"windows of class {labels.quote(spec.cls)}"
            present = sorted({n.class_name for n in windows})
        else:
            objs = [n for n in nodes if isinstance(n, labels.ObjectNode)]
            ordinals = _ordinals([n.type_name for n in objs])
            if spec.name is not None:
                same = [labels.quote(n.name) for n in objs if n.name]
                kind = "children with an x:Name"
            else:
                same = [
                    f"#{ordinals[i]} {_quoted(n.text)}"
                    for i, n in enumerate(objs)
                    if n.type_name == spec.cls
                ]
                kind = f"children of type {labels.quote(spec.cls or '')}"
            present = sorted({n.type_name for n in objs})
        if not same:
            shown = ", ".join(labels.quote(t) for t in present[:_LISTED]) or "none"
            return f"the parent has no {kind}; its children have the types {shown}"
        more = f" (+{len(same) - _LISTED} more)" if len(same) > _LISTED else ""
        return f"{kind}: {', '.join(same[:_LISTED])}{more}"


def _origin(parent: Parent) -> Parent:
    """The parent as the walk needs it: a page with a root element stands for that root."""
    if isinstance(parent, PageObject):
        root = cast(Any, parent)._effective_root()
        if root is not None:
            return BoundElement(parent, root, cast(Any, model)._element_locator(parent, root))
    return parent


def _children_of_parent(parent: Parent) -> list[objects.Child]:
    """The children of whatever a step is written below: the application, an element, a window."""
    __tracebackhide__ = True
    if isinstance(parent, App):
        return objects.children_of(parent, None)
    if isinstance(parent, BoundControl):
        node = is_window_node(parent.locator)
        return objects.children_of(_app_of(parent), parent.resolve_once(), window_node=node)
    app = _app_of(parent)
    if isinstance(parent, BoundWindow):
        window_locator = parent.locator
    elif isinstance(parent, PageObject):
        window_locator = cast(Any, model).scope_window(parent)
    else:
        window_locator = parent.window
    root = route(resolve_window(app, window_locator))
    # On a WPF window the root visual is the (only) child of the window node.
    return objects.children_of(app, root, window_node=isinstance(root, WpfElement))


def _object_locator(spec: labels.ObjectSpec, *, strict: bool) -> Locator:
    where: list[tuple[str, Any]] = []
    if spec.name is not None:
        where.append(("clr:Name", _matcher(spec.name)))
    else:
        where.append(("type:Name", spec.cls))
        if spec.index is not None:
            where.append(("wpf:Ordinal", spec.index))
        if spec.text is not None:
            where.append(("wpf:Text", _matcher(spec.text)))
    # An ordinal already picks one child; otherwise the first match, in object-tree order, wins.
    index = 0 if spec.index is None and not strict else None
    return Locator(where=tuple(where), tree="objects", depth=1, index=index)


def _window_locator(spec: labels.WindowSpec, *, strict: bool) -> Locator:
    if spec.index is not None:
        index: int | None = spec.index - 1
    else:
        index = None if strict else 0
    caption = _matcher(spec.caption) if spec.caption is not None else None
    return Locator(
        class_name=spec.cls,
        name=caption if spec.index is None else None,
        name_after_index=caption if spec.index is not None else None,
        depth=1,
        index=index,
    )


def _bind(parent: Parent, locator: Locator, spec: labels.ObjectSpec | labels.WindowSpec) -> Any:
    origin = _origin(parent)
    result = _search(origin, locator)
    return _StepElement(result.page, result.definition, result.locator, origin=origin, spec=spec)


def _object_step(parent: Parent, spec: labels.ObjectSpec, *, strict: bool = False) -> Any:
    __tracebackhide__ = True
    at_app = isinstance(parent, App)
    if at_app and not spec.is_window_node:
        raise ValueError(
            "From an application WPFObject selects a window node: its type is "
            f'"{labels.WINDOW_NODE_PREFIX}<root visual type>" and the title is the second '
            'argument ("*" for any); chain the objects below it. A lone argument is an x:Name'
        )
    if spec.is_window_node and not at_app:
        raise ValueError("A window node can only be selected from an application")
    return _bind(parent, _object_locator(spec, strict=strict), spec)


def _window_step(parent: Parent, spec: labels.WindowSpec, *, strict: bool = False) -> Any:
    __tracebackhide__ = True
    return _bind(parent, _window_locator(spec, strict=strict), spec)


def wpf_object(
    parent: Parent,
    cls: str,
    text: str | int | None = None,
    index: int | None = None,
    *,
    strict: bool = False,
) -> BoundElement:
    """``WPFObject(cls, text, index)``: a direct object-tree child of ``parent``.

    ``cls`` is the runtime CLR short type name. With ``index`` (1-based) it is the ``index``-th
    child of that type (``wpf:Ordinal``) and the text is checked unless it is ``""`` or ``"*"``.
    Without it the first child of that type whose text matches wins: ``"*"`` is any text, ``""``
    empty text, anything else matches with ``*`` and ``?`` as wildcards. ``wpf_object(parent,
    name)`` alone selects by x:Name, and an integer ``text`` is ``text=""`` with that index.
    ``cls="HwndSource: <root visual x:Name or type>"`` is a window node, selected from an ``App``
    (its text is the window title); the node's child is the root visual itself.

    The result is a lazy bound element that re-resolves on every use. Without an index it takes
    the first match; ``strict=True`` fails when several children match. When nothing matches the
    error lists the parent's children of that type with their texts and ordinals.
    """
    __tracebackhide__ = True
    spec = labels.object_spec(cls, text, index)
    return cast(BoundElement, _object_step(parent, spec, strict=strict))


def window(
    parent: Parent,
    cls: str,
    caption: str | int | None = "*",
    index: int | None = None,
    *,
    strict: bool = False,
) -> BoundElement:
    """``Window(cls, caption, index)``: a Win32 child window of ``parent``, or a top-level window.

    ``cls`` is the window class. ``caption`` is the raw Win32 caption (mnemonic ``&`` removed,
    wildcards allowed, ``"*"`` by default). ``index`` is 1-based among the sibling windows of the
    same class in child/z order; the caption is checked too unless it is ``""`` or ``"*"``.
    Without an index the first window of that class whose caption matches wins. This uses UI
    Automation, not the managed tree, so it works for Win32 dialogs and their controls.
    """
    __tracebackhide__ = True
    spec = labels.window_spec(cls, caption, index)
    return cast(BoundElement, _window_step(parent, spec, strict=strict))


def _apply(parent: Parent, step: labels.Step) -> Any:
    spec = labels.step_spec(step)
    if isinstance(spec, labels.ObjectSpec):
        return _object_step(parent, spec)
    return _window_step(parent, spec)


def _chain(parent: Parent, steps: Sequence[labels.Step]) -> Any:
    result: Any = parent
    for step in steps:
        result = _apply(result, step)
    return result


def from_label(parent: Parent | None, label: str) -> BoundElement:
    """Resolve a whole label chain below ``parent``, e.g. the text of a Spy label.

    ``'WPFObject("A").WPFObject("B", "x", 2).Window("Edit")'`` is
    ``parent.wpf_object("A").wpf_object("B", "x", 2).window("Edit")``. Quotes may be single or
    double, escapes are the usual backslash ones and whitespace is free; a mistake raises
    :class:`wintestkit.labels.LabelSyntaxError` with its position. A leading ``Process("name")``
    or ``Sys.Process("name")`` starts at the application of that name: ``parent`` is used when it
    is (in) that application and may be ``None`` (the process is then attached by name).
    """
    __tracebackhide__ = True
    parsed = labels.parse_label(label)
    start: Any = parent
    if parsed.process is not None:
        current = _app_of(parent) if parent is not None else None
        if current is not None and current.matches_process(parsed.process):
            start = current
        else:
            start = process(parsed.process)
    elif parent is None:
        raise ValueError("from_label needs a parent unless the label starts with Process(...)")
    return cast(BoundElement, _chain(start, parsed.steps))


# -- processes: Sys.Process(name) and Sys.WaitProcess(name, ms) -----------------------------------
#
# A migrated suite starts at a process: ``Sys.Process("x.exe").WPFObject(...)``. These return the
# ``App`` that stands for it. They work for any process with a window, also one this test did not
# start (a second application, Notepad, a dialog owned by the shell): the App is found by exe name
# and drives its windows through UI Automation, or through the inspector for a WPF one.

_PROCESS_POLL = 0.1


def process(name: str) -> App:
    """``Sys.Process(name)``: the :class:`~wintestkit.app.App` of a running process.

    ``name`` is the exe name; ``"notepad"`` and ``"notepad.exe"`` are the same. Raises
    :class:`~wintestkit.errors.AppNotRunningError` when no process of that name is running; use
    :func:`wait_process` to wait for one. Every call returns a fresh ``App`` bound to the processes
    running now. Closing or killing it affects the processes of that exe only, never other apps.
    """
    __tracebackhide__ = True
    if not isinstance(name, str) or not name.strip():  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError(f"invalid process name: {name!r}")
    return App.attach(process=name.strip())


def wait_process(name: str, timeout_ms: float = 0) -> App | None:
    """``Sys.WaitProcess(name, ms)``: wait up to ``timeout_ms`` for a process; ``None`` if none.

    ``0`` (the default) looks once and returns at once. It never raises for a missing process, and
    it is one report step with the name, the time allowed and whether the process was found. The
    process is running, which is not the same as having a window yet: look for the window with a
    finder or ``app.main_window(timeout)``.
    """
    __tracebackhide__ = True
    if not isinstance(name, str) or not name.strip():  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError(f"invalid process name: {name!r}")
    budget = max(0.0, timeout_ms / 1000)
    args = {"name": name, "timeout_ms": round(budget * 1000)}
    with runtime.step("wait_process", name, "", args) as record:
        deadline = time.monotonic() + budget
        while True:
            try:
                found = App.attach(process=name.strip())
            except AppNotRunningError:
                found = None
            if found is not None or time.monotonic() >= deadline:
                break
            time.sleep(_PROCESS_POLL)
        record.args["found"] = found is not None
    return found


class _Sys:
    """``Sys``: the system node of a migrated suite, so ported code reads as it did.

    ``Sys.Process("x.exe")`` and ``Sys.WaitProcess("x.exe", 5000)`` are :func:`process` and
    :func:`wait_process`; the snake_case names work too.
    """

    def process(self, name: str) -> App:
        __tracebackhide__ = True
        return process(name)

    def wait_process(self, name: str, timeout_ms: float = 0) -> App | None:
        __tracebackhide__ = True
        return wait_process(name, timeout_ms)

    Process = process
    WaitProcess = wait_process

    def __repr__(self) -> str:
        return "Sys"


Sys = _Sys()


# -- navigation: parent, children, label, full_name ---------------------------------------------


def _anchor(bound: BoundControl) -> tuple[App, TargetElement, bool]:
    __tracebackhide__ = True
    return _app_of(bound), bound.resolve(), is_window_node(bound.locator)


def label_of(bound: BoundControl) -> str:
    """The element's own label: the arguments that tell it apart from its siblings."""
    __tracebackhide__ = True
    app, element, node = _anchor(bound)
    return labels.format_step(objects.own_step(app, element, window_node=node))


def full_name_of(bound: BoundControl) -> str:
    """The label chain from the process, which :func:`from_label` parses back to this element."""
    __tracebackhide__ = True
    app, element, node = _anchor(bound)
    steps = objects.label_chain(app, element, window_node=node)
    return labels.format_label(labels.Label(app.process_name, tuple(steps)))


def parent_of(bound: BoundControl) -> BoundElement | None:
    """The parent in the object tree (WPF) or the enclosing window (UIA); ``None`` at the top.

    The parent of a WPF root visual is its window node, and a window node has no parent.
    """
    __tracebackhide__ = True
    app, element, node = _anchor(bound)
    if node:
        return None
    steps = objects.label_chain(app, element)
    return cast(BoundElement, _chain(app, steps[:-1])) if len(steps) > 1 else None


def children_of(bound: BoundControl) -> list[BoundElement]:
    """The children as bound elements that re-resolve by their label step below ``bound``."""
    __tracebackhide__ = True
    children = _children_of_parent(bound)
    return [cast(BoundElement, _apply(bound, step)) for step in objects.child_steps(children)]


def child_count_of(bound: BoundControl) -> int:
    __tracebackhide__ = True
    return len(_children_of_parent(bound))


def send_keys(
    target: model.BoundControl | model.BoundWindow,
    text: str,
    *,
    secret: bool = False,
    timeout: float | None = None,
) -> None:
    """Focus a bound target and send a migration key string as one report step."""
    segments = parse_keys(text)
    classifier = actions.PasswordClassifier()
    if isinstance(target, model.BoundControl):
        secret = secret or model.is_password_locator(target.locator)
    with runtime.step(
        "send_keys", target.qualname, target.locator.describe(), {"keys": text}, secret=True
    ) as record:

        def send(element: Any) -> None:
            nonlocal secret
            record.sensitive = True
            secret = secret or classifier.is_password(element)
            record.set_arguments({"keys": text}, secret=secret)
            if isinstance(target, model.BoundWindow):
                actions.activate_for_keys(element)  # keys go to whatever has focus in the window
            elif isinstance(element, WpfElement):
                actions.focus(element)
                cast(Any, actions)._wpf_keyboard_target(element)
            else:
                element = uia_of(element)
                actions.focus(element)
                cast(Any, actions)._keyboard_target(element)
            play_keys(segments)

        if isinstance(target, model.BoundControl):
            target.perform(timeout, send)
        else:
            send(target.resolve(timeout))


# -- property checks and waits of migrated suites -------------------------------------------------
#
# Existing suites check a property by an old name and a condition name (``Exists``, ``wItemCount``,
# ``lessOrEqual``...) and wait for one with ``WaitProperty``. These helpers translate the names and
# run the check as an ``expect`` assertion, so a failure is reported like one.

# The old names whose property does not depend on the kind of element.
_PROPERTY_NAMES = {
    "exists": "exists",
    "visibleonscreen": "visible_on_screen",
    "wtext": "text",
    "witemlist": "item_list",
    "witemcount": "item_count",
    "childcount": "child_count",
    "wndcaption": "name",
    "wpfcontrolname": "AutomationId",
    "winformscontrolname": "AutomationId",
    "controlid": "AutomationId",
    "wndclass": "ClassName",
    "classname": "ClassName",
    "frameworkid": "FrameworkId",
    "localizedcontroltype": "LocalizedControlType",
    "clrclassname": "type:Name",
    "clrfullclassname": "type:FullName",
    "wpfcontrolordinalno": "wpf:Ordinal",
}

# The old names that mean a managed property on a WPF element and a UIA reading on any other.
_PROPERTY_BY_KIND = {
    "wpfcontroltext": ("wpf:Text", "name"),
    "enabled": ("clr:IsEnabled", "enabled"),
    "isenabled": ("clr:IsEnabled", "enabled"),
    "visible": ("clr:IsVisible", "visible_on_screen"),
    "isvisible": ("clr:IsVisible", "visible_on_screen"),
    "ischecked": ("clr:IsChecked", "checked"),
    "value": ("clr:Value", "value"),
}


def map_property(name: str, *, wpf: bool = True) -> str:
    """The property a migrated name stands for: what ``expect(...).to_have_property`` reads.

    ``WPFControlText`` is ``wpf:Text`` on a WPF element (``wpf=True``) and the UIA name on any
    other; ``Exists`` is ``exists``; ``VisibleOnScreen`` ``visible_on_screen``; ``wText`` ``text``;
    ``wItemList`` ``item_list`` (the items, one per line); ``wItemCount`` ``item_count``;
    ``ChildCount`` ``child_count``; ``WndCaption`` ``name``; ``Enabled``/``IsEnabled``,
    ``Visible``/``IsVisible``, ``IsChecked`` and ``Value`` their managed property on WPF
    (``clr:IsEnabled``...) and a UIA reading elsewhere; the locator names (``WPFControlName``,
    ``ClassName``, ``ClrClassName``...) their readable form. A trailing ``.OleValue`` is dropped,
    a name with a ``:`` is taken as it is, and every other name, with or without a path
    (``DataContext.Name``), is the managed property ``clr:<name>``.
    """
    if not isinstance(name, str) or not name.strip():  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError(f"invalid property name: {name!r}")
    text = name.strip()
    if ":" in text:
        return text
    if text.casefold() == "olevalue":
        raise ValueError("OleValue must follow a property path")
    if text.casefold().endswith(".olevalue"):
        text = text[: -len(".OleValue")]
    key = text.casefold()
    if key in _PROPERTY_NAMES:
        return _PROPERTY_NAMES[key]
    if key in _PROPERTY_BY_KIND:
        managed, other = _PROPERTY_BY_KIND[key]
        return managed if wpf else other
    if ":" in text or text in pseudo.PSEUDO:
        return text
    return f"clr:{text}"


def _legacy_reader(prop: str) -> Callable[[Any, TargetElement | None], Any]:
    """Read ``prop`` from whatever element is found, mapping its name for that kind of element."""
    map_property(prop)  # validate the name once

    def read(target: Any, element: TargetElement | None) -> Any:
        __tracebackhide__ = True
        wpf = element is None or isinstance(element, WpfElement) or wpf_capable(element)
        key = map_property(prop, wpf=wpf)
        if not wpf and key.startswith("clr:") and key[4:] in PROPERTY_IDS:
            key = key[4:]  # a UIA property of a window that is not WPF, by its own name
        return pseudo.read_any(target, element, key)

    return read


def _allows_missing(prop: str) -> bool:
    return map_property(prop) in pseudo.ALLOW_MISSING


def check_property(
    target: BoundControl | BoundWindow,
    prop: str,
    condition: str,
    value: Any,
    *,
    timeout: float | None = None,
    soft: bool = False,
) -> bool:
    """A migrated property check: ``prop`` of ``target`` must meet ``condition`` against ``value``.

    ``prop`` is an old property name (see :func:`map_property`) and ``condition`` an old condition
    name or a symbol: ``equal``, ``notEqual``, ``contains``, ``lessOrEqual``, ``greaterOrEqual``
    (also ``less``, ``greater``, ``notContains``, ``==``, ``!=``, ``<=``...). Numbers and booleans
    may be given as text: ``"15"`` equals 15 and ``"True"`` equals True, and order compares
    numerically.

    The check is an ``expect`` assertion: it waits up to ``timeout`` seconds (default: the usual
    timeout; ``0`` looks once), and a failure is a failed step in the report with the expected
    value, the actual one and the condition. It raises ``AssertionError``, unless ``soft`` (or
    ``soft.continue_on_error()``) records it so that the test carries on and fails at its end;
    the result is then ``False``. ``True`` means the check passed.
    """
    __tracebackhide__ = True
    expectation = Expectation(target, timeout, soft=soft)
    return cast(Any, expectation)._property(
        prop,
        value,
        condition,
        reader=_legacy_reader(prop),
        lenient=True,
        allow_missing=_allows_missing(prop),
    )


def wait_property(
    target: BoundControl | BoundWindow,
    prop: str,
    value: Any,
    timeout_ms: float | None = None,
    *,
    condition: str = "equal",
) -> bool:
    """Wait until ``prop`` of ``target`` equals ``value`` (or meets ``condition``): ``True`` when
    it did, ``False`` when ``timeout_ms`` passed first; it never raises for a timeout.

    ``prop`` is an old property name (see :func:`map_property`): ``wait_property(el, "Exists",
    False, 5000)`` waits for the element to disappear and ``wait_property(el, "wItemCount", 3,
    600_000)`` for a list to hold three items. A missing element is just not there yet, except for
    ``Exists`` and ``VisibleOnScreen``, which have an answer for it. ``None`` waits for the usual
    timeout.
    """
    __tracebackhide__ = True
    op = conditions.parse_condition(condition)
    read = _legacy_reader(prop)
    allow_missing = _allows_missing(prop)
    budget = cast(Any, target)._timeout(None) if timeout_ms is None else max(0.0, timeout_ms / 1000)
    secret = isinstance(target, BoundControl) and model.is_password_locator(target.locator)
    classifier = actions.PasswordClassifier()
    args = {"name": prop, "expected": value, "condition": op, "timeout_ms": round(budget * 1000)}
    latest: list[Any] = []
    with runtime.step(
        "wait_property", target.qualname, target.locator.describe(), args, secret=secret
    ) as record:

        def poll() -> bool | None:
            __tracebackhide__ = True
            nonlocal secret
            element: TargetElement | None = None
            try:
                element = target.resolve_once()
            except AmbiguousElementError:
                if map_property(prop) != "exists":
                    raise
                latest[:] = [True]  # several matches still exist
                return True if conditions.compare(True, value, op, lenient=True) else None
            except LocatorError:
                pass
            except UIAError as exc:
                if not exc.element_gone:
                    raise
            if element is None and not allow_missing:
                return None
            try:
                if element is not None:
                    record.sensitive = True
                    secret = secret or classifier.is_password(element)
                    record.set_arguments(args, secret=secret)
                actual = read(target, element)
            except UIAError as exc:
                if not exc.element_gone:
                    raise
                return None
            latest[:] = [actual]
            try:
                return True if conditions.compare(actual, value, op, lenient=True) else None
            except conditions.ComparisonError:
                return None

        try:
            waits.wait_until(
                poll, budget, description=f"{target.qualname} property {prop}", retry_on=()
            )
            matched = True
        except WaitTimeoutError:
            matched = False
        record.args["matched"] = matched
        if not matched and latest and not secret:
            record.args["last"] = runtime.redact_details({"last": latest[0]})["last"]
    return matched
