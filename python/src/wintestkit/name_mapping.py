"""Safe, opt-in conversion of a NameMapping export to page skeletons.

The export is an XML tree. Mapped objects are the ``Child`` elements below
``Nodes/Children``; the properties that identify each one are ``Property/Value`` attributes. A
separate ``LogicalNodes`` tree gives some of them aliases, which the tests use as names.
"""

from __future__ import annotations

import json
import keyword
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from wintestkit.engine.locator import Locator
from wintestkit.engine.properties import AsText
from wintestkit.finders import to_locator
from wintestkit.labels import LabelSyntaxError
from wintestkit.model import PageObject

MAX_XML_BYTES = 10 * 1024 * 1024
MAX_DEPTH = 200
RESERVED_NAMES = (
    set(dir(PageObject))
    | set(PageObject.__annotations__)
    | {
        "AsText",
        "Element",
        "Page",
        "Window",
        "re",
    }
)

_ROOT_ATTRIBUTES = {"Signature", "NameMappingVersion", "SaveImages"}
_NODE_ATTRIBUTES = {"Name", "Key", "ExtendedFind"}
_IGNORED_CHILDREN = {"Image", "TypeInfo"}
#: Properties of a mapped object that name no property WinTestKit can compare.
_NO_EQUIVALENT = {
    "objectidentifier": "no equivalent; compare by hand",
    "objectgroupindex": "no equivalent; compare by hand",
}
_TEXT_AND_ORDINAL = {"wpfcontroltext", "wpfcontrolordinalno"}
#: Properties that hold a type or a name. A typed non-string value (the integer ``0`` that real
#: exports store for a popup window whose root visual has no class name) can never equal one.
_TEXT_PROPERTIES = {
    "clrclassname",
    "clrfullclassname",
    "wpfcontrolname",
    "winformscontrolname",
    "wndclass",
    "classname",
    "wndcaption",
}

Value = str | int | bool


class _SafeTreeBuilder(ET.TreeBuilder):
    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise ValueError("DTD and entity declarations are not allowed")


@dataclass(eq=False)
class _Node:
    """One mapped object: the properties that identify it, how far to search and its children."""

    name: str
    key: str
    extended: bool
    properties: list[tuple[str, Value]] = field(default_factory=lambda: [])
    children: list[_Node] = field(default_factory=lambda: [])
    aliases: list[str] = field(default_factory=lambda: [])

    @property
    def label(self) -> str:
        """The name tests use: the first alias, else the mapped name."""
        return self.aliases[0] if self.aliases else self.name

    def get(self, name: str) -> Value | None:
        return next((value for prop, value in self.properties if prop == name), None)


@dataclass(frozen=True)
class Conversion:
    """Generated code and what a review of it has to cover."""

    code: str
    #: Elements and windows declared.
    declared: int
    #: ``# TODO`` comments in the code: properties and objects that need manual work.
    todos: int
    #: Parts of the export that were ignored or could not be read.
    warnings: tuple[str, ...]


def _identifier(value: str, fallback: str = "element") -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\W+", "_", value, flags=re.UNICODE).strip("_")
    value = "".join(character if ("a" + character).isidentifier() else "_" for character in value)
    if not value or not value.isidentifier() or keyword.iskeyword(value) or value in RESERVED_NAMES:
        value = f"{fallback}_{value}" if value else fallback
    return value


def _unique(base: str, used: set[str]) -> str:
    name, suffix = base, 2
    while name in used:
        name, suffix = f"{base}_{suffix}", suffix + 1
    used.add(name)
    return name


def _literal(value: Any) -> str:
    if isinstance(value, AsText):
        return f"AsText({_literal(value.text)})"
    if isinstance(value, re.Pattern):
        return f"re.compile({_literal(cast(re.Pattern[str], value).pattern)}, re.DOTALL)"
    if isinstance(value, str):
        if value.count('"') > value.count("'"):
            return repr(value)
        return json.dumps(value, ensure_ascii=False)
    return repr(value)


# -- reading the export ------------------------------------------------------------------------


class _Reader:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.by_key: dict[str, _Node] = {}

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def check_attributes(self, element: ET.Element, known: set[str], where: str) -> None:
        for attribute in element.attrib:
            if attribute not in known:
                self.warn(f"unknown attribute {attribute!r} on <{element.tag}> in {where} ignored")

    def value(self, text: str, kind: str | None, where: str) -> Value:
        """A property value by its ``Type``: none is a string, ``0`` an integer, ``6`` a boolean."""
        if kind is None:
            return text
        if kind == "0":
            try:
                return int(text)
            except ValueError:
                self.warn(f"{where}: {text!r} is not an integer; kept as text")
                return text
        if kind == "6":
            lowered = text.strip().casefold()
            if lowered in {"true", "false"}:
                return lowered == "true"
            self.warn(f"{where}: {text!r} is not a boolean; kept as text")
            return text
        self.warn(f"{where}: unknown value type {kind!r}; kept as text")
        return text

    def properties(self, element: ET.Element, where: str) -> list[tuple[str, Value]]:
        result: list[tuple[str, Value]] = []
        for prop in element:
            if prop.tag != "Property":
                self.warn(f"unknown element <{prop.tag}> in the properties of {where} ignored")
                continue
            self.check_attributes(prop, {"Name"}, where)
            name = prop.get("Name")
            values = [item for item in prop if item.tag == "Value"]
            for item in prop:
                if item.tag != "Value":
                    self.warn(f"unknown element <{item.tag}> in property {name!r} of {where}")
            if not name or not values:
                self.warn(f"a property of {where} has no name or value; skipped")
                continue
            if len(values) > 1:
                self.warn(f"property {name!r} of {where} has several values; the first is used")
            item = values[0]
            self.check_attributes(item, {"Value", "Type"}, where)
            text = item.get("Value")
            if text is None:
                self.warn(f"property {name!r} of {where} has no Value attribute; skipped")
                continue
            result.append((name, self.value(text, item.get("Type"), f"{where}.{name}")))
        return result

    def node(self, element: ET.Element, depth: int) -> _Node:
        if depth > MAX_DEPTH:
            raise ValueError(f"NameMapping nodes are nested deeper than {MAX_DEPTH} levels")
        name = element.get("Name") or ""
        where = repr(name) if name else "a node without a name"
        self.check_attributes(element, _NODE_ATTRIBUTES, where)
        extended = element.get("ExtendedFind")
        if extended not in (None, "True"):
            self.warn(f'{where}: ExtendedFind="{extended}" is not "True"; ignored')
        key = element.get("Key") or ""
        node = _Node(name, key, extended == "True")
        if key in self.by_key:
            self.warn(f"{where}: key {key} is used by more than one node; aliases use the first")
        else:
            self.by_key[key] = node
        seen_properties = False
        for part in element:
            if part.tag in _IGNORED_CHILDREN:
                continue
            if part.tag == "Properties":
                if seen_properties:
                    self.warn(f"{where} has several Properties; only the first is used")
                    continue
                seen_properties = True
                node.properties = self.properties(part, where)
            elif part.tag == "Children":
                for child in part:
                    if child.tag == "Child":
                        node.children.append(self.node(child, depth + 1))
                    else:
                        self.warn(f"unknown element <{child.tag}> in the children of {where}")
            else:
                self.warn(f"unknown element <{part.tag}> in {where} ignored")
        if not seen_properties:
            self.warn(f"{where} has no Properties")
        return node

    def aliases(self, element: ET.Element, depth: int) -> None:
        """Alias children nest directly; each one names a mapped node by its key."""
        if depth > MAX_DEPTH:
            raise ValueError(f"NameMapping aliases are nested deeper than {MAX_DEPTH} levels")
        for child in element:
            if child.tag != "Child":
                self.warn(f"unknown element <{child.tag}> in the aliases ignored")
                continue
            self.check_attributes(child, {"Name", "Owner"}, "the aliases")
            name, owner = child.get("Name") or "", child.get("Owner") or ""
            target = self.by_key.get(owner)
            if target is None:
                self.warn(f"alias {name!r}: owner {owner} matches no mapped node; skipped")
            elif name and name not in target.aliases:
                target.aliases.append(name)
            self.aliases(child, depth + 1)


def _parse(path: Path) -> tuple[list[_Node], list[str]]:
    with path.open("rb") as stream:
        data = stream.read(MAX_XML_BYTES + 1)
    if len(data) > MAX_XML_BYTES:
        raise ValueError(f"XML exceeds the {MAX_XML_BYTES}-byte import limit")
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)\b", data, re.IGNORECASE):
        raise ValueError("DTD and entity declarations are not allowed")
    try:
        root = ET.fromstring(data, parser=ET.XMLParser(target=_SafeTreeBuilder()))
    except ET.ParseError as exc:
        raise ValueError(f"invalid NameMapping XML: {exc}") from exc
    if root.tag != "Root":
        raise ValueError(f"not a NameMapping export: expected <Root>, found <{root.tag}>")
    reader = _Reader()
    reader.check_attributes(root, _ROOT_ATTRIBUTES, "the export")
    roots: list[_Node] = []
    logical: list[ET.Element] = []
    for part in root:
        if part.tag == "Storages":
            continue
        if part.tag == "Nodes":
            reader.check_attributes(part, {"Name", "Key"}, "Nodes")
            for children in part:
                if children.tag != "Children":
                    reader.warn(f"unknown element <{children.tag}> in Nodes ignored")
                    continue
                roots.extend(reader.node(child, 1) for child in children if child.tag == "Child")
        elif part.tag == "LogicalNodes":
            logical.append(part)
        else:
            reader.warn(f"unknown element <{part.tag}> in the export ignored")
    if not roots:
        raise ValueError("no NameMapping nodes were found: expected Nodes/Children/Child elements")
    for part in logical:
        reader.check_attributes(part, {"Name", "Owner"}, "LogicalNodes")
        if part.get("Name") == "Aliases":
            reader.aliases(part, 1)
        else:
            reader.warn(f"LogicalNodes {part.get('Name')!r} is not the alias tree; ignored")
    return roots, reader.warnings


# -- generating code ---------------------------------------------------------------------------


def _is_system(node: _Node) -> bool:
    return node.get("ProcessName") is None and node.get("Name") == "Sys"


@dataclass
class _Declaration:
    """What the generated code needs of one converted node."""

    names: list[str]
    values: list[Value]
    todos: list[tuple[str, Value, str | None]]


def _translate(node: _Node, *, window: bool) -> _Declaration:
    """The properties of a node that ``to_locator`` accepts; the rest become TODO comments.

    ``RootVisual.`` properties describe the root visual of a WPF window, which is the object the
    mapped node stands for, so they are read as properties of that object: ``RootVisual.Name`` is
    its WPF name, as ``WPFControlName``.
    """
    names: list[str] = []
    values: list[Value] = []
    todos: list[tuple[str, Value, str | None]] = []
    for name, value in node.properties:
        lowered = name.casefold()
        if lowered in _NO_EQUIVALENT:
            todos.append((name, value, _NO_EQUIVALENT[lowered]))
            continue
        if lowered == "extendedfind":
            continue
        mapped = name
        if lowered.startswith("rootvisual."):
            mapped = name[len("rootvisual.") :]
            if mapped.casefold() == "name":
                mapped = "WPFControlName"
        if not isinstance(value, str) and (
            mapped.casefold() in _TEXT_PROPERTIES
            or mapped.casefold().endswith((".clrclassname", ".clrfullclassname"))
        ):
            reason = f"a type or name holds the non-string value {value!r}; check it by hand"
            todos.append((name, value, reason))
            continue
        if window and mapped.casefold() in _TEXT_AND_ORDINAL:
            todos.append((name, value, "a window has no text or ordinal among its siblings"))
            continue
        converted: Any = value
        if mapped.casefold() == "wpfcontrolordinalno" and isinstance(value, str):
            try:
                converted = int(value)
            except ValueError:
                todos.append((name, value, None))
                continue
        try:
            to_locator([*names, mapped], [*values, converted], depth=1)
        except LabelSyntaxError as exc:
            reason = f'Name takes a label step such as WPFObject("Button", "OK", 2): {exc.reason}'
            todos.append((name, value, reason))
            continue
        except ValueError as exc:
            todos.append((name, value, str(exc)))
            continue
        names.append(mapped)
        values.append(converted)
    return _Declaration(names, values, todos)


_DEFAULT_KEYS = {"type:FullName": "ClrFullClassName", "type:Name": "ClrClassName"}


def _where(form: Locator, managed: bool) -> list[tuple[str, Any]]:
    """The ``where`` of a locator; without the inspector class names keep their migration keys."""
    if managed:
        return list(form.where)
    return [(_DEFAULT_KEYS.get(key, key), value) for key, value in form.where]


class _Generator:
    def __init__(self, roots: list[_Node], managed: bool) -> None:
        self.roots = roots
        self.managed = managed
        self.todos = 0
        self.declared = 0
        self.needs_re = False
        self.needs_as_text = False
        self.uses_element = False
        self.uses_window = False
        self.warnings: list[str] = []
        self.processes: list[str] = []

    def todo(self, lines: list[str], text: str, indent: str = "    ") -> None:
        self.todos += 1
        lines.append(f"{indent}# TODO {text}")

    def todo_property(
        self, lines: list[str], label: str, todo: tuple[str, Value, str | None]
    ) -> None:
        name, value, reason = todo
        suffix = f" ({reason})" if reason else ""
        self.todo(lines, f"{label}: {name!r} = {value!r}{suffix}")

    def note(self, form: Locator, where: list[tuple[str, Any]]) -> None:
        values = [getattr(form, key) for key in ("automation_id", "name", "class_name")]
        values.extend(value for _, value in where)
        self.needs_re |= any(isinstance(value, re.Pattern) for value in values)
        self.needs_as_text |= any(isinstance(value, AsText) for _, value in where)

    # windows ---------------------------------------------------------------------------------

    def windows(self) -> list[tuple[str | None, _Node]]:
        """The top-level windows, with the process each one belongs to."""
        found: list[tuple[str | None, _Node]] = []
        for root in self.roots:
            for node in root.children if _is_system(root) else [root]:
                process = node.get("ProcessName")
                if process is not None:
                    name = str(process)
                    if name not in self.processes:
                        self.processes.append(name)
                    found.extend((name, child) for child in node.children)
                else:
                    self.warnings.append(
                        f"{node.label!r} has no ProcessName; it is treated as a window"
                    )
                    found.append((None, node))
        return found

    def window(self, lines: list[str], node: _Node, process: str | None) -> None:
        declaration = _translate(node, window=True)
        label = node.label
        for todo in declaration.todos:
            self.todo_property(lines, label, todo)
        arguments: list[str] = []
        if declaration.names:
            locator = to_locator(declaration.names, declaration.values)
            form = locator.uia_form or locator
            where = _where(form, self.managed)
            self.note(form, where)
            for key, field_name in (
                ("name", "title"),
                ("class_name", "class_name"),
                ("automation_id", "automation_id"),
            ):
                value = getattr(form, key)
                if value is not None:
                    arguments.append(f"{field_name}={_literal(value)}")
            if where:
                items = ", ".join(f"{_literal(key)}: {_literal(value)}" for key, value in where)
                arguments.append("where={" + items + "}")
        else:
            self.todo(lines, f"{label}: the window has no mapped properties; it is the main window")
        if process is not None and len(self.processes) > 1:
            arguments.append(f"process={_literal(process)}")
        self.uses_window = True
        self.declared += 1
        if len(arguments) > 1:
            lines.append("    window = Window(")
            lines.extend(f"        {argument}," for argument in arguments)
            lines.append("    )")
        else:
            lines.append(f"    window = Window({', '.join(arguments)})")

    # elements --------------------------------------------------------------------------------

    def elements(
        self,
        lines: list[str],
        node: _Node,
        parent: str | None,
        used: set[str],
        blocked: bool,
    ) -> None:
        alias = _unique(_identifier(node.label), used)
        declaration = _translate(node, window=False)
        for todo in declaration.todos:
            self.todo_property(lines, alias, todo)
        extended = node.extended
        if not declaration.names or blocked:
            if node.properties or blocked:
                reason = (
                    "because its parent is unmappable" if blocked else "without mapped properties"
                )
                self.todo(lines, f"{alias}: cannot declare element {reason}")
            blocked = True
        else:
            locator = to_locator(
                declaration.names, declaration.values, depth=None if extended else 1
            )
            # Managed output searches the object tree with the migration keys (wpf:Text and
            # wpf:Ordinal); without the inspector it keeps the UIA form (name, global index).
            form = locator if self.managed else cast(Locator, locator.uia_form)
            where = _where(form, self.managed)
            self.note(form, where)
            lines.append(f"    {alias} = Element(")
            for key in ("automation_id", "name", "class_name", "index"):
                value = getattr(form, key)
                if value is not None:
                    lines.append(f"        {key}={_literal(value)},")
            if where:
                lines.append("        where={")
                lines.extend(
                    f"            {_literal(key)}: {_literal(value)}," for key, value in where
                )
                lines.append("        },")
            if self.managed:
                lines.append('        tree="objects",')
            if not extended:
                lines.append("        depth=1,")
            if parent is not None:
                lines.append(f"        within={parent},")
            lines.append("    )")
            self.uses_element = True
            self.declared += 1
            parent = alias
        for child in node.children:
            self.elements(lines, child, parent, used, blocked)

    # the module ------------------------------------------------------------------------------

    def generate(self) -> str:
        classes: list[list[str]] = []
        class_names: set[str] = set()
        for process, node in self.windows():
            name = _unique(_identifier(node.label, "Window"), class_names)
            lines = [f"class {name}(Page):"]
            self.window(lines, node, process)
            used: set[str] = {"window"}
            if node.children:
                lines.append("")
            for child in node.children:
                self.elements(lines, child, None, used, False)
            classes.append(lines)
        if not classes:
            raise ValueError("no NameMapping windows were found below the process nodes")
        header = ['"""Generated from NameMapping; review locators before use.', ""]
        if self.processes:
            names = ", ".join(self.processes)
            header.append(
                f"Processes: {names}. Attach or launch the application, then use these pages."
            )
            header.append("")
        header.append(
            'Managed class names and the object tree (tree="objects", wpf:Text and wpf:Ordinal)'
            " require the WPF inspector."
            if self.managed
            else "ClrFullClassName and ClrClassName require verified application-specific "
            "UIA property aliases."
        )
        header.extend(['"""', ""])
        imports = ["Element"] if self.uses_element else []
        imports = sorted(
            [*imports, "Page", *(["Window"] if self.uses_window else [])]
            + (["AsText"] if self.needs_as_text else [])
        )
        if self.needs_re:
            header.extend(["import re", ""])
        header.append(f"from wintestkit import {', '.join(imports)}")
        body: list[str] = []
        for lines in classes:
            body.extend(["", ""])
            body.extend(lines)
        return "\n".join([*header, *body, ""])


def convert_detailed(xml_path: Path, *, managed_class_names: bool = False) -> Conversion:
    """Parse a bounded NameMapping export and return reviewable Python declarations."""
    roots, warnings = _parse(xml_path)
    generator = _Generator(roots, managed_class_names)
    code = generator.generate()
    return Conversion(code, generator.declared, generator.todos, (*warnings, *generator.warnings))


def convert(xml_path: Path, *, managed_class_names: bool = False) -> str:
    """The generated code only; see ``convert_detailed`` for the counts and warnings."""
    return convert_detailed(xml_path, managed_class_names=managed_class_names).code
