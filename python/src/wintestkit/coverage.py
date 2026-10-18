"""Which element definitions of the project's pages resolve to a given UI Automation element.

The Spy view asks two questions: "which definitions point at the selected object?" (exact, one
object) and "which of these loaded tree nodes are defined at all?" (many objects, approximate cost
matters). Both are answered from one lazily built index:

* a **catalogue** of every definition reachable from the project's pages, built once per change to
  the project's files (it imports the pages, so it is not rebuilt per request);
* a **sound pre-filter** that compares a node's cheap, already-read properties with each
  definition's own properties, so only definitions that *can* match are ever resolved;
* a **resolution cache** that resolves each distinct (window, locator) once per UI epoch and keeps
  the runtime ids it found, so a node is "defined" when its id is in a candidate's id set.

A definition counts only when the engine's own resolver, in its strict single-match form, returns
exactly the node. Misses are cheap: diagnostics are switched off and relocation is never searched.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from wintestkit import runtime
from wintestkit.engine.diagnose import quiet_diagnostics
from wintestkit.engine.locator import Locator, WindowLocator, match_value
from wintestkit.errors import WtkError
from wintestkit.uia import win32

if TYPE_CHECKING:
    from wintestkit.config import WtkConfig
    from wintestkit.targets import ModuleLoader
    from wintestkit.uia.element import ElementInfo

log = logging.getLogger("wintestkit.coverage")

#: Wall-clock budget of one ``covered_nodes`` call; the caller asks again for what is pending.
DEFAULT_BUDGET_SECONDS = 0.25
#: Page paths listed per definition (the rest are only counted).
MAX_PAGES_LISTED = 5


@dataclass(frozen=True)
class _Prefilter:
    """The properties of a definition's final link that the node's own properties must satisfy.

    ``None`` fields are unconstrained. ``item`` locators (grid rows and cells) resolve to an element
    other than the one the link matches, so they are never filtered.
    """

    automation_id: Any = None
    name: Any = None
    class_name: Any = None
    control_type: str | None = None
    unfiltered: bool = False

    def accepts(self, info: ElementInfo) -> bool:
        if self.unfiltered:
            return True
        return (
            (self.control_type is None or info.control_type == self.control_type)
            and (self.automation_id is None or match_value(self.automation_id, info.automation_id))
            and (self.name is None or match_value(self.name, info.name))
            and (self.class_name is None or match_value(self.class_name, info.class_name))
        )


def _prefilter(locator: Locator | WindowLocator, *, window: bool) -> _Prefilter:
    if window:
        assert isinstance(locator, WindowLocator)
        return _Prefilter(
            automation_id=locator.automation_id,
            name=locator.title,
            class_name=locator.class_name,
            unfiltered=locator.process is not None,
        )
    assert isinstance(locator, Locator)
    return _Prefilter(
        automation_id=locator.automation_id,
        name=locator.name,
        class_name=locator.class_name,
        control_type=locator.control_type,
        unfiltered=locator.item is not None,
    )


@dataclass(frozen=True)
class _Entry:
    """One (page, attribute) pair and the definition it reaches."""

    page_class: type
    attribute: str  # dotted path through mounted components, e.g. ``address.street``
    page_path: str  # ``Page.address.street``
    definition_id: str  # shared by every path that reaches the same definition
    resolution_key: Any  # equal keys resolve identically, so they share one resolution
    prefilter: _Prefilter
    kind: str  # "element" | "elements" | "window"


@dataclass(frozen=True)
class _Definition:
    """What the editor needs to show and open one definition."""

    id: str
    qualname: str
    kind: str
    element_type: str | None
    locator: str
    file: str
    line: int  # 1-based
    range: dict[str, Any] | None


@dataclass
class Catalogue:
    entries: list[_Entry] = field(default_factory=lambda: list[_Entry]())
    definitions: dict[str, _Definition] = field(default_factory=lambda: dict[str, _Definition]())
    errors: list[dict[str, str]] = field(default_factory=lambda: list[dict[str, str]]())


class _Placeholder:
    """Stands in for the application while definitions are bound but never resolved."""

    process_name = "placeholder.exe"


class _SnapshotApp:
    """Wraps an application so its processes and windows are listed once per batch.

    Every resolution otherwise re-enumerates the application's processes and windows (and wraps
    each window in a UIA element), which dominates the cost of resolving hundreds of definitions.
    Everything else is delegated to the wrapped application.
    """

    def __init__(self, app: Any) -> None:
        self._app = app
        self._pids: list[int] | None = None
        self._windows: list[Any] | None = None
        self._main: Any = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._app, name)

    @property
    def pids(self) -> list[int]:
        if self._pids is None:
            self._pids = list(self._app.pids)
        return self._pids

    def is_running(self) -> bool:
        return bool(self.pids)

    def top_level_windows(self) -> list[Any]:
        if self._windows is None:
            self._windows = list(self._app.top_level_windows())
        return list(self._windows)

    def main_window(self, timeout: float = 0.0) -> Any:
        if self._main is None:
            self._main = self._app.main_window(timeout)
        return self._main


def _range_dict(range_: Any) -> dict[str, Any]:
    return dict(range_.to_dict())


def build_catalogue(loader: ModuleLoader, cfg: WtkConfig) -> Catalogue:
    """Import the project's pages and index every definition reachable from them."""
    from wintestkit.discovery import discover
    from wintestkit.model import BoundWindow, Elements, scope_window
    from wintestkit.targets import TargetError

    catalogue = Catalogue()
    root = cfg.root.resolve()
    discovered = discover(root)
    ranges = {element.id: element.range for page in discovered.pages for element in page.elements}
    files = sorted({Path(page.file) for page in discovered.pages})
    placeholder = _Placeholder()  # never resolved: only used to build bound definitions
    mounted: set[type] = set()
    pages_by_file: dict[Path, dict[str, type]] = {}
    with runtime.config_scope(cfg):
        for file in files:
            try:
                pages_by_file[file] = dict(loader.pages_in(file))
            except TargetError as exc:
                catalogue.errors.append({"file": file.as_posix(), "message": str(exc)})
        mounted = loader.mounted_components()
        for pages in pages_by_file.values():
            for page_name, page_class in pages.items():
                if page_class in mounted:
                    continue  # reached through the pages that mount it, under dotted paths
                for attribute in loader.element_names(page_class):
                    try:
                        page = page_class(placeholder)
                        bound = page.bound_at(attribute)
                        definition = bound.definition
                        window = isinstance(bound, BoundWindow)
                        locator = bound.locator
                        page_window = None if window else scope_window(page)
                    except Exception:  # a definition that cannot even be bound is not indexable
                        log.debug("skipping %s.%s", page_name, attribute, exc_info=True)
                        continue
                    owner = getattr(definition, "owner", None)
                    name = getattr(definition, "name", None)
                    source = getattr(definition, "source", None)
                    file_path = Path(source[0]) if source else None
                    if owner is not None and name is not None and file_path is not None:
                        rel = _relative(file_path, root)
                        definition_id = f"{rel}::{owner.__qualname__}.{name}"
                        qualname = f"{owner.__qualname__}.{name}"
                    else:  # a root supplied by a mount, or an undeclared window
                        definition_id = f"{page_name}.{attribute}"
                        qualname = definition_id
                    kind = (
                        "window"
                        if window
                        else "elements"
                        if isinstance(definition, Elements)
                        else "element"
                    )
                    if definition_id not in catalogue.definitions and file_path is not None:
                        catalogue.definitions[definition_id] = _Definition(
                            id=definition_id,
                            qualname=qualname,
                            kind=kind,
                            element_type=None if window else type(definition).__name__,
                            locator=locator.describe(),
                            file=file_path.as_posix(),
                            line=int(source[1]) if source else 1,
                            range=(
                                _range_dict(ranges[definition_id])
                                if definition_id in ranges
                                else None
                            ),
                        )
                    if definition_id not in catalogue.definitions:
                        continue  # no source file to open: not worth listing
                    catalogue.entries.append(
                        _Entry(
                            page_class=page_class,
                            attribute=attribute,
                            page_path=f"{page_name}.{attribute}",
                            definition_id=definition_id,
                            resolution_key=(
                                kind,
                                page_window,
                                locator,
                                type(definition),
                                getattr(definition, "validate", True),
                            ),
                            prefilter=_prefilter(locator, window=window),
                            kind=kind,
                        )
                    )
    return catalogue


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


class Coverage:
    """Answers "which definitions resolve to this node?" with a shared resolution cache."""

    def __init__(self, loader: ModuleLoader, cfg: WtkConfig) -> None:
        self.loader = loader
        self.cfg = cfg
        self.catalogue: Catalogue | None = None
        self._generation = -1
        self._epoch: tuple[Any, ...] | None = None
        self._resolved: dict[Any, frozenset[str]] = {}

    # -- freshness ------------------------------------------------------------------------------

    def invalidate(self) -> None:
        """Forget every resolution (the UI may have changed); the catalogue is kept."""
        self._resolved.clear()
        self._epoch = None

    def _ensure_fresh(self, app: Any) -> None:
        self.loader.refresh()
        if self.catalogue is None or self._generation != self.loader.generation:
            self._generation = self.loader.generation
            self.catalogue = build_catalogue(self.loader, self.cfg)
            self._resolved.clear()
        epoch = self._ui_epoch(app) if app is not None else None
        if epoch != self._epoch:
            self._epoch = epoch
            self._resolved.clear()

    @staticmethod
    def _ui_epoch(app: Any) -> tuple[Any, ...]:
        """What invalidates resolutions on its own: other processes or other (real) windows."""
        pids = tuple(app.pids)
        windows = frozenset(
            hwnd
            for hwnd in win32.top_level_windows(set(pids))
            if win32.window_class_name(hwnd) not in _TRANSIENT_WINDOW_CLASSES
        )
        return pids, windows

    # -- resolution -----------------------------------------------------------------------------

    def _resolve(self, app: Any, entry: _Entry) -> frozenset[str]:
        """The runtime ids ``entry`` resolves to now (empty when it does not resolve)."""
        try:
            with quiet_diagnostics():
                bound = entry.page_class(app).bound_at(entry.attribute)
                if entry.kind == "elements":
                    return frozenset(element.runtime_id for element in bound.resolve_all())
                return frozenset({bound.resolve_once().runtime_id})
        except WtkError:
            return frozenset()
        except Exception:
            log.debug("could not resolve %s", entry.page_path, exc_info=True)
            return frozenset()

    def _ids(self, app: Any, entry: _Entry, *, fresh: bool = False) -> frozenset[str]:
        key = entry.resolution_key
        if fresh or key not in self._resolved:
            self._resolved[key] = self._resolve(app, entry)
        return self._resolved[key]

    # -- queries --------------------------------------------------------------------------------

    def _candidates(self, info: ElementInfo, kinds: tuple[str, ...]) -> list[_Entry]:
        assert self.catalogue is not None
        return [
            entry
            for entry in self.catalogue.entries
            if entry.kind in kinds and entry.prefilter.accepts(info)
        ]

    @staticmethod
    def _kinds(info: ElementInfo) -> tuple[str, ...]:
        # A window definition can only resolve to a top-level window.
        return (
            ("element", "elements", "window")
            if info.control_type == "Window"
            else (
                "element",
                "elements",
            )
        )

    def definitions_of(self, app: Any, node_id: str, info: ElementInfo) -> dict[str, Any]:
        """Every definition that resolves to exactly ``node_id``, re-resolved now."""
        with runtime.config_scope(self.cfg):
            self._ensure_fresh(app)
            assert self.catalogue is not None
            if app is None:
                return {
                    "definitions": [],
                    "errors": self.catalogue.errors,
                    "pageCount": len({entry.page_class for entry in self.catalogue.entries}),
                    "appRunning": False,
                }
            snapshot = _SnapshotApp(app)
            fresh: dict[Any, frozenset[str]] = {}
            grouped: dict[str, list[str]] = {}
            for entry in self._candidates(info, self._kinds(info)):
                key = entry.resolution_key
                if key not in fresh:
                    fresh[key] = self._ids(snapshot, entry, fresh=True)
                if node_id in fresh[key]:
                    grouped.setdefault(entry.definition_id, []).append(entry.page_path)
            matches = [
                self._match(self.catalogue.definitions[definition_id], paths)
                for definition_id, paths in grouped.items()
            ]
            return {
                "definitions": sorted(matches, key=lambda m: (m["file"], m["line"])),
                "errors": self.catalogue.errors,
                "pageCount": len({entry.page_class for entry in self.catalogue.entries}),
                "appRunning": True,
            }

    @staticmethod
    def _match(definition: _Definition, paths: list[str]) -> dict[str, Any]:
        unique = list(dict.fromkeys(paths))
        data: dict[str, Any] = {
            "id": definition.id,
            "qualname": definition.qualname,
            "kind": definition.kind,
            "locator": definition.locator,
            "file": definition.file,
            "line": definition.line,
            "pages": unique[:MAX_PAGES_LISTED],
            "pageCount": len(unique),
        }
        if definition.element_type:
            data["elementType"] = definition.element_type
        if definition.range is not None:
            data["range"] = definition.range
        return data

    def covered_nodes(
        self,
        app: Any,
        nodes: dict[str, ElementInfo],
        budget: float = DEFAULT_BUDGET_SECONDS,
    ) -> dict[str, Any]:
        """For each node id, how many definitions resolve to it, resolving as little as possible.

        Stops starting new resolutions once ``budget`` seconds are spent; the node ids it could
        not finish are returned as ``pending`` so the caller can ask again.
        """
        with runtime.config_scope(self.cfg):
            self._ensure_fresh(app)
            # The budget covers resolving definitions, not importing the pages to index them.
            deadline = time.monotonic() + budget
            assert self.catalogue is not None
            snapshot = _SnapshotApp(app)
            covered: dict[str, Any] = {}
            pending: list[str] = []
            for node_id, info in nodes.items():
                defined: dict[str, None] = {}  # distinct definitions, in catalogue order
                complete = True
                for entry in self._candidates(info, self._kinds(info)):
                    key = entry.resolution_key
                    if key not in self._resolved:
                        if time.monotonic() >= deadline:
                            complete = False
                            continue
                        self._ids(snapshot, entry)
                    if node_id in self._resolved[key]:
                        defined[entry.definition_id] = None
                if defined:
                    first = self.catalogue.definitions[next(iter(defined))].qualname
                    covered[node_id] = {"count": len(defined), "first": first}
                if not complete:
                    pending.append(node_id)
            return {"covered": covered, "pending": pending}


# Popup/helper windows that come and go with tooltips and menus must not invalidate resolutions.
_TRANSIENT_WINDOW_CLASSES = frozenset(
    {"Xaml_WindowedPopupClass", "Microsoft.UI.Content.PopupWindowSiteBridge", "tooltips_class32"}
)
