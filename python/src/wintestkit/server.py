"""Newline-delimited JSON-RPC for the editor, with serialized UI Automation requests."""

from __future__ import annotations

import base64
import binascii
import contextlib
import dataclasses
import hmac
import json
import logging
import math
import ntpath
import platform
import queue
import secrets
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, cast

from wintestkit import __version__
from wintestkit.config import load_config, sync_object_previews_ignore
from wintestkit.errors import AppNotRunningError, ConfigError, EnvironmentNotReadyError, WtkError
from wintestkit.protocol import PROTOCOL_VERSION

if TYPE_CHECKING:
    from wintestkit.app import App
    from wintestkit.backends.element import TargetElement
    from wintestkit.config import WtkConfig
    from wintestkit.coverage import Coverage
    from wintestkit.engine.spy import SpySession
    from wintestkit.inspector.client import InspectorClient
    from wintestkit.inspector.models import ObjectRef, ProcessFacts, ProcessIdentity
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
    "element.check": ({"file", "qualname"}, set()),
    "page.check": ({"file", "page"}, set()),
    "flow.run": ({"file", "name"}, {"arguments"}),
    "inspect.roots": (set(), {"includeOtherApps", "foregroundForProcessId"}),
    "inspect.refresh": (set(), {"includeOtherApps", "foregroundForProcessId"}),
    "inspect.managed.identify": ({"nodeId"}, set()),
    "inspect.managed.attach": ({"process"}, {"hostCapability"}),
    "inspect.managed.spySelect": ({"hostCapability"}, {"sessionId", "nodeId"}),
    "inspect.managed.spyPrepareInvoke": (
        {"hostCapability", "sessionId", "objectId", "generation", "memberKey", "arguments"},
        set(),
    ),
    "inspect.managed.spyInvoke": ({"hostCapability", "ticket"}, set()),
    "inspect.managed.status": ({"process"}, set()),
    "inspect.managed.detach": ({"sessionId"}, set()),
    "inspect.managed.keepalive": ({"sessionId"}, set()),
    "inspect.managed.resolve": ({"sessionId", "nodeId"}, set()),
    "inspect.managed.roots": ({"sessionId"}, {"pageSize", "pageToken"}),
    "inspect.managed.children": (
        {"sessionId", "objectId", "generation", "tree"},
        {"pageSize", "pageToken"},
    ),
    "inspect.managed.members": ({"sessionId", "objectId", "generation"}, {"pageSize", "pageToken"}),
    "inspect.managed.spyMethods": (
        {"sessionId", "objectId", "generation"},
        {"pageSize", "pageToken"},
    ),
    "inspect.managed.read": ({"sessionId", "objectId", "generation", "paths"}, set()),
    "inspect.managed.spyRead": ({"sessionId", "objectId", "generation", "paths"}, set()),
    "inspect.managed.bindings": ({"sessionId", "objectId", "generation", "memberKeys"}, set()),
    "inspect.managed.release": ({"sessionId", "objectIds"}, set()),
    "inspect.children": ({"nodeId"}, {"tree", "pageSize", "pageToken"}),
    "inspect.properties": ({"nodeId"}, {"full", "includeAncestors", "include"}),
    "inspect.highlight": ({"nodeId"}, {"durationMs", "bringToFront"}),
    "inspect.preview": ({"nodeId"}, set()),
    "suggest.locator": ({"nodeId"}, set()),
    "inspect.definitions": ({"nodeId"}, set()),
    "inspect.coverage": ({"nodeIds"}, set()),
    "spy.start": (set(), {"sessionId", "foregroundForProcessId", "tree"}),
    "spy.stop": (set(), set()),
}


MAX_COVERAGE_NODES = 500
MAX_INCLUDED_PROPERTIES = 64

# The automatic Properties read: each getter gets 250 ms, one request gets 2 s.
SPY_GETTER_LIMIT = 0.25
SPY_READ_BUDGET = 2.0

# Requests that wait on the inspected application's UI thread. They run on a small worker pool so
# that a long read never holds up the short requests (picker, roots, coverage, keepalive) the
# single ordered worker answers.
_APPLICATION_READS = frozenset(
    {
        "inspect.managed.read",
        "inspect.managed.spyRead",
        "inspect.managed.members",
        "inspect.managed.children",
        "inspect.managed.bindings",
        "inspect.managed.spyMethods",
    }
)
_READ_WORKERS = 4
_APPLICATION_SLOW = frozenset({"timeout", "dispatcherUnavailable", "busy"})
# Changing which processes are attached is the only managed work that is serialized.
_MANAGED_LIFECYCLE = frozenset(
    {"inspect.managed.attach", "inspect.managed.status", "inspect.managed.detach"}
)

# Windows that XAML apps (UWP, WinUI) create to show a popup: they turn visible while a tooltip,
# menu or flyout is open and hidden again afterwards, so they come and go in the roots list.
POPUP_SURFACE_CLASSES = frozenset(
    {"Xaml_WindowedPopupClass", "Microsoft.UI.Content.PopupWindowSiteBridge"}
)


def _summarize(description: dict[str, Any]) -> str:
    """One line for a described property, as the flat property map shows it."""
    children = cast("list[dict[str, Any]]", description.get("children", []))
    if description["kind"] == "array" and children:
        if all(child["kind"] == "scalar" for child in children):
            return ", ".join(str(child.get("value")) for child in children)
        return f"{len(children)} items"
    if description["kind"] == "object" and children:
        named = {child["name"]: child.get("value") for child in children}
        label = " ".join(
            part
            for part in (
                named.get("ControlType"),
                f'"{named["Name"]}"' if named.get("Name") else None,
            )
            if part
        )
        return label or "element"
    return str(description.get("value", description.get("status", "")))


def _is_popup_surface(window: UIAElement) -> bool:
    try:
        return window.class_name in POPUP_SURFACE_CLASSES
    except Exception:
        return False  # the window closed while reading it; registering it reports the failure


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


@dataclasses.dataclass
class _SpyTarget:
    element: Any
    node: dict[str, Any] | None = None
    extra: dict[str, Any] = dataclasses.field(default_factory=lambda: dict[str, Any]())

    @property
    def rect(self) -> Any:
        return self.element.rect

    def same_as(self, other: Any) -> bool:
        if not isinstance(other, _SpyTarget) or self.extra != other.extra:
            return False
        if self.node is not None or other.node is not None:
            return (
                self.node is not None
                and other.node is not None
                and self.node["nodeId"] == other.node["nodeId"]
            )
        return bool(self.element.same_as(other.element))


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
    def __init__(self, output: BinaryIO, *, spy_host_capability: str | None = None) -> None:
        self.output = output
        self._spy_host_capability: bytes | None = None
        if spy_host_capability is not None:
            try:
                decoded = base64.b64decode(spy_host_capability, validate=True)
                if (
                    len(decoded) != 32
                    or base64.b64encode(decoded).decode("ascii") != spy_host_capability
                ):
                    raise ValueError("invalid capability")
                self._spy_host_capability = decoded
            except (ValueError, binascii.Error):
                raise ValueError("invalid Spy host capability") from None
        self.cfg: WtkConfig | None = None
        self.loader: ModuleLoader | None = None
        self.app: App | None = None
        # Ownership is deliberately independent of the configured launch mode. The server can
        # attach to a process it did not start.
        self._owned_app_pids: set[int] | None = None
        self._owned_app_identities: set[ProcessIdentity] = set()
        self.nodes: OrderedDict[str, TargetElement] = OrderedDict()
        self._wpf_windows: set[str] = set()
        self.node_infos: dict[str, ElementInfo] = {}
        self._wpf_parents: dict[str, str] = {}
        self._wpf_descriptions: dict[str, dict[str, Any]] = {}
        self._wpf_text: dict[str, str | None] = {}
        self.coverage: Coverage | None = None
        self.spy: SpySession | None = None
        self._write_lock = threading.Lock()
        self._node_lock = threading.Lock()
        self._spy_lock = threading.RLock()
        self._stopping = threading.Event()
        self._spy_epoch = 0
        self._managed_lock = threading.RLock()
        self._managed_rpc_lock = threading.RLock()
        self._managed_clients: dict[str, InspectorClient] = {}
        self._managed_objects: dict[str, dict[str, int]] = {}
        self._spy_selection: tuple[InspectorClient, ObjectRef] | None = None
        self._spy_ticket: (
            tuple[str, float, InspectorClient, ObjectRef, str, list[dict[str, object]]] | None
        ) = None

    def _clear_managed_spy(self) -> None:
        with self._managed_lock:
            self._spy_selection = None
            self._spy_ticket = None

    def _verify_spy_host(self, value: Any) -> None:
        try:
            if not isinstance(value, str):
                raise ValueError
            decoded = base64.b64decode(value, validate=True)
            if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != value:
                raise ValueError
        except (ValueError, binascii.Error):
            raise RpcError(-32000, "Spy host access denied") from None
        if self._spy_host_capability is None or not hmac.compare_digest(
            self._spy_host_capability, decoded
        ):
            raise RpcError(-32000, "Spy host access denied")

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
        if method in {
            "inspect.managed.spySelect",
            "inspect.managed.spyPrepareInvoke",
            "inspect.managed.spyInvoke",
        } or (method == "inspect.managed.attach" and "hostCapability" in params):
            self._verify_spy_host(params.get("hostCapability"))
            if method == "inspect.managed.spySelect":
                self._clear_managed_spy()
        if not required <= params.keys() or params.keys() - required - optional:
            raise RpcError(-32602, "invalid params")
        if method.startswith("inspect.managed.") or method == "inspect.children":
            self._managed_params(params)
            if method == "inspect.managed.spySelect" and (
                ("sessionId" in params) != ("nodeId" in params)
            ):
                raise RpcError(-32602, "invalid managed parameters")
            if (
                method == "inspect.children"
                and "tree" not in params
                and ("pageSize" in params or "pageToken" in params)
            ):
                raise RpcError(-32602, "paging requires tree")
            return params
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
            elif key == "tree":
                if value not in ("visual", "logical"):
                    raise RpcError(-32602, "tree must be visual or logical")
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
            elif key == "include":
                if (
                    not isinstance(value, list)
                    or len(cast("list[Any]", value)) > MAX_INCLUDED_PROPERTIES
                    or any(
                        not isinstance(item, str) or not item or len(item) > 64
                        for item in cast("list[Any]", value)
                    )
                ):
                    raise RpcError(
                        -32602,
                        f"include must list at most {MAX_INCLUDED_PROPERTIES} property names",
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

    @staticmethod
    def _managed_params(params: dict[str, Any]) -> None:
        from wintestkit.inspector.models import (
            ProcessIdentity,
            identifier_value,
            integer_value,
            key_value,
            parse_path,
        )

        try:
            for key, value in params.items():
                if key == "process":
                    ProcessIdentity.from_json(value)
                elif key in {"sessionId", "objectId", "pageToken"}:
                    identifier_value(value)
                elif key == "nodeId":
                    if not isinstance(value, str) or not value:
                        raise ValueError("invalid node ID")
                elif key == "generation":
                    integer_value(value, 1)
                elif key == "pageSize":
                    integer_value(value, 1, 200)
                elif key == "tree":
                    if value not in ("visual", "logical"):
                        raise ValueError("invalid tree")
                elif key == "memberKey":
                    from wintestkit.inspector.models import string_value

                    string_value(value, 8192)
                elif key == "arguments":
                    from wintestkit.inspector.client import validate_spy_arguments

                    validate_spy_arguments(value)
                elif key == "ticket":
                    identifier_value(value)
                elif key in {"paths", "memberKeys", "objectIds"}:
                    maximum = 256 if key == "objectIds" else 32
                    if not isinstance(value, list) or not (
                        1 <= len(cast("list[Any]", value)) <= maximum
                    ):
                        raise ValueError("invalid managed array")
                    for item in cast("list[Any]", value):
                        if key == "paths":
                            parse_path(item)
                        elif key == "memberKeys":
                            key_value(item)
                        else:
                            identifier_value(item)
        except (ValueError, TypeError, OverflowError, UnicodeError) as exc:
            raise RpcError(-32602, "invalid managed parameters") from exc

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
        method = request["method"]
        try:
            if self.cfg is None and method not in ("initialize", "shutdown"):
                raise RpcError(-32600, "not initialized")
            params = self._params(method, request.get("params", {}))
            result = self.dispatch(method, params, request.get("_spyEpoch"))
            if not notification and (not self._stopping.is_set() or method == "shutdown"):
                self._write({"jsonrpc": "2.0", "id": request_id, "result": result})
        except Exception as exc:
            if notification or self._stopping.is_set():
                return
            if method == "inspect.managed.spyInvoke" and isinstance(exc, WtkError):
                self._error(request_id, -32000, "Spy invocation failed")
                return
            if isinstance(exc, RpcError):
                self._error(request_id, exc.code, exc.message, exc.data)
            elif isinstance(exc, WtkError):
                from wintestkit.errors import InspectorError
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
                data = exc.to_dict()
                if isinstance(exc, InspectorError):
                    from wintestkit.inspector.hints import inspector_error_hint

                    data["code"] = exc.code
                    data["hint"] = inspector_error_hint(exc.code)
                self._error(request_id, code, str(exc), data)
            else:
                if method.startswith("inspect.managed."):
                    log.error("Managed RPC request failed (%s)", type(exc).__name__)
                    self._error(request_id, -32603, "internal error")
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

    def _flash(self, rect: Rect | None, params: dict[str, Any]) -> None:
        """Outline ``rect`` for a moment in the configured highlight colour."""
        from wintestkit.engine import overlay

        if rect is not None:
            color = overlay.parse_color(
                self.cfg.highlight_color if self.cfg is not None else "#FF0000"
            )
            overlay.flash(rect, int(params.get("durationMs", 1500)), color=color, block=False)

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

    def _is_app_under_test(self, facts: ProcessFacts) -> bool:
        """Match launched identities or the configured application executable."""
        if facts.identity in self._owned_app_identities:
            return True
        cfg = self.cfg
        if cfg is None or cfg.app is None:
            return False
        executable = ntpath.normcase(ntpath.normpath(facts.executable))
        name = ntpath.basename(executable).removesuffix(".exe")
        configured_name = ntpath.basename(cfg.app.process_name).lower().removesuffix(".exe")
        if name != configured_name:
            return False
        if cfg.app.path is not None:
            path = cfg.app.path
            if not path.is_absolute():
                path = (cfg.root / path).resolve()
            configured = ntpath.normcase(ntpath.normpath(str(path)))
            if executable != configured:
                return False
        return True

    def _coverage(self) -> Coverage:
        from wintestkit.coverage import Coverage

        assert self.cfg is not None and self.loader is not None
        if self.coverage is None:
            self.coverage = Coverage(self.loader, self.cfg)
        return self.coverage

    @staticmethod
    def _signature(element: UIAElement) -> tuple[Any, ...]:
        """What tells siblings apart when UI Automation cannot compare elements reliably."""
        rect = element.rect
        return (
            element.control_type,
            element.name,
            element.automation_id,
            element.class_name,
            None if rect is None else (rect.left, rect.top, rect.width, rect.height),
            element.is_offscreen,
        )

    def _positional_id(self, element: UIAElement) -> str | None:
        """Key for an element without a runtime id: its path of sibling positions below the
        nearest ancestor that has one, written the way ``inspect.children`` writes it.

        ``CompareElements`` cannot tell such elements apart reliably (a menu's items all compare
        equal), so siblings are matched by their properties first. Siblings that are identical in
        every property resolve to the first of them.
        """
        from wintestkit.uia.constants import TreeScope
        from wintestkit.uia.element import ElementEnumerationError

        path: list[int] = []
        current = element
        for _ in range(64):
            parent = current.parent()
            if parent is None:
                return None
            try:
                siblings: list[UIAElement | None] = list(
                    parent.as_live().find_all(TreeScope.Children, cached=True)
                )
            except ElementEnumerationError as exc:
                siblings = exc.elements
            wanted = self._signature(current)
            twins = [
                (index, sibling)
                for index, sibling in enumerate(siblings)
                if sibling is not None and self._signature(sibling) == wanted
            ]
            if not twins:
                return None
            position = next((i for i, sibling in twins if sibling.same_as(current)), twins[0][0])
            path.append(position)
            with contextlib.suppress(Exception):
                parent_id = parent.runtime_id
                if parent_id:
                    return parent_id + "".join(f"~{index}" for index in reversed(path))
            current = parent
        return None

    def _register(
        self, element: UIAElement, fallback_id: str | None = None, locate: bool = True
    ) -> dict[str, Any]:
        """Remember ``element`` under its node id and describe it for the editor.

        With ``locate=False`` an element that has no runtime id is only described, with an empty
        node id and without being remembered: finding its place among its siblings is slow, and a
        hover hint does not need it.
        """
        from wintestkit.uia.constants import TreeScope

        info = element.info()
        if not info.runtime_id and not fallback_id and not locate:
            return {"nodeId": "", "info": info.to_dict(), "hasChildren": False, "source": "uia"}
        if not info.runtime_id:
            # Some providers (TeamViewer's custom-drawn content) return an empty runtime id. A node
            # needs a key, so its place under the parent stands in for it: stable between refreshes
            # as long as the siblings keep their order. A caller that does not know the parent
            # (the picker, the ancestors of a picked object) has it worked out.
            fallback_id = fallback_id or self._positional_id(element)
            if fallback_id is None:
                raise RpcError(-32005, "element has no runtime id")
            info = dataclasses.replace(info, runtime_id=fallback_id)
        with self._node_lock:
            self.nodes[info.runtime_id] = element
            self.node_infos[info.runtime_id] = info
            self.nodes.move_to_end(info.runtime_id)
            if len(self.nodes) > 5000:
                evicted, old_node = self.nodes.popitem(last=False)
                self.node_infos.pop(evicted, None)
                self._wpf_text.pop(evicted, None)
                self._wpf_windows.discard(evicted)
                self._release_tree_node(old_node)
        return {
            "nodeId": info.runtime_id,
            "info": info.to_dict(),
            "hasChildren": element.find_first(TreeScope.Children) is not None,
            "source": "uia",
        }

    def _node(self, node_id: str) -> UIAElement:
        with self._node_lock:
            node = self.nodes.get(node_id)
            if node is not None:
                self.nodes.move_to_end(node_id)
        from wintestkit.backends.element import WpfElement

        if isinstance(node, WpfElement):
            raise RpcError(-32005, "unknown node id: method does not yet support WPF nodes")
        if node is None or not node.is_alive():
            raise RpcError(-32005, "unknown node id")
        return cast("UIAElement", node.as_live())

    def _release_tree_node(self, node: TargetElement) -> None:
        from wintestkit.backends.element import WpfElement

        if isinstance(node, WpfElement):
            with self._managed_lock:
                if self._spy_selection and (
                    self._spy_selection[1].session_id,
                    self._spy_selection[1].object_id,
                ) == (node.ref.session_id, node.ref.object_id):
                    self._clear_managed_spy()
                self._managed_objects.get(node.ref.session_id, {}).pop(node.ref.object_id, None)
            node.release()

    def _wpf_control_text(
        self, client: Any, ref: Any, names: tuple[str | None, ...], deadline: float
    ) -> str | None:
        """Read only the bounded text members used by the WPF tree labels."""
        from wintestkit.inspector.paths import PathSegment

        assert self.cfg is not None
        sensitive = (
            "password",
            "passwd",
            "pwd",
            "secret",
            "token",
            "credential",
            "connectionstring",
            "apikey",
            "privatekey",
            *self.cfg.inspector.redact_names,
        )
        if any(
            rule.lower() in name.lower() for rule in sensitive for name in names if rule and name
        ):
            return None
        members = {
            "TextBlock": ("Text",),
            "TextBox": ("Text",),
            "ListBoxItem": ("Content",),
            "Button": ("Content",),
            "CheckBox": ("Content",),
            "RadioButton": ("Content",),
            "Label": ("Content",),
            "ContentControl": ("Content",),
            "TabItem": ("Header", "Content"),
            "MenuItem": ("Header",),
            "Expander": ("Header",),
            "GroupBox": ("Header",),
            "Window": ("Title",),
        }
        text = None
        for member in members.get(ref.type.name, ()):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                values, _ = client.read(
                    ref.object_id,
                    ref.generation,
                    [[PathSegment("property", member)]],
                    deadline=time.monotonic() + min(0.25, remaining),
                )
                value = values[0].value
                if value.status == "ok" and isinstance(value.scalar, str):
                    if value.scalar:
                        return value.scalar
                    text = ""
            except Exception:
                log.debug("Unable to read WPF tree text", exc_info=True)
        return text

    def _wpf_properties(
        self, node: Any, params: dict[str, Any], peer: UIAElement | None = None
    ) -> dict[str, Any]:
        """Describe a WPF object; ``peer`` is its known UIA element, if any.

        Window roots pass the UIA element they were listed from, because a
        window's WPF peer can report a runtime ID that differs from the HWND
        provider's ID that UIA clients see.
        """
        from wintestkit.engine.properties import SUPPORTED
        from wintestkit.errors import NoUiaPeerError
        from wintestkit.inspector.paths import PathSegment
        from wintestkit.uia.constants import PROPERTY_IDS
        from wintestkit.uia.element import ElementInfo, inspection_property

        assert self.cfg is not None
        paths = [
            (PathSegment("property", "Name", declaring_type="System.Windows.FrameworkElement"),),
            *((PathSegment("uia", name),) for name in ("automation_id", "name", "control_type")),
        ]
        values, _ = node.client.read(
            node.ref.object_id,
            node.ref.generation,
            paths,
            deadline=time.monotonic() + self.cfg.inspector.request_timeout,
        )
        identity = [
            item.value.scalar
            if item.value.status == "ok" and isinstance(item.value.scalar, str)
            else ""
            for item in values
        ]
        x_name, automation_id, peer_name, control_type = identity
        state = node.state()
        info = ElementInfo(
            automation_id,
            peer_name,
            control_type,
            node.ref.type.full_name,
            "WPF",
            node.process_id,
            node.rect,
            state.enabled,
            state.offscreen,
            state.focused,
            params["nodeId"],
        )
        properties = {
            "ClrFullClassName": node.ref.type.full_name,
            "x:Name": x_name,
            "AutomationId": automation_id,
            "Name": peer_name,
            "ControlType": control_type,
            "Bounds": str(state.bounds.to_json() if state.bounds is not None else ""),
            "Visible": str(state.visible),
            "IsEnabled": str(state.enabled),
            "HasKeyboardFocus": str(state.focused),
            "ProcessId": str(node.process_id),
            "WindowHandle": str(state.window_handle or 0),
        }
        with self._node_lock:
            text_cached = params["nodeId"] in self._wpf_text
            text = self._wpf_text.get(params["nodeId"])
        if not text_cached:
            text = self._wpf_control_text(
                node.client,
                node.ref,
                (node.ref.type.full_name, x_name, automation_id),
                time.monotonic() + 0.5,
            )
            with self._node_lock:
                self._wpf_text[params["nodeId"]] = text
        if text is not None:
            properties["WPFControlText"] = text
        inspection = [inspection_property(name, value) for name, value in properties.items()]
        result: dict[str, Any] = {
            "info": info.to_dict(),
            "properties": properties,
            "inspection": inspection,
            "ancestors": [],
            "source": "wpf",
            "uiaMapped": False,
        }
        if params.get("includeAncestors", False):
            with self._node_lock:
                parent_id = self._wpf_parents.get(params["nodeId"])
                seen = {params["nodeId"]}
                ancestors: list[dict[str, Any]] = []
                while parent_id and parent_id not in seen and len(ancestors) < 100:
                    seen.add(parent_id)
                    description = self._wpf_descriptions.get(parent_id)
                    if description is None:
                        info = self.node_infos.get(parent_id)
                        if info is None:
                            break
                        description = {
                            "nodeId": parent_id,
                            "info": info.to_dict(),
                            "hasChildren": True,
                            "source": "wpf",
                        }
                    ancestors.append(description)
                    parent_id = self._wpf_parents.get(parent_id)
                result["ancestors"] = list(reversed(ancestors))
        if peer is None and state.uia_runtime_id:
            try:
                peer = node.as_uia()
            except NoUiaPeerError:
                log.debug("WPF object has no reachable UIA peer", exc_info=True)
        if peer is not None:
            result["uiaMapped"] = True
            try:
                password = (
                    bool(peer.get_property("IsPassword")) or node.ref.type.name == "PasswordBox"
                )
            except Exception:
                password = True
            names = (
                list(PROPERTY_IDS)
                if params.get("full", False)
                else [spec.uia_name for spec in SUPPORTED.values()]
            )
            names.extend(params.get("include", ()))
            uia_properties: dict[str, str] = {}
            uia_inspection: list[dict[str, Any]] = []
            for name in dict.fromkeys(names):
                if name not in PROPERTY_IDS:
                    continue
                if password and ("value" in name.lower() or name in ("Name", "HelpText")):
                    continue
                try:
                    description = inspection_property(name, peer.get_property(name))
                    uia_properties[name] = _summarize(description)
                except Exception as exc:
                    description = {
                        "name": name,
                        "typeName": "UIA",
                        "kind": "unavailable",
                        "status": str(exc)[:512],
                    }
                uia_inspection.append(description)
            result["uia"] = {"properties": uia_properties, "inspection": uia_inspection}
        return result

    def _wpf_enabled(self, element: UIAElement) -> bool:
        return bool(
            self.cfg is not None and self.cfg.backend == "auto" and element.framework_id == "WPF"
        )

    def _mark_roots(self, nodes: list[dict[str, Any]]) -> None:
        from wintestkit.uia import win32

        names = dict(win32.list_processes())
        for item in nodes:
            name = names.get(item["info"].get("processId"))
            if name:
                item["info"]["processName"] = name
            node_id = item["nodeId"]
            with self._node_lock:
                node = self.nodes.get(node_id)
            if node is not None and self._wpf_enabled(cast("UIAElement", node)):
                item["source"] = "wpf"
                self._wpf_windows.add(node_id)

    @staticmethod
    def _is_hwnd_host(ref: Any) -> bool:
        return "System.Windows.Interop.HwndHost" in (ref.type.full_name, *ref.type.base_types)

    def _hosted_children(self, node: Any) -> list[Any]:
        from wintestkit.uia.constants import TreeScope

        try:
            return list(node.as_uia().find_all(TreeScope.Children, cached=True))
        except Exception:
            log.debug("Unable to map hosted HWND children", exc_info=True)
            return []

    def _hosted_nodes(
        self, children: list[Any], parent_id: str, offset: int
    ) -> list[dict[str, Any]]:
        nodes = self._register_nodes(children, parent_id=parent_id, start_index=offset)
        with self._node_lock:
            for item in nodes:
                self._wpf_parents[item["nodeId"]] = parent_id
                self._wpf_descriptions[item["nodeId"]] = item
        return nodes

    def _registered_hosted_hit(self, element: Any, process_id: int) -> _SpyTarget | None:
        """Match a UIA hit to a known host, preserving the tree's sibling-based IDs."""
        from wintestkit.backends.element import WpfElement
        from wintestkit.uia.constants import TreeScope

        with self._node_lock:
            registered = [
                (node, self._wpf_descriptions.get(node_id))
                for node_id, node in self.nodes.items()
                if node_id in self._wpf_parents and not isinstance(node, WpfElement)
            ]
            hosts = [
                (node_id, node)
                for node_id, node in self.nodes.items()
                if isinstance(node, WpfElement)
                and node.process_id == process_id
                and self._is_hwnd_host(node.ref)
            ]
        for node, description in registered:
            try:
                if description is not None and node.same_as(element):
                    return _SpyTarget(element, description)
            except Exception:
                log.debug("Unable to compare registered hosted HWND", exc_info=True)
        for host_id, host in hosts:
            try:
                peer = host.as_uia()
                current = element
                chain: list[Any] = []
                for _ in range(100):
                    if current is None or current.same_as(peer):
                        break
                    chain.append(current)
                    current = current.parent()
                if current is None or not current.same_as(peer) or not chain:
                    continue
                parent = peer
                description = None
                for part in reversed(chain):
                    siblings = parent.find_all(TreeScope.Children, cached=True)
                    index = next(i for i, sibling in enumerate(siblings) if sibling.same_as(part))
                    description = self._hosted_nodes([part], host_id, index)[0]
                    host_id = description["nodeId"]
                    parent = part
                if description is not None:
                    return _SpyTarget(element, description)
            except Exception:
                log.debug("Unable to match registered hosted HWND", exc_info=True)
        return None

    def _spy_resolve(self, element: Any, x: int, y: int, pick: bool, tree: str) -> _SpyTarget:
        from wintestkit import runtime
        from wintestkit.backends.element import WpfElement
        from wintestkit.inspector.hints import inspector_error_hint
        from wintestkit.inspector.models import ManagedNode
        from wintestkit.inspector.probe import current_identity
        from wintestkit.uia import element as uia_element
        from wintestkit.uia import win32
        from wintestkit.uia.element import ElementInfo

        fallback = _SpyTarget(element)
        try:
            process_id = getattr(element, "process_id", None)
            if process_id is not None:
                hosted_hit = self._registered_hosted_hit(element, process_id)
                if hosted_hit is not None:
                    return hosted_hit
            hwnd = int(win32.WindowFromPoint(win32.POINT(x, y)) or 0)
            if not hwnd:
                return fallback
            root_hwnd = win32.root_window(hwnd)
            window = uia_element.from_handle(root_hwnd)
            if not self._wpf_enabled(window):
                return fallback
            assert self.cfg is not None
            identity = current_identity(window.process_id)
            with runtime.config_scope(self.cfg):
                registry = runtime.inspector_sessions()
                client = registry.get(identity)
                if client is None:
                    status = registry.status(identity)
                    if status.state == "faulted" and status.error:
                        fallback.extra = {
                            "blocked": {
                                "code": status.error,
                                "hint": inspector_error_hint(status.error),
                            }
                        }
                    else:
                        fallback.extra = {"attachRequired": True, "process": identity.to_json()}
                    return fallback
                deadline = time.monotonic() + self.cfg.inspector.request_timeout
                hit = client.hit_test(
                    root_hwnd,
                    x,
                    y,
                    include_path=pick,
                    timeout_ms=max(1, int(self.cfg.inspector.request_timeout * 1000)),
                    deadline=deadline,
                )
                if hit is None:
                    log.debug("WPF Spy hit test missed at %s, %s", x, y)
                    fallback.extra = {"source": "uia"}
                    return fallback
                entries = hit.path if pick else (ManagedNode(hit.handle, "", False, False),)
                if not entries or entries[-1].object_ref != hit.handle:
                    raise ValueError("hit test returned an incomplete path")
                with self._managed_lock:
                    self._managed_clients[client.session.session_id] = client
                parent_id: str | None = None
                description: dict[str, Any] = {}
                target: Any = None
                for entry in entries:
                    ref = entry.object_ref
                    self._remember_managed(client.session.session_id, ref.to_json())
                    node_id = "wpf:" + json.dumps(
                        [ref.session_id, ref.object_id, ref.generation], separators=(",", ":")
                    )
                    identity_data = {"type": ref.type.full_name}
                    if entry.identity is not None:
                        if entry.identity.x_name:
                            identity_data["xName"] = entry.identity.x_name
                        if entry.identity.automation_id:
                            identity_data["automationId"] = entry.identity.automation_id
                    info = ElementInfo(
                        identity_data.get("automationId", ""),
                        identity_data.get("xName", ""),
                        ref.type.name,
                        ref.type.full_name,
                        "WPF",
                        window.process_id,
                        None,
                        True,
                        False,
                        False,
                        node_id,
                    )
                    target = WpfElement(client, ref, window.process_id)
                    description = {
                        "nodeId": node_id,
                        "info": info.to_dict(),
                        "hasChildren": (
                            entry.has_visual_children
                            if tree == "visual"
                            else entry.has_logical_children
                        )
                        or (self._is_hwnd_host(ref) and bool(self._hosted_children(target))),
                        "source": "wpf",
                        "identity": identity_data,
                    }
                    with self._node_lock:
                        self.nodes[node_id] = target
                        self.node_infos[node_id] = info
                        self.nodes.move_to_end(node_id)
                        if parent_id is not None:
                            self._wpf_parents[node_id] = parent_id
                        elif pick:
                            self._wpf_parents.pop(node_id, None)
                        self._wpf_descriptions[node_id] = description
                        if len(self.nodes) > 5000:
                            evicted, old = self.nodes.popitem(last=False)
                            self.node_infos.pop(evicted, None)
                            self._wpf_text.pop(evicted, None)
                            self._wpf_windows.discard(evicted)
                            self._release_tree_node(old)
                    parent_id = node_id
                if pick and len(entries) > 1:
                    root_description = self._register(window)
                    root_description["source"] = "wpf"
                    first = entries[1].object_ref
                    first_id = "wpf:" + json.dumps(
                        [first.session_id, first.object_id, first.generation],
                        separators=(",", ":"),
                    )
                    with self._node_lock:
                        self._wpf_windows.add(root_description["nodeId"])
                        self._wpf_descriptions[root_description["nodeId"]] = root_description
                        self._wpf_parents[first_id] = root_description["nodeId"]
                if self._is_hwnd_host(hit.handle):
                    # Only accept UIA hits below this host's peer, never its siblings.
                    try:
                        peer = target.as_uia()
                        current = element
                        chain: list[Any] = []
                        for _ in range(100):
                            if current is None or current.same_as(peer):
                                break
                            chain.append(current)
                            current = current.parent()
                        if current is not None and current.same_as(peer) and chain:
                            if pick:
                                host_id = description["nodeId"]
                                from wintestkit.uia.constants import TreeScope

                                uia_parent = peer
                                for part in reversed(chain):
                                    siblings = uia_parent.find_all(TreeScope.Children, cached=True)
                                    index = next(
                                        i
                                        for i, sibling in enumerate(siblings)
                                        if sibling is not None and sibling.same_as(part)
                                    )
                                    description = self._hosted_nodes([part], host_id, index)[0]
                                    host_id = description["nodeId"]
                                    uia_parent = part
                            else:
                                description = self._register(element, locate=False)
                            return _SpyTarget(element, description)
                    except Exception:
                        log.debug("Unable to resolve hosted HWND hit", exc_info=True)
                # Fetch geometry here so failures still fall back for this event.
                _ = target.rect
                return _SpyTarget(target, description)
        except Exception:
            log.debug("WPF Spy hit test failed", exc_info=True)
            fallback.extra = {"source": "uia"}
            return fallback

    def _wpf_children(
        self, node: TargetElement, tree: str, page_size: int, page_token: str | None, parent_id: str
    ) -> Any:
        from wintestkit import runtime
        from wintestkit.backends.element import WpfElement
        from wintestkit.errors import InspectorError
        from wintestkit.inspector.hints import inspector_error_hint
        from wintestkit.inspector.probe import current_identity
        from wintestkit.uia.element import ElementInfo

        assert self.cfg is not None
        with runtime.config_scope(self.cfg):
            if not self.cfg.inspector.enabled:
                return {
                    "blocked": {
                        "code": "inspectorDisabled",
                        "hint": inspector_error_hint("inspectorDisabled"),
                    }
                }
            if isinstance(node, WpfElement):
                client, ref = node.client, node.ref
                process_id = node.process_id
            else:
                process_id = node.process_id
                identity = current_identity(process_id)
                registry = runtime.inspector_sessions()
                client = registry.get(identity)
                if client is None:
                    session = registry.status(identity)
                    if session.state == "faulted" and session.error:
                        return {
                            "blocked": {
                                "code": session.error,
                                "hint": inspector_error_hint(session.error),
                            }
                        }
                    return {"attachRequired": True, "process": identity.to_json()}
                rid, hwnd = runtime.managed_element_identity(cast("UIAElement", node))
                try:
                    mapping = client.resolve(
                        rid, hwnd, deadline=time.monotonic() + self.cfg.inspector.request_timeout
                    )
                    if mapping.status != "exact" or mapping.object_ref is None:
                        raise RpcError(-32005, "unknown node id: WPF window mapping is not exact")
                    ref = mapping.object_ref
                except InspectorError as error:
                    return {
                        "blocked": {"code": error.code, "hint": inspector_error_hint(error.code)}
                    }
                self._remember_managed(client.session.session_id, ref.to_json())
            with self._managed_lock:
                self._managed_clients[client.session.session_id] = client
            output: list[dict[str, Any]] = []
            with self._node_lock:
                parent_info = self.node_infos.get(parent_id)
                if parent_info is not None and parent_id not in self._wpf_descriptions:
                    self._wpf_descriptions[parent_id] = {
                        "nodeId": parent_id,
                        "info": parent_info.to_dict(),
                        "hasChildren": True,
                        "source": "wpf",
                    }
            host = isinstance(node, WpfElement) and self._is_hwnd_host(ref)
            if host and page_token is not None and page_token.startswith("uia:"):
                from wintestkit.errors import InspectorError

                token = page_token[4:]
                if not token.isascii() or not token.isdecimal():
                    raise InspectorError("invalid page token", code="invalidPageToken")
                offset = int(token)
                hosted = self._hosted_children(node)
                if offset >= len(hosted):
                    raise InspectorError("invalid page token", code="invalidPageToken")
                end = offset + page_size
                result = {"nodes": self._hosted_nodes(hosted[offset:end], parent_id, offset)}
                if end < len(hosted):
                    result["nextPageToken"] = f"uia:{end}"
                return result
            page = client.children(
                ref.object_id,
                ref.generation,
                cast("Any", tree),
                page_size=page_size,
                page_token=page_token,
                deadline=time.monotonic() + self.cfg.inspector.request_timeout,
            )
            text_deadline = time.monotonic() + 5.0
            for child in page.items:
                child_ref = child.object_ref
                text = self._wpf_control_text(
                    client,
                    child_ref,
                    (
                        child_ref.type.full_name,
                        child.identity.x_name if child.identity else "",
                        child.identity.automation_id if child.identity else "",
                    ),
                    text_deadline,
                )
                self._remember_managed(client.session.session_id, child_ref.to_json())
                identity_data: dict[str, str] = {"type": child_ref.type.full_name}
                if child.identity is not None:
                    if child.identity.x_name:
                        identity_data["xName"] = child.identity.x_name
                    if child.identity.automation_id:
                        identity_data["automationId"] = child.identity.automation_id
                node_id = "wpf:" + json.dumps(
                    [child_ref.session_id, child_ref.object_id, child_ref.generation],
                    separators=(",", ":"),
                )
                info = ElementInfo(
                    identity_data.get("automationId", ""),
                    (text or "")[:100],
                    child_ref.type.name,
                    child_ref.type.full_name,
                    "WPF",
                    process_id,
                    None,
                    True,
                    False,
                    False,
                    node_id,
                )
                element = WpfElement(client, child_ref, process_id)
                with self._node_lock:
                    self.nodes[node_id] = element
                    self.node_infos[node_id] = info
                    self.nodes.move_to_end(node_id)
                    if len(self.nodes) > 5000:
                        evicted, evicted_node = self.nodes.popitem(last=False)
                        self.node_infos.pop(evicted, None)
                        self._wpf_text.pop(evicted, None)
                        self._wpf_windows.discard(evicted)
                        self._release_tree_node(evicted_node)
                description = {
                    "nodeId": node_id,
                    "info": info.to_dict(),
                    "hasChildren": (
                        child.has_visual_children
                        if tree == "visual"
                        else child.has_logical_children
                    )
                    or (self._is_hwnd_host(child_ref) and bool(self._hosted_children(element))),
                    "source": "wpf",
                    "identity": identity_data,
                }
                with self._node_lock:
                    self._wpf_parents[node_id] = parent_id
                    self._wpf_descriptions[node_id] = description
                    self._wpf_text[node_id] = text
                output.append(description)
            result: dict[str, Any] = {"nodes": output}
            if page.next_token is not None:
                result["nextPageToken"] = page.next_token
            elif host:
                hosted = self._hosted_children(node)
                remaining = max(0, page_size - len(output))
                output.extend(self._hosted_nodes(hosted[:remaining], parent_id, 0))
                if remaining < len(hosted):
                    result["nextPageToken"] = f"uia:{remaining}"
            return result

    def _remember_managed(self, session_id: str, value: Any) -> None:
        """Remember only handles actually returned by this authenticated session."""
        if isinstance(value, list):
            for item in cast("list[Any]", value):
                self._remember_managed(session_id, item)
        elif isinstance(value, dict):
            item = cast("dict[str, Any]", value)
            if {"sessionId", "objectId", "generation", "type", "dispatcherId"} <= item.keys():
                if item["sessionId"] != session_id:
                    from wintestkit.errors import InspectorUnavailableError

                    raise InspectorUnavailableError(
                        "Inspector returned an object from another session", code="sessionStale"
                    )
                with self._managed_lock:
                    self._managed_objects.setdefault(session_id, {})[item["objectId"]] = item[
                        "generation"
                    ]
            for child in item.values():
                self._remember_managed(session_id, child)

    def _managed_client(self, session_id: str) -> InspectorClient:
        from wintestkit import runtime
        from wintestkit.errors import InspectorUnavailableError

        with self._managed_lock:
            client = self._managed_clients.get(session_id)
        if client is None or runtime.inspector_sessions().get(client.session.process) is not client:
            with self._managed_lock:
                if self._spy_selection and self._spy_selection[1].session_id == session_id:
                    self._clear_managed_spy()
                self._managed_clients.pop(session_id, None)
                self._managed_objects.pop(session_id, None)
            raise InspectorUnavailableError(
                "Inspector session is no longer attached", code="sessionStale"
            )
        return client

    def _release_managed_objects(self) -> None:
        """Invalidate server-held leases on refresh without detaching the session."""
        assert self.cfg is not None
        from wintestkit.backends.element import WpfElement

        with self._node_lock:
            for node_id, node in list(self.nodes.items()):
                if isinstance(node, WpfElement):
                    node.forget_release()
                    del self.nodes[node_id]
                    self.node_infos.pop(node_id, None)
            self._wpf_windows.clear()
            self._wpf_parents.clear()
            self._wpf_descriptions.clear()
            self._wpf_text.clear()
        with self._managed_lock:
            self._clear_managed_spy()
            objects, self._managed_objects = self._managed_objects, {}
            clients = dict(self._managed_clients)
        for session_id, handles in objects.items():
            client = clients.get(session_id)
            if client is None:
                continue
            ids = list(handles)
            for offset in range(0, len(ids), 256):
                with contextlib.suppress(WtkError):
                    client.release(
                        ids[offset : offset + 256],
                        deadline=time.monotonic() + self.cfg.inspector.request_timeout,
                    )

    def _dispatch_managed(self, method: str, params: dict[str, Any]) -> Any:
        from wintestkit import runtime
        from wintestkit.errors import InspectorUnavailableError
        from wintestkit.inspector.models import ProcessIdentity, parse_path
        from wintestkit.inspector.probe import current_identity, identify

        assert self.cfg is not None
        with runtime.config_scope(self.cfg):
            if method == "inspect.managed.detach":
                session_id = params["sessionId"]
                with self._managed_lock:
                    if self._spy_selection and self._spy_selection[1].session_id == session_id:
                        self._clear_managed_spy()
                    client = self._managed_clients.pop(session_id, None)
                    self._managed_objects.pop(session_id, None)
                if client is not None:
                    client.close()
                return {"detached": True}
            if method == "inspect.managed.identify":
                from wintestkit.backends.element import WpfElement

                with self._node_lock:
                    selected = self.nodes.get(params["nodeId"])
                if isinstance(selected, WpfElement):
                    if not selected.is_alive():
                        raise RpcError(-32005, "unknown node id")
                    pid = selected.process_id
                else:
                    pid = self._node(params["nodeId"]).process_id
                facts = identify(pid)
                return {
                    "process": facts.identity.to_json(),
                    "executable": facts.executable,
                    "runtime": facts.runtime,
                    "architecture": facts.architecture,
                    "wpfLoaded": facts.wpf_loaded,
                    "appUnderTest": self._is_app_under_test(facts),
                }
            runtime.require_managed()
            if method in {"inspect.managed.attach", "inspect.managed.status"}:
                identity = ProcessIdentity.from_json(params["process"])
                registry = runtime.inspector_sessions()
                if method == "inspect.managed.attach":
                    options = {"spy_invoke": True} if "hostCapability" in params else {}
                    client = runtime.attach_managed(
                        identity,
                        deadline=time.monotonic() + self.cfg.inspector.attach_timeout,
                        **options,
                    )
                    session = client.session
                    if session.state != "ready":
                        from wintestkit.errors import InspectorUnavailableError

                        raise InspectorUnavailableError(
                            f"Inspector attachment ended in state {session.state}",
                            code=session.error or "attachFailed",
                        )
                else:
                    session = registry.status(identity)
                    if session.state == "faulted" and session.error:
                        from wintestkit.errors import InspectorUnavailableError

                        raise InspectorUnavailableError(
                            "Inspector session is faulted", code=session.error
                        )
                    client = registry.get(identity) if session.state == "ready" else None
                if client is not None:
                    with self._managed_lock:
                        self._managed_clients[client.session.session_id] = client
                return session.to_json()
            if method.startswith("inspect.managed.spy") and method in {
                "inspect.managed.spySelect",
                "inspect.managed.spyPrepareInvoke",
                "inspect.managed.spyInvoke",
            }:
                if method == "inspect.managed.spySelect":
                    return self._dispatch_spy_invoke(method, params)
                with self._managed_lock:
                    return self._dispatch_spy_invoke(method, params)
            session_id = params["sessionId"]
            client = self._managed_client(session_id)
            deadline = time.monotonic() + self.cfg.inspector.request_timeout
            if method == "inspect.managed.keepalive":
                # An empty release touches no application objects or property getters.
                client.release([], deadline=deadline)
                result = {"alive": True}
            elif method == "inspect.managed.resolve":
                from wintestkit.backends.element import WpfElement

                with self._node_lock:
                    selected = self.nodes.get(params["nodeId"])
                if isinstance(selected, WpfElement):
                    if not selected.is_alive():
                        raise RpcError(-32005, "unknown node id")
                    if selected.ref.session_id != session_id:
                        raise InspectorUnavailableError(
                            "Selected element belongs to another session", code="objectStale"
                        )
                    node = selected
                else:
                    node = self._node(params["nodeId"])
                if current_identity(node.process_id) != client.session.process:
                    raise InspectorUnavailableError(
                        "Selected element belongs to another process identity", code="processReused"
                    )
                if isinstance(node, WpfElement):
                    result = {
                        "status": "exact",
                        "process": client.session.process.to_json(),
                        "object": node.ref.to_json(),
                        "source": "wpf",
                    }
                else:
                    runtime_id, hwnd = runtime.managed_element_identity(node)
                    result = client.resolve(runtime_id, hwnd, deadline=deadline).to_json()
            elif method == "inspect.managed.roots":
                result = client.roots(
                    page_size=params.get("pageSize"),
                    page_token=params.get("pageToken"),
                    deadline=deadline,
                ).to_json()
            else:
                object_id = cast("str", params.get("objectId", ""))
                with self._managed_lock:
                    handles = self._managed_objects.get(session_id, {})
                    if object_id and handles.get(object_id) != params["generation"]:
                        raise InspectorUnavailableError(
                            "Object is not held by this session", code="objectStale"
                        )
                    if method == "inspect.managed.release" and any(
                        item not in handles for item in params["objectIds"]
                    ):
                        raise InspectorUnavailableError(
                            "Object is not held by this session", code="objectStale"
                        )
                if method == "inspect.managed.children":
                    result = client.children(
                        object_id,
                        params["generation"],
                        params["tree"],
                        page_size=params.get("pageSize"),
                        page_token=params.get("pageToken"),
                        deadline=deadline,
                    ).to_json()
                elif method == "inspect.managed.members":
                    result = client.members(
                        object_id,
                        params["generation"],
                        page_size=params.get("pageSize"),
                        page_token=params.get("pageToken"),
                        deadline=deadline,
                    ).to_json()
                elif method == "inspect.managed.spyMethods":
                    result = client.spy_methods(
                        object_id,
                        params["generation"],
                        page_size=params.get("pageSize"),
                        page_token=params.get("pageToken"),
                        deadline=deadline,
                    ).to_json()
                elif method == "inspect.managed.spyRead":
                    result = self._spy_read(
                        client,
                        object_id,
                        params["generation"],
                        [parse_path(path) for path in params["paths"]],
                        deadline,
                    )
                elif method == "inspect.managed.read":
                    values, read_id = client.read(
                        object_id,
                        params["generation"],
                        [parse_path(path) for path in params["paths"]],
                        deadline=deadline,
                    )
                    result = {"values": [value.to_json() for value in values], "readId": read_id}
                elif method == "inspect.managed.bindings":
                    bindings = client.bindings(
                        object_id, params["generation"], params["memberKeys"], deadline=deadline
                    )
                    result = {"bindings": [binding.to_json() for binding in bindings]}
                elif method == "inspect.managed.release":
                    if (
                        self._spy_selection
                        and self._spy_selection[1].session_id == session_id
                        and self._spy_selection[1].object_id in params["objectIds"]
                    ):
                        self._clear_managed_spy()
                    released = client.release(params["objectIds"], deadline=deadline)
                    with self._managed_lock:
                        for item in params["objectIds"]:
                            self._managed_objects.get(session_id, {}).pop(item, None)
                    result = {"releasedCount": released}
                else:
                    raise RpcError(-32601, "method not found")
            self._remember_managed(session_id, result)
            return result

    @staticmethod
    def _spy_read(
        client: InspectorClient,
        object_id: str,
        generation: int,
        paths: list[tuple[Any, ...]],
        deadline: float,
    ) -> dict[str, Any]:
        """Read the getters of one object for the Properties sidebar's automatic read.

        Every getter gets ``SPY_GETTER_LIMIT``; the whole request gets ``SPY_READ_BUDGET``. The
        properties go to the application as one batched request. If that batch runs into its
        limit, a getter hangs or the application is busy, so the properties are read again one by
        one: the slow ones answer "timeout" for their own row and the rest still arrive. Fields
        are always read one by one, the inspector has no batched field read.
        """
        from wintestkit.errors import InspectorDeadlineError, InspectorError
        from wintestkit.inspector.models import PathValue, Value

        def slow(error: InspectorError) -> bool:
            """The application did not answer in time: a hung getter or a busy UI thread."""
            return isinstance(error, InspectorDeadlineError) or error.code in _APPLICATION_SLOW

        budget = min(deadline, time.monotonic() + SPY_READ_BUDGET)
        values: dict[int, PathValue] = {}
        read_id = ""

        def timeout(index: int) -> PathValue:
            return PathValue(paths[index], Value("timeout", "unavailable", "", ""))

        def one(index: int) -> PathValue:
            if time.monotonic() >= budget:
                return timeout(index)
            single = (
                client.spy_field_read
                if len(paths[index]) == 1 and paths[index][0].kind == "field"
                else client.read
            )
            limit = min(budget, time.monotonic() + SPY_GETTER_LIMIT)
            try:
                found, _ = single(object_id, generation, [paths[index]], deadline=limit)
            except InspectorError as error:
                if not slow(error):
                    raise
                return timeout(index)
            return found[0]

        batched = [
            index
            for index, path in enumerate(paths)
            if not (len(path) == 1 and path[0].kind == "field")
        ]
        if len(batched) > 1 and time.monotonic() < budget:
            limit = min(budget, time.monotonic() + SPY_GETTER_LIMIT + 0.02 * len(batched))
            try:
                found, read_id = client.read(
                    object_id, generation, [paths[index] for index in batched], deadline=limit
                )
                values.update(zip(batched, found, strict=True))
            except InspectorError as error:
                if not slow(error):
                    raise
        for index in range(len(paths)):
            if index not in values:
                values[index] = one(index)
        return {
            "values": [values[index].to_json() for index in range(len(paths))],
            "readId": read_id or secrets.token_hex(16),
        }

    def _dispatch_spy_invoke(self, method: str, params: dict[str, Any]) -> Any:
        from wintestkit.inspector.client import validate_spy_arguments
        from wintestkit.inspector.models import ObjectRef

        assert self.cfg is not None
        if method == "inspect.managed.spySelect":
            if "sessionId" not in params:
                return {"canInvoke": False}
            mapping = self._dispatch_managed(
                "inspect.managed.resolve",
                {"sessionId": params["sessionId"], "nodeId": params["nodeId"]},
            )
            client = self._managed_client(params["sessionId"])
            if mapping.get("status") == "exact" and "object" in mapping:
                ref = ObjectRef.from_json(mapping["object"])
                if ref.session_id != params["sessionId"]:
                    raise RpcError(-32000, "Spy selection unavailable")
                with self._managed_lock:
                    if (
                        self._managed_objects.get(ref.session_id, {}).get(ref.object_id)
                        != ref.generation
                    ):
                        raise RpcError(-32000, "Spy selection unavailable")
                    self._spy_selection = (client, ref)
            return {
                "canInvoke": self._spy_selection is not None
                and bool(getattr(client, "_spy_invoke_available", False)),
                "mapping": mapping,
            }
        selection = self._spy_selection
        if selection is None:
            raise RpcError(-32000, "Spy selection unavailable")
        client, ref = selection
        if (
            self._managed_client(ref.session_id) is not client
            or not getattr(client, "_spy_invoke_available", False)
            or self._managed_objects.get(ref.session_id, {}).get(ref.object_id) != ref.generation
        ):
            self._clear_managed_spy()
            raise RpcError(-32000, "Spy selection unavailable")
        if method == "inspect.managed.spyPrepareInvoke":
            self._spy_ticket = None
            if (params["sessionId"], params["objectId"], params["generation"]) != (
                ref.session_id,
                ref.object_id,
                ref.generation,
            ):
                raise RpcError(-32000, "Spy selection unavailable")
            ticket = secrets.token_urlsafe(32)
            self._spy_ticket = (
                ticket,
                time.monotonic() + 30,
                client,
                ref,
                params["memberKey"],
                validate_spy_arguments(params["arguments"]),
            )
            return {"ticket": ticket}
        ticket_state = self._spy_ticket
        self._spy_ticket = None
        if (
            ticket_state is None
            or not hmac.compare_digest(ticket_state[0], params["ticket"])
            or time.monotonic() >= ticket_state[1]
            or ticket_state[2] is not client
            or ticket_state[3] != ref
        ):
            raise RpcError(-32000, "Spy ticket unavailable")
        deadline = time.monotonic() + self.cfg.inspector.request_timeout
        invoke_method = "_spy_invoke"
        audit, result = getattr(client, invoke_method)(
            ref,
            ticket_state[4],
            ticket_state[5],
            timeout_ms=min(2000, max(1, int(self.cfg.inspector.request_timeout * 1000))),
            deadline=deadline,
        )
        response = {"audit": audit.to_json(), "result": result.to_json()}
        self._remember_managed(ref.session_id, response)
        return response

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
        parent_id: str | None = None,
        start_index: int = 0,
    ) -> list[dict[str, Any]]:
        from wintestkit.uia import win32

        nodes: list[dict[str, Any]] = []
        names = dict(win32.list_processes())
        errors = list(errors or [])
        for index, element in enumerate(elements):
            if element is None:
                continue
            try:
                fallback_id = None if parent_id is None else f"{parent_id}~{index + start_index}"
                node = self._register(element, fallback_id)
                name = names.get(node["info"].get("processId"))
                if name:
                    node["info"]["processName"] = name
                nodes.append(node)
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
            from wintestkit import runtime

            with self._managed_rpc_lock, self._managed_lock:
                runtime.reset()
                self._clear_managed_spy()
                self._managed_clients.clear()
                self._managed_objects.clear()
            self.stop_spy()
            self._stopping.set()
            return None
        if method == "initialize":
            if self.cfg is not None:
                raise RpcError(-32600, "already initialized")
            cfg = load_config(Path(params["root"]))
            loader = ModuleLoader(cfg)
            if cfg.found and cfg.object_previews and (cfg.root / "object-previews").is_dir():
                sync_object_previews_ignore(cfg.root, cfg.object_previews_share)
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
            managed_available = False
            try:
                from wintestkit.inspector.payload import load_payload

                load_payload().verify()
                managed_available = True
            except Exception:
                pass
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "wintestkitVersion": __version__,
                "python": platform.python_version(),
                "config": settings,
                "capabilities": {"managedInspector": managed_available},
            }
        if self.cfg is None or self.loader is None:
            raise RpcError(-32600, "not initialized")
        if method.startswith("inspect.managed."):
            # Only changing the attachment is serialized. Reading an object, the keepalive and the
            # rest must never queue behind a slow attach or another read.
            if method in _MANAGED_LIFECYCLE:
                with self._managed_rpc_lock:
                    return self._dispatch_managed(method, params)
            return self._dispatch_managed(method, params)
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
                from wintestkit.inspector.probe import current_identity

                self._owned_app_identities.clear()
                if app.launched:
                    for pid in app.pids:
                        with contextlib.suppress(Exception):
                            self._owned_app_identities.add(current_identity(pid))
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
        if method in ("element.highlight", "element.check", "page.check"):
            app = self._app()
            assert app is not None
            file = Path(params["file"])
            file = (self.cfg.root / file).resolve()
            if method == "page.check":
                return {
                    "results": [
                        result.to_dict()
                        for result in check_page(
                            app, self.loader, file, params["page"], capture=True
                        )
                    ]
                }
            if method == "element.check":
                return resolve_target(
                    app, self.loader, Target(file, params["qualname"]), timeout=0, capture=True
                ).to_dict()
            result = resolve_target(app, self.loader, Target(file, params["qualname"]), timeout=0)
            if result.uia is not None:
                rect = self._raise_for_highlight(result.uia)
            else:
                rect = result.element.rect if result.element is not None else None
            self._flash(rect, params)
            return result.to_dict()
        if method == "inspect.coverage":
            from wintestkit.backends.element import WpfElement
            from wintestkit.errors import NoUiaPeerError

            app = self._app(False)
            if app is None:
                return {"covered": {}, "pending": []}
            with self._node_lock:
                infos = {
                    node_id: self.node_infos[node_id]
                    for node_id in params["nodeIds"]
                    if node_id in self.node_infos
                }
                selected_nodes = {node_id: self.nodes.get(node_id) for node_id in infos}
            aliases: dict[str, list[str]] = {
                node_id: [node_id]
                for node_id, selected_node in selected_nodes.items()
                if not isinstance(selected_node, WpfElement)
            }
            for node_id, selected_node in selected_nodes.items():
                if isinstance(selected_node, WpfElement):
                    del infos[node_id]
                    try:
                        peer = selected_node.as_live().as_uia()
                        info = peer.info()
                        infos[info.runtime_id] = info
                        aliases.setdefault(info.runtime_id, []).append(node_id)
                    except NoUiaPeerError:
                        continue
            result = self._coverage().covered_nodes(app, infos)
            result["covered"] = {
                alias: value
                for key, value in result["covered"].items()
                for alias in aliases.get(key, [key])
            }
            result["pending"] = [
                alias for key in result["pending"] for alias in aliases.get(key, [key])
            ]
            return result
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
                self._mark_roots(nodes)
                return {"nodes": nodes, "status": status} if status is not None else nodes
            include_other = params.get("includeOtherApps", False)
            roots: list[UIAElement | None]
            if app is not None and not include_other:
                roots = list(windows)
                source_indices = list(range(len(roots)))
            else:
                from wintestkit.errors import UIAError
                from wintestkit.uia import element, win32

                desktop: list[UIAElement | None] = []
                for hwnd in win32.desktop_windows():
                    try:
                        desktop.append(element.from_handle(hwnd))
                    except UIAError:
                        continue  # the window closed while enumerating
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
                source_indices=source_indices,
            )
            self._mark_roots(nodes)
            return {"nodes": nodes, "status": status} if status is not None else nodes
        if method == "spy.start":
            from wintestkit.engine.spy import SpySession
            from wintestkit.uia import win32

            app = self._app(False)
            pids = frozenset(app.pids) if app is not None else None
            epoch = self._spy_epoch
            session_params = {"sessionId": params["sessionId"]} if "sessionId" in params else {}
            host_window = (
                win32.foreground_window_for_process(params["foregroundForProcessId"])
                if "foregroundForProcessId" in params
                else None
            )

            def publish(method: str, element: Any, locate: bool = True) -> None:
                with self._spy_lock:
                    if epoch != self._spy_epoch or self.spy is not session:
                        return
                target = element if isinstance(element, _SpyTarget) else _SpyTarget(element)
                node = (
                    target.node
                    if target.node is not None
                    else self._register(target.element, locate=locate)
                )
                with self._spy_lock:
                    if epoch == self._spy_epoch and self.spy is session:
                        if method == "spy.picked" and host_window is not None:
                            try:
                                win32.bring_to_foreground(host_window)
                            except Exception:
                                log.exception("Could not reactivate the element picker host window")
                        self.notify(method, {"node": node, **session_params, **target.extra})

            def hover(element: UIAElement) -> None:
                publish("spy.hover", element, locate=False)

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
                    options: dict[str, Any] = {}
                    if "tree" in params:

                        def resolve(
                            element: UIAElement, x: int, y: int, picked: bool
                        ) -> _SpyTarget:
                            return self._spy_resolve(element, x, y, picked, params["tree"])

                        options["resolve"] = resolve
                    session = SpySession(
                        hover, pick, cancel, None if pids is None else pids.__contains__, **options
                    )
                    self.spy = session
                    try:
                        session.start()
                    except Exception:
                        self.spy = None
                        self._spy_epoch += 1
                        raise
            return None
        if method == "inspect.children":
            from wintestkit.backends.element import WpfElement

            with self._node_lock:
                tree_node = self.nodes.get(params["nodeId"])
            if "tree" in params and (
                isinstance(tree_node, WpfElement)
                or (tree_node is not None and params["nodeId"] in self._wpf_windows)
            ):
                return self._wpf_children(
                    tree_node,
                    params["tree"],
                    params.get("pageSize", 200),
                    params.get("pageToken"),
                    params["nodeId"],
                )
        from wintestkit.backends.element import WpfElement

        with self._node_lock:
            selected = self.nodes.get(params["nodeId"])
        if (
            method == "inspect.properties"
            and selected is not None
            and params["nodeId"] in self._wpf_windows
        ):
            # Roots retain their UIA identity for window enumeration and locators.  Once
            # attached, resolve that identity to the Window object for its properties.
            from wintestkit import runtime
            from wintestkit.errors import InspectorError
            from wintestkit.inspector.probe import current_identity

            assert self.cfg is not None
            try:
                with runtime.config_scope(self.cfg):
                    client = runtime.inspector_sessions().get(current_identity(selected.process_id))
                    if client is not None:
                        rid, hwnd = runtime.managed_element_identity(cast("UIAElement", selected))
                        mapping = client.resolve(
                            rid,
                            hwnd,
                            deadline=time.monotonic() + self.cfg.inspector.request_timeout,
                        )
                        if mapping.status == "exact" and mapping.object_ref is not None:
                            ref = mapping.object_ref
                            return self._wpf_properties(
                                WpfElement(client, ref, selected.process_id),
                                params,
                                cast("UIAElement", selected).as_live(),
                            )
            except InspectorError:
                log.debug("WPF window properties unavailable; using UIA", exc_info=True)
        if isinstance(selected, WpfElement) and method in (
            "inspect.highlight",
            "inspect.preview",
            "inspect.properties",
        ):
            if not selected.is_alive():
                raise RpcError(-32005, "unknown node id")
            wpf_node = selected.as_live()
            if method == "inspect.properties":
                return self._wpf_properties(wpf_node, params)
            if method == "inspect.preview":
                from wintestkit.live_preview import capture_live_preview

                return capture_live_preview(wpf_node)
            from wintestkit.uia import win32

            state = wpf_node.state()
            hwnd = state.window_handle
            if (
                params.get("bringToFront", False)
                and hwnd
                and (wpf_node.rect is not None or win32.IsIconic(hwnd))
            ):
                win32.raise_window(win32.root_window(hwnd))
                wpf_node = wpf_node.as_live()
            self._flash(wpf_node.rect, params)
            return None
        if isinstance(selected, WpfElement) and method in (
            "inspect.definitions",
            "suggest.locator",
        ):
            from wintestkit.errors import NoUiaPeerError

            if not selected.is_alive():
                raise RpcError(-32005, "unknown node id")
            if method == "suggest.locator":
                from wintestkit import runtime
                from wintestkit.engine.suggest import WindowSelectedError, suggest_locator

                wpf_ancestors: list[WpfElement] = []
                with self._node_lock:
                    parent_id = self._wpf_parents.get(params["nodeId"])
                    seen = {params["nodeId"]}
                    while parent_id and parent_id not in seen and len(seen) < 100:
                        seen.add(parent_id)
                        parent = self.nodes.get(parent_id)
                        if isinstance(parent, WpfElement):
                            wpf_ancestors.append(parent)
                        parent_id = self._wpf_parents.get(parent_id)
                try:
                    assert self.cfg is not None
                    with runtime.config_scope(self.cfg):
                        return suggest_locator(
                            selected, self._app(False), ancestors=tuple(wpf_ancestors)
                        ).to_dict()
                except WindowSelectedError as exc:
                    raise RpcError(-32006, str(exc)) from exc
            try:
                peer = selected.as_live().as_uia()
            except NoUiaPeerError:
                return self._coverage().definitions_of(
                    self._app(False), params["nodeId"], selected.info()
                )
            if method == "inspect.definitions":
                return self._coverage().definitions_of(
                    self._app(False), peer.runtime_id, peer.info()
                )
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
                return self._register_nodes(exc.elements, exc.errors, parent_id=params["nodeId"])
            if "tree" not in params:
                return self._register_nodes(children, parent_id=params["nodeId"])
            from wintestkit.errors import InspectorError

            token = params.get("pageToken")
            if token is not None and (
                not token.isascii() or not token.isdecimal() or token.startswith("0")
            ):
                raise InspectorError("invalid page token", code="invalidPageToken")
            offset = int(token) if token is not None else 0
            if token is not None and offset >= len(children):
                raise InspectorError("invalid page token", code="invalidPageToken")
            end = offset + params.get("pageSize", 200)
            if params["nodeId"] in self._wpf_parents:
                page_nodes = self._hosted_nodes(children[offset:end], params["nodeId"], offset)
            else:
                page_nodes = self._register_nodes(
                    children[offset:end], parent_id=params["nodeId"], start_index=offset
                )
            page_result: dict[str, Any] = {"nodes": page_nodes}
            if end < len(children):
                page_result["nextPageToken"] = str(end)
            return page_result
        if method == "inspect.highlight":
            # The outline is drawn on top of every window, so raising the window is opt-in.
            rect = (
                self._raise_for_highlight(node) if params.get("bringToFront", False) else node.rect
            )
            self._flash(rect, params)
            return None
        if method == "inspect.preview":
            from wintestkit.live_preview import capture_live_preview

            return capture_live_preview(node)
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

            def read_property(name: str) -> None:
                try:
                    description = inspection_property(name, node.get_property(name))
                    inspection.append(description)
                    properties[name] = _summarize(description)
                except Exception as exc:
                    inspection.append(
                        {
                            "name": name,
                            "typeName": "UIA",
                            "kind": "unavailable",
                            "status": str(exc)[:512],
                        }
                    )

            for name in PROPERTY_IDS if full else ():
                read_property(name)
            if not full:
                values = inspection_values(node, self.cfg.property_aliases, base=())
                inspection.extend(inspection_property(key, value) for key, value in values.items())
                properties.update({key: str(value) for key, value in values.items()})
                # Properties the user pinned to the default list are read with every selection.
                for name in dict.fromkeys(params.get("include", ())):
                    if name in PROPERTY_IDS and name not in properties:
                        read_property(name)
            for alias, target in self.cfg.property_aliases.items():
                if target not in SUPPORTED:
                    continue  # managed aliases never trigger reads in the UIA properties view
                property_name = SUPPORTED[target].uia_name if full else target
                if property_name in properties:
                    properties[alias] = properties[property_name]
            ancestors: list[dict[str, Any]] = []
            parent = node.parent() if params.get("includeAncestors", False) else None
            hosted_parent = self._wpf_parents.get(params["nodeId"]) if parent is not None else None
            seen = {params["nodeId"]}
            while hosted_parent and len(ancestors) < 100:
                registered = self._wpf_descriptions.get(hosted_parent)
                if registered is None or hosted_parent in seen:
                    break
                seen.add(hosted_parent)
                ancestors.append(registered)
                hosted_parent = self._wpf_parents.get(hosted_parent)
            if ancestors:
                parent = None
            while parent is not None and len(ancestors) < 100:
                registered = self._register(parent)
                if registered["nodeId"] in seen:
                    break
                seen.add(registered["nodeId"])
                ancestors.append(registered)
                parent = parent.parent()
            info = node.info(with_patterns=full)
            if not info.runtime_id:
                info = dataclasses.replace(info, runtime_id=params["nodeId"])
            return {
                "info": info.to_dict(),
                "properties": properties,
                "ancestors": list(reversed(ancestors)),
                "inspection": inspection,
            }
        raise RpcError(-32601, "method not found")

    def serve(self, source: BinaryIO) -> int:
        requests: queue.Queue[Any] = queue.Queue()
        finished = object()
        reads = ThreadPoolExecutor(max_workers=_READ_WORKERS, thread_name_prefix="wtk-rpc-read")

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
                elif (
                    isinstance(request, dict)
                    and cast("dict[str, Any]", request).get("method") in _APPLICATION_READS
                ):
                    reads.submit(self.handle, request)
                else:
                    if isinstance(request, dict):
                        request["_spyEpoch"] = self._spy_epoch
                    requests.put(request)
            requests.put(finished)
            self.stop_spy()
            worker.join(timeout=5 if self._stopping.is_set() else None)
        finally:
            from wintestkit import runtime

            runtime.close_inspector_sessions()
            self._clear_managed_spy()
            self._stopping.set()
            self.stop_spy()
            requests.put(finished)
            reads.shutdown(wait=False, cancel_futures=True)
            logger.removeHandler(handler)
            sys.stdout = previous_stdout
        return 0
