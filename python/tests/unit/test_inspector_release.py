"""Lease releases must never do I/O or take locks from a finalizer.

A finalizer runs at any allocation on any thread: on the pipe reader thread (where a request can
never be answered) or inside a request that holds the client's locks (where it would stall). The
client therefore queues object IDs and sends them in batches from an ordinary caller's thread.
"""

from __future__ import annotations

import gc
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from test_inspector_client import ScriptedTransport, page, session

import wintestkit.inspector.client as client_module
from wintestkit.backends.element import WpfElement
from wintestkit.errors import InspectorDeadlineError
from wintestkit.inspector.client import MAX_RELEASE_BATCH, InspectorClient, InspectorThreadError
from wintestkit.inspector.models import ObjectRef, TypeInfo

WATCHDOG = 5.0


def ref(object_id: str, session_id: str = "session") -> ObjectRef:
    return ObjectRef(session_id, object_id, 1, TypeInfo("T", "T", "A", "T, A", ()), "dispatcher")


class Agent:
    """A fake agent that answers everything promptly and records releases."""

    def __init__(self, *, release_reply: bool = True) -> None:
        self.batches: list[list[str]] = []
        self.release_threads: list[threading.Thread] = []
        self.release_reply = release_reply
        self.closed = False
        self.transport = ScriptedTransport(self.handle)

    @property
    def released(self) -> list[str]:
        return [item for batch in list(self.batches) for item in batch]

    def handle(self, request: dict[str, Any]) -> object | None:
        method = request["method"]
        if method == "release":
            ids = request["params"]["objectIds"]
            self.batches.append(list(ids))
            self.release_threads.append(threading.current_thread())
            if not self.release_reply:
                return None
            return {"id": request["id"], "result": {"releasedCount": len(ids)}}
        if method == "session.close":
            self.closed = True
            return {"id": request["id"], "result": {"closed": True}}
        if method == "roots":
            return {"id": request["id"], "result": page()}
        if method == "request.cancel":
            return {"id": request["id"], "result": {"accepted": True}}
        return None

    def requests(self, method: str) -> list[dict[str, Any]]:
        return [item for item in list(self.transport.requests) if item["method"] == method]


@pytest.fixture
def agent() -> Agent:
    return Agent()


@pytest.fixture
def client(agent: Agent) -> Any:
    instance = InspectorClient(agent.transport, session(), request_timeout=1.0)
    yield instance
    instance.close()


@pytest.fixture
def unlimited_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the flush time budget so a slow machine cannot change the batch count."""
    monkeypatch.setattr(client_module, "_RELEASE_FLUSH_BUDGET", 1000.0)


def run_on_reader(monkeypatch: pytest.MonkeyPatch, action: Any) -> list[object]:
    """Run ``action`` once on the client's reader thread, as a finalizer might."""
    outcomes: list[object] = []
    original = client_module._response

    def wrapped(value: object) -> Any:
        if not outcomes:
            outcomes.append(None)
            try:
                outcomes[0] = action()
            except BaseException as error:
                outcomes[0] = error
        return original(value)

    monkeypatch.setattr(client_module, "_response", wrapped)
    return outcomes


def test_finalizer_on_the_reader_thread_neither_blocks_nor_ends_the_session(
    agent: Agent, client: InspectorClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder = [WpfElement(client, ref("a"), 1), WpfElement(client, ref("b"), 1)]
    seen: dict[str, object] = {}

    def drop_on_reader() -> None:
        seen["on_reader"] = threading.current_thread() is client._reader
        before = len(agent.transport.requests)
        holder.clear()  # the last references die here, so the finalizers run on this thread
        seen["requests_sent"] = len(agent.transport.requests) - before
        seen["queued"] = client.pending_releases

    outcomes = run_on_reader(monkeypatch, drop_on_reader)

    assert client.roots(deadline=time.monotonic() + 1).complete
    assert outcomes == [None]
    assert seen == {"on_reader": True, "requests_sent": 0, "queued": 2}
    # The ids went out in one batch, from the caller's thread after its own request finished.
    assert [sorted(batch) for batch in agent.batches] == [["a", "b"]]
    assert agent.release_threads == [threading.current_thread()]
    assert client.session.state == "ready"
    assert (client.releases_sent, client.release_failures) == (2, 0)
    assert client.roots(deadline=time.monotonic() + 1).complete


def test_finalizer_while_a_request_holds_the_client_locks_does_not_block(
    agent: Agent, client: InspectorClient
) -> None:
    holder = [WpfElement(client, ref("a"), 1), WpfElement(client, ref("b"), 1)]
    answer = threading.Event()
    original_handle = agent.handle

    def slow(request: dict[str, Any]) -> object | None:
        if request["method"] == "roots":
            answer.wait(WATCHDOG)
        return original_handle(request)

    agent.transport.handler = slow
    with ThreadPoolExecutor(max_workers=2) as pool:
        inflight = pool.submit(client.roots, deadline=time.monotonic() + 1)
        # The request is blocked inside the fake transport's write, holding the write lock. Also
        # hold the state lock, as a request does while it records its ID.
        deadline = time.monotonic() + WATCHDOG
        while not agent.requests("roots") and time.monotonic() < deadline:
            time.sleep(0.001)
        assert agent.requests("roots")
        with client._lock:
            finalizer = pool.submit(holder.clear)
            finalizer.result(timeout=WATCHDOG)  # would hang if it tried to send or lock
            assert client.pending_releases == 2
            assert not agent.requests("release")
        answer.set()
        assert inflight.result(timeout=WATCHDOG).complete
    assert [sorted(batch) for batch in agent.batches] == [["a", "b"]]
    assert client.session.state == "ready"


def test_finalizer_inside_the_callers_own_request_is_safe(
    agent: Agent, client: InspectorClient
) -> None:
    """The same thread, holding the write lock: a re-entrant request would time out."""
    holder = [WpfElement(client, ref("a"), 1)]
    original_handle = agent.handle

    def drop_during_write(request: dict[str, Any]) -> object | None:
        if request["method"] == "roots":
            holder.clear()  # runs inside write_frame, with the write lock held
        return original_handle(request)

    agent.transport.handler = drop_during_write
    started = time.monotonic()
    assert client.roots(deadline=time.monotonic() + 1).complete
    assert agent.batches == [["a"]]
    assert client.release_failures == 0
    assert time.monotonic() - started < 0.2  # a re-entrant release would wait 0.25 s


def test_late_response_after_a_timeout_is_discarded_and_the_session_stays_usable(
    agent: Agent,
) -> None:
    held = {"on": True}
    original_handle = agent.handle

    def silent_roots(request: dict[str, Any]) -> object | None:
        if request["method"] == "roots" and held["on"]:
            return None
        return original_handle(request)

    agent.transport.handler = silent_roots
    client = InspectorClient(agent.transport, session(), request_timeout=0.2)
    try:
        with pytest.raises(InspectorDeadlineError):
            client.roots(deadline=time.monotonic() + 1)
        first = agent.requests("roots")[0]["id"]
        held["on"] = False
        agent.transport.feed({"id": first, "result": page()})  # the late answer
        assert client.roots(deadline=time.monotonic() + 1).complete
        assert client.session.state == "ready"
        deadline = time.monotonic() + WATCHDOG
        while client._abandoned and time.monotonic() < deadline:
            time.sleep(0.005)  # the cancel request's own answer is discarded too
        assert not client._abandoned
    finally:
        client.close()


def test_late_response_for_an_evicted_abandoned_id_is_still_discarded(
    agent: Agent, client: InspectorClient
) -> None:
    with client._lock:
        for request_id in range(2, 400):
            client._abandon(request_id)
    assert len(client._abandoned) == 256
    agent.transport.feed({"id": 5, "result": page()})  # evicted from the set, but issued earlier
    agent.transport.feed({"id": 399, "result": page()})  # still remembered
    assert client.roots(deadline=time.monotonic() + 1).complete
    assert client.session.state == "ready"


def test_a_response_with_an_id_never_issued_still_faults_the_session(
    agent: Agent, client: InspectorClient
) -> None:
    agent.transport.feed({"id": 9_999, "result": page()})
    deadline = time.monotonic() + WATCHDOG
    while client.session.state == "ready" and time.monotonic() < deadline:
        time.sleep(0.005)
    assert client.session.state == "faulted"


def test_a_request_on_the_reader_thread_is_rejected_at_once(
    agent: Agent, client: InspectorClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def request_on_reader() -> None:
        before = len(agent.transport.requests)
        started = time.monotonic()
        try:
            client.release(["x"], deadline=time.monotonic() + 1)
        except InspectorThreadError as error:
            seen["error"] = str(error)
        seen["flushed"] = client.flush_releases()
        seen["sent"] = len(agent.transport.requests) - before
        seen["seconds"] = time.monotonic() - started

    outcomes = run_on_reader(monkeypatch, request_on_reader)
    client.defer_release("queued")
    assert client.roots(deadline=time.monotonic() + 1).complete
    assert outcomes == [None]
    assert "reader thread" in str(seen["error"])
    assert seen["flushed"] == 0 and seen["sent"] == 0
    assert isinstance(seen["seconds"], float) and seen["seconds"] < 0.2
    assert client.session.state == "ready"
    assert agent.released == ["queued"]  # sent later, by the caller's thread


def test_more_than_a_batch_is_flushed_as_several_requests(
    agent: Agent, client: InspectorClient, unlimited_flush: None
) -> None:
    ids = [f"o{index}" for index in range(2 * MAX_RELEASE_BATCH + 88)]
    client.defer_release(ids[0])  # a duplicate in the same batch is sent once
    for object_id in ids:
        client.defer_release(object_id)
    assert client.flush_releases() == len(ids)
    assert [len(batch) for batch in agent.batches] == [256, 256, 88]
    assert agent.released == ids
    assert client.pending_releases == 0
    assert client.session.state == "ready"


def test_flush_runs_after_an_ordinary_request(
    agent: Agent, client: InspectorClient, unlimited_flush: None
) -> None:
    for index in range(300):
        client.defer_release(f"o{index}")
    assert client.roots(deadline=time.monotonic() + 1).complete
    assert [len(batch) for batch in agent.batches] == [256, 44]
    methods = [item["method"] for item in agent.transport.requests]
    assert methods == ["roots", "release", "release"]


def test_a_failed_release_is_counted_and_never_ends_the_session(
    agent: Agent, client: InspectorClient
) -> None:
    original_handle = agent.handle

    def failing(request: dict[str, Any]) -> object | None:
        if request["method"] == "release":
            agent.batches.append(list(request["params"]["objectIds"]))
            return {"id": request["id"], "error": {"code": "objectStale", "message": "gone"}}
        return original_handle(request)

    agent.transport.handler = failing
    client.defer_release("a")
    assert client.roots(deadline=time.monotonic() + 1).complete
    assert (client.releases_sent, client.release_failures) == (0, 1)
    assert client.session.state == "ready"
    assert client.pending_releases == 0
    # Flushing pauses briefly after a failure, so a struggling target is left alone.
    client.defer_release("b")
    assert client.roots(deadline=time.monotonic() + 1).complete
    assert agent.batches == [["a"]]
    assert client.pending_releases == 1


def test_a_timed_out_release_is_swallowed_and_its_late_answer_discarded() -> None:
    agent = Agent(release_reply=False)
    client = InspectorClient(agent.transport, session(), request_timeout=0.3)
    try:
        client.defer_release("a")
        assert client.roots(deadline=time.monotonic() + 1).complete
        assert client.release_failures == 1
        release_id = agent.requests("release")[0]["id"]
        agent.transport.feed({"id": release_id, "result": {"releasedCount": 1}})
        assert client.roots(deadline=time.monotonic() + 1).complete
        assert client.session.state == "ready"
    finally:
        client.close()


def test_close_drops_pending_releases_and_later_ones(agent: Agent) -> None:
    client = InspectorClient(agent.transport, session(), request_timeout=1.0)
    element = WpfElement(client, ref("a"), 1)
    client.defer_release("b")
    client.close()
    assert not agent.requests("release")
    assert client.pending_releases == 0 and client.releases_dropped == 1
    del element  # the lease of a closed session
    gc.collect()
    client.defer_release("c")
    assert client.pending_releases == 0
    assert not agent.requests("release")
    assert client.flush_releases() == 0


def test_leases_of_a_replaced_session_do_not_reach_the_new_one() -> None:
    old_agent, new_agent = Agent(), Agent()
    old = InspectorClient(old_agent.transport, session(), request_timeout=1.0)
    new = InspectorClient(new_agent.transport, session(), request_timeout=1.0)
    try:
        element = WpfElement(old, ref("a"), 1)
        old.close()
        del element
        gc.collect()
        assert new.roots(deadline=time.monotonic() + 1).complete
        assert not new_agent.requests("release") and not old_agent.requests("release")
    finally:
        new.close()


def test_wrapper_release_and_collection_only_queue(agent: Agent, client: InspectorClient) -> None:
    first, shared = WpfElement(client, ref("a"), 1), WpfElement(client, ref("b"), 1)
    first.release()
    assert client.pending_releases == 1 and not agent.transport.requests
    clone = shared.as_live()
    del shared
    assert client.pending_releases == 1  # the clone still holds the lease
    clone.forget_release()
    del clone
    gc.collect()
    assert client.pending_releases == 1 and not agent.transport.requests


def test_a_busy_lock_in_trace_output_cannot_stall_a_request(
    agent: Agent, client: InspectorClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("WTK_INSPECTOR_TRACE", str(tmp_path / "trace.csv"))
    monkeypatch.setattr(client_module, "_TRACE_LOCK_WAIT", 0.01)
    with client_module._trace_lock:  # held by someone else, e.g. a thread stuck in file I/O
        worker = threading.Thread(
            target=lambda: client.roots(deadline=time.monotonic() + 1), daemon=True
        )
        worker.start()
        worker.join(WATCHDOG)
        assert not worker.is_alive()


def test_stress_wrappers_created_and_dropped_across_threads_while_requests_run(
    agent: Agent, unlimited_flush: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Collections hold the GIL, so give each request the full two seconds rather than racing a
    # starved reader thread; the bound that matters is the overall one below.
    monkeypatch.setattr(client_module, "_RELEASE_BATCH_TIMEOUT", 2.0)
    client = InspectorClient(agent.transport, session(), request_timeout=2.0)
    try:
        stress(agent, client)
    finally:
        client.close()


def stress(agent: Agent, client: InspectorClient) -> None:
    threads, per_thread = 4, 1500
    expected = {f"t{thread}-{index}" for thread in range(threads) for index in range(per_thread)}
    stop = threading.Event()
    failures: list[BaseException] = []

    def churn(thread: int) -> None:
        try:
            for index in range(per_thread):
                element = WpfElement(client, ref(f"t{thread}-{index}"), 1)
                if index % 3 == 0:
                    element.as_live()  # a second wrapper sharing the lease
                cycle: list[Any] = [element]
                cycle.append(
                    cycle
                )  # only the cycle collector frees it, on whichever thread runs it
                del element, cycle
                if index % 97 == 0:
                    gc.collect(1)
        except BaseException as error:
            failures.append(error)

    def requests() -> None:
        try:
            while not stop.is_set():
                client.roots(deadline=time.monotonic() + 2)
                gc.collect(1)
        except BaseException as error:
            failures.append(error)

    started = time.monotonic()
    requesters = [threading.Thread(target=requests, daemon=True) for _ in range(2)]
    workers = [
        threading.Thread(target=churn, args=(index,), daemon=True) for index in range(threads)
    ]
    for item in (*requesters, *workers):
        item.start()
    for item in workers:
        item.join(WATCHDOG * 4)
    stop.set()
    for item in requesters:
        item.join(WATCHDOG)
    gc.collect()
    for _ in range(50):
        if not client.pending_releases:
            break
        client.flush_releases()
    elapsed = time.monotonic() - started

    assert not any(item.is_alive() for item in (*requesters, *workers))
    assert not failures
    assert elapsed < 20
    assert client.session.state == "ready"
    assert client.release_failures == 0
    assert all(len(batch) <= MAX_RELEASE_BATCH for batch in agent.batches)
    released = agent.released
    assert len(released) == len(set(released))  # nothing released twice
    assert set(released) == expected
