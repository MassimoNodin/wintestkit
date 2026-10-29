"""Generic UI Automation property matching: the engine behind ``where={...}``.

A ``where`` mapping names UI Automation properties such as ``HelpText`` and ``ItemStatus``
and the value each must have. Keys that are not UIA properties are looked up in the configured
``property_aliases`` when the locator is resolved, so declarations stay importable without a
configuration (``ClrFullClassName`` can stand for ``ItemStatus``, for example).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from difflib import get_close_matches
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from wintestkit.engine.managed import ManagedCondition

from wintestkit import runtime
from wintestkit.errors import InvalidLocatorError
from wintestkit.uia.constants import (
    CONTROL_TYPE_NAMES,
    CONTROL_TYPES,
    PROPERTY_IDS,
    normalize_control_type,
)

__all__ = [
    "BUILTIN_KWARGS",
    "SUPPORTED",
    "Condition",
    "PropertySpec",
    "Where",
    "WhereValue",
    "inspection_values",
    "matches",
    "native_value",
    "normalize_where",
    "read",
    "resolve_where",
]

WhereValue = bool | int | float | str | re.Pattern[str]
Where = tuple[tuple[str, WhereValue], ...]
Kind = Literal["str", "bool", "int", "number", "control_type"]


@dataclass(frozen=True, slots=True)
class PropertySpec:
    """A UI Automation property that ``where`` can match."""

    name: str  # the key users write
    uia_name: str  # the name in ``PROPERTY_IDS``
    kind: Kind
    condition: str  # the key understood by ``com.create_condition``


_ROWS: tuple[tuple[str, str, Kind, str], ...] = (
    ("Name", "Name", "str", "name"),
    ("AutomationId", "AutomationId", "str", "automation_id"),
    ("ClassName", "ClassName", "str", "class_name"),
    ("ControlType", "ControlType", "control_type", "control_type"),
    ("FrameworkId", "FrameworkId", "str", "framework_id"),
    ("HelpText", "HelpText", "str", "help_text"),
    ("ItemStatus", "ItemStatus", "str", "item_status"),
    ("ItemType", "ItemType", "str", "item_type"),
    ("AcceleratorKey", "AcceleratorKey", "str", "accelerator_key"),
    ("AccessKey", "AccessKey", "str", "access_key"),
    ("LocalizedControlType", "LocalizedControlType", "str", "localized_control_type"),
    ("Value", "ValueValue", "str", "value"),
    ("IsEnabled", "IsEnabled", "bool", "is_enabled"),
    ("IsOffscreen", "IsOffscreen", "bool", "is_offscreen"),
    ("IsPassword", "IsPassword", "bool", "is_password"),
    ("IsKeyboardFocusable", "IsKeyboardFocusable", "bool", "is_keyboard_focusable"),
    ("ProcessId", "ProcessId", "int", "process_id"),
)

SUPPORTED: dict[str, PropertySpec] = {
    name: PropertySpec(name, uia, kind, cond) for name, uia, kind, cond in _ROWS
}

_NON_SCALAR = {
    "RuntimeId",
    "BoundingRectangle",
    "ClickablePoint",
    "LabeledBy",
    "SelectionSelection",
    "GridItemContainingGrid",
    "MultipleViewSupportedViews",
    "SelectionItemSelectionContainer",
    "TableRowHeaders",
    "TableColumnHeaders",
    "TableItemRowHeaderItems",
    "TableItemColumnHeaderItems",
    "LegacyIAccessibleSelection",
    "ControllerFor",
    "DescribedBy",
    "FlowsTo",
}
_STRING_PROPERTIES = {
    "ValueValue",
    "LegacyIAccessibleName",
    "LegacyIAccessibleValue",
    "LegacyIAccessibleDescription",
    "LegacyIAccessibleHelp",
    "LegacyIAccessibleKeyboardShortcut",
    "LegacyIAccessibleDefaultAction",
    "AriaRole",
    "AriaProperties",
    "ProviderDescription",
}
_BOOL_PROPERTIES = {
    "HasKeyboardFocus",
    "ValueIsReadOnly",
    "RangeValueIsReadOnly",
    "ScrollHorizontallyScrollable",
    "ScrollVerticallyScrollable",
    "SelectionCanSelectMultiple",
    "SelectionIsSelectionRequired",
    "WindowCanMaximize",
    "WindowCanMinimize",
    "WindowIsModal",
    "WindowIsTopmost",
    "SelectionItemIsSelected",
    "TransformCanMove",
    "TransformCanResize",
    "TransformCanRotate",
    "OptimizeForVisualContent",
}
_NUMERIC_PROPERTIES = {name for name in PROPERTY_IDS if name.startswith(("RangeValue", "Scroll"))}
for _name in PROPERTY_IDS:
    if _name in SUPPORTED or _name in _NON_SCALAR:
        continue
    _kind: Kind = (
        "str"
        if _name in _STRING_PROPERTIES
        else "bool"
        if _name.startswith("Is") or _name in _BOOL_PROPERTIES
        else "number"
        if _name in _NUMERIC_PROPERTIES
        else "int"
    )
    SUPPORTED[_name] = PropertySpec(_name, _name, _kind, _name)

# Property -> the dedicated keyword argument that sets the same property.
BUILTIN_KWARGS = {
    "Name": "name",
    "AutomationId": "automation_id",
    "ClassName": "class_name",
    "ControlType": "control_type",
}

_KIND_TEXT = {
    "str": "a string or compiled regex",
    "control_type": "a control type name or compiled regex",
    "bool": "True or False",
    "int": "an integer",
    "number": "a number",
}


@dataclass(frozen=True, slots=True)
class Condition:
    """One resolved ``where`` entry: the key as written, its property and the expected value."""

    key: str
    spec: PropertySpec
    value: WhereValue

    @property
    def is_regex(self) -> bool:
        __tracebackhide__ = True
        return isinstance(self.value, re.Pattern)


def _value_problem(kind: Kind | None, value: Any) -> str | None:
    """Why ``value`` does not fit ``kind`` (``None`` kind = a not yet known alias target)."""
    __tracebackhide__ = True
    if kind is None:
        ok = isinstance(value, bool | int | float | str | re.Pattern)
    elif kind in ("str", "control_type"):
        ok = isinstance(value, str | re.Pattern)
    elif kind == "bool":
        ok = isinstance(value, bool)
    elif kind == "number":
        ok = isinstance(value, int | float) and not isinstance(value, bool)
    else:
        ok = isinstance(value, int) and not isinstance(value, bool)
    if ok:
        return None
    expected = _KIND_TEXT[kind] if kind is not None else "a string, regex, bool or number"
    return f"expects {expected}, got {value!r}"


def normalize_where(where: Mapping[str, WhereValue] | None, taken: Mapping[str, str]) -> Where:
    """Validate a ``where=`` argument at declaration time and freeze it into a tuple.

    ``taken`` maps UIA property names to the keyword argument that already sets them. Keys that
    are not UIA properties are kept: they may be configured aliases (checked at resolve time).
    """
    __tracebackhide__ = True
    if where is None:
        return ()
    if not isinstance(where, Mapping):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError("where= must be a dict of UIA property names to expected values")
    items: list[tuple[str, WhereValue]] = []
    for key, value in cast("Mapping[Any, Any]", where).items():
        if not isinstance(key, str) or not key:
            raise TypeError(f"where= keys must be non-empty strings, got {key!r}")
        if key in taken:
            raise TypeError(f"{key} is set by both {taken[key]}= and where=; use only one of them")
        spec = SUPPORTED.get(key)
        if key.startswith(("type:", "clr:", "field:", "dp:")):
            from wintestkit.inspector.paths import parse_managed_key

            parse_managed_key(key)
            if _value_problem(None, value) is not None:
                raise InvalidLocatorError(f"where[{key!r}] expects a scalar or compiled regex")
        problem = _value_problem(spec.kind if spec else None, value)
        if problem is not None:
            raise TypeError(f"where[{key!r}] {problem}")
        if spec is not None and spec.kind == "control_type" and isinstance(value, str):
            value = normalize_control_type(value)
        items.append((key, value))
    return tuple(items)


def _unknown(key: str, owner: str, aliases: Mapping[str, str]) -> InvalidLocatorError:
    __tracebackhide__ = True
    known = [*SUPPORTED, *aliases]
    close = get_close_matches(key, known, n=3, cutoff=0.6)
    if not close:
        close = [name for name in known if name.lower() == key.lower()]
    message = f"Unknown property {key!r} in where= of {owner}"
    if close:
        message += f" (did you mean {', '.join(repr(c) for c in close)}?)"
    message += f". UIA properties: {', '.join(SUPPORTED)}"
    if aliases:
        shown = ", ".join(f"{alias} -> {target}" for alias, target in aliases.items())
        message += f". Configured property_aliases: {shown}"
    else:
        message += (
            ". To use another name, map it to a UIA property under property_aliases "
            "in wintestkit.yaml"
        )
    return InvalidLocatorError(message)


def resolve_where(where: Where, owner: str, taken: Collection[str] = ()) -> tuple[Condition | ManagedCondition, ...]:
    """Resolve aliases and check types; ``taken`` are the properties the locator already sets.

    ``owner`` is the locator description used in error messages. Reads the active configuration
    only when a key is not a UIA property name.
    """
    __tracebackhide__ = True
    if not where:
        return ()
    aliases: Mapping[str, str] | None = None
    seen: dict[str, str] = {name: name for name in taken}
    resolved: list[Condition | ManagedCondition] = []
    for key, value in where:
        spec = SUPPORTED.get(key)
        target = key
        if spec is None and not key.startswith(("type:", "clr:", "field:", "dp:")):
            if aliases is None:
                aliases = runtime.get_config().property_aliases
            target = aliases.get(key, key)
        if target.startswith(("type:", "clr:", "field:", "dp:")):
            from wintestkit.engine.managed import ManagedCondition
            from wintestkit.inspector.paths import parse_managed_key

            path = parse_managed_key(target)
            if _value_problem(None, value) is not None:
                raise InvalidLocatorError(f"where[{key!r}] expects a scalar or compiled regex")
            if target in seen:
                raise InvalidLocatorError(f"{owner} sets {target} twice (via {seen[target]!r} and {key!r})")
            seen[target] = key
            resolved.append(ManagedCondition(target, path, value, key if key != target else None))
            continue
        if spec is None:
            if aliases is None:
                aliases = runtime.get_config().property_aliases
            target = aliases.get(key)
            if target is None or target not in SUPPORTED:
                raise _unknown(key, owner, aliases)
            spec = SUPPORTED[target]
            problem = _value_problem(spec.kind, value)
            if problem is not None:
                raise InvalidLocatorError(
                    f"where[{key!r}] (alias of {spec.name}) {problem} in {owner}"
                )
            if spec.kind == "control_type" and isinstance(value, str):
                value = normalize_control_type(value)
        identity = spec.uia_name
        if identity in seen:
            raise InvalidLocatorError(
                f"{owner} sets {identity} twice (via {seen[identity]!r} and {key!r})"
            )
        seen[identity] = key
        resolved.append(Condition(key, spec, value))
    return tuple(resolved)


def native_value(condition: Condition) -> str | int | float | bool:
    """The value to put into a native UIA condition (exact, non-regex values only)."""
    __tracebackhide__ = True
    value = condition.value
    assert not isinstance(value, re.Pattern)
    if condition.spec.kind == "control_type":
        return CONTROL_TYPES[str(value)]
    return value


def read(element: Any, spec: PropertySpec) -> str | bool | int | float:
    """The element's current value of ``spec``, normalized to ``str``, ``bool`` or ``int``."""
    __tracebackhide__ = True
    raw = element.get_property(spec.uia_name)
    if spec.kind == "control_type":
        return CONTROL_TYPE_NAMES.get(raw, "") if isinstance(raw, int) else ""
    if spec.kind == "bool":
        return raw if isinstance(raw, bool) else False
    if spec.kind == "int":
        return raw if isinstance(raw, int) and not isinstance(raw, bool) else 0
    if spec.kind == "number":
        return raw if isinstance(raw, int | float) and not isinstance(raw, bool) else 0.0
    return raw if isinstance(raw, str) else ""


def matches(condition: Condition, actual: str | bool | int | float) -> bool:
    """Exact equality, or ``re.search`` for a compiled pattern."""
    __tracebackhide__ = True
    expected = condition.value
    if isinstance(expected, re.Pattern):
        return isinstance(actual, str) and expected.search(actual) is not None
    return actual == expected


DEFAULT_INSPECTION_PROPERTIES = ("HelpText", "ItemStatus", "ItemType")


def inspection_values(
    element: Any,
    aliases: Mapping[str, str],
    base: Iterable[str] = DEFAULT_INSPECTION_PROPERTIES,
) -> dict[str, Any]:
    """Read useful extra locator properties without enumerating every UIA property.

    ``base`` are the properties read whatever the aliases are; the editor's Spy passes none, so it
    reads only what the configured aliases point at.
    """
    values: dict[str, Any] = {}
    names = dict.fromkeys([*base, *aliases.values()])
    for name in names:
        try:
            value = element.get_property(SUPPORTED[name].uia_name)
        except Exception:
            continue
        if isinstance(value, str | bool | int | float):
            values[name] = value
    for alias, target in aliases.items():
        if target in values:
            values[alias] = values[target]
    return values
