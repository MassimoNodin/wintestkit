"""Static discovery of tests and screen definitions.

Pure ``ast`` analysis: user code is never imported and UI Automation is never touched, so the
editor can call this on every keystroke. Positions follow the protocol: 0-based lines and
UTF-16 code unit offsets (what VS Code uses).
"""

from __future__ import annotations

import ast
import configparser
import contextlib
import fnmatch
import os
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from wintestkit.config import load_config
from wintestkit.errors import ConfigError
from wintestkit.uia.constants import normalize_control_type

__all__ = [
    "DiscoveryError",
    "DiscoveryResult",
    "ElementEntry",
    "Position",
    "Range",
    "ScreenEntry",
    "TestEntry",
    "discover",
    "discover_file",
]

EXCLUDED_DIRS = frozenset(
    {
        ".venv",
        "venv",
        "env",
        ".git",
        "node_modules",
        "__pycache__",
        "build",
        "dist",
        ".tox",
        ".pytest_cache",
        "site-packages",
    }
)
DEFAULT_PYTHON_FILES = ("test_*.py", "*_test.py")
DEFAULT_PYTHON_CLASSES = ("Test",)
DEFAULT_PYTHON_FUNCTIONS = ("test",)
DEFAULT_REPORT_DIR = "wtk-report"

_ELEMENT_FUNCTIONS = {"Window": "window", "Element": "element", "Elements": "elements"}
_LOCATOR_KEYS = {
    "automation_id": "automationId",
    "name": "name",
    "control_type": "controlType",
    "class_name": "className",
    "index": "index",
    "depth": "depth",
}
_WINDOW_KEYS = {
    "title": "title",
    "process": "process",
    "class_name": "className",
    "automation_id": "automationId",
    "index": "index",
}
_STRING_KEYS = {"automationId", "name", "controlType", "className", "title", "process"}
_MATCHER_KEYS = {"automationId", "name", "className", "title"}
_REGEX_FLAGS = {
    "I": "i",
    "IGNORECASE": "i",
    "M": "m",
    "MULTILINE": "m",
    "S": "s",
    "DOTALL": "s",
    "X": "x",
    "VERBOSE": "x",
}
_NO_OP_FLAGS = {"A", "ASCII", "U", "UNICODE", "L", "LOCALE"}
_LINE_BREAK = re.compile(r"\r\n|\r|\n")


# -- result types ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Position:
    line: int
    character: int

    def to_dict(self) -> dict[str, int]:
        return {"line": self.line, "character": self.character}


@dataclass(frozen=True)
class Range:
    start: Position
    end: Position

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start.to_dict(), "end": self.end.to_dict()}


@dataclass(frozen=True)
class TestEntry:
    __test__ = False  # not a pytest test class

    id: str
    file: str
    name: str
    kind: str
    parent: str | None
    range: Range
    name_range: Range

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "file": self.file,
            "name": self.name,
            "kind": self.kind,
            "parent": self.parent,
            "range": self.range.to_dict(),
            "nameRange": self.name_range.to_dict(),
        }


@dataclass(frozen=True)
class ElementEntry:
    id: str
    name: str
    qualname: str
    kind: str
    range: Range
    name_range: Range
    locator: dict[str, Any]
    dynamic: bool
    within_name: str | None = None
    window_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "qualname": self.qualname,
            "kind": self.kind,
            "range": self.range.to_dict(),
            "nameRange": self.name_range.to_dict(),
            "locator": self.locator,
            "dynamic": self.dynamic,
        }
        if self.within_name is not None:
            data["withinName"] = self.within_name
        if self.window_name is not None:
            data["windowName"] = self.window_name
        return data


@dataclass(frozen=True)
class ScreenEntry:
    id: str
    file: str
    name: str
    qualname: str
    bases: tuple[str, ...]
    range: Range
    name_range: Range
    elements: tuple[ElementEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "file": self.file,
            "name": self.name,
            "qualname": self.qualname,
            "bases": list(self.bases),
            "range": self.range.to_dict(),
            "nameRange": self.name_range.to_dict(),
            "elements": [e.to_dict() for e in self.elements],
        }


@dataclass(frozen=True)
class DiscoveryError:
    file: str
    message: str
    line: int

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "message": self.message, "line": self.line}


@dataclass(frozen=True)
class DiscoveryResult:
    root: str
    tests: tuple[TestEntry, ...] = ()
    screens: tuple[ScreenEntry, ...] = ()
    errors: tuple[DiscoveryError, ...] = ()
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "root": self.root,
            "tests": [t.to_dict() for t in self.tests],
            "screens": [s.to_dict() for s in self.screens],
            "errors": [e.to_dict() for e in self.errors],
        }


# -- pytest collection rules ----------------------------------------------------------------------


@dataclass(frozen=True)
class PytestRules:
    python_files: tuple[str, ...] = DEFAULT_PYTHON_FILES
    python_classes: tuple[str, ...] = DEFAULT_PYTHON_CLASSES
    python_functions: tuple[str, ...] = DEFAULT_PYTHON_FUNCTIONS
    testpaths: tuple[str, ...] = ()


def _words(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(value.split())
    if isinstance(value, list | tuple):
        return tuple(str(v) for v in value)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return ()


def _table(parent: Mapping[str, Any], key: str) -> dict[str, Any]:
    value: Any = parent.get(key)
    return dict(cast("Mapping[str, Any]", value)) if isinstance(value, dict) else {}


def load_pytest_rules(root: Path) -> PytestRules:
    """Collection settings from ``[tool.pytest.ini_options]`` or ``pytest.ini``/``tox.ini``."""
    options: dict[str, Any] = {}
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            data = {}
        options = _table(_table(_table(data, "tool"), "pytest"), "ini_options")
    if not options:
        for name, section in (("pytest.ini", "pytest"), ("tox.ini", "pytest")):
            path = root / name
            if path.is_file():
                parser = configparser.ConfigParser()
                try:
                    parser.read(path, encoding="utf-8")
                except configparser.Error:
                    continue
                if parser.has_section(section):
                    options = dict(parser.items(section))
                    break
    files = _words(options.get("python_files")) or DEFAULT_PYTHON_FILES
    classes = _words(options.get("python_classes")) or DEFAULT_PYTHON_CLASSES
    functions = _words(options.get("python_functions")) or DEFAULT_PYTHON_FUNCTIONS
    return PytestRules(files, classes, functions, _words(options.get("testpaths")))


def _name_matches(name: str, patterns: Sequence[str]) -> bool:
    """pytest semantics: a pattern matches as a prefix or as a glob."""
    return any(name.startswith(p) or fnmatch.fnmatchcase(name, p) for p in patterns)


def _is_test_file(rel: str, rules: PytestRules) -> bool:
    base = rel.rsplit("/", 1)[-1]
    return any(
        fnmatch.fnmatchcase(rel if "/" in pattern else base, pattern)
        for pattern in rules.python_files
    )


# -- source handling ------------------------------------------------------------------------------


class _Source:
    """One parsed file with helpers converting ``ast`` offsets to protocol positions."""

    def __init__(self, path: Path, rel: str, text: str) -> None:
        self.path = path
        self.rel = rel
        self.text = text
        self.lines = _LINE_BREAK.split(text)
        self.tree: ast.Module | None = None
        self.error: DiscoveryError | None = None
        try:
            self.tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            self.error = DiscoveryError(path.as_posix(), exc.msg, max((exc.lineno or 1) - 1, 0))
        except (ValueError, RecursionError, MemoryError) as exc:
            self.error = DiscoveryError(path.as_posix(), str(exc) or type(exc).__name__, 0)

    def position(self, line1: int, col_utf8: int) -> Position:
        line = self.lines[line1 - 1] if 0 < line1 <= len(self.lines) else ""
        prefix = line.encode("utf-8")[:col_utf8].decode("utf-8", errors="ignore")
        return Position(line1 - 1, len(prefix.encode("utf-16-le")) // 2)

    def range_of(self, node: ast.AST) -> Range:
        """Range of a statement; for decorated definitions it starts at the first decorator."""
        start_line = getattr(node, "lineno", 1)
        start_col = getattr(node, "col_offset", 0)
        decorators: list[ast.expr] = getattr(node, "decorator_list", [])
        if decorators:
            first = min(decorators, key=lambda d: d.lineno)
            start_line = first.lineno
            line = self.lines[start_line - 1] if start_line <= len(self.lines) else ""
            start_col = len(line.encode("utf-8")) - len(line.lstrip().encode("utf-8"))
        return Range(
            self.position(start_line, start_col),
            self.position(
                getattr(node, "end_lineno", start_line) or start_line,
                getattr(node, "end_col_offset", 0) or 0,
            ),
        )

    def name_range(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> Range:
        """Range of the identifier after ``def`` / ``async def`` / ``class``."""
        line = self.lines[node.lineno - 1] if node.lineno <= len(self.lines) else ""
        match = re.compile(r"\b(?:async\s+def|def|class)\s+(\w+)").search(line)
        if match is None:
            return self.range_of(node)
        # Character offsets here are in str characters; convert through UTF-16.
        start = len(line[: match.start(1)].encode("utf-16-le")) // 2
        end = len(line[: match.end(1)].encode("utf-16-le")) // 2
        return Range(Position(node.lineno - 1, start), Position(node.lineno - 1, end))


@dataclass
class _ClassInfo:
    name: str
    qualname: str
    node: ast.ClassDef
    source: _Source
    bases: tuple[str, ...]
    base_names: tuple[str, ...]
    parent_qualname: str | None = None
    elements: dict[str, tuple[str, ast.Call]] = field(default_factory=lambda: {})


def _base_text(base: ast.expr) -> str:
    return ast.unparse(base)


def _base_short_name(base: ast.expr) -> str | None:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return None


def _collect_classes(
    source: _Source, body: Sequence[ast.stmt], prefix: str = ""
) -> list[_ClassInfo]:
    found: list[_ClassInfo] = []
    for node in body:
        if not isinstance(node, ast.ClassDef):
            continue
        qualname = f"{prefix}{node.name}"
        info = _ClassInfo(
            name=node.name,
            qualname=qualname,
            node=node,
            source=source,
            bases=tuple(_base_text(b) for b in node.bases),
            base_names=tuple(n for n in (_base_short_name(b) for b in node.bases) if n),
            parent_qualname=prefix[:-1] or None,
        )
        for stmt in node.body:
            target_name, value = _assignment(stmt)
            if target_name and isinstance(value, ast.Call):
                kind = _call_kind(value)
                if kind:
                    info.elements[target_name] = (kind, value)
        found.append(info)
        found.extend(_collect_classes(source, node.body, f"{qualname}."))
    return found


def _assignment(stmt: ast.stmt) -> tuple[str | None, ast.expr | None]:
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        target = stmt.targets[0]
        if isinstance(target, ast.Name):
            return target.id, stmt.value
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value:
        return stmt.target.id, stmt.value
    return None, None


def _call_kind(call: ast.Call) -> str | None:
    func = call.func
    name = (
        func.id
        if isinstance(func, ast.Name)
        else func.attr
        if isinstance(func, ast.Attribute)
        else None
    )
    return _ELEMENT_FUNCTIONS.get(name) if name else None


# -- locator extraction ---------------------------------------------------------------------------


@dataclass
class _Built:
    locator: dict[str, Any] = field(default_factory=lambda: {})
    dynamic: bool = False
    within_name: str | None = None
    window_name: str | None = None


class _Index:
    """All classes of the project, to resolve ``within=`` across inheritance."""

    def __init__(self, classes: Sequence[_ClassInfo]) -> None:
        self.by_name: dict[str, list[_ClassInfo]] = {}
        for info in classes:
            self.by_name.setdefault(info.name, []).append(info)

    def find_element(
        self, cls: _ClassInfo, attribute: str, seen: frozenset[int] = frozenset()
    ) -> tuple[_ClassInfo, str, ast.Call] | None:
        """The definition of ``attribute`` in ``cls`` or its (statically known) base classes."""
        if id(cls) in seen:
            return None
        if attribute in cls.elements:
            kind, call = cls.elements[attribute]
            return cls, kind, call
        for base_name in cls.base_names:
            for base in self.by_name.get(base_name, []):
                found = self.find_element(base, attribute, seen | {id(cls)})
                if found is not None:
                    return found
        return None


def _literal(node: ast.expr) -> Any:
    """str / int / None literal value, or the sentinel ``_NOT_LITERAL``."""
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return _NOT_LITERAL
    if value is None or (isinstance(value, str | int) and not isinstance(value, bool)):
        return value
    return _NOT_LITERAL


_NOT_LITERAL: Any = object()


def _flag_letters(node: ast.expr) -> str | None:
    """Letters for ``re.I | re.M`` style flag expressions; ``None`` if not statically known."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left, right = _flag_letters(node.left), _flag_letters(node.right)
        return None if left is None or right is None else left + right
    name = (
        node.attr
        if isinstance(node, ast.Attribute)
        else node.id
        if isinstance(node, ast.Name)
        else None
    )
    if name in _REGEX_FLAGS:
        return _REGEX_FLAGS[name]
    if name in _NO_OP_FLAGS:
        return ""
    if isinstance(node, ast.Constant) and node.value == 0:
        return ""
    return None


def _matcher(node: ast.expr) -> Any:
    """A string, a ``{"regex", "flags"}`` dict for ``re.compile`` calls, or ``_NOT_LITERAL``."""
    if isinstance(node, ast.Call):
        func = node.func
        name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else func.id
            if isinstance(func, ast.Name)
            else None
        )
        if name == "compile" and node.args:
            pattern = _literal(node.args[0])
            if not isinstance(pattern, str):
                return _NOT_LITERAL
            flag_node: ast.expr | None = node.args[1] if len(node.args) > 1 else None
            for keyword in node.keywords:
                if keyword.arg == "flags":
                    flag_node = keyword.value
            letters = ""
            if flag_node is not None:
                found = _flag_letters(flag_node)
                if found is None:
                    return _NOT_LITERAL
                letters = found
            data: dict[str, str] = {"regex": pattern}
            flags = "".join(sorted(set(letters)))
            if flags:
                data["flags"] = flags
            return data
        return _NOT_LITERAL
    value = _literal(node)
    return value if isinstance(value, str) or value is None else _NOT_LITERAL


def _window_data(call: ast.Call) -> tuple[dict[str, Any], bool]:
    data: dict[str, Any] = {}
    dynamic = False
    for keyword in call.keywords:
        key = _WINDOW_KEYS.get(keyword.arg or "")
        if key is None:
            if keyword.arg != "timeout":
                dynamic = dynamic or keyword.arg is None or keyword.arg not in _WINDOW_KEYS
            continue
        value = _matcher(keyword.value) if key in _MATCHER_KEYS else _literal(keyword.value)
        if value is _NOT_LITERAL or (key == "index" and not isinstance(value, int | None)):
            dynamic = True
        elif value is not None:
            data[key] = value
    return data, dynamic


def _build(
    call: ast.Call,
    kind: str,
    cls: _ClassInfo,
    index: _Index,
    visiting: frozenset[tuple[int, str]] = frozenset(),
    own_name: str | None = None,
) -> _Built:
    built = _Built()
    if kind == "window":
        data, dynamic = _window_data(call)
        built.dynamic = dynamic
        if data:
            built.locator["window"] = data
        return built
    for keyword in call.keywords:
        arg = keyword.arg
        if arg is None:  # **kwargs
            built.dynamic = True
            continue
        if arg == "timeout":
            continue
        if arg == "within":
            _resolve_within(keyword.value, built, cls, index, visiting, own_name)
        elif arg == "window":
            _resolve_window(keyword.value, built, cls, index)
        elif arg in _LOCATOR_KEYS:
            key = _LOCATOR_KEYS[arg]
            value = _matcher(keyword.value) if key in _MATCHER_KEYS else _literal(keyword.value)
            if value is _NOT_LITERAL or (
                key in ("index", "depth") and not isinstance(value, int | None)
            ):
                built.dynamic = True
            elif value is not None:
                if key == "controlType" and isinstance(value, str):
                    with contextlib.suppress(ValueError):  # keep the text as written
                        value = normalize_control_type(value)
                built.locator[key] = value
        else:
            built.dynamic = True  # unknown keyword: cannot be sure the locator is complete
    return built


def _resolve_within(
    node: ast.expr,
    built: _Built,
    cls: _ClassInfo,
    index: _Index,
    visiting: frozenset[tuple[int, str]],
    own_name: str | None,
) -> None:
    if not isinstance(node, ast.Name):
        built.dynamic = True
        return
    built.within_name = node.id
    found = index.find_element(cls, node.id)
    if found is None:
        built.dynamic = True
        return
    owner, kind, call = found
    key = (id(owner), node.id)
    if kind != "element" or key in visiting or (owner is cls and node.id == own_name):
        built.dynamic = True
        return
    inner = _build(call, kind, owner, index, visiting | {key}, node.id)
    inner_locator = {k: v for k, v in inner.locator.items() if k != "window"}
    if inner_locator:
        built.locator["within"] = inner_locator
    built.dynamic = built.dynamic or inner.dynamic


def _resolve_window(node: ast.expr, built: _Built, cls: _ClassInfo, index: _Index) -> None:
    if isinstance(node, ast.Call) and _call_kind(node) == "window":
        data, dynamic = _window_data(node)
        built.dynamic = built.dynamic or dynamic
        if data:
            built.locator["window"] = data
        return
    if isinstance(node, ast.Name):
        built.window_name = node.id
        found = index.find_element(cls, node.id)
        if found is not None and found[1] == "window":
            data, dynamic = _window_data(found[2])
            built.dynamic = built.dynamic or dynamic
            if data:
                built.locator["window"] = data
            return
    built.dynamic = True


# -- per-file analysis ----------------------------------------------------------------------------


def _screen_names(classes: Sequence[_ClassInfo]) -> set[str]:
    names = {"Screen"}
    changed = True
    while changed:
        changed = False
        for info in classes:
            if info.name not in names and any(base in names for base in info.base_names):
                names.add(info.name)
                changed = True
    return names


def _screen_entries(
    source: _Source, classes: Sequence[_ClassInfo], screens: set[str], index: _Index
) -> list[ScreenEntry]:
    entries: list[ScreenEntry] = []
    for info in classes:
        if info.source is not source or info.name not in screens or info.name == "Screen":
            continue
        elements: list[ElementEntry] = []
        for stmt in info.node.body:
            name, value = _assignment(stmt)
            if not name or not isinstance(value, ast.Call):
                continue
            kind = _call_kind(value)
            if kind is None:
                continue
            built = _build(value, kind, info, index, own_name=name)
            target: ast.AST = (
                stmt.targets[0]
                if isinstance(stmt, ast.Assign)
                else cast("ast.AnnAssign", stmt).target
            )
            elements.append(
                ElementEntry(
                    id=f"{source.rel}::{info.qualname}.{name}",
                    name=name,
                    qualname=f"{info.qualname}.{name}",
                    kind=kind,
                    range=source.range_of(stmt),
                    name_range=source.range_of(target),
                    locator=built.locator,
                    dynamic=built.dynamic,
                    within_name=built.within_name,
                    window_name=built.window_name,
                )
            )
        entries.append(
            ScreenEntry(
                id=f"{source.rel}::{info.qualname}",
                file=source.path.as_posix(),
                name=info.name,
                qualname=info.qualname,
                bases=info.bases,
                range=source.range_of(info.node),
                name_range=source.name_range(info.node),
                elements=tuple(elements),
            )
        )
    return entries


def _test_entries(source: _Source, rules: PytestRules) -> list[TestEntry]:
    assert source.tree is not None
    entries: list[TestEntry] = []

    def visit_class(node: ast.ClassDef, prefix: str, parent_id: str | None) -> None:
        if not _name_matches(node.name, rules.python_classes):
            return
        if any(
            isinstance(s, ast.FunctionDef) and s.name in ("__init__", "__new__") for s in node.body
        ):
            return
        class_id = f"{prefix}::{node.name}"
        before = len(entries)
        for stmt in node.body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                if _name_matches(stmt.name, rules.python_functions):
                    entries.append(_function_entry(stmt, class_id, class_id))
            elif isinstance(stmt, ast.ClassDef):
                visit_class(stmt, class_id, class_id)
        if len(entries) > before:
            entries.insert(
                before,
                TestEntry(
                    id=class_id,
                    file=source.path.as_posix(),
                    name=node.name,
                    kind="class",
                    parent=parent_id,
                    range=source.range_of(node),
                    name_range=source.name_range(node),
                ),
            )

    def _function_entry(
        node: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str, parent_id: str | None
    ) -> TestEntry:
        return TestEntry(
            id=f"{prefix}::{node.name}",
            file=source.path.as_posix(),
            name=node.name,
            kind="function",
            parent=parent_id,
            range=source.range_of(node),
            name_range=source.name_range(node),
        )

    for stmt in source.tree.body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            if _name_matches(stmt.name, rules.python_functions):
                entries.append(_function_entry(stmt, source.rel, None))
        elif isinstance(stmt, ast.ClassDef):
            visit_class(stmt, source.rel, None)
    return entries


# -- scanning -------------------------------------------------------------------------------------

_cache: dict[tuple[str, int, int], _Source] = {}
_CACHE_LIMIT = 4096


def _read_source(path: Path, rel: str, overrides: Mapping[Path, str]) -> _Source:
    if path in overrides:
        return _Source(path, rel, overrides[path])
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _cache.get(key)
    if cached is not None and cached.rel == rel:
        return cached
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        source = _Source(path, rel, "")
        source.tree = None
        source.error = DiscoveryError(path.as_posix(), f"not valid UTF-8: {exc.reason}", 0)
    else:
        source = _Source(path, rel, text)
    if len(_cache) >= _CACHE_LIMIT:
        _cache.pop(next(iter(_cache)))
    _cache[key] = source
    return source


def _report_dir(root: Path) -> Path | None:
    try:
        return load_config(root).report_dir.resolve()
    except ConfigError:
        return (root / DEFAULT_REPORT_DIR).resolve()


def _scan(root: Path, report_dir: Path | None) -> list[Path]:
    files: list[Path] = []
    for directory, subdirs, names in os.walk(root):
        here = Path(directory)
        subdirs[:] = sorted(
            d
            for d in subdirs
            if d not in EXCLUDED_DIRS and (report_dir is None or (here / d).resolve() != report_dir)
        )
        files.extend(here / name for name in sorted(names) if name.endswith(".py"))
    return files


def _within(path: Path, candidates: Sequence[Path]) -> bool:
    return any(path == c or c in path.parents for c in candidates)


def _testpath_roots(root: Path, rules: PytestRules) -> list[Path]:
    roots: list[Path] = []
    for pattern in rules.testpaths:
        matches = (
            sorted(root.glob(pattern)) if any(ch in pattern for ch in "*?[") else [root / pattern]
        )
        roots.extend(m.resolve() for m in matches)
    return roots


def discover(
    root: Path,
    *,
    paths: Sequence[Path] | None = None,
    overrides: Mapping[Path, str] | None = None,
) -> DiscoveryResult:
    """Discover tests and screens under ``root``.

    ``paths`` restricts which files are *reported*; the whole project is still read (from a
    cache) so screens that inherit from a screen in another file are recognized. ``overrides``
    maps absolute paths to unsaved editor contents, which win over the files on disk.
    """
    root = root.resolve()
    contents = {p.resolve(): text for p, text in (overrides or {}).items()}
    rules = load_pytest_rules(root)
    disk_files = _scan(root, _report_dir(root))
    all_files = sorted(
        {*(f.resolve() for f in disk_files), *(p for p in contents if _is_under(p, root))}
    )
    sources: list[_Source] = []
    for path in all_files:
        rel = path.relative_to(root).as_posix()
        try:
            sources.append(_read_source(path, rel, contents))
        except OSError:
            continue  # deleted between the scan and the read
    selected = [p.resolve() for p in paths] if paths else None
    testpath_roots = _testpath_roots(root, rules) if rules.testpaths else None

    parsed = [s for s in sources if s.tree is not None]
    classes: list[_ClassInfo] = []
    for source in parsed:
        assert source.tree is not None
        classes.extend(_collect_classes(source, source.tree.body))
    screens = _screen_names(classes)
    index = _Index(classes)

    tests: list[TestEntry] = []
    screen_entries: list[ScreenEntry] = []
    errors: list[DiscoveryError] = []
    for source in sources:
        if selected is not None and not _within(source.path, selected):
            continue
        if source.error is not None:
            errors.append(source.error)
            continue
        if _is_test_file(source.rel, rules) and (
            testpath_roots is None or _within(source.path, testpath_roots)
        ):
            tests.extend(_test_entries(source, rules))
        screen_entries.extend(_screen_entries(source, classes, screens, index))
    return DiscoveryResult(
        root=root.as_posix(),
        tests=tuple(tests),
        screens=tuple(screen_entries),
        errors=tuple(errors),
    )


def _is_under(path: Path, root: Path) -> bool:
    return root == path or root in path.parents


def discover_file(
    root: Path, file: Path, source: str
) -> tuple[list[TestEntry], list[ScreenEntry], list[DiscoveryError]]:
    """Analyse one file in isolation (screens are recognized only through bases in this file)."""
    root = root.resolve()
    path = file.resolve()
    rel = path.relative_to(root).as_posix() if _is_under(path, root) else path.name
    parsed = _Source(path, rel, source)
    if parsed.error is not None or parsed.tree is None:
        return [], [], [parsed.error] if parsed.error else []
    rules = load_pytest_rules(root)
    classes = _collect_classes(parsed, parsed.tree.body)
    index = _Index(classes)
    tests = _test_entries(parsed, rules) if _is_test_file(rel, rules) else []
    return tests, _screen_entries(parsed, classes, _screen_names(classes), index), []
