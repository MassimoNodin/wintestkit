"""Newline-delimited JSON-RPC for the editor, with serialized UI Automation requests."""

from __future__ import annotations

import contextlib
import json
import logging
import math
import platform
import queue
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, cast

from wintestkit import __version__
from wintestkit.config import load_config
from wintestkit.errors import AppNotRunningError, ConfigError, EnvironmentNotReadyError, WtkError
from wintestkit.protocol import PROTOCOL_VERSION

if TYPE_CHECKING:
    from wintestkit.app import App
    from wintestkit.config import WtkConfig
    from wintestkit.coverage import Coverage
    from wintestkit.engine.spy import SpySession
    from wintestkit.targets import ModuleLoader
    from wintestkit.uia.element import ElementInfo, Rect, UIAElement

log = logging.getLogger("wintestkit.server")

_PARAMS: dict[str, tuple[set[str], set[str]]] = {
    "initialize": ({"root"}, set()),
    "shutdown": (set(), set()),
    "discover": (set(), {"overrides"}),
    "app.status": (set(), set()),
    "app.launch": (set(), set()),
    "app.close": (set(), set()),
    "app.processes": (set(), set()),
    "element.highlight": ({"file", "qualname"}, {"durationMs"}),
    "page.check": ({"file", "page"}, set()),
    "flow.run": ({"file", "name"}, {"arguments"}),
    "inspect.roots": (set(), {"includeOtherApps", "foregroundForProcessId"}),
    "inspect.refresh": (set(), {"includeOtherApps", "foregroundForProcessId"}),
    "inspect.children": ({"nodeId"}, set()),
    "inspect.properties": ({"nodeId"}, {"full", "includeAncestors"}),
    "inspect.highlight": ({"nodeId"}, {"durationMs", "bringToFront"}),
    "suggest.locator": ({"nodeId"}, set()),
    "inspect.definitions": ({"nodeId"}, set()),
    "inspect.coverage": ({"nodeIds"}, set()),
    "spy.start": (set(), {"sessionId"}),
    "spy.stop": (set(), set()),
}


MAX_COVERAGE_NODES = 500

# Windows that XAML apps (UWP, WinUI) create to show a popup: they turn visible while a tooltip,
# menu or flyout is open and hidden again afterwards, so they come and go in the roots list.
POPUP_SURFACE_CLASSES = frozenset(
    {"Xaml_WindowedPopupClass", "Microsoft.UI.Content.PopupWindowSiteBridge"}
)


def _is_popup_surface(window: UIAElement) -> bool:
    try:
        return window.class_name in POPUP_SURFACE_CLASSES
    except Exception:
        return False  # the window closed while reading it; registering it reports the failure


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def _invalid_constant(value: str) -> Any:
    raise ValueError(f"invalid JSON constant: {value}")


class _LogForwarder(logging.Handler):
    def __init__(self, server: Server) -> None:
        super().__init__(logging.getLogger("wintestkit").getEffectiveLevel())
        self.server = server

    def emit(self, record: logging.LogRecord) -> None:
        self.server.notify(
            "log", {"level": record.levelname.lower(), "message": record.getMessage()}
        )


class Server:
    def __init__(self, output: BinaryIO) -> None:
        self.output = output
        self.cfg: WtkConfig | None = None
        self.loader: ModuleLoader | None = None
        self.app: App | None = None
        # Ownership is deliberately independent of the configured launch mode. The server can
        # attach to a process it did not start.
        self._owned_app_pids: set[int] | None = None
        self.nodes: OrderedDict[str, UIAElement] = OrderedDict()
        self.node_infos: dict[str, ElementInfo] = {}
        self.coverage: Coverage | None = None
        self.spy: SpySession | None = None
        self._write_lock = threading.Lock()
        self._node_lock = threading.Lock()
        self._spy_lock = threading.RLock()
        self._stopping = threading.Event()
        self._spy_epoch = 0

    def _write(self, message: dict[str, Any]) -> None:
        encoded = (json.dumps(message, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        with self._write_lock:
            self.output.write(encoded)
            self.output.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        if not self._stopping.is_set():
            self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _error(self, request_id: Any, code: int, message: str, data: Any = None) -> None:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        self._write({"jsonrpc": "2.0", "id": request_id, "error": error})

    def _params(self, method: str, params: Any) -> dict[str, Any]:
        if method not in _PARAMS:
            raise RpcError(-32601, "method not found")
        required, optional = _PARAMS[method]
        if not isinstance(params, dict):
            raise RpcError(-32602, "invalid params")
        params = cast("dict[str, Any]", params)
        if not required <= params.keys() or params.keys() - required - optional:
            raise RpcError(-32602, "invalid params")
        for key, value in params.items():
            if key == "durationMs":
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int | float)
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise RpcError(-32602, "durationMs must be a finite nonnegative number")
            elif key == "foregroundForProcessId":
                if type(value) is not int or value <= 0:
                    raise RpcError(-32602, "foregroundForProcessId must be a positive integer")
            elif key in ("full", "includeAncestors", "includeOtherApps", "bringToFront"):
                if not isinstance(value, bool):
                    raise RpcError(-32602, f"{key} must be a boolean")
            elif key == "nodeIds":
                if (
                    not isinstance(value, list)
                    or len(cast("list[Any]", value)) > MAX_COVERAGE_NODES
                    or any(
                        not isinstance(item, str) or not item for item in cast("list[Any]", value)
                    )
                ):
                    raise RpcError(
                        -32602, f"nodeIds must list at most {MAX_COVERAGE_NODES} nonempty strings"
                    )
            elif key == "arguments":
                if not isinstance(value, dict):
                    raise RpcError(-32602, "flow arguments must be an object")
            elif key == "overrides":
                if not isinstance(value, dict):
                    raise RpcError(-32602, "overrides must map paths to source strings")
                value = cast("dict[Any, Any]", value)
                if any(
                    not isinstance(path, str) or not isinstance(source, str)
                    for path, source in value.items()
                ):
                    raise RpcError(-32602, "overrides must map paths to source strings")
            elif not isinstance(value, str) or not value:
                raise RpcError(-32602, f"{key} must be a nonempty string")
        return params

    def handle(self, request: Any) -> None:
        if not isinstance(request, dict):
            self._error(None, -32600, "invalid request")
            return
        request = cast("dict[str, Any]", request)
        valid_id = (
            "id" not in request
            or request["id"] is None
            or (isinstance(request["id"], str | int) and not isinstance(request["id"], bool))
        )
        if (
            not valid_id
            or request.get("jsonrpc") != "2.0"
            or not isinstance(request.get("method"), str)
        ):
            self._error(None, -32600, "invalid request")
            return
        request_id = request.get("id")
        notification = "id" not in request
        try:
            method = request["method"]
            if self.cfg is None and method not in ("initialize", "shutdown"):
                raise RpcError(-32600, "not initialized")
            params = self._params(method, request.get("params", {}))
            result = self.dispatch(method, params, request.get("_spyEpoch"))
            if not notification and (not self._stopping.is_set() or method == "shutdown"):
                self._write({"jsonrpc": "2.0", "id": request_id, "result": result})
        except Exception as exc:
            if notification or self._stopping.is_set():
                return
            if isinstance(exc, RpcError):
                self._error(request_id, exc.code, exc.message, exc.data)
            elif isinstance(exc, WtkError):
                from wintestkit.targets import TargetError

                code = (
                    -32001
                    if isinstance(exc, ConfigError)
                    else -32002
                    if isinstance(exc, AppNotRunningError)
                    else -32003
                    if isinstance(exc, TargetError)
                    else -32004
                    if isinstance(exc, EnvironmentNotReadyError)
                    else -32603
                )
                self._error(request_id, code, str(exc), exc.to_dict())
            else:
                log.exception("RPC request failed")
                self._error(request_id, -32603, "internal error", {"message": str(exc)})

    @staticmethod
    def _raise_for_highlight(element: UIAElement) -> Rect | None:
        """Raise the element's window without taking focus, then read its bounds.

        An element without bounds (offscreen, collapsed, never laid out) has nothing to outline, so
        its window is left alone. A minimized window is the exception: its controls have no bounds
        until it is restored.
        """
        from wintestkit.engine.actions import raise_without_activating, window_is_minimized

        if element.rect is None and not window_is_minimized(element):
            return None
        raise_without_activating(element)
        return element.rect

    @staticmethod
    def _flash(rect: Rect | None, params: dict[str, Any]) -> None:
        """Outline ``rect`` for a moment."""
        from wintestkit.engine import overlay

        if rect is not None:
            overlay.flash(rect, int(params.get("durationMs", 1500)), block=False)

    def _app(self, required: bool = True) -> App | None:
        from wintestkit.app import App

        if self.app is not None and self.app.is_running():
            return self.app
        self.app = None
        self._owned_app_pids = None
        if self.cfg is not None and self.cfg.app is not None:
            with contextlib.suppress(AppNotRunningError):
                self.app = App.attach(process=self.cfg.app.process_name)
        if self.app is None and required:
            raise AppNotRunningError("App is not running. Start it or call app.launch.")
        return self.app

    def _coverage(self) -> Coverage:
        from wintestkit.coverage import Coverage

        assert self.cfg is not None and self.loader is not None
        if self.coverage is None:
            self.coverage = Coverage(self.loader, self.cfg)
        return self.coverage

    def _register(self, element: UIAElement) -> dict[str, Any]:
        from wintestkit.uia.constants import TreeScope

        info = element.info()
        if not info.runtime_id:
            raise RpcError(-32005, "element has no runtime id")
        with self._node_lock:
            self.nodes[info.runtime_id] = element
            self.node_infos[info.runtime_id] = info
            self.nodes.move_to_end(info.runtime_id)
            if len(self.nodes) > 5000:
                evicted, _ = self.nodes.popitem(last=False)
                self.node_infos.pop(evicted, None)
        return {
            "nodeId": info.runtime_id,
            "info": info.to_dict(),
            "hasChildren": element.find_first(TreeScope.Children) is not None,
        }

    def _node(self, node_id: str) -> UIAElement:
        with self._node_lock:
            node = self.nodes.get(node_id)
            if node is not None:
                self.nodes.move_to_end(node_id)
        if node is None or not node.is_alive():
            raise RpcError(-32005, "unknown node id")
        return node.as_live()

    def stop_spy(self, expected_epoch: int | None = None) -> None:
        with self._spy_lock:
            if expected_epoch is not None and expected_epoch != self._spy_epoch:
                return
            self._spy_epoch += 1
            session, self.spy = self.spy, None
        if session is not None:
            session.stop()

    def _register_nodes(
        self,
        elements: list[UIAElement] | list[UIAElement | None],
        errors: list[dict[str, Any]] | None = None,
        source_indices: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        errors = list(errors or [])
        for index, element in enumerate(elements):
            if element is None:
                continue
            try:
                nodes.append(self._register(element))
            except Exception as exc:
                errors.append(
                    {
                        "index": source_indices[index] if source_indices is not None else index,
                        "message": str(exc),
                    }
                )
        if errors:
            raise RpcError(
                -32005,
                "some elements are unavailable",
                {"nodes": nodes, "complete": False, "errors": errors},
            )
        return nodes

    def _app_status(
        self, app: App | None, pids: list[int], windows: list[UIAElement] | None = None
    ) -> dict[str, Any]:
        owned = bool(pids) and self._owned_app_pids == set(pids)
        if self._owned_app_pids is not None and not owned:
            self._owned_app_pids = None
        status: dict[str, Any] = {"running": bool(pids), "pids": pids, "owned": owned}
        if app is not None:
            if windows is None:
                with contextlib.suppress(WtkError):
                    status["mainWindowTitle"] = app.main_window().name
            else:
                from wintestkit.uia import win32

                for window in windows:
                    try:
                        if window.control_type == "Window" and not win32.window_owner(
                            window.native_window_handle
                        ):
                            status["mainWindowTitle"] = window.name
                            break
                    except Exception:
                        continue
        return status

    def dispatch(self, method: str, params: dict[str, Any], spy_epoch: int | None = None) -> Any:
        from wintestkit.targets import ModuleLoader, Target, check_page, resolve_target

        if method == "shutdown":
            self.stop_spy()
            self._stopping.set()
            return None
        if method == "initialize":
            if self.cfg is not None:
                raise RpcError(-32600, "already initialized")
            cfg = load_config(Path(params["root"]))
            loader = ModuleLoader(cfg)
            settings: dict[str, Any] = {
                "found": cfg.found,
                "launch": cfg.launch,
                "timeout": cfg.timeout,
                "reportDir": str(cfg.report_dir),
            }
            if cfg.app is not None:
                settings["app"] = {
                    "path": str(cfg.app.path) if cfg.app.path is not None else "",
                    "process": cfg.app.process_name,
                }
            self.cfg, self.loader = cfg, loader
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "wintestkitVersion": __version__,
                "python": platform.python_version(),
                "config": settings,
            }
        if self.cfg is None or self.loader is None:
            raise RpcError(-32600, "not initialized")
        if method == "spy.stop":
            self.stop_spy()
            return None
        if method == "discover":
            from wintestkit.discovery import discover

            overrides = {Path(path): source for path, source in params.get("overrides", {}).items()}
            return discover(self.cfg.root, overrides=overrides).to_dict()
        if method == "app.status":
            app = self._app(False)
            pids = app.pids if app is not None else []
            return self._app_status(app, pids)
        if method == "app.launch":
            app = self._app(False)
            if app is None:
                from wintestkit.pytest_plugin import launch_app

                app = self.app = launch_app(
                    self.cfg, progress=lambda stage: self.notify("app.starting", {"stage": stage})
                )
                self._owned_app_pids = set(app.pids) or None
            return {"pids": app.pids}
        if method == "app.processes":
            from wintestkit.uia import win32

            return {
                "processes": [
                    {"name": name, "pids": pids, "windowTitle": title}
                    for name, pids, title in win32.windowed_processes()
                ]
            }
        if method == "app.close":
            app = self._app(False)
            if app is not None:
                app.close(timeout=self.cfg.app.close_timeout if self.cfg.app is not None else 10)
                self.app = None
                self._owned_app_pids = None
                with self._node_lock:
                    self.nodes.clear()
                    self.node_infos.clear()
            return None
        if method == "flow.run":
            from wintestkit.targets import run_flow

            app = self._app()
            assert app is not None
            file = (self.cfg.root / Path(params["file"])).resolve()
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict):
                raise RpcError(-32602, "flow arguments must be an object")
            flow_arguments = cast("dict[str, Any]", arguments)
            return run_flow(app, self.loader, file, params["name"], flow_arguments).to_dict()
        if method in ("element.highlight", "page.check"):
            app = self._app()
            assert app is not None
            file = Path(params["file"])
            file = (self.cfg.root / file).resolve()
            if method == "page.check":
                return {
                    "results": [
                        result.to_dict()
                        for result in check_page(app, self.loader, file, params["page"])
                    ]
                }
            result = resolve_target(app, self.loader, Target(file, params["qualname"]), timeout=0)
            if result.uia is not None:
                rect = self._raise_for_highlight(result.uia)
            else:
                rect = result.element.rect if result.element is not None else None
            self._flash(rect, params)
            return result.to_dict()
        if method == "inspect.coverage":
            app = self._app(False)
            if app is None:
                return {"covered": {}, "pending": []}
            with self._node_lock:
                infos = {
                    node_id: self.node_infos[node_id]
                    for node_id in params["nodeIds"]
                    if node_id in self.node_infos
                }
            return self._coverage().covered_nodes(app, infos)
        if method in ("inspect.roots", "inspect.refresh"):
            if self.coverage is not None:
                self.coverage.invalidate()
            app = self._app(False)
            pids = list(app.pids) if app is not None else []
            windows = list(app.top_level_windows()) if app is not None else []
            status = self._app_status(app, pids, windows) if method == "inspect.refresh" else None
            if "foregroundForProcessId" in params:
                from wintestkit.uia import element, win32

                hwnd = win32.foreground_window_for_process(params["foregroundForProcessId"])
                if hwnd is None:
                    raise RpcError(
                        -32001,
                        "Focus the VS Code window hosting WinTestKit, "
                        "then reopen the Spy tutorial.",
                    )
                nodes = self._register_nodes([element.from_handle(hwnd)])
                return {"nodes": nodes, "status": status} if status is not None else nodes
            include_other = params.get("includeOtherApps", False)
            enumeration_errors: list[dict[str, Any]] = []
            roots: list[UIAElement | None]
            if app is not None and not include_other:
                roots = list(windows)
                source_indices = list(range(len(roots)))
            else:
                from wintestkit.uia import com
                from wintestkit.uia.element import ElementEnumerationError, UIAElement

                desktop: list[UIAElement | None]
                try:
                    desktop = list(UIAElement(com.get_uia().GetRootElement()).children())
                except ElementEnumerationError as exc:
                    desktop = exc.elements
                    enumeration_errors = exc.errors
                if app is None:
                    roots = desktop
                    source_indices = list(range(len(roots)))
                else:
                    roots = list(windows)
                    source_indices = list(range(len(roots)))
                    seen: set[str] = set()
                    for root in windows:
                        with contextlib.suppress(Exception):
                            seen.add(root.runtime_id)
                    for index, window in enumerate(desktop):
                        if window is None:
                            continue
                        try:
                            runtime_id = window.runtime_id
                            if not runtime_id or runtime_id in seen or window.process_id in pids:
                                continue
                        except Exception:
                            roots.append(window)
                            source_indices.append(index)
                            continue
                        seen.add(runtime_id)
                        roots.append(window)
                        source_indices.append(index)
            nodes = self._register_nodes(
                [
                    root if root is not None and not _is_popup_surface(root) else None
                    for root in roots
                ],
                enumeration_errors,
                source_indices,
            )
            return {"nodes": nodes, "status": status} if status is not None else nodes
        if method == "spy.start":
            from wintestkit.engine.spy import SpySession

            app = self._app(False)
            pids = frozenset(app.pids) if app is not None else None
            epoch = self._spy_epoch
            session_params = {"sessionId": params["sessionId"]} if "sessionId" in params else {}

            def publish(method: str, element: UIAElement) -> None:
                with self._spy_lock:
                    if epoch != self._spy_epoch or self.spy is not session:
                        return
                node = self._register(element)
                with self._spy_lock:
                    if epoch == self._spy_epoch and self.spy is session:
                        self.notify(method, {"node": node, **session_params})

            def hover(element: UIAElement) -> None:
                publish("spy.hover", element)

            def pick(element: UIAElement) -> None:
                publish("spy.picked", element)

            def cancel() -> None:
                with self._spy_lock:
                    if epoch != self._spy_epoch or self.spy is not session:
                        return
                    self.notify("spy.cancelled", session_params)
                self.stop_spy(expected_epoch=epoch)

            with self._spy_lock:
                if self._stopping.is_set() or (
                    spy_epoch is not None and spy_epoch != self._spy_epoch
                ):
                    return None
                if self.spy is None:
                    epoch = self._spy_epoch
                    session = SpySession(
                        hover, pick, cancel, None if pids is None else pids.__contains__
                    )
                    self.spy = session
                    try:
                        session.start()
                    except Exception:
                        self.spy = None
                        self._spy_epoch += 1
                        raise
            return None
        node = self._node(params["nodeId"])
        if method == "inspect.definitions":
            app = self._app(False)
            return self._coverage().definitions_of(app, params["nodeId"], node.info())
        if method == "inspect.children":
            from wintestkit.uia.constants import TreeScope
            from wintestkit.uia.element import ElementEnumerationError

            if self.coverage is not None:
                self.coverage.invalidate()
            try:
                children = node.find_all(TreeScope.Children, cached=True)
            except ElementEnumerationError as exc:
                return self._register_nodes(exc.elements, exc.errors)
            return self._register_nodes(children)
        if method == "inspect.highlight":
            # The outline is drawn on top of every window, so raising the window is opt-in.
            rect = (
                self._raise_for_highlight(node) if params.get("bringToFront", False) else node.rect
            )
            self._flash(rect, params)
            return None
        if method == "suggest.locator":
            from wintestkit.engine.suggest import WindowSelectedError, suggest_locator

            try:
                return suggest_locator(node, self._app(False)).to_dict()
            except WindowSelectedError as exc:
                raise RpcError(-32006, str(exc)) from exc
        if method == "inspect.properties":
            from wintestkit.engine.properties import SUPPORTED, inspection_values
            from wintestkit.uia.constants import PROPERTY_IDS
            from wintestkit.uia.element import inspection_property

            properties: dict[str, str] = {}
            inspection: list[dict[str, Any]] = []
            full = params.get("full", False)
            for name in PROPERTY_IDS if full else ():
                try:
                    value = node.get_property(name)
                    description = inspection_property(name, value)
                    inspection.append(description)
                    properties[name] = (
                        ", ".join(
                            str(child.get("value", child.get("status", "[array]")))
                            for child in description["children"]
                        )
                        if description["kind"] == "array" and "children" in description
                        else str(description.get("value", description.get("status", "")))
                    )
                except Exception as exc:
                    inspection.append(
                        {
                            "name": name,
                            "typeName": "UIA",
                            "kind": "unavailable",
                            "status": str(exc)[:512],
                        }
                    )
            if not full:
                values = inspection_values(node, self.cfg.property_aliases)
                inspection.extend(inspection_property(key, value) for key, value in values.items())
                properties.update({key: str(value) for key, value in values.items()})
            for alias, target in self.cfg.property_aliases.items():
                property_name = SUPPORTED[target].uia_name if full else target
                if property_name in properties:
                    properties[alias] = properties[property_name]
            ancestors: list[dict[str, Any]] = []
            parent = node.parent() if params.get("includeAncestors", False) else None
            seen = {node.runtime_id}
            while parent is not None and len(ancestors) < 100:
                if parent.runtime_id in seen:
                    break
                seen.add(parent.runtime_id)
                ancestors.append(self._register(parent))
                parent = parent.parent()
            return {
                "info": node.info(with_patterns=full).to_dict(),
                "properties": properties,
                "ancestors": list(reversed(ancestors)),
                "inspection": inspection,
            }
        raise RpcError(-32601, "method not found")

    def serve(self, source: BinaryIO) -> int:
        requests: queue.Queue[Any] = queue.Queue()
        finished = object()

        def work() -> None:
            while not self._stopping.is_set():
                request = requests.get()
                if request is finished:
                    break
                self.handle(request)

        worker = threading.Thread(target=work, name="wtk-rpc-worker", daemon=True)
        previous_stdout = sys.stdout
        sys.stdout = sys.stderr
        handler = _LogForwarder(self)
        logger = logging.getLogger("wintestkit")
        logger.addHandler(handler)
        worker.start()
        try:
            for line in source:
                try:
                    request = json.loads(line.decode("utf-8"), parse_constant=_invalid_constant)
                except (ValueError, UnicodeError):
                    self._error(None, -32700, "parse error")
                    continue
                if isinstance(request, dict):
                    request = cast("dict[str, Any]", request)
                if isinstance(request, dict) and cast("dict[str, Any]", request).get("method") in (
                    "spy.stop",
                    "shutdown",
                ):
                    self.handle(request)
                    if self._stopping.is_set():
                        break
                else:
                    if isinstance(request, dict):
                        request["_spyEpoch"] = self._spy_epoch
                    requests.put(request)
            requests.put(finished)
            self.stop_spy()
            worker.join(timeout=5 if self._stopping.is_set() else None)
        finally:
            self._stopping.set()
            self.stop_spy()
            requests.put(finished)
            logger.removeHandler(handler)
            sys.stdout = previous_stdout
        return 0
