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

if TYPE_CHECKING:
    from wintestkit.app import App
    from wintestkit.config import WtkConfig
    from wintestkit.engine.spy import SpySession
    from wintestkit.targets import ModuleLoader
    from wintestkit.uia.element import UIAElement

log = logging.getLogger("wintestkit.server")

_PARAMS: dict[str, tuple[set[str], set[str]]] = {
    "initialize": ({"root"}, set()),
    "shutdown": (set(), set()),
    "discover": (set(), {"overrides"}),
    "app.status": (set(), set()),
    "app.launch": (set(), set()),
    "app.close": (set(), set()),
    "element.highlight": ({"file", "qualname"}, {"durationMs"}),
    "screen.check": ({"file", "screen"}, set()),
    "inspect.roots": (set(), set()),
    "inspect.children": ({"nodeId"}, set()),
    "inspect.properties": ({"nodeId"}, set()),
    "inspect.highlight": ({"nodeId"}, {"durationMs"}),
    "suggest.locator": ({"nodeId"}, set()),
    "spy.start": (set(), set()),
    "spy.stop": (set(), set()),
}


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
        self.nodes: OrderedDict[str, UIAElement] = OrderedDict()
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

    def _app(self, required: bool = True) -> App | None:
        from wintestkit.app import App

        if self.app is not None and self.app.is_running():
            return self.app
        self.app = None
        if self.cfg is not None and self.cfg.app is not None:
            with contextlib.suppress(AppNotRunningError):
                self.app = App.attach(process=self.cfg.app.process_name)
        if self.app is None and required:
            raise AppNotRunningError("App is not running. Start it or call app.launch.")
        return self.app

    def _register(self, element: UIAElement) -> dict[str, Any]:
        from wintestkit.uia.constants import TreeScope

        info = element.info()
        if not info.runtime_id:
            raise RpcError(-32005, "element has no runtime id")
        with self._node_lock:
            self.nodes[info.runtime_id] = element
            self.nodes.move_to_end(info.runtime_id)
            if len(self.nodes) > 5000:
                self.nodes.popitem(last=False)
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

    def stop_spy(self) -> None:
        with self._spy_lock:
            self._spy_epoch += 1
            session, self.spy = self.spy, None
        if session is not None:
            session.stop()

    def dispatch(self, method: str, params: dict[str, Any], spy_epoch: int | None = None) -> Any:
        from wintestkit.engine import overlay
        from wintestkit.targets import ModuleLoader, Target, check_screen, resolve_target

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
                "protocolVersion": 1,
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
            status: dict[str, Any] = {
                "running": app is not None,
                "pids": app.pids if app is not None else [],
            }
            if app is not None:
                status["mainWindowTitle"] = app.main_window().name
            return status
        if method == "app.launch":
            app = self._app(False)
            if app is None:
                from wintestkit.pytest_plugin import launch_app

                app = self.app = launch_app(self.cfg)
            return {"pids": app.pids}
        if method == "app.close":
            app = self._app(False)
            if app is not None:
                app.close(timeout=self.cfg.app.close_timeout if self.cfg.app is not None else 10)
                self.app = None
                with self._node_lock:
                    self.nodes.clear()
            return None
        if method in ("element.highlight", "screen.check"):
            app = self._app()
            assert app is not None
            file = Path(params["file"])
            file = (self.cfg.root / file).resolve()
            if method == "screen.check":
                return {
                    "results": [
                        result.to_dict()
                        for result in check_screen(app, self.loader, file, params["screen"])
                    ]
                }
            result = resolve_target(app, self.loader, Target(file, params["qualname"]), timeout=0)
            if result.element is not None and result.element.rect is not None:
                overlay.flash(result.element.rect, int(params.get("durationMs", 1500)), block=False)
            return result.to_dict()
        if method == "inspect.roots":
            app = self._app(False)
            if app is not None:
                roots = app.top_level_windows()
            else:
                from wintestkit.uia import com
                from wintestkit.uia.element import UIAElement

                roots = UIAElement(com.get_uia().GetRootElement()).children()
            return [self._register(root) for root in roots]
        if method == "spy.start":
            from wintestkit.engine.spy import SpySession
            from wintestkit.engine.suggest import suggest_locator

            app = self._app(False)
            pids = frozenset(app.pids) if app is not None else None

            def hover(element: UIAElement) -> None:
                self.notify("spy.hover", {"node": self._register(element)})

            def pick(element: UIAElement) -> None:
                self.notify(
                    "spy.picked",
                    {
                        "node": self._register(element),
                        "suggestion": suggest_locator(element, app).to_dict(),
                    },
                )

            def cancel() -> None:
                self.notify("spy.cancelled", {})
                self.stop_spy()

            with self._spy_lock:
                if self._stopping.is_set() or (
                    spy_epoch is not None and spy_epoch != self._spy_epoch
                ):
                    return None
                if self.spy is None:
                    session = SpySession(
                        hover, pick, cancel, None if pids is None else pids.__contains__
                    )
                    self.spy = session
                    try:
                        session.start()
                    except Exception:
                        self.spy = None
                        raise
            return None
        node = self._node(params["nodeId"])
        if method == "inspect.children":
            return [self._register(child) for child in node.children()]
        if method == "inspect.highlight":
            if node.rect is not None:
                overlay.flash(node.rect, int(params.get("durationMs", 1500)), block=False)
            return None
        if method == "suggest.locator":
            from wintestkit.engine.suggest import suggest_locator

            return suggest_locator(node, self._app(False)).to_dict()
        if method == "inspect.properties":
            from wintestkit.uia.constants import PROPERTY_IDS

            properties: dict[str, str] = {}
            for name in PROPERTY_IDS:
                try:
                    value = node.get_property(name)
                    properties[name] = (
                        ", ".join(map(str, cast("list[Any] | tuple[Any, ...]", value)))
                        if isinstance(value, list | tuple)
                        else str(value)
                    )
                except Exception:
                    continue
            ancestors: list[dict[str, Any]] = []
            parent = node.parent()
            seen = {node.runtime_id}
            while parent is not None and len(ancestors) < 100:
                if parent.runtime_id in seen:
                    break
                seen.add(parent.runtime_id)
                ancestors.append(self._register(parent))
                parent = parent.parent()
            return {
                "info": node.info(with_patterns=True).to_dict(),
                "properties": properties,
                "ancestors": list(reversed(ancestors)),
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
            worker.join(timeout=5 if self._stopping.is_set() else None)
        finally:
            self._stopping.set()
            self.stop_spy()
            requests.put(finished)
            logger.removeHandler(handler)
            sys.stdout = previous_stdout
        return 0
