"""Safe, opt-in conversion of TestComplete NameMapping XML to page skeletons."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


def _identifier(value: str, fallback: str = "element") -> str:
    value = re.sub(r"\W+", "_", value, flags=re.UNICODE).strip("_")
    if not value or value[0].isdigit() or value in __import__("keyword").kwlist:
        value = f"{fallback}_{value}" if value else fallback
    return value


def convert(xml_path: Path) -> str:
    """Parse NameMapping XML without resolving external entities; return reviewable Python."""
    parser = ET.XMLParser()
    root = ET.parse(xml_path, parser=parser).getroot()
    lines = ['"""Generated from TestComplete NameMapping; review locators before use."""',
             "", "from wintestkit import Element, Page", "", "", "class ImportedPage(Page):"]
    used: set[str] = set()
    count = 0
    for node in root.iter():
        props: dict[str, str] = {}
        for prop in node.iter():
            name = prop.attrib.get("name", "")
            value = (prop.text or "").strip()
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
        where = {k: v for k, v in (("class_name", class_name), ("name", control_name)) if v}
        lines.append(f"    {alias} = Element(where={where!r})")
        count += 1
    if not count:
        raise ValueError("no NameMapping nodes with ClrFullClassName or WPFControlName were found")
    lines.append("")
    return "\n".join(lines)
