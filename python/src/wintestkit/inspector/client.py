"""Authenticated inspector requests, deadlines, and session-scoped DTOs."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any, Literal

from wintestkit.errors import InspectorError, InspectorLimitError, InspectorUnavailableError
from wintestkit.inspector.models import (
    ERROR_CODES,
    BindingInfo,
    CandidateResult,
    HelloResult,
    ManagedNode,
    Mapping,
    Member,
    ObjectRef,
    Page,
    PathValue,
    ProcessFacts,
    Session,
    Value,
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
from wintestkit.inspector.paths import ManagedPath, PathSegment
from wintestkit.inspector.transport import ByteTransport, read_frame, write_frame


def _error(code: str) -> InspectorError:
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


def _response(value: object) -> tuple[int, object, str | None]:
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
    return request_id, None, code


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
                        "protocolMajor": 1,
                        "protocolMinor": 0,
                        "sessionId": session_id,
                        "token": token,
                        "process": facts.identity.to_json(),
                    },
                },
                deadline,
            )
            response_id, result, code = _response(read_frame(transport, deadline))
            if response_id != 1:
                raise ValueError("Mismatched hello response ID")
            if code is not None:
                raise _error(code)
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
                1,
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
                request_id, result, code = _response(
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
                    pending.error = _error(code) if code is not None else None
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
            raise InspectorError("Inspector request deadline expired", code="timeout")
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
            try:
                write_frame(
                    self._transport,
                    {"id": request_id, "method": method, "params": params},
                    deadline,
                )
            except (ValueError, TimeoutError, EOFError, OSError, UnicodeError) as error:
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
        deadline = min(deadline, time.monotonic() + self._request_timeout)
        entry = self._send(method, params, deadline)
        if not entry.event.wait(max(0, deadline - time.monotonic())):
            request_id = entry.request_id
            with self._lock:
                if self._pending.pop(request_id, None) is not None:
                    self._abandoned.add(request_id)
                    threading.Thread(target=self._cancel, args=(request_id,), daemon=True).start()
                    raise InspectorError("Inspector request deadline expired", code="timeout")
        if entry.error is not None:
            raise entry.error
        return entry.result

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
