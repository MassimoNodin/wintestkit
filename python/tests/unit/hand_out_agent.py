"""A fake inspector agent that counts hand-outs the way the real one does.

The real agent hands out the same object ID again while that object's lease is live, counts every
handle it sends, ends a lease only when the count returns to zero, and answers ``objectStale`` for
an ID whose lease has ended. Releases are applied in the order they reach it, however they
interleave with the requests that hand the ID out.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from test_inspector_client import IDENTITY, ScriptedTransport, session

from wintestkit.inspector.client import InspectorClient

_FIXTURES = Path(__file__).resolve().parents[3] / "wpf-inspector/protocol/fixtures/valid"
_STATE = json.loads((_FIXTURES / "p2-state-runtime-id.json").read_text(encoding="utf-8"))[
    "instance"
]
_PROCESS = IDENTITY.to_json()
_TYPE = {
    "name": "T",
    "fullName": "Example.T",
    "assemblyName": "A",
    "assemblyQualifiedName": "Example.T, A",
    "baseTypes": [],
}


def locator_json(scope_id: str, generation: int) -> dict[str, Any]:
    scope = handle_json("session", scope_id, generation)
    return {
        "scope": {"kind": "object", "handle": scope},
        "tree": "combined",
        "predicates": [],
        "depth": 256,
        "limit": 200,
        "depthMode": "tree",
    }


def handle_json(session_id: str, object_id: str, generation: int) -> dict[str, Any]:
    return {
        "sessionId": session_id,
        "objectId": object_id,
        "generation": generation,
        "type": dict(_TYPE),
        "dispatcherId": "dispatcher",
    }


class HandOutAgent:
    """Objects are named; their IDs are minted per lease (``name:1``, then ``name:2`` ...)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.counts: dict[str, int] = {}
        self.minted: dict[str, int] = {}
        self.live: dict[str, str] = {}
        self.handed_out = 0
        self.releases: list[list[tuple[str, int]]] = []
        self.over_released = 0
        self.stale: list[tuple[str, str]] = []
        #: Which object a query or a resolve answers with: a name, or a callable of the request.
        self.answer: str | Callable[[dict[str, Any]], str] = "page"
        #: Called, with the lock held, after a request handed an ID out and before it answers.
        self.after_hand_out: Callable[[dict[str, Any]], None] | None = None
        #: When set, query answers are held back until this is released (the counts are not).
        self.hold_answers: threading.Event | None = None
        self.transport = ScriptedTransport(self.handle)
        self.transport.answer_release = False

    # -- helpers ---------------------------------------------------------------------------------

    def hand_out(self, name: str) -> dict[str, Any]:
        """Count one hand-out of the object and return its handle (the same ID while it is live)."""
        object_id = self.live.get(name)
        if object_id is None:
            self.minted[name] = self.minted.get(name, 0) + 1
            object_id = f"{name}:{self.minted[name]}"
            self.live[name] = object_id
        self.counts[object_id] = self.counts.get(object_id, 0) + 1
        self.handed_out += 1
        return handle_json("session", object_id, self.minted[name])

    def outstanding(self, name: str) -> int:
        object_id = self.live.get(name)
        return self.counts.get(object_id or "", 0)

    def is_live(self, object_id: str) -> bool:
        return self.counts.get(object_id, 0) > 0

    def _name_of(self, object_id: str) -> str:
        return object_id.rpartition(":")[0]

    def _stale(self, request: dict[str, Any], object_id: str) -> dict[str, Any]:
        self.stale.append((request["method"], object_id))
        return {
            "id": request["id"],
            "error": {"code": "objectStale", "message": "Request failed."},
        }

    def _target(self, request: dict[str, Any]) -> str:
        return self.answer(request) if callable(self.answer) else self.answer

    def client(self, **kwargs: Any) -> InspectorClient:
        return InspectorClient(self.transport, session(), **kwargs)

    # -- protocol --------------------------------------------------------------------------------

    def handle(self, request: dict[str, Any]) -> object | None:
        method, params = request["method"], request["params"]
        with self.lock:
            if method == "release":
                return self._release(request, params)
            if method == "session.close":
                return {"id": request["id"], "result": {"closed": True}}
            if method == "request.cancel":
                return {"id": request["id"], "result": {"accepted": True}}
            if method == "element.resolve":
                handle = self.hand_out(self._target(request))
                result: dict[str, Any] = {
                    "status": "exact",
                    "process": _PROCESS,
                    "runtimeId": params["runtimeId"],
                    "object": handle,
                }
            elif method in ("query.find", "query.findAll"):
                scope = params["locator"]["scope"]["handle"]
                if not self.is_live(scope["objectId"]):
                    return self._stale(request, scope["objectId"])
                handle = self.hand_out(self._target(request))
                result = (
                    {"match": handle}
                    if method == "query.find"
                    else {"matches": [handle], "complete": True}
                )
            elif method == "state.get":
                object_id = params["handle"]["objectId"]
                if not self.is_live(object_id):
                    return self._stale(request, object_id)
                state = dict(_STATE)
                state["handle"] = self.hand_out(self._name_of(object_id))
                result = {"state": state}
            else:
                raise AssertionError(f"unexpected request {method}")
            if self.after_hand_out is not None:
                self.after_hand_out(request)
            response = {"id": request["id"], "result": result}
        gate = self.hold_answers
        if gate is not None and method.startswith("query."):
            threading.Thread(target=self._answer_later, args=(gate, response), daemon=True).start()
            return None
        return response

    def _answer_later(self, gate: threading.Event, response: dict[str, Any]) -> None:
        gate.wait(5.0)
        self.transport.feed(response)

    def _release(self, request: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        batch = [(item["objectId"], item["count"]) for item in params["objects"]]
        self.releases.append(batch)
        freed = over = 0
        for object_id, count in batch:
            outstanding = self.counts.get(object_id, 0)
            if count > outstanding:
                over += 1
            if outstanding == 0:
                continue
            remaining = outstanding - min(count, outstanding)
            if remaining:
                self.counts[object_id] = remaining
                continue
            del self.counts[object_id]
            self.live.pop(self._name_of(object_id), None)
            freed += 1
        self.over_released += over
        return {"id": request["id"], "result": {"releasedCount": freed, "overReleasedCount": over}}
