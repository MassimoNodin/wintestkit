"""Targets: how the CLI and the editor refer to a page or element definition in user code.

A target is ``path/to/pages/main.py::MainPage.sign_in`` (or ``...::MainPage`` for a whole
page). The module loader imports the user's modules and reloads them when files change, so
edits in the editor take effect without restarting the server.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

from wintestkit import runtime
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
    from wintestkit.model import Page
    from wintestkit.uia.element import ElementInfo, UIAElement

_SCAN_INTERVAL = 0.2


class TargetError(WtkError):
    """A target that cannot be resolved to a page or element definition."""


@dataclass(frozen=True)
class Target:
    """A page or element definition: a file plus a dotted qualified name inside it."""

    file: Path
    qualname: str

    def display(self, root: Path | None = None) -> str:
        try:
            shown = self.file.relative_to(root).as_posix() if root else self.file.as_posix()
        except ValueError:
            shown = self.file.as_posix()
        return f"{shown}::{self.qualname}" if self.qualname else shown


def parse_target(text: str, root: Path, *, require_qualname: bool = False) -> Target:
    """Parse ``FILE::Page.element``. Relative files are resolved against ``root``."""
    file_part, separator, qualname = text.partition("::")
    if not file_part.strip():
        raise TargetError(f"invalid target {text!r}: expected FILE::Page.element")
    if (separator and not qualname.strip()) or (require_qualname and not separator):
        raise TargetError(f"invalid target {text!r}: expected FILE::Page.element")
    if qualname and not all(part.isidentifier() for part in qualname.strip().split(".")):
        raise TargetError(f"invalid target {text!r}: expected a dotted page attribute")
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
    """An :class:`ElementResult` for one element of a page."""

    qualname: str = ""
    locator: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["qualname"] = self.qualname
        return data


@dataclass
class FlowResult:
    """Outcome of running one flow (mirrors the protocol ``FlowRunResult``)."""

    status: str
    duration_ms: float
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"status": self.status, "durationMs": round(self.duration_ms, 1)}
        if self.message is not None:
            data["message"] = self.message
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
        #: Bumped whenever the project's modules are purged because a file changed, so callers that
        #: cache what the pages declare can tell when it is stale.
        self.generation = 0

    # -- change detection -----------------------------------------------------------------------

    def _scan(self) -> dict[Path, tuple[int, int]]:
        stamps: dict[Path, tuple[int, int]] = {}
        report_dir = self.cfg.report_dir.resolve()
        for directory, subdirs, names in os.walk(self.root):
            here = Path(directory)
            subdirs[:] = [
                d
                for d in subdirs
                if not d.startswith(".")
                and d not in EXCLUDED_DIRS
                and (here / d).resolve() != report_dir
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
            self.generation += 1
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

    def pages_in(self, file: Path) -> dict[str, type[Page]]:
        """Page classes defined in ``file`` (not merely imported there), by name."""
        from wintestkit.model import Page

        module = self.load(file)
        return {
            name: value
            for name, value in vars(module).items()
            if isinstance(value, type)
            and issubclass(value, Page)
            and value is not Page
            and value.__module__ == module.__name__
        }

    def mounted_components(self) -> set[type[Page]]:
        """Page classes mounted as a component by any page class loaded from the project."""
        from wintestkit.model import Page

        mounted: set[type[Page]] = set()
        for module in list(sys.modules.values()):
            file = getattr(module, "__file__", None)
            if not file or self.root not in Path(file).resolve().parents:
                continue
            for value in list(vars(module).values()):
                if (
                    isinstance(value, type)
                    and issubclass(value, Page)
                    and value.__module__ == module.__name__
                ):
                    mounted.update(type(child) for child in value.children().values())
        return mounted

    def _walk(self, target: Target) -> tuple[type[Page], list[str]]:
        """The deepest ``Page`` class on the qualified name and the remaining attributes."""
        from wintestkit.model import Page

        module = self.load(target.file)
        parts = [p for p in target.qualname.split(".") if p]
        if not parts:
            raise TargetError(f"{target.file.name}: the target names no page")
        obj: Any = module
        page: type[Page] | None = None
        page_parts = 0
        consumed = 0
        for index, part in enumerate(parts):
            try:
                obj = getattr(cast("object", obj), part)
            except AttributeError:
                break
            consumed = index + 1
            if isinstance(obj, type) and issubclass(obj, Page):
                page = obj
                page_parts = consumed
            elif page is not None:
                break
        if page is None:
            names = ", ".join(sorted(self.pages_in(target.file))) or "none"
            raise TargetError(
                f"{target.file.name} has no page {parts[0]!r} (pages in this file: {names})"
            )
        return page, parts[page_parts:]

    def get_page(self, target: Target) -> type[Page]:
        page, remaining = self._walk(target)
        if remaining:
            raise TargetError(
                f"{target.qualname!r} names an element, not a page; use FILE::{page.__name__}"
            )
        return page

    def get_element(self, target: Target) -> tuple[type[Page], str]:
        """The page class and attribute path; a bare page means its ``window``.

        The path is dotted through mounted components (``address.street``); a component on its
        own means its ``root``.
        """
        from wintestkit.model import Element, PageObject, Window

        page, remaining = self._walk(target)
        if not remaining:
            return page, "window"
        owner: type[Page] = page
        for part in remaining[:-1]:
            child: Any = getattr(owner, part, None)
            if not isinstance(child, PageObject):
                raise TargetError(f"{target.qualname!r} is not a page attribute")
            owner = type(child)
        attribute = remaining[-1]
        definition: Any = getattr(owner, attribute, None)
        if isinstance(definition, PageObject):
            return page, ".".join(remaining)
        if not isinstance(definition, Element | Window):
            known = ", ".join(sorted(self.element_names(owner))) or "none"
            raise TargetError(f"{owner.__name__} has no element {attribute!r} (elements: {known})")
        return page, ".".join(remaining)

    @staticmethod
    def element_names(page: type[Page], _seen: tuple[type, ...] = ()) -> list[str]:
        """Own elements and windows, then those of mounted components under dotted names."""
        from wintestkit.model import Element, Window

        names: dict[str, None] = {}
        for klass in reversed(page.__mro__):
            for name, value in vars(klass).items():
                if isinstance(value, Element | Window):
                    names[name] = None
                else:
                    names.pop(name, None)
        for name, child in page.children().items():
            if type(child) in (*_seen, page):
                continue  # composition cycle
            nested = ModuleLoader.element_names(type(child), (*_seen, page))
            if "root" in child.declared() and "root" not in nested:
                nested.insert(0, "root")  # a root supplied by the mount itself
            names.update({f"{name}.{inner}": None for inner in nested})
        return list(names)


# -- resolving ------------------------------------------------------------------------------------


def _bound_for(app: App, page_class: type[Page], attribute: str) -> Any:
    return page_class(app).bound_at(attribute)


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
    """Bind the target's page to ``app`` and resolve the element (``timeout`` 0: immediately)."""
    started = time.perf_counter()
    with runtime.config_scope(loader.cfg):
        page_class, attribute = loader.get_element(target)
        return resolve_bound(_bound_for(app, page_class, attribute), timeout, started)


def check_page(
    app: App, loader: ModuleLoader, file: Path, page_name: str | None = None, timeout: float = 0.0
) -> list[CheckResult]:
    """Resolve every element of one page (or every page of ``file``) once, in source order.

    A not-found element is always a failure ("broken/moved"); its message says where it went when
    the relocation search found it. All searches share one time budget.
    """
    from wintestkit.engine import relocate

    with runtime.config_scope(loader.cfg), relocate.shared_budget():
        return _check_page(app, loader, file, page_name, timeout)


def _check_page(
    app: App, loader: ModuleLoader, file: Path, page_name: str | None, timeout: float
) -> list[CheckResult]:
    """Resolve every element of one page (or every page of ``file``) once, in source order."""
    pages = loader.pages_in(file)
    if not pages:
        raise TargetError(f"{file.name} defines no pages")
    if page_name:
        if page_name not in pages:
            known = ", ".join(sorted(pages)) or "none"
            raise TargetError(f"{file.name} has no page {page_name!r} (pages: {known})")
        pages = {page_name: pages[page_name]}
    else:
        # Reusable components are checked through the pages that mount them; searching a box
        # standalone in the main window only produces false "not found" noise.
        mounted = loader.mounted_components()
        pages = {name: klass for name, klass in pages.items() if klass not in mounted}
    results: list[CheckResult] = []
    for name, page_class in pages.items():
        for attribute in loader.element_names(page_class):
            bound = _bound_for(app, page_class, attribute)
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


def run_flow(
    app: App,
    loader: ModuleLoader,
    file: Path,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> FlowResult:
    """Call a flow with its app and validated scalar arguments, awaiting async flows.

    An exception raised by the flow is a failed result rather than an error, with the user's
    innermost frame in the message.
    """
    module = loader.load(file)
    flow = getattr(module, name, None)
    if name.startswith("_") or not callable(flow) or isinstance(flow, type):
        raise TargetError(f"{file.name} has no flow {name!r}")
    parameters = list(inspect.signature(flow).parameters.values())
    required = [
        p.name
        for p in parameters
        if p.default is p.empty and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    ]
    first = parameters[0] if parameters else None
    if (
        not required
        or required[0] != "app"
        or first is None
        or first.name != "app"
        or first.kind is first.KEYWORD_ONLY
    ):
        needs = ", ".join(required) or "no parameters"
        raise TargetError(
            f"flow {name!r} cannot be run from the editor: it needs ({needs}); "
            "only flows whose only required parameter is 'app' can be run"
        )
    started = time.perf_counter()
    try:
        with runtime.config_scope(loader.cfg):
            values = arguments or {}
            signature = inspect.signature(flow)
            allowed = {parameter for parameter in signature.parameters if parameter != "app"}
            missing = set(required[1:]) - set(values)
            if missing:
                raise TargetError(
                    "flow arguments are missing required parameters: "
                    + ", ".join(sorted(missing))
                )
            if set(values) - allowed:
                raise TargetError("flow arguments contain unknown parameter names")
            for key, value in values.items():
                annotation = signature.parameters[key].annotation
                expected = (
                    annotation
                    if annotation in (str, int, float, bool)
                    else {"str": str, "int": int, "float": float, "bool": bool}.get(
                        annotation
                    )
                )
                if expected is None or type(value) is not expected:
                    raise TargetError(f"flow argument {key!r} must be a supported typed scalar")
            outcome = flow(app, **values)
            if inspect.isawaitable(outcome):

                async def finish() -> None:
                    await outcome

                asyncio.run(finish())
    except Exception as exc:
        frames = [
            f
            for f in traceback.extract_tb(exc.__traceback__)
            if loader.root in Path(f.filename).resolve().parents
        ]
        where = f" ({Path(frames[-1].filename).as_posix()}:{frames[-1].lineno})" if frames else ""
        return FlowResult(
            "failed", (time.perf_counter() - started) * 1000, f"{type(exc).__name__}: {exc}{where}"
        )
    return FlowResult("passed", (time.perf_counter() - started) * 1000)
