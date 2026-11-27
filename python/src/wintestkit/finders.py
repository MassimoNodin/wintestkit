"""Translate property lists into WinTestKit locators.

The search helpers use the same lazy locators as page objects.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from wintestkit import log, model, runtime
from wintestkit.app import App
from wintestkit.backends.element import WpfElement, uia_of
from wintestkit.engine import actions
from wintestkit.engine.locator import Locator
from wintestkit.engine.properties import AsText
from wintestkit.engine.resolve import Scope, resolve_all
from wintestkit.errors import AmbiguousMatchWarning
from wintestkit.model import (
    BoundControl,
    BoundElement,
    BoundElements,
    Elements,
    PageObject,
)
from wintestkit.uia import input as keyboard

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
    if not isinstance(value, str) or not any(c in value for c in "*?"):
        return value
    # Only escape regex metacharacters: re.escape also escapes characters outside
    # the agent's shared regex grammar, such as spaces and #.
    special = r"\.^$|+()[]{}"
    pattern = "".join(
        ".*" if c == "*" else "." if c == "?" else "\\" + c if c in special else c for c in value
    )
    return re.compile(rf"^{pattern}\Z", re.DOTALL)


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
    for prop, value in zip(names, items, strict=True):
        if not isinstance(prop, str) or not all(_name_part(part) for part in prop.split(".")):
            raise ValueError(f"invalid property name: {prop!r}")
        if prop.casefold() == "olevalue":
            raise ValueError("OleValue must follow a property path")
        if prop.casefold().endswith(".olevalue"):
            prop = prop[: -len(".OleValue")]
        key = prop.casefold()
        if key == "name":
            raise ValueError("Name is an object name; use mapped properties instead")
        if key in seen:
            raise ValueError(f"duplicate property: {prop!r}")
        seen.add(key)
        target = PROPERTY_MAP.get(key, f"clr:{prop}")
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
                value = re.sub(
                    r"&(&|.)?", lambda m: "&" if m.group(1) == "&" else (m.group(1) or ""), value
                )
            value = uia_value = _matcher(value)
            if isinstance(value, str) and target.startswith("clr:"):
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


def _search(parent: BoundControl | PageObject | Scope | App, locator: Locator) -> BoundElements:
    if isinstance(parent, App):
        page = PageObject(parent)
        root = None
        locator = replace(locator, app_scope=True)
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
        self.parent = parent
        self.match_locator = locator

    def resolve_once(self) -> Any:
        target = self.parent.resolve_once()
        # A parent found at application level may be in any window: search where it was found.
        locator = replace(
            self.match_locator,
            depth=None,
            index=None,
            window=self.parent.locator.window,
            app_scope=self.parent.locator.app_scope,
        )
        candidates = resolve_all(cast(Any, model)._scope(self.parent.page), locator)
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


@dataclass(frozen=True)
class KeySegment:
    """A literal, key combination, or modifier hold/release command."""

    kind: str
    text: str = ""
    combo: keyboard.KeyCombo | None = None
    modifiers: tuple[int, ...] = ()


_PREFIXES = {"^": 0x11, "!": 0x12, "~": 0x10}
_KEY_NAMES = {
    "bs": "Backspace",
    "del": "Delete",
    "ins": "Insert",
    "esc": "Escape",
    "prtsc": "PrintScreen",
    "win": "Win",
    "apps": "Apps",
    "pause": "Pause",
    "capslock": "CapsLock",
    "numlock": "NumLock",
    "scrolllock": "ScrollLock",
}
_EXTRA_KEYS = {
    "PrintScreen": 0x2C,
    "Pause": 0x13,
    "CapsLock": 0x14,
    "NumLock": 0x90,
    "ScrollLock": 0x91,
    "Win": 0x5B,
}
_ALLOWED_NAMES = {
    "enter",
    "tab",
    "bs",
    "del",
    "ins",
    "esc",
    "home",
    "end",
    "pageup",
    "pagedown",
    "up",
    "down",
    "left",
    "right",
    "win",
    "apps",
    "pause",
    "capslock",
    "numlock",
    "scrolllock",
    "prtsc",
    "space",
}


def parse_keys(text: str) -> list[KeySegment]:
    """Parse migration key strings into text, key, and modifier segments."""
    segments: list[KeySegment] = []
    pending: list[int] = []
    held: list[int] = []
    position = 0
    while position < len(text):
        char = text[position]
        if char in _PREFIXES and (position + 1 >= len(text) or text[position + 1] != char):
            modifier = _PREFIXES[char]
            if modifier not in pending and modifier not in held:
                pending.append(modifier)
            position += 1
            continue
        if char in "^!~[" and position + 1 < len(text) and text[position + 1] == char:
            value = char
            position += 2
            named = False
        elif char == "[":
            end = text.find("]", position + 1)
            if end < 0:
                raise ValueError(f"unclosed bracket at position {position}")
            value = text[position + 1 : end]
            position = end + 1
            named = True
        else:
            value = char
            position += 1
            named = False
        if named and value.casefold() == "hold":
            if not pending:
                raise ValueError("[Hold] requires modifier prefixes")
            held.extend(pending)
            segments.append(KeySegment("hold", modifiers=tuple(pending)))
            pending.clear()
            continue
        if named and value.casefold() == "release":
            if pending:
                raise ValueError("modifier prefix before [Release]")
            segments.append(KeySegment("release", modifiers=tuple(held)))
            held.clear()
            continue
        if named:
            name = value.casefold()
            if name not in _ALLOWED_NAMES and not (
                name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24
            ):
                raise ValueError(f"unknown bracketed key [{value}]")
            canonical = _KEY_NAMES.get(name, value.capitalize())
            code = _EXTRA_KEYS.get(canonical) or cast(Any, keyboard)._key_code(canonical)
            assert code is not None
            segments.append(KeySegment("key", canonical, keyboard.KeyCombo(tuple(pending), code)))
        elif pending or held:
            code = cast(Any, keyboard)._key_code(value)
            if code is None:
                raise ValueError(f"modifier prefix cannot be applied to {value!r}")
            segments.append(
                KeySegment("key", value.upper(), keyboard.KeyCombo(tuple(pending), code))
            )
        elif segments and segments[-1].kind == "text":
            segments[-1] = replace(segments[-1], text=segments[-1].text + value)
        else:
            segments.append(KeySegment("text", value))
        pending.clear()
    if pending:
        raise ValueError("dangling modifier prefix at end of key string")
    return segments


def to_keys(text: str) -> str | None:
    """Convert key-only input to press syntax, or return None for literal text."""
    segments = parse_keys(text)
    if any(segment.kind == "text" for segment in segments):
        return None
    names = {0x11: "Ctrl", 0x12: "Alt", 0x10: "Shift"}
    held: list[int] = []
    result: list[str] = []
    for segment in segments:
        if segment.kind == "hold":
            held.extend(segment.modifiers)
        elif segment.kind == "release":
            held.clear()
        elif segment.combo is not None:
            modifiers = [*held, *segment.combo.modifiers]
            result.append("+".join([*(names[modifier] for modifier in modifiers), segment.text]))
    return " ".join(result)


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
            held: list[int] = []
            try:
                for segment in segments:
                    if segment.kind == "text":
                        keyboard.type_text(segment.text)
                    elif segment.kind == "hold":
                        for modifier in segment.modifiers:
                            cast(Any, keyboard)._send(
                                [cast(Any, keyboard)._key_event(modifier, up=False)]
                            )
                            held.append(modifier)
                    elif segment.kind == "release":
                        while held:
                            cast(Any, keyboard)._send(
                                [cast(Any, keyboard)._key_event(held.pop(), up=True)]
                            )
                    else:
                        combo = segment.combo
                        assert combo is not None
                        events = [
                            cast(Any, keyboard)._key_event(modifier, up=False)
                            for modifier in combo.modifiers
                        ]
                        events += [
                            cast(Any, keyboard)._key_event(combo.key, up=False),
                            cast(Any, keyboard)._key_event(combo.key, up=True),
                        ]
                        events += [
                            cast(Any, keyboard)._key_event(modifier, up=True)
                            for modifier in reversed(combo.modifiers)
                        ]
                        cast(Any, keyboard)._send(events)
            finally:
                while held:
                    cast(Any, keyboard)._send([cast(Any, keyboard)._key_event(held.pop(), up=True)])

        if isinstance(target, model.BoundControl):
            target.perform(timeout, send)
        else:
            send(target.resolve(timeout))
