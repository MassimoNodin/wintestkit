"""Live Detach then Attach, the sequence behind the Properties sidebar's actions menu.

The host's detach sends `inspect.managed.detach` with the session id only. The selected tree node keeps its
id, so the next Attach identifies that same node again, attaches the process and resolves the node. Every
round must attach, return members and leave neither a leaked session nor an agent that cannot be attached.
"""

import os
from typing import Any

import pytest
from test_spy_properties_real import (
    CAPABILITY,
    InProcess,
    Rpc,
    Stdio,
    find,
    pages,
    result,
)

from wintestkit import runtime

pytest_plugins = ("test_wpf_query_gate_real",)
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
        reason="requires owned Windows fixture",
    ),
]

ROUNDS = 3


def attach(rpc: Rpc, node: dict[str, Any]) -> dict[str, Any]:
    """ManagedInspector.attach: identify the selected node, then attach its process."""
    facts = result(rpc, "inspect.managed.identify", {"nodeId": node["nodeId"]})
    assert facts["executable"], facts
    session = result(
        rpc, "inspect.managed.attach", {"process": facts["process"], "hostCapability": CAPABILITY}
    )
    assert session["state"] == "ready", session
    return session


def members_of(rpc: Rpc, session: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    mapping = result(
        rpc, "inspect.managed.resolve", {"sessionId": session["sessionId"], "nodeId": node_id}
    )
    assert mapping["status"] == "exact", mapping
    ref = mapping["object"]
    items = pages(
        rpc,
        "inspect.managed.members",
        {
            "sessionId": session["sessionId"],
            "objectId": ref["objectId"],
            "generation": ref["generation"],
        },
    )
    assert items
    return items


def registry_size() -> int:
    return len(runtime.inspector_sessions()._entries)  # type: ignore[attr-defined]


def check_detach_attach(rpc: Rpc, pid: int, *, count_sessions: bool) -> None:
    roots = result(rpc, "inspect.roots", {})
    window = next(node for node in roots if node["info"]["processId"] == pid)
    first = result(rpc, "inspect.children", {"nodeId": window["nodeId"], "tree": "visual"})
    assert first.get("attachRequired") is True
    session = attach(rpc, window)
    selected = find(rpc, window, {"ScrollViewer"})["ScrollViewer"]
    assert members_of(rpc, session, selected["nodeId"])
    sizes = [registry_size()] if count_sessions else []
    seen = {session["sessionId"]}
    for _ in range(ROUNDS):
        detached = result(rpc, "inspect.managed.detach", {"sessionId": session["sessionId"]})
        assert detached == {"detached": True}
        # The selected node belongs to the closed session: identify must still name its process,
        # and the next attach must open a new session.
        session = attach(rpc, selected)
        assert session["sessionId"] not in seen, "attach reused a closed session"
        seen.add(session["sessionId"])
        # The old node is a handle of the closed session: stale, never "not ready", and never mapped by the new one.
        stale = rpc.call(
            "inspect.managed.resolve",
            {"sessionId": session["sessionId"], "nodeId": selected["nodeId"]},
        )
        assert stale["error"]["data"]["code"] == "objectStale", stale
        # A fresh tree walk gives the same object a new node.
        roots = result(rpc, "inspect.roots", {})
        window = next(node for node in roots if node["info"]["processId"] == pid)
        selected = find(rpc, window, {"ScrollViewer"})["ScrollViewer"]
        assert members_of(rpc, session, selected["nodeId"])
        if count_sessions:
            sizes.append(registry_size())
    if count_sessions:
        assert len(set(sizes)) == 1, f"the session registry grew: {sizes}"
    result(rpc, "inspect.managed.detach", {"sessionId": session["sessionId"]})


def test_detach_then_attach_in_process(owned: Any) -> None:
    scope, path = owned
    check_detach_attach(
        InProcess(path, scope.app), scope.app.main_window().process_id, count_sessions=True
    )


def test_detach_then_attach_over_stdio(owned: Any) -> None:
    scope, path = owned
    server = Stdio(path)
    try:
        check_detach_attach(server, scope.app.main_window().process_id, count_sessions=False)
    finally:
        server.close()
