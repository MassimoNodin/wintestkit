"""Safe, opt-in conversion of TestComplete NameMapping XML to page skeletons."""

from __future__ import annotations

import keyword
import re
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_XML_BYTES = 10 * 1024 * 1024


def _identifier(value: str, fallback: str = "element") -> str:
    value = re.sub(r"\W+", "_", value, flags=re.UNICODE).strip("_")
    if not value or value[0].isdigit() or value in keyword.kwlist:
        value = f"{fallback}_{value}" if value else fallback
    return value


def _local(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].casefold()


def _attribute(element: ET.Element, *names: str) -> str | None:
    attributes = {key.casefold(): value for key, value in element.attrib.items()}
    return next(
        (attributes[name.casefold()] for name in names if attributes.get(name.casefold())), None
    )


def convert(xml_path: Path) -> str:
    """Parse a bounded NameMapping export and return reviewable Python declarations."""
    with xml_path.open("rb") as stream:
        data = stream.read(MAX_XML_BYTES + 1)
    if len(data) > MAX_XML_BYTES:
        raise ValueError(f"XML exceeds the {MAX_XML_BYTES}-byte import limit")
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)\b", data, re.IGNORECASE):
        raise ValueError("DTD and entity declarations are not allowed")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"invalid NameMapping XML: {exc}") from exc
    lines = [
        '"""Generated from TestComplete NameMapping; review locators before use."""',
        "# Configure property_aliases: {ClrFullClassName: ItemStatus} in wintestkit.yaml.",
        "",
        "from wintestkit import Element, Page",
        "",
        "",
        "class ImportedPage(Page):",
    ]
    used: set[str] = set()
    count = 0
    # TestComplete stores each mapped object under an Item/Node with its own Properties
    # collection. Never recursively read descendants here: that duplicates child properties
    # onto each ancestor object.
    object_nodes = [n for n in root.iter() if _local(n) in {"item", "node", "mappedobject"}]
    for node in object_nodes:
        props: dict[str, str] = {}
        containers = [child for child in node if _local(child) in {"properties", "props"}]
        for container in containers:
            for prop in container:
                if _local(prop) not in {"property", "prop"}:
                    continue
                children = {_local(child): (child.text or "") for child in prop}
                name = (
                    _attribute(prop, "name") or children.get("propname") or children.get("name", "")
                )
                value = (
                    _attribute(prop, "value")
                    or children.get("propvalue")
                    or children.get("value")
                    or (prop.text or "")
                )
                value = value.strip()
                if name and value:
                    props[name] = value
        if not props:
            continue
        class_name = props.get("ClrFullClassName")
        control_name = props.get("WPFControlName")
        if not class_name and not control_name:
            continue
        alias = _identifier(control_name or class_name.rsplit(".", 1)[-1])
        base = alias
        suffix = 2
        while alias in used:
            alias, suffix = f"{base}_{suffix}", suffix + 1
        used.add(alias)
        args = []
        if control_name:
            args.append(f"automation_id={control_name!r}")
        if class_name:
            args.append(f"where={{'ClrFullClassName': {class_name!r}}}")
        lines.append(f"    {alias} = Element({', '.join(args)})")
        count += 1
    if not count:
        raise ValueError("no NameMapping nodes with ClrFullClassName or WPFControlName were found")
    lines.append("")
    return "\n".join(lines)
