"""Authenticated inspector requests, deadlines, and session-scoped DTOs."""

from __future__ import annotations

import csv
import math
import os
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, cast

from wintestkit.errors import (
    InspectorDeadlineError,
    InspectorError,
    InspectorLimitError,
    InspectorReadError,
    InspectorUnavailableError,
    WriteDeniedError,
    WriteRateExceededError,
)
from wintestkit.inspector.models import (
    ERROR_CODES,
    ActResult,
    BindingInfo,
    CandidateResult,
    ElementState,
    HelloResult,
    ItemMatch,
    Locator,
    ManagedNode,
    Mapping,
    Member,
    ObjectRef,
    Page,
    PathValue,
    ProcessFacts,
    QueryFindAllResult,
    QueryFindResult,
    RealizeResult,
    Session,
    Value,
    WaitCondition,
    WaitResult,
    WriteAudit,
    parse_path,
)
from wintestkit.inspector.models import array_value as _array
from wintestkit.inspector.models import bool_value as _bool
from wintestkit.inspector.models import choice_value as _choice
from wintestkit.inspector.models import identifier_value as _identifier
from wintestkit.inspector.models import integer_value as _int
from wintestkit.inspector.models import key_value as _key
from wintestkit.inspector.models import object_value as _obj
from wintestkit.inspector.models import runtime_id_value as _runtime_id
from wintestkit.inspector.models import scalar_value as _scalar
from wintestkit.inspector.paths import ManagedPath, PathSegment
from wintestkit.inspector.transport import ByteTransport, read_frame, write_frame


@dataclass(frozen=True)
class HitTestResult:
    handle: ObjectRef
    path: tuple[ManagedNode, ...] | None = None


_trace_lock = threading.Lock()


def _write_scalar(value: object) -> str | bool | int | float:
    scalar = _scalar(value)
    if type(scalar) is int and not -(2**63) <= scalar <= 2**63 - 1:
        raise ValueError("Invalid write integer")
    return scalar


def _error(code: str, details: object = None) -> InspectorError:
    if code == "writeDenied":
        return WriteDeniedError("Inspector request failed: writeDenied", code=code)
    if code == "writeRateExceeded":
        return WriteRateExceededError("Inspector request failed: writeRateExceeded", code=code)
    if code == "timeout" or (
        code == "limitExceeded"
        and isinstance(details, dict)
        and cast(dict[str, object], details).get("deadline") is True
    ):
        return InspectorDeadlineError(
            f"Inspector request failed: {code}",
            code=code,
            busy=code == "timeout"
            and isinstance(details, dict)
            and cast(dict[str, object], details).get("dispatcherBusy") is True,
        )
    if code == "valueUnreadable":
        status = (
            cast(dict[str, object], details).get("status") if isinstance(details, dict) else None
        )
        status = status if isinstance(status, str) else code
        return InspectorReadError(f"Inspector value unreadable: {status}", code=status)
    if code in {"busy", "limitExceeded"}:
        return InspectorLimitError(f"Inspector request failed: {code}", code=code)
    if code in {
        "unsupportedProtocol",
        "unsupportedTarget",
        "accessDenied",
        "authenticationFailed",
        "payloadMissing",
        "payloadMismatch",
        "alreadyAttached",
        "notAttached",
        "attachFailed",
        "blockedByPolicy",
        "agentVersionMismatch",
        "processExited",
        "processReused",
        "sessionStale",
    }:
        return InspectorUnavailableError(f"Inspector request failed: {code}", code=code)
    return InspectorError(f"Inspector request failed: {code}", code=code)


def _response(value: object) -> tuple[int, object, InspectorError | None]:
    data = _obj(value, "id", "result error")
    request_id = _int(data["id"], 1)
    if ("result" in data) == ("error" in data):
        raise ValueError("Invalid response envelope")
    if "error" not in data:
        return request_id, data["result"], None
    error = _obj(data["error"], "code message", "details")
    code = _choice(error["code"], ERROR_CODES)
    if not isinstance(error["message"], str) or len(error["message"]) > 1024:
        raise ValueError("Invalid error message")
    if "details" in error and not isinstance(error["details"], dict):
        raise ValueError("Invalid error details")
    details = error.get("details")
    result = _error(code, details)
    if isinstance(details, dict) and "audit" in details:
        result.audit = WriteAudit.from_json(cast(dict[str, object], details)["audit"])
    return request_id, None, result


@dataclass
class _Pending:
    event: threading.Event
    result: object = None
    error: InspectorError | None = None
    request_id: int = 0


class InspectorClient:
    def __init__(
        self,
        transport: ByteTransport,
        session: Session,
        *,
        request_timeout: float = 2.0,
        on_closed: Callable[[InspectorClient], None] | None = None,
    ) -> None:
        if not 0 < request_timeout <= 2:
            raise ValueError("Request timeout must be between zero and two seconds")
        self._transport = transport
        self.session = session
        self._request_timeout = request_timeout
        self._on_closed = on_closed
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._abandoned: set[int] = set()
        self._next_id = 2
        self._closed = False
        self._closing_session = False
        self._reader = threading.Thread(
            target=self._read_responses, name="WinTestKit inspector pipe", daemon=True
        )
        self._reader.start()

    @classmethod
    def authenticate(
        cls,
        transport: ByteTransport,
        facts: ProcessFacts,
        session_id: str,
        token: str,
        agent_version: str,
        *,
        deadline: float,
        request_timeout: float = 2.0,
        on_closed: Callable[[InspectorClient], None] | None = None,
    ) -> InspectorClient:
        try:
            write_frame(
                transport,
                {
                    "id": 1,
                    "method": "session.hello",
                    "params": {
                        "protocolMajor": 2,
                        "protocolMinor": 0,
                        "sessionId": session_id,
                        "token": token,
                        "process": facts.identity.to_json(),
                    },
                },
                deadline,
            )
            response_id, result, error = _response(read_frame(transport, deadline))
            if response_id != 1:
                raise ValueError("Mismatched hello response ID")
            if error is not None:
                raise error
            hello = HelloResult.from_json(result)
            if hello.process != facts.identity:
                raise InspectorUnavailableError(
                    "Inspector hello process identity mismatch", code="processReused"
                )
            if hello.agent_version != agent_version:
                raise InspectorUnavailableError(
                    "Inspector agent version mismatch; restart the application",
                    code="agentVersionMismatch",
                )
            expected_tfm = {
                "net48": "net48",
                "net8": "net8.0-windows",
                "net10": "net10.0-windows",
            }.get(facts.runtime or "")
            expected_major = {"net48": "4", "net8": "8", "net10": "10"}.get(facts.runtime or "")
            if (
                hello.tfm != expected_tfm
                or hello.architecture != facts.architecture
                or hello.runtime_version.split(".")[0] != expected_major
            ):
                raise InspectorUnavailableError(
                    "Inspector hello runtime or architecture mismatch", code="unsupportedTarget"
                )
            session = Session(
                session_id,
                facts.identity,
                "ready",
                2,
                0,
                hello.features,
                hello.runtime_version,
                hello.architecture,
                hello.agent_version,
            )
            return cls(transport, session, request_timeout=request_timeout, on_closed=on_closed)
        except InspectorError:
            transport.close()
            raise
        except TimeoutError as error:
            transport.close()
            raise InspectorUnavailableError("Inspector hello timed out", code="timeout") from error
        except (ValueError, TypeError, OverflowError, EOFError, OSError, UnicodeError) as error:
            transport.close()
            raise InspectorUnavailableError(
                "Invalid or unavailable inspector hello", code="authenticationFailed"
            ) from error
        except BaseException:
            transport.close()
            raise

    def invalidate(self, error: InspectorError, state: str = "faulted") -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.session = replace(self.session, state=state, error=error.code)
            pending = tuple(self._pending.values())
            self._pending.clear()
            for entry in pending:
                entry.error = error
                entry.event.set()
        self._transport.close()
        if self._on_closed is not None:
            self._on_closed(self)

    def _read_responses(self) -> None:
        try:
            while True:
                request_id, result, error = _response(
                    read_frame(self._transport, time.monotonic() + 301)
                )
                with self._lock:
                    if request_id in self._abandoned:
                        self._abandoned.remove(request_id)
                        continue
                    pending = self._pending.pop(request_id, None)
                    if pending is None:
                        raise ValueError("Response ID is not outstanding")
                    pending.result = result
                    pending.error = error
                    pending.event.set()
        except TimeoutError:
            self.invalidate(
                InspectorUnavailableError("Inspector session became idle", code="sessionStale")
            )
        except (ValueError, EOFError, OSError, UnicodeError):
            if self._closing_session:
                self.invalidate(
                    InspectorUnavailableError("Inspector session detached", code="notAttached"),
                    "detached",
                )
            else:
                self.invalidate(
                    InspectorUnavailableError(
                        "Inspector connection closed or returned invalid data", code="sessionStale"
                    )
                )

    def _send(
        self, method: str, params: dict[str, object], deadline: float, *, discard: bool = False
    ) -> _Pending:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._write_lock.acquire(timeout=max(0, remaining)):
            raise InspectorDeadlineError("Inspector request deadline expired", code="timeout")
        entry = _Pending(threading.Event())
        try:
            with self._lock:
                if self._closed:
                    raise InspectorUnavailableError(
                        "Inspector session is not ready", code="sessionStale"
                    )
                if len(self._pending) >= 16 or len(self._abandoned) >= 256:
                    raise InspectorLimitError("Inspector request queue is full", code="busy")
                request_id = self._next_id
                self._next_id += 1
                if discard:
                    self._abandoned.add(request_id)
                else:
                    self._pending[request_id] = entry
            if time.monotonic() >= deadline:
                with self._lock:
                    self._pending.pop(request_id, None)
                    self._abandoned.discard(request_id)
                raise InspectorDeadlineError("Inspector request deadline expired", code="timeout")
            try:
                write_frame(
                    self._transport,
                    {"id": request_id, "method": method, "params": params},
                    deadline,
                )
            except TimeoutError as error:
                self.invalidate(
                    InspectorUnavailableError("Inspector pipe write failed", code="sessionStale")
                )
                raise InspectorDeadlineError(
                    "Inspector pipe write timed out", code="timeout"
                ) from error
            except (ValueError, EOFError, OSError, UnicodeError) as error:
                self.invalidate(
                    InspectorUnavailableError("Inspector pipe write failed", code="sessionStale")
                )
                raise InspectorUnavailableError(
                    "Inspector pipe write failed", code="sessionStale"
                ) from error
            entry.request_id = request_id
            return entry
        finally:
            self._write_lock.release()

    def _cancel(self, request_id: int) -> None:
        with suppress(InspectorError):
            self._send(
                "request.cancel", {"requestId": request_id}, time.monotonic() + 0.25, discard=True
            )

    def _request(self, method: str, params: dict[str, object], deadline: float) -> object:
        start = time.monotonic()
        trace_path = os.environ.get("WTK_INSPECTOR_TRACE")
        outcome = "ok"
        retries = 0
        retryable = (
            method
            in {
                "roots",
                "children",
                "members",
                "read",
                "bindings",
                "element.resolve",
                "element.readBatch",
                "state.get",
                "wait.until",
                "hitTest",
            }
            or method.startswith("query.")
            or (method.startswith("act.") and method != "act.realizeItem")
        )
        try:
            deadline = min(deadline, start + self._request_timeout)
            while True:
                entry = self._send(method, params, deadline)
                if not entry.event.wait(max(0, deadline - time.monotonic())):
                    request_id = entry.request_id
                    with self._lock:
                        if self._pending.pop(request_id, None) is not None:
                            self._abandoned.add(request_id)
                            threading.Thread(
                                target=self._cancel, args=(request_id,), daemon=True
                            ).start()
                            raise InspectorDeadlineError(
                                "Inspector request deadline expired", code="timeout"
                            )
                if (
                    isinstance(entry.error, InspectorDeadlineError)
                    and entry.error.busy
                    and retryable
                ):
                    with self._lock:
                        if self._closed:
                            raise InspectorUnavailableError(
                                "Inspector session is not ready", code="sessionStale"
                            )
                    remaining = deadline - time.monotonic()
                    if remaining <= 0.05:
                        if remaining > 0:
                            time.sleep(remaining)
                        with self._lock:
                            if self._closed:
                                raise InspectorUnavailableError(
                                    "Inspector session is not ready", code="sessionStale"
                                )
                        raise entry.error
                    retries += 1
                    time.sleep(min(0.05, remaining))
                    with self._lock:
                        if self._closed:
                            raise InspectorUnavailableError(
                                "Inspector session is not ready", code="sessionStale"
                            )
                    if time.monotonic() >= deadline:
                        raise entry.error
                    continue
                if (
                    isinstance(entry.error, InspectorDeadlineError)
                    and entry.error.busy
                    and not retryable
                ):
                    entry.error.busy = False
                    raise entry.error
                if entry.error is not None:
                    raise entry.error
                return entry.result
        except InspectorDeadlineError as error:
            outcome = error.code if error.code in ERROR_CODES else "timeout"
            wrapped = InspectorDeadlineError(
                f"Inspector request {method} timed out "
                f"(budget={max(0, deadline - start):g}s, "
                f"inspector.request_timeout={self._request_timeout:g}s)"
                + ("; target's UI thread stayed busy" if error.busy else ""),
                code=error.code,
                busy=error.busy,
            )
            wrapped.audit = error.audit
            raise wrapped from error
        except InspectorError as error:
            outcome = error.code if error.code in ERROR_CODES else "error"
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            if trace_path:
                with (
                    suppress(OSError, csv.Error),
                    _trace_lock,
                    open(trace_path, "a", encoding="utf-8", newline="") as trace,
                ):
                    csv.writer(trace).writerow(
                        (
                            datetime.now(UTC).isoformat(),
                            method,
                            f"{time.monotonic() - start:.6f}",
                            f"{outcome};retries={retries}" if retries else outcome,
                        )
                    )

    def _parse(self, parser: Callable[[object], Any], value: object) -> Any:
        try:
            return parser(value)
        except (ValueError, TypeError, OverflowError, UnicodeError) as error:
            self.invalidate(
                InspectorUnavailableError("Invalid inspector response", code="sessionStale")
            )
            raise InspectorUnavailableError(
                "Invalid inspector response", code="sessionStale"
            ) from error

    def _feature(self, *names: str) -> None:
        if not set(names) <= set(self.session.features):
            raise InspectorUnavailableError(
                "Inspector agent does not support this operation", code="unsupportedTarget"
            )

    def _path_features(self, paths: Sequence[Sequence[PathSegment]]) -> None:
        for path in paths:
            for segment in path:
                if segment.kind == "uia":
                    continue
                self._feature(
                    {
                        "type": "typeMetadata",
                        "dependency": "dependencyProperties",
                        "property": "clrMembers",
                        "field": "clrMembers",
                    }[segment.kind]
                )

    def _object_ref(self, reference: ObjectRef | None) -> None:
        if reference is not None and reference.session_id != self.session.session_id:
            raise ValueError("Object belongs to another session")

    def _mapping(self, value: object) -> Mapping:
        result = Mapping.from_json(value)
        if result.process != self.session.process:
            raise ValueError("Mapping belongs to another process")
        self._object_ref(result.object_ref)
        return result

    def _value(self, value: Value) -> None:
        self._object_ref(value.object_ref)
        self._object_ref(value.cycle_to)

    def resolve(
        self, runtime_id: tuple[int, ...], native_window_handle: int | None, *, deadline: float
    ) -> Mapping:
        self._feature("exactUiaMapping")
        try:
            expected = _runtime_id(list(runtime_id))
            params: dict[str, object] = {"runtimeId": list(expected)}
            if native_window_handle is not None:
                params["nativeWindowHandle"] = _int(
                    native_window_handle, -9_223_372_036_854_775_808
                )
        except ValueError as error:
            raise InspectorError("Invalid UIA identity", code="invalidParams") from error

        def parse(value: object) -> Mapping:
            result = self._mapping(value)
            if result.runtime_id != expected:
                raise ValueError("Mismatched mapping identity")
            return result

        return self._parse(parse, self._request("element.resolve", params, deadline))

    def _timed_params(self, timeout_ms: int, deadline: float) -> int:
        try:
            requested = _int(timeout_ms, 1, 2000)
        except (ValueError, TypeError) as error:
            raise InspectorError("Invalid request timeout", code="invalidParams") from error
        remaining = int((deadline - time.monotonic()) * 1000)
        if remaining < 1:
            raise InspectorDeadlineError("Inspector request deadline expired", code="timeout")
        return min(requested, remaining)

    def _query(self, method: str, locator: Locator, timeout_ms: int, deadline: float) -> object:
        self._feature("query")
        self._object_ref(locator.scope.handle)
        try:
            wire = Locator.from_json(locator.to_json()).to_json()
        except (ValueError, TypeError) as error:
            raise InspectorError("Invalid query locator", code="invalidParams") from error
        return self._request(
            method,
            {"locator": wire, "timeoutMs": self._timed_params(timeout_ms, deadline)},
            deadline,
        )

    def query_find(self, locator: Locator, *, timeout_ms: int, deadline: float) -> QueryFindResult:
        def parse(value: object) -> QueryFindResult:
            result = QueryFindResult.from_json(value)
            self._object_ref(result.match)
            return result

        return self._parse(parse, self._query("query.find", locator, timeout_ms, deadline))

    def query_find_all(
        self, locator: Locator, *, timeout_ms: int, deadline: float
    ) -> QueryFindAllResult:
        def parse(value: object) -> QueryFindAllResult:
            result = QueryFindAllResult.from_json(value)
            if len(result.matches) > locator.limit:
                raise ValueError("Too many matches")
            for match in result.matches:
                self._object_ref(match)
            return result

        return self._parse(parse, self._query("query.findAll", locator, timeout_ms, deadline))

    def wait_until(
        self, condition: WaitCondition, *, timeout_ms: int, deadline: float
    ) -> WaitResult:
        self._feature("waits")
        self._object_ref(condition.locator.scope.handle)
        try:
            wire = WaitCondition.from_json(condition.to_json()).to_json()
        except (ValueError, TypeError) as error:
            raise InspectorError("Invalid wait condition", code="invalidParams") from error

        def parse(value: object) -> WaitResult:
            result = WaitResult.from_json(value)
            self._object_ref(result.handle)
            if result.state is not None:
                self._object_ref(result.state.handle)
                if result.state.handle != result.handle:
                    raise ValueError("Mismatched state handle")
            return result

        return self._parse(
            parse,
            self._request(
                "wait.until",
                {"condition": wire, "timeoutMs": self._timed_params(timeout_ms, deadline)},
                deadline,
            ),
        )

    def hit_test(
        self,
        native_window_handle: int,
        x: float,
        y: float,
        *,
        timeout_ms: int,
        deadline: float,
        include_path: bool = False,
    ) -> HitTestResult | None:
        self._feature("hitTest")

        def parse(value: object) -> HitTestResult:
            data = _obj(value, "handle", "path")
            reference = ObjectRef.from_json(data["handle"])
            self._object_ref(reference)
            path = _array(data["path"], self._node, 256) if "path" in data else None
            if include_path != (path is not None):
                raise ValueError("Unexpected hit test path")
            return HitTestResult(reference, path)

        try:
            result = self._request(
                "hitTest",
                {
                    "nativeWindowHandle": native_window_handle,
                    "point": {"x": x, "y": y},
                    **({"includePath": True} if include_path else {}),
                    "timeoutMs": self._timed_params(timeout_ms, deadline),
                },
                deadline,
            )
        except InspectorError as error:
            if error.code == "notFound":
                return None
            raise
        return self._parse(parse, result)

    def state_get(self, handle: ObjectRef, *, timeout_ms: int, deadline: float) -> ElementState:
        self._feature("geometry")
        self._object_ref(handle)

        def parse(value: object) -> ElementState:
            state = ElementState.from_json(_obj(value, "state")["state"])
            self._object_ref(state.handle)
            if state.handle != handle:
                raise ValueError("Mismatched state handle")
            return state

        return self._parse(
            parse,
            self._request(
                "state.get",
                {"handle": handle.to_json(), "timeoutMs": self._timed_params(timeout_ms, deadline)},
                deadline,
            ),
        )

    def _act(
        self,
        method: str,
        ref: ObjectRef,
        params: dict[str, object],
        timeout_ms: int,
        deadline: float,
    ) -> ActResult:
        self._feature("actions")
        self._object_ref(ref)
        try:
            handle = ObjectRef.from_json(ref.to_json()).to_json()
        except (ValueError, TypeError, AttributeError) as error:
            raise InspectorError("Invalid action handle", code="invalidParams") from error

        def parse(value: object) -> ActResult:
            result = ActResult.from_json(value)
            self._object_ref(result.handle)
            if result.handle != ref:
                raise ValueError("Mismatched action handle")
            return result

        return self._parse(
            parse,
            self._request(
                method,
                {"handle": handle, **params, "timeoutMs": self._timed_params(timeout_ms, deadline)},
                deadline,
            ),
        )

    def _write(
        self,
        method: str,
        ref: ObjectRef,
        member_key: str,
        params: dict[str, object],
        timeout_ms: int,
        deadline: float,
    ) -> WriteAudit:
        self._feature("writes")
        try:
            self._object_ref(ref)
            handle = ObjectRef.from_json(ref.to_json()).to_json()
            member = _key(member_key)
        except (ValueError, TypeError, AttributeError) as error:
            raise InspectorError("Invalid write target", code="invalidParams") from error

        def parse(value: object) -> WriteAudit:
            audit = WriteAudit.from_json(_obj(value, "audit")["audit"])
            if audit.operation != method.removeprefix("write.") or audit.outcome != "performed":
                raise ValueError("Invalid write audit")
            return audit

        return self._parse(
            parse,
            self._request(
                method,
                {
                    "handle": handle,
                    "memberKey": member,
                    **params,
                    "timeoutMs": self._timed_params(timeout_ms, deadline),
                },
                deadline,
            ),
        )

    def write_set_property(
        self,
        ref: ObjectRef,
        member_key: str,
        value: object,
        *,
        timeout_ms: int,
        deadline: float,
    ) -> WriteAudit:
        try:
            scalar = _write_scalar(value)
        except (ValueError, TypeError, OverflowError) as error:
            raise InspectorError("Invalid write value", code="invalidParams") from error
        return self._write(
            "write.setProperty", ref, member_key, {"value": scalar}, timeout_ms, deadline
        )

    def write_call(
        self,
        ref: ObjectRef,
        member_key: str,
        arguments: Sequence[object],
        *,
        timeout_ms: int,
        deadline: float,
    ) -> WriteAudit:
        try:
            if not isinstance(arguments, (list, tuple)) or len(arguments) > 16:
                raise ValueError("Invalid arguments")
            values = [_write_scalar(value) for value in arguments]
        except (ValueError, TypeError, OverflowError) as error:
            raise InspectorError("Invalid write arguments", code="invalidParams") from error
        return self._write(
            "write.call", ref, member_key, {"arguments": values}, timeout_ms, deadline
        )

    def act_realize_item(
        self,
        container_ref: ObjectRef,
        match: ItemMatch,
        *,
        max_items: int,
        timeout_ms: int,
        deadline: float,
    ) -> RealizeResult:
        self._feature("virtualItems")
        self._object_ref(container_ref)
        try:
            container = ObjectRef.from_json(container_ref.to_json()).to_json()
            item_match = ItemMatch.from_json(match.to_json()).to_json()
            maximum = _int(max_items, 1, 10000)
        except (ValueError, TypeError, AttributeError) as error:
            raise InspectorError("Invalid item search", code="invalidParams") from error

        def parse(value: object) -> RealizeResult:
            result = RealizeResult.from_json(value)
            self._object_ref(result.handle)
            return result

        return self._parse(
            parse,
            self._request(
                "act.realizeItem",
                {
                    "search": {"container": container, "match": item_match, "maxItems": maximum},
                    "timeoutMs": self._timed_params(timeout_ms, deadline),
                },
                deadline,
            ),
        )

    def act_focus(self, ref: ObjectRef, *, timeout_ms: int, deadline: float) -> ActResult:
        return self._act("act.focus", ref, {}, timeout_ms, deadline)

    def act_bring_into_view(self, ref: ObjectRef, *, timeout_ms: int, deadline: float) -> ActResult:
        return self._act("act.bringIntoView", ref, {}, timeout_ms, deadline)

    def act_scroll_into_view(
        self, ref: ObjectRef, *, timeout_ms: int, deadline: float
    ) -> ActResult:
        return self._act("act.scrollIntoView", ref, {}, timeout_ms, deadline)

    def act_invoke(self, ref: ObjectRef, *, timeout_ms: int, deadline: float) -> ActResult:
        return self._act("act.invoke", ref, {}, timeout_ms, deadline)

    def act_toggle(self, ref: ObjectRef, *, timeout_ms: int, deadline: float) -> ActResult:
        return self._act("act.toggle", ref, {}, timeout_ms, deadline)

    def act_expand(self, ref: ObjectRef, *, timeout_ms: int, deadline: float) -> ActResult:
        return self._act("act.expand", ref, {}, timeout_ms, deadline)

    def act_collapse(self, ref: ObjectRef, *, timeout_ms: int, deadline: float) -> ActResult:
        return self._act("act.collapse", ref, {}, timeout_ms, deadline)

    def act_select(self, ref: ObjectRef, *, timeout_ms: int, deadline: float) -> ActResult:
        return self._act("act.select", ref, {}, timeout_ms, deadline)

    def act_set_value(
        self, ref: ObjectRef, value: str, *, timeout_ms: int, deadline: float
    ) -> ActResult:
        self._feature("actions")
        if (
            not isinstance(cast(object, value), str)
            or len(value) > 4096
            or any(0xD800 <= ord(character) <= 0xDFFF for character in value)
        ):
            raise InspectorError("Invalid action value", code="invalidParams")
        return self._act("act.setValue", ref, {"value": value}, timeout_ms, deadline)

    def act_set_range(
        self, ref: ObjectRef, value: float, *, timeout_ms: int, deadline: float
    ) -> ActResult:
        self._feature("actions")
        if isinstance(value, bool) or not isinstance(cast(object, value), (int, float)):
            raise InspectorError("Invalid range value", code="invalidParams")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise InspectorError("Invalid range value", code="invalidParams")
        return self._act("act.setRange", ref, {"value": value}, timeout_ms, deadline)

    def act_scroll(
        self, ref: ObjectRef, horizontal: str, vertical: str, *, timeout_ms: int, deadline: float
    ) -> ActResult:
        self._feature("actions")
        amounts = {"none", "smallIncrement", "smallDecrement", "largeIncrement", "largeDecrement"}
        if (
            not isinstance(cast(object, horizontal), str)
            or not isinstance(cast(object, vertical), str)
            or horizontal not in amounts
            or vertical not in amounts
        ):
            raise InspectorError("Invalid scroll amount", code="invalidParams")
        return self._act(
            "act.scroll",
            ref,
            {"horizontal": horizontal, "vertical": vertical},
            timeout_ms,
            deadline,
        )

    def read_batch(
        self,
        candidates: Sequence[tuple[tuple[int, ...], int | None]],
        paths: Sequence[ManagedPath],
        *,
        deadline: float,
    ) -> list[CandidateResult]:
        self._feature("exactUiaMapping", "batchReads")
        if not 1 <= len(candidates) <= 32 or not 1 <= len(paths) <= 32:
            raise InspectorLimitError(
                "Batch requires 1 to 32 candidates and paths", code="limitExceeded"
            )
        try:
            requests: list[dict[str, object]] = []
            expected_ids: list[tuple[int, ...]] = []
            for runtime_id, handle in candidates:
                runtime_id = _runtime_id(list(runtime_id))
                expected_ids.append(runtime_id)
                item: dict[str, object] = {"runtimeId": list(runtime_id)}
                if handle is not None:
                    item["nativeWindowHandle"] = _int(handle, -9_223_372_036_854_775_808)
                requests.append(item)
            expected_paths = tuple(parse_path(path.to_json()) for path in paths)
        except (ValueError, TypeError, UnicodeError) as error:
            raise InspectorError("Invalid batch input", code="invalidParams") from error
        self._path_features(expected_paths)

        def parse(value: object) -> list[CandidateResult]:
            data = _obj(value, "candidates")
            results = _array(data["candidates"], CandidateResult.from_json, 32, 1)
            if len(results) != len(expected_ids):
                raise ValueError("Incomplete batch")
            for expected, result in zip(expected_ids, results, strict=True):
                if (
                    result.runtime_id != expected
                    or result.mapping.runtime_id != expected
                    or result.mapping.process != self.session.process
                ):
                    raise ValueError("Mismatched batch identity")
                self._object_ref(result.mapping.object_ref)
                if (
                    result.mapping.status == "exact"
                    and tuple(item.path for item in result.values) != expected_paths
                ):
                    raise ValueError("Mismatched batch paths")
                for item in result.values:
                    self._value(item.value)
            return list(results)

        return self._parse(
            parse,
            self._request(
                "element.readBatch",
                {"candidates": requests, "paths": [path.to_json() for path in paths]},
                deadline,
            ),
        )

    def _page_params(self, page_size: int | None, page_token: str | None) -> dict[str, object]:
        params: dict[str, object] = {"sessionId": self.session.session_id}
        try:
            if page_size is not None:
                params["pageSize"] = _int(page_size, 1, 200)
            if page_token is not None:
                params["pageToken"] = _identifier(page_token)
        except ValueError as error:
            raise InspectorError("Invalid page parameters", code="invalidParams") from error
        return params

    def _object_params(self, object_id: str, generation: int) -> dict[str, object]:
        try:
            return {
                "sessionId": self.session.session_id,
                "objectId": _identifier(object_id),
                "generation": _int(generation, 1),
            }
        except ValueError as error:
            raise InspectorError("Invalid object identity", code="invalidParams") from error

    def _node(self, value: object) -> ManagedNode:
        node = ManagedNode.from_json(value)
        self._object_ref(node.object_ref)
        return node

    def roots(
        self, *, page_size: int | None = None, page_token: str | None = None, deadline: float
    ) -> Page[ManagedNode]:
        params = self._page_params(page_size, page_token)
        return self._parse(
            lambda value: Page[ManagedNode].from_json(value, self._node),
            self._request("roots", params, deadline),
        )

    def children(
        self,
        object_id: str,
        generation: int,
        tree: Literal["visual", "logical"],
        *,
        page_size: int | None = None,
        page_token: str | None = None,
        deadline: float,
    ) -> Page[ManagedNode]:
        if tree not in ("visual", "logical"):
            raise InspectorError("Invalid tree", code="invalidParams")
        params = self._page_params(page_size, page_token)
        params.update(self._object_params(object_id, generation))
        params["tree"] = tree
        return self._parse(
            lambda value: Page[ManagedNode].from_json(value, self._node),
            self._request("children", params, deadline),
        )

    def members(
        self,
        object_id: str,
        generation: int,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
        deadline: float,
    ) -> Page[Member]:
        self._feature("clrMembers")
        params = self._page_params(page_size, page_token)
        params.update(self._object_params(object_id, generation))
        return self._parse(
            lambda value: Page[Member].from_json(value, Member.from_json),
            self._request("members", params, deadline),
        )

    def read(
        self,
        object_id: str,
        generation: int,
        paths: Sequence[Sequence[PathSegment]],
        *,
        deadline: float,
    ) -> tuple[tuple[PathValue, ...], str]:
        if not 1 <= len(paths) <= 32:
            raise InspectorLimitError("Read requires 1 to 32 paths", code="limitExceeded")
        try:
            expected = tuple(parse_path([segment.to_json() for segment in path]) for path in paths)
        except (ValueError, TypeError, UnicodeError) as error:
            raise InspectorError("Invalid read paths", code="invalidParams") from error
        self._path_features(expected)
        params = self._object_params(object_id, generation)
        params["paths"] = [[segment.to_json() for segment in path] for path in expected]

        def parse(value: object) -> tuple[tuple[PathValue, ...], str]:
            data = _obj(value, "values readId")
            values = _array(data["values"], PathValue.from_json, 32)
            if tuple(item.path for item in values) != expected:
                raise ValueError("Mismatched read paths")
            for item in values:
                self._value(item.value)
            return values, _identifier(data["readId"])

        return self._parse(parse, self._request("read", params, deadline))

    def bindings(
        self, object_id: str, generation: int, member_keys: Sequence[str], *, deadline: float
    ) -> tuple[BindingInfo, ...]:
        self._feature("bindings")
        if len(member_keys) > 32:
            raise InspectorLimitError("At most 32 binding keys are allowed", code="limitExceeded")
        try:
            keys = [_key(key) for key in member_keys]
        except ValueError as error:
            raise InspectorError("Invalid binding key", code="invalidParams") from error
        params = self._object_params(object_id, generation)
        params["memberKeys"] = keys

        def parse(value: object) -> tuple[BindingInfo, ...]:
            data = _obj(value, "bindings")
            return _array(data["bindings"], BindingInfo.from_json, 32)

        return self._parse(parse, self._request("bindings", params, deadline))

    def release(self, object_ids: Sequence[str], *, deadline: float) -> int:
        if len(object_ids) > 256:
            raise InspectorLimitError("At most 256 object IDs are allowed", code="limitExceeded")
        try:
            ids = [_identifier(item) for item in object_ids]
        except ValueError as error:
            raise InspectorError("Invalid object ID", code="invalidParams") from error

        def parse(value: object) -> int:
            data = _obj(value, "releasedCount")
            return _int(data["releasedCount"], 0, min(256, len(ids)))

        return self._parse(
            parse,
            self._request(
                "release", {"sessionId": self.session.session_id, "objectIds": ids}, deadline
            ),
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closing_session = True
        try:
            result = self._request(
                "session.close", {}, time.monotonic() + min(self._request_timeout, 1.0)
            )
            data = _obj(result, "closed")
            if not _bool(data["closed"]):
                raise ValueError("Close was not acknowledged")
        except (InspectorError, ValueError):
            pass
        finally:
            self.invalidate(
                InspectorUnavailableError("Inspector session detached", code="notAttached"),
                "detached",
            )
            if threading.current_thread() is not self._reader:
                self._reader.join(timeout=2.0)
