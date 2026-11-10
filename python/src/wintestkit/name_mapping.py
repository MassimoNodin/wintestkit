"""Safe, opt-in conversion of TestComplete NameMapping XML to page skeletons."""

from __future__ import annotations

import json
import keyword
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, cast

from wintestkit.model import PageObject
from wintestkit.testcomplete import to_locator

MAX_XML_BYTES = 10 * 1024 * 1024
RESERVED_NAMES = set(dir(PageObject)) | set(PageObject.__annotations__) | {"Element", "Page", "re"}
_OBJECTS = {"item", "node", "mappedobject"}


class _SafeTreeBuilder(ET.TreeBuilder):
    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise ValueError("DTD and entity declarations are not allowed")


def _identifier(value: str, fallback: str = "element") -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\W+", "_", value, flags=re.UNICODE).strip("_")
    value = "".join(character if ("a" + character).isidentifier() else "_" for character in value)
    if not value or not value.isidentifier() or keyword.iskeyword(value) or value in RESERVED_NAMES:
        value = f"{fallback}_{value}" if value else fallback
    return value


def _local(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].casefold()


def _attribute(element: ET.Element, *names: str) -> str | None:
    attributes = {key.casefold(): value for key, value in element.attrib.items()}
    return next(
        (attributes[name.casefold()] for name in names if name.casefold() in attributes), None
    )


def _properties(node: ET.Element) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for container in node:
        if _local(container) not in {"properties", "props"}:
            continue
        for prop in container:
            if _local(prop) not in {"property", "prop"}:
                continue
            children = {_local(child): (child.text or "") for child in prop}
            name = _attribute(prop, "name") or children.get("propname") or children.get("name", "")
            value = _attribute(prop, "value")
            if value is None:
                value = children.get("propvalue", children.get("value", prop.text or ""))
            if name:
                result.append((name.strip(), value.strip()))
    return result


def _literal(value: Any) -> str:
    if isinstance(value, re.Pattern):
        return f"re.compile({_literal(cast(re.Pattern[str], value).pattern)}, re.DOTALL)"
    if isinstance(value, str):
        if value.count('"') > value.count("'"):
            return repr(value)
        return json.dumps(value, ensure_ascii=False)
    return repr(value)


def convert(xml_path: Path, *, managed_class_names: bool = False) -> str:
    """Parse a bounded NameMapping export and return reviewable Python declarations."""
    with xml_path.open("rb") as stream:
        data = stream.read(MAX_XML_BYTES + 1)
    if len(data) > MAX_XML_BYTES:
        raise ValueError(f"XML exceeds the {MAX_XML_BYTES}-byte import limit")
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)\b", data, re.IGNORECASE):
        raise ValueError("DTD and entity declarations are not allowed")
    try:
        root = ET.fromstring(data, parser=ET.XMLParser(target=_SafeTreeBuilder()))
    except ET.ParseError as exc:
        raise ValueError(f"invalid NameMapping XML: {exc}") from exc

    declarations: list[str] = []
    used: set[str] = set()
    has_properties = False
    needs_re = False
    count = 0

    def visit(node: ET.Element, parent: str | None, blocked: bool = False) -> None:
        nonlocal count, has_properties, needs_re
        if _local(node) not in _OBJECTS:
            for child in node:
                visit(child, parent, blocked)
            return
        properties = _properties(node)
        has_properties |= bool(properties)
        # Export samples do not establish the flag spelling; accept these two forms.
        extended = (_attribute(node, "extendedFind") or "").casefold() == "true"
        extended |= any(
            name.casefold() == "extendedfind" and value.casefold() == "true"
            for name, value in properties
        )
        candidates = [
            (name, value) for name, value in properties if name.casefold() != "extendedfind"
        ]
        control = next(
            (value for name, value in candidates if name.casefold() == "wpfcontrolname"), ""
        )
        class_name = next(
            (value for name, value in candidates if name.casefold() == "clrfullclassname"), ""
        )
        alias = _identifier(_attribute(node, "alias") or control or class_name.rsplit(".", 1)[-1])
        base = alias
        suffix = 2
        while alias in used:
            alias, suffix = f"{base}_{suffix}", suffix + 1
        used.add(alias)
        names: list[str] = []
        values: list[Any] = []
        todos: list[tuple[str, str]] = []
        for name, value in candidates:
            converted: Any = value
            if name.casefold() == "wpfcontrolordinalno":
                try:
                    converted = int(value)
                except ValueError:
                    todos.append((name, value))
                    continue
            try:
                to_locator([*names, name], [*values, converted], depth=None if extended else 1)
            except ValueError:
                todos.append((name, value))
                continue
            names.append(name)
            values.append(converted)
        for name, value in todos:
            declarations.append(f"    # TODO {alias}: {name!r} = {value!r}")
        if not names or blocked:
            if candidates or blocked:
                declarations.append(
                    f"    # TODO {alias}: cannot declare element"
                    + (
                        " because its parent is unmappable"
                        if blocked
                        else " without mapped properties"
                    )
                )
            blocked = True
        else:
            locator = to_locator(names, values, depth=None if extended else 1)
            fields = [
                (key, getattr(locator, key))
                for key in ("automation_id", "name", "class_name", "index")
                if getattr(locator, key) is not None
            ]
            where = list(locator.where)
            if not managed_class_names:
                where = [
                    ("ClrFullClassName" if key == "type:FullName" else key, value)
                    for key, value in where
                ]
            needs_re |= any(isinstance(value, re.Pattern) for _, value in [*fields, *where])
            declarations.append(f"    {alias} = Element(")
            for key, value in fields:
                declarations.append(f"        {key}={_literal(value)},")
            if where:
                declarations.append("        where={")
                for key, value in where:
                    declarations.append(f"            {_literal(key)}: {_literal(value)},")
                declarations.append("        },")
            if not extended:
                declarations.append("        depth=1,")
            if parent is not None:
                declarations.append(f"        within={parent},")
            declarations.append("    )")
            count += 1
            parent = alias
        for child in node:
            if _local(child) not in {"properties", "props"}:
                visit(child, parent, blocked)

    visit(root, None)
    if not has_properties:
        raise ValueError("no NameMapping nodes with properties were found")
    lines = [
        '"""Generated from TestComplete NameMapping; review locators before use.',
        "",
        "Managed class names require the WPF inspector."
        if managed_class_names
        else "ClrFullClassName requires a verified application-specific UIA property alias.",
        '"""',
        "",
    ]
    if needs_re:
        lines.extend(["import re", ""])
    if count:
        lines.extend(["from wintestkit import Element, Page", "", "", "class ImportedPage(Page):"])
    else:
        lines.extend(
            ["from wintestkit import Page", "", "", "class ImportedPage(Page):", "    pass"]
        )
    lines.extend(declarations)
    lines.append("")
    return "\n".join(lines)
