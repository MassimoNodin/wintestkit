"""Builders for NameMapping exports, in the structure of a real file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

Prop = tuple[str, str] | tuple[str, str, str]


def properties(*props: Prop) -> str:
    items: list[str] = []
    for prop in props:
        kind = f' Type="{prop[2]}"' if len(prop) == 3 else ""
        items.append(f'<Property Name="{prop[0]}"><Value Value="{prop[1]}"{kind} /></Property>')
    return "<Properties>" + "".join(items) + "</Properties>"


def node(
    name: str,
    key: str,
    *props: Prop,
    children: str = "",
    extended: bool = False,
    extra: str = "",
) -> str:
    flag = ' ExtendedFind="True"' if extended else ""
    inner = f"<Children>{children}</Children>" if children else ""
    return (
        f'<Child Name="{name}" Key="{key}"{flag}>'
        '<Image FileName="1" Left="0" Top="0" Right="1" Bottom="1" />'
        f"{properties(*props)}{extra}{inner}</Child>"
    )


def alias(name: str, owner: str, children: str = "") -> str:
    return f'<Child Name="{name}" Owner="{owner}">{children}</Child>'


def export(
    windows: str,
    aliases: str = "",
    *,
    process: str | None = "App",
    root_extra: str = "",
) -> str:
    """A complete export: ``Sys`` > the process node (when given) > ``windows``."""
    inner = windows
    if process is not None:
        inner = node("App", "{P}", ("ProcessName", process), children=windows)
    sys_node = node("Sys", "{S}", ("Name", "Sys"), children=inner)
    logical = (
        f'<LogicalNodes Name="Aliases" Owner="{{N}}">{aliases}</LogicalNodes>' if aliases else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Root Signature="{X}" NameMappingVersion="7" SaveImages="0">'
        '<Storages Current="0"><Child Name="Default Configuration" /></Storages>'
        f'<Nodes Name="NameMapping" Key="{{N}}"><Children>{sys_node}</Children></Nodes>'
        f"{logical}{root_extra}</Root>"
    )


def write(tmp_path: Path, text: str, name: str = "mapping.xml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def run(code: str, tmp_path: Path) -> dict[str, Any]:
    """Execute generated code as a module and return its namespace."""
    namespace: dict[str, Any] = {"__name__": "generated"}
    exec(compile(code, str(tmp_path / "generated.py"), "exec"), namespace)
    return namespace
