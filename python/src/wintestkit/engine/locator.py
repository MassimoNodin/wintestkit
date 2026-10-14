"""Locator data model: how elements and windows are described.

``describe()`` output is used in errors, events, reports and the editor UI, so its format is
stable and mirrored by ``describeLocator()`` in the VS Code extension (see
``tests/contract/fixtures/describe_cases.json``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, cast

from wintestkit.uia.constants import CONTROL_TYPES, normalize_control_type

Matcher = str | re.Pattern[str]
MatcherData = str | dict[str, str]

_FLAG_BITS = ((re.IGNORECASE, "i"), (re.MULTILINE, "m"), (re.DOTALL, "s"), (re.VERBOSE, "x"))
_FLAG_BY_LETTER = {letter: bit for bit, letter in _FLAG_BITS}


def match_value(matcher: Matcher, value: str) -> bool:
    """Strings match by equality, compiled patterns by ``re.search``."""
    if isinstance(matcher, str):
        return matcher == value
    return matcher.search(value) is not None


def _flag_letters(pattern: re.Pattern[str]) -> str:
    return "".join(letter for bit, letter in _FLAG_BITS if pattern.flags & bit)


def matcher_to_data(matcher: Matcher) -> MatcherData:
    """Convert a matcher to its protocol ``Matcher`` JSON shape."""
    if isinstance(matcher, str):
        return matcher
    data = {"regex": matcher.pattern}
    flags = _flag_letters(matcher)
    if flags:
        data["flags"] = flags
    return data


def matcher_from_data(data: Any) -> Matcher:
    """Inverse of :func:`matcher_to_data`."""
    if isinstance(data, str):
        return data
    if isinstance(data, Mapping):
        mapping = cast("Mapping[str, Any]", data)
        pattern = mapping.get("regex")
        if isinstance(pattern, str):
            flags = 0
            for letter in str(mapping.get("flags", "")):
                if letter not in _FLAG_BY_LETTER:
                    raise ValueError(f"unknown regex flag {letter!r} (expected a subset of 'imsx')")
                flags |= _FLAG_BY_LETTER[letter]
            return re.compile(pattern, flags)
    raise ValueError(f"invalid matcher: {data!r}")


def describe_matcher(matcher: Matcher) -> str:
    """Render a matcher as ``"text"`` or ``/pattern/flags``."""
    if isinstance(matcher, str):
        return json.dumps(matcher, ensure_ascii=False)
    return f"/{matcher.pattern}/{_flag_letters(matcher)}"


def _check_unknown_keys(kind: str, data: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"unknown {kind} key(s): {', '.join(unknown)}")


def _check_index(name: str, value: int | None, minimum: int = 0) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")


@dataclass(frozen=True, slots=True)
class WindowLocator:
    """Selects a top-level window of the application under test."""

    title: Matcher | None = None
    process: str | None = None
    class_name: Matcher | None = None
    automation_id: Matcher | None = None
    index: int | None = None

    def __post_init__(self) -> None:
        _check_index("window index", self.index)

    def is_empty(self) -> bool:
        return (
            self.title is None
            and self.process is None
            and self.class_name is None
            and self.automation_id is None
            and self.index is None
        )

    def describe(self) -> str:
        parts: list[str] = []
        if self.title is not None:
            parts.append(f"title={describe_matcher(self.title)}")
        if self.process is not None:
            parts.append(f"process={json.dumps(self.process, ensure_ascii=False)}")
        if self.class_name is not None:
            parts.append(f"class={describe_matcher(self.class_name)}")
        if self.automation_id is not None:
            parts.append(f"id={describe_matcher(self.automation_id)}")
        if self.index is not None:
            parts.append(f"index={self.index}")
        return f"Window[{', '.join(parts)}]" if parts else "Window"

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.title is not None:
            data["title"] = matcher_to_data(self.title)
        if self.process is not None:
            data["process"] = self.process
        if self.class_name is not None:
            data["className"] = matcher_to_data(self.class_name)
        if self.automation_id is not None:
            data["automationId"] = matcher_to_data(self.automation_id)
        if self.index is not None:
            data["index"] = self.index
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WindowLocator:
        _check_unknown_keys(
            "window locator", data, {"title", "process", "className", "automationId", "index"}
        )
        return cls(
            title=matcher_from_data(data["title"]) if "title" in data else None,
            process=data.get("process"),
            class_name=matcher_from_data(data["className"]) if "className" in data else None,
            automation_id=(
                matcher_from_data(data["automationId"]) if "automationId" in data else None
            ),
            index=data.get("index"),
        )


@dataclass(frozen=True, slots=True)
class ItemSelector:
    """Selects a grid row or cell after the grid itself has been resolved."""

    kind: Literal["row", "cell"]
    row: int
    column: int | str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("row", "cell"):
            raise ValueError(f"item kind must be 'row' or 'cell', got {self.kind!r}")
        _check_index("row", self.row)
        if self.kind == "cell" and self.column is None:
            raise ValueError("a cell selector needs a column")
        if isinstance(self.column, int) and not isinstance(self.column, bool):
            _check_index("column", self.column)

    def describe(self) -> str:
        if self.kind == "row":
            return f"row({self.row})"
        column = (
            json.dumps(self.column, ensure_ascii=False)
            if isinstance(self.column, str)
            else self.column
        )
        return f"cell({self.row}, {column})"

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind, "row": self.row}
        if self.column is not None:
            data["column"] = self.column
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ItemSelector:
        _check_unknown_keys("item selector", data, {"kind", "row", "column"})
        return cls(kind=data["kind"], row=data["row"], column=data.get("column"))


@dataclass(frozen=True, slots=True)
class Locator:
    """Describes one UI Automation element, optionally relative to a ``within`` ancestor."""

    automation_id: Matcher | None = None
    name: Matcher | None = None
    control_type: str | None = None
    class_name: Matcher | None = None
    index: int | None = None
    depth: int | None = None
    within: Locator | None = None
    window: WindowLocator | None = None
    item: ItemSelector | None = None

    def __post_init__(self) -> None:
        if self.control_type is not None:
            object.__setattr__(self, "control_type", normalize_control_type(self.control_type))
        _check_index("index", self.index)
        _check_index("depth", self.depth, minimum=1)
        if self.is_empty() and self.index is None:
            raise ValueError("locator needs at least one property")

    def is_empty(self) -> bool:
        """True when no property is given (only valid together with ``index``)."""
        return (
            self.automation_id is None
            and self.name is None
            and self.control_type is None
            and self.class_name is None
        )

    def chain(self) -> list[Locator]:
        """The ``within`` chain, outermost first, ``self`` last."""
        links: list[Locator] = []
        node: Locator | None = self
        while node is not None:
            links.append(node)
            node = node.within
        links.reverse()
        return links

    def with_index(self, index: int) -> Locator:
        return replace(self, index=index)

    def with_item(self, item: ItemSelector) -> Locator:
        return replace(self, item=item)

    def exact_props(self) -> dict[str, str | int]:
        """Properties usable directly in a UIA condition (string matchers and control type)."""
        props: dict[str, str | int] = {}
        if isinstance(self.automation_id, str):
            props["automation_id"] = self.automation_id
        if isinstance(self.name, str):
            props["name"] = self.name
        if isinstance(self.class_name, str):
            props["class_name"] = self.class_name
        if self.control_type is not None:
            props["control_type"] = CONTROL_TYPES[self.control_type]
        return props

    def regex_props(self) -> dict[str, re.Pattern[str]]:
        """Properties that must be filtered in Python because they are regular expressions."""
        props: dict[str, re.Pattern[str]] = {}
        if isinstance(self.automation_id, re.Pattern):
            props["automation_id"] = self.automation_id
        if isinstance(self.name, re.Pattern):
            props["name"] = self.name
        if isinstance(self.class_name, re.Pattern):
            props["class_name"] = self.class_name
        return props

    def describe_link(self, include_item: bool = True, include_index: bool = True) -> str:
        """Describe this locator alone, without its ``within`` chain or window prefix."""
        parts: list[str] = []
        if self.automation_id is not None:
            parts.append(f"id={describe_matcher(self.automation_id)}")
        if self.name is not None:
            parts.append(f"name={describe_matcher(self.name)}")
        if self.class_name is not None:
            parts.append(f"class={describe_matcher(self.class_name)}")
        if include_index and self.index is not None:
            parts.append(f"index={self.index}")
        if self.depth is not None:
            parts.append(f"depth={self.depth}")
        head = self.control_type or "*"
        text = f"{head}[{', '.join(parts)}]" if parts else head
        if include_item and self.item is not None:
            text += f" > {self.item.describe()}"
        return text

    def describe(self) -> str:
        """Stable human-readable form, e.g. ``Group[name="A"] > Button[name="OK"]``."""
        text = " > ".join(link.describe_link() for link in self.chain())
        if self.window is not None:
            text = f"{self.window.describe()} >> {text}"
        return text

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.automation_id is not None:
            data["automationId"] = matcher_to_data(self.automation_id)
        if self.name is not None:
            data["name"] = matcher_to_data(self.name)
        if self.control_type is not None:
            data["controlType"] = self.control_type
        if self.class_name is not None:
            data["className"] = matcher_to_data(self.class_name)
        if self.index is not None:
            data["index"] = self.index
        if self.depth is not None:
            data["depth"] = self.depth
        if self.within is not None:
            data["within"] = self.within.to_dict()
        if self.window is not None:
            data["window"] = self.window.to_dict()
        if self.item is not None:
            data["item"] = self.item.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Locator:
        _check_unknown_keys(
            "locator",
            data,
            {
                "automationId",
                "name",
                "controlType",
                "className",
                "index",
                "depth",
                "within",
                "window",
                "item",
            },
        )
        return cls(
            automation_id=matcher_from_data(data["automationId"])
            if "automationId" in data
            else None,
            name=matcher_from_data(data["name"]) if "name" in data else None,
            control_type=data.get("controlType"),
            class_name=matcher_from_data(data["className"]) if "className" in data else None,
            index=data.get("index"),
            depth=data.get("depth"),
            within=cls.from_dict(data["within"]) if "within" in data else None,
            window=WindowLocator.from_dict(data["window"]) if "window" in data else None,
            item=ItemSelector.from_dict(data["item"]) if "item" in data else None,
        )
