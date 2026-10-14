"""Targets: how the CLI and the editor refer to a screen or element definition in user code.

A target is ``path/to/screens/main.py::MainScreen.sign_in`` (or ``...::MainScreen`` for a whole
screen). The module loader imports the user's modules and reloads them when files change, so
edits in the editor take effect without restarting the server.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

from wintestkit.config import WtkConfig
from wintestkit.discovery import EXCLUDED_DIRS
from wintestkit.errors import (
    AmbiguousElementError,
    LocatorError,
    WtkError,
)

if TYPE_CHECKING:
    from wintestkit.app import App
    from wintestkit.engine.diagnose import Diagnostic
    from wintestkit.model import Screen
    from wintestkit.uia.element import ElementInfo, UIAElement

_SCAN_INTERVAL = 0.2


class TargetError(WtkError):
    """A target that cannot be resolved to a screen or element definition."""


@dataclass(frozen=True)
class Target:
    """A screen or element definition: a file plus a dotted qualified name inside it."""

    file: Path
    qualname: str

    def display(self, root: Path | None = None) -> str:
        try:
            shown = self.file.relative_to(root).as_posix() if root else self.file.as_posix()
        except ValueError:
            shown = self.file.as_posix()
        return f"{shown}::{self.qualname}" if self.qualname else shown


def parse_target(text: str, root: Path, *, require_qualname: bool = False) -> Target:
    """Parse ``FILE::Screen.element``. Relative files are resolved against ``root``."""
    file_part, separator, qualname = text.partition("::")
    if not file_part.strip():
        raise TargetError(f"invalid target {text!r}: expected FILE::Screen.element")
    if (separator and not qualname.strip()) or (require_qualname and not separator):
        raise TargetError(f"invalid target {text!r}: expected FILE::Screen.element")
    if qualname and not all(part.isidentifier() for part in qualname.strip().split(".")):
        raise TargetError(f"invalid target {text!r}: expected a dotted screen attribute")
    path = Path(file_part)
    file = path if path.is_absolute() else root / path
    return Target(file.resolve(), qualname.strip())


# -- results --------------------------------------------------------------------------------------


@dataclass
class ElementResult:
    """Outcome of resolving a target (mirrors the protocol ``ElementResult``)."""

    status: str
    duration_ms: float
    element: ElementInfo | None = None
    diagnostic: Diagnostic | None = None
    message: str | None = None
    uia: UIAElement | None = None  # the live element; never serialized

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"status": self.status, "durationMs": round(self.duration_ms, 1)}
        if self.element is not None:
            data["element"] = self.element.to_dict()
        if self.diagnostic is not None:
            data["diagnostic"] = self.diagnostic.to_dict()
        if self.message is not None:
            data["message"] = self.message
        return data


@dataclass
class CheckResult(ElementResult):
    """An :class:`ElementResult` for one element of a screen."""

    qualname: str = ""
    locator: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["qualname"] = self.qualname
        return data


# -- module loading -------------------------------------------------------------------------------


class ModuleLoader:
    """Imports user modules by file and reloads them when the project's files change."""

    def __init__(self, cfg: WtkConfig) -> None:
        self.cfg = cfg
        self.root = cfg.root.resolve()
        self.python_paths = [p.resolve() for p in cfg.python_paths] or [self.root]
        for path in reversed(self.python_paths):
            text = str(path)
            if text in sys.path:
                sys.path.remove(text)
            sys.path.insert(0, text)
        self._stamps: dict[Path, tuple[int, int]] | None = None
        self._last_scan = 0.0

    # -- change detection -----------------------------------------------------------------------

    def _scan(self) -> dict[Path, tuple[int, int]]:
        stamps: dict[Path, tuple[int, int]] = {}
        report_dir = self.cfg.report_dir.resolve()
        for directory, subdirs, names in os.walk(self.root):
            here = Path(directory)
            subdirs[:] = [
                d for d in subdirs if d not in EXCLUDED_DIRS and (here / d).resolve() != report_dir
            ]
            for name in names:
                if name.endswith(".py"):
                    path = here / name
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    stamps[path] = (stat.st_mtime_ns, stat.st_size)
        return stamps

    def _purge_project_modules(self) -> None:
        for name, module in list(sys.modules.items()):
            if name == "wintestkit" or name.startswith("wintestkit."):
                continue
            file = getattr(module, "__file__", None)
            if not file:
                continue
            path = Path(file).resolve()
            if self.root in path.parents and not any(
                part in EXCLUDED_DIRS for part in path.relative_to(self.root).parts
            ):
                del sys.modules[name]
                if path.suffix == ".py":
                    cached = Path(importlib.util.cache_from_source(str(path)))
                    if cached.parent == path.parent / "__pycache__":
                        cached.unlink(missing_ok=True)
        importlib.invalidate_caches()

    def refresh(self, *, force: bool = False) -> bool:
        """Reload-on-change: purge the project's modules if any file changed; ``True`` if purged."""
        now = time.monotonic()
        if not force and self._stamps is not None and now - self._last_scan < _SCAN_INTERVAL:
            return False
        self._last_scan = now
        stamps = self._scan()
        changed = self._stamps is not None and stamps != self._stamps
        self._stamps = stamps
        if changed:
            self._purge_project_modules()
        return changed

    # -- loading --------------------------------------------------------------------------------

    def module_name(self, file: Path) -> str:
        """Dotted module name of ``file`` relative to the first python path containing it."""
        file = file.resolve()
        for base in self.python_paths:
            if base == file.parent or base in file.parents:
                parts = list(file.relative_to(base).with_suffix("").parts)
                if parts[-1] == "__init__":
                    parts.pop()
                if parts:
                    return ".".join(parts)
        return file.stem

    def load(self, file: Path) -> ModuleType:
        file = file.resolve()
        if not file.is_file() or file.suffix != ".py":
            raise TargetError(f"file not found: {file}")
        self.refresh()
        name = self.module_name(file)
        if not any(base in file.parents or base == file.parent for base in self.python_paths):
            parent = str(file.parent)
            if parent not in sys.path:
                sys.path.insert(0, parent)
        for prefix_length in range(1, len(name.split(".")) + 1):
            prefix = ".".join(name.split(".")[:prefix_length])
            existing = sys.modules.get(prefix)
            if existing is None:
                continue
            locations = getattr(existing, "__path__", None)
            origin = getattr(existing, "__file__", None)
            matches = (
                any(file.is_relative_to(Path(location).resolve()) for location in locations)
                if locations is not None
                else origin is not None and Path(origin).resolve() == file
            )
            if not matches:
                for cached_name in list(sys.modules):
                    if cached_name == prefix or cached_name.startswith(prefix + "."):
                        del sys.modules[cached_name]
                importlib.invalidate_caches()
        try:
            return importlib.import_module(name)
        except Exception as exc:
            raise TargetError(self._summarize(file, exc)) from exc

    def _summarize(self, file: Path, exc: BaseException) -> str:
        """``cannot import FILE: ErrorType: message (file:line)`` — the user's innermost frame."""
        where = ""
        if isinstance(exc, SyntaxError) and exc.lineno:
            where = f" ({Path(exc.filename or file).as_posix()}:{exc.lineno})"
        else:
            frames = [
                f
                for f in traceback.extract_tb(exc.__traceback__)
                if self.root in Path(f.filename).resolve().parents
            ]
            if frames:
                where = f" ({Path(frames[-1].filename).as_posix()}:{frames[-1].lineno})"
        reason = exc.msg if isinstance(exc, SyntaxError) else str(exc)
        return f"cannot import {file.name}: {type(exc).__name__}: {reason}{where}"

    # -- lookup ---------------------------------------------------------------------------------

    def screens_in(self, file: Path) -> dict[str, type[Screen]]:
        """Screen classes defined in ``file`` (not merely imported there), by name."""
        from wintestkit.model import Screen

        module = self.load(file)
        return {
            name: value
            for name, value in vars(module).items()
            if isinstance(value, type)
            and issubclass(value, Screen)
            and value is not Screen
            and value.__module__ == module.__name__
        }

    def _walk(self, target: Target) -> tuple[type[Screen], list[str]]:
        """The deepest ``Screen`` class on the qualified name and the remaining attributes."""
        from wintestkit.model import Screen

        module = self.load(target.file)
        parts = [p for p in target.qualname.split(".") if p]
        if not parts:
            raise TargetError(f"{target.file.name}: the target names no screen")
        obj: Any = module
        screen: type[Screen] | None = None
        screen_parts = 0
        consumed = 0
        for index, part in enumerate(parts):
            try:
                obj = getattr(cast("object", obj), part)
            except AttributeError:
                break
            consumed = index + 1
            if isinstance(obj, type) and issubclass(obj, Screen):
                screen = obj
                screen_parts = consumed
            elif screen is not None:
                break
        if screen is None:
            names = ", ".join(sorted(self.screens_in(target.file))) or "none"
            raise TargetError(
                f"{target.file.name} has no screen {parts[0]!r} (screens in this file: {names})"
            )
        return screen, parts[screen_parts:]

    def get_screen(self, target: Target) -> type[Screen]:
        screen, remaining = self._walk(target)
        if remaining:
            raise TargetError(
                f"{target.qualname!r} names an element, not a screen; use FILE::{screen.__name__}"
            )
        return screen

    def get_element(self, target: Target) -> tuple[type[Screen], str]:
        """The screen class and attribute name; a bare screen means its ``window``."""
        from wintestkit.model import Element, Window

        screen, remaining = self._walk(target)
        if not remaining:
            return screen, "window"
        if len(remaining) != 1:
            raise TargetError(f"{target.qualname!r} is not a screen attribute")
        attribute = remaining[0]
        definition: Any = getattr(screen, attribute, None)
        if not isinstance(definition, Element | Window):
            known = ", ".join(sorted(self.element_names(screen))) or "none"
            raise TargetError(f"{screen.__name__} has no element {attribute!r} (elements: {known})")
        return screen, attribute

    @staticmethod
    def element_names(screen: type[Screen]) -> list[str]:
        from wintestkit.model import Element, Window

        names: dict[str, None] = {}
        for klass in reversed(screen.__mro__):
            for name, value in vars(klass).items():
                if isinstance(value, Element | Window):
                    names[name] = None
                else:
                    names.pop(name, None)
        return list(names)


# -- resolving ------------------------------------------------------------------------------------


def _bound_for(app: App, screen_class: type[Screen], attribute: str) -> Any:
    from wintestkit.model import BoundWindow, Window

    screen = screen_class(app)
    bound: Any = getattr(screen, attribute, None) if hasattr(screen_class, attribute) else None
    if bound is None:
        return BoundWindow(screen, Window())  # no window declared: the application's main window
    return bound


def resolve_bound(bound: Any, timeout: float, started: float | None = None) -> ElementResult:
    """Resolve a bound element or window into an :class:`ElementResult`; never raises Wtk errors."""
    from wintestkit.model import BoundElements

    started = time.perf_counter() if started is None else started

    def elapsed() -> float:
        return (time.perf_counter() - started) * 1000

    try:
        if isinstance(bound, BoundElements):
            bound = bound.first()
        element = bound.resolve(timeout)
        return ElementResult("found", elapsed(), element=element.info(), uia=element)
    except AmbiguousElementError as exc:
        return ElementResult("ambiguous", elapsed(), diagnostic=exc.diagnostic, message=str(exc))
    except LocatorError as exc:
        return ElementResult("not_found", elapsed(), diagnostic=exc.diagnostic, message=str(exc))
    except WtkError as exc:
        return ElementResult("error", elapsed(), message=str(exc))


def resolve_target(
    app: App, loader: ModuleLoader, target: Target, timeout: float = 0.0
) -> ElementResult:
    """Bind the target's screen to ``app`` and resolve the element (``timeout`` 0: immediately)."""
    started = time.perf_counter()
    screen_class, attribute = loader.get_element(target)  # TargetError propagates
    return resolve_bound(_bound_for(app, screen_class, attribute), timeout, started)


def check_screen(
    app: App, loader: ModuleLoader, file: Path, screen_name: str | None = None, timeout: float = 0.0
) -> list[CheckResult]:
    """Resolve every element of one screen (or every screen of ``file``) once, in source order."""
    screens = loader.screens_in(file)
    if not screens:
        raise TargetError(f"{file.name} defines no screens")
    if screen_name:
        if screen_name not in screens:
            known = ", ".join(sorted(screens)) or "none"
            raise TargetError(f"{file.name} has no screen {screen_name!r} (screens: {known})")
        screens = {screen_name: screens[screen_name]}
    results: list[CheckResult] = []
    for name, screen_class in screens.items():
        for attribute in loader.element_names(screen_class):
            bound = _bound_for(app, screen_class, attribute)
            outcome = resolve_bound(bound, timeout)
            locator = getattr(bound, "locator", None)
            results.append(
                CheckResult(
                    status=outcome.status,
                    duration_ms=outcome.duration_ms,
                    element=outcome.element,
                    diagnostic=outcome.diagnostic,
                    message=outcome.message,
                    uia=outcome.uia,
                    qualname=f"{name}.{attribute}",
                    locator=locator.describe() if locator is not None else "",
                )
            )
    return results
