"""Hand-outs are counted by the agent and owned by the references the client parsed.

The agent hands the same object ID out again while its lease is live and counts each hand-out; a
``release`` carries a count. These tests run the real client against a fake agent that behaves the
same way, including the interleavings of a multithreaded server.
"""

from __future__ import annotations

import gc
import threading
import time
from typing import Any

import pytest
from hand_out_agent import HandOutAgent, locator_json

import wintestkit.inspector.client as client_module
from wintestkit.backends.element import WpfElement
from wintestkit.errors import InspectorError
from wintestkit.inspector.client import InspectorClient
from wintestkit.inspector.handouts import object_refs, wire_refs
from wintestkit.inspector.models import Locator, ObjectRef

WATCHDOG = 5.0


def deadline() -> float:
    return time.monotonic() + 2


def locator(scope: ObjectRef) -> Locator:
    return Locator.from_json(locator_json(scope.object_id, scope.generation))


def resolve_window(client: InspectorClient) -> WpfElement:
    mapping = client.resolve((1, 2), None, deadline=deadline())
    assert mapping.object_ref is not None
    return WpfElement(client, mapping.object_ref, 42)


def find_page(client: InspectorClient, window: WpfElement) -> WpfElement:
    result = client.query_find(locator(window.ref), timeout_ms=1000, deadline=deadline())
    return WpfElement(client, result.match, 42)


@pytest.fixture
def agent() -> HandOutAgent:
    return HandOutAgent()


@pytest.fixture
def client(agent: HandOutAgent) -> Any:
    instance = agent.client(request_timeout=1.0)
    yield instance
    instance.close()


def settle(client: InspectorClient) -> None:
    """Collect dead references and send what they queued, as the next request would."""
    gc.collect()
    client.flush_releases()


# -- the live regression -----------------------------------------------------------------------


def test_alternating_scope_lookups_never_find_their_own_scope_released(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    """The window handle dies and is handed out again at once, 20 times over.

    Before hand-outs were counted, the release of the dead wrapper's ID ran right after the response
    that handed the same ID out again, so the next request on the new wrapper failed objectStale.
    """
    answers = iter(["app-page", "page"] * 10)
    agent.answer = lambda request: (
        "window" if request["method"] == "element.resolve" else next(answers)
    )
    for _ in range(20):
        window = resolve_window(client)
        page = find_page(client, window)  # findAll/find on the scope handle: stale if released
        assert page.state().enabled
        del window, page
    settle(client)
    assert agent.stale == []
    assert client.release_failures == 0 and client.over_releases == 0
    assert agent.over_released == 0


def test_five_consecutive_reads_of_one_element_all_succeed(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    agent.answer = lambda request: "window" if request["method"] == "element.resolve" else "page"
    held = resolve_window(client)
    for _ in range(5):
        again = resolve_window(client)  # the same ID, handed out again while `held` is alive
        assert again.ref.object_id == held.ref.object_id
        again._state = None
        assert again.state().enabled
        del again
        gc.collect()
        assert held.state().enabled  # the first wrapper is untouched by its siblings' release
    assert agent.stale == []
    del held
    settle(client)
    assert agent.outstanding("window") >= 0


def test_the_last_wrapper_releases_by_count_and_frees_the_lease(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    agent.answer = "window"
    first = resolve_window(client)
    second = resolve_window(client)
    assert first.ref.object_id == second.ref.object_id
    assert agent.outstanding("window") == 2
    del first
    settle(client)
    assert agent.outstanding("window") == 1  # one hand-out given back, the lease lives on
    assert second.state().enabled
    del second
    settle(client)
    assert agent.outstanding("window") == 0 and agent.live == {}
    assert agent.over_released == 0


def test_a_queued_release_is_taken_over_by_the_fresh_hand_out(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    agent.answer = "window"
    first = resolve_window(client)
    object_id = first.ref.object_id
    del first
    gc.collect()  # queued, not yet sent
    assert client.pending_releases == 1
    second = resolve_window(client)  # hands the ID out again: the release becomes unnecessary
    assert second.ref.object_id == object_id
    assert client.pending_releases == 0
    assert agent.releases == []
    assert agent.outstanding("window") == 2  # the agent still counts both
    del second
    settle(client)
    assert agent.releases == [[(object_id, 2)]]  # one release, for both hand-outs
    assert agent.live == {} and agent.over_released == 0


def test_hand_outs_in_one_response_are_each_counted_and_each_given_back(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    agent.answer = "window"
    window = resolve_window(client)
    assert window.state().enabled  # the state's own handle is a second hand-out of the window
    assert agent.outstanding("window") == 2
    assert client.hand_outs_owned == agent.handed_out == 2
    del window
    settle(client)  # the wrapper is gone, but the cached state still holds one hand-out
    assert agent.live == {} and agent.releases == [[("window:1", 2)]]


def test_the_client_owns_exactly_the_handles_the_agent_counted(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    agent.answer = lambda request: "window" if request["method"] == "element.resolve" else "page"
    window = resolve_window(client)
    page = find_page(client, window)
    page.state()
    window.state()
    found = client.query_find_all(locator(window.ref), timeout_ms=1000, deadline=deadline())
    assert len(found.matches) == 1
    assert client.hand_outs_owned == agent.handed_out
    assert len(list(object_refs(found))) == 1


def test_wire_refs_counts_the_shape_the_agent_counts() -> None:
    handle = {
        "sessionId": "s",
        "objectId": "o",
        "generation": 1,
        "type": {"name": "T"},
        "dispatcherId": "d",
    }
    assert (
        wire_refs({"matches": [handle, handle], "other": {"objectId": "x", "generation": 1}}) == 2
    )
    assert wire_refs({"state": {"handle": handle}, "x": [[handle]]}) == 2
    assert wire_refs({"objectId": "x"}) == 0


# -- over-release, closing, replaced sessions --------------------------------------------------


def test_an_over_release_is_reported_and_ends_nothing(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    agent.answer = "window"
    first = resolve_window(client)
    outcome = client.release([(first.ref.object_id, 5), ("window:9", 1)], deadline=deadline())
    assert (outcome.released, outcome.over_released) == (1, 2)
    assert client.over_releases == 2
    assert client.session.state == "ready"
    first.forget_release()


def test_references_of_a_closed_session_queue_nothing(agent: HandOutAgent) -> None:
    agent.answer = "window"
    client = agent.client(request_timeout=1.0)
    window = resolve_window(client)
    client.close()
    del window
    gc.collect()
    assert client.pending_releases == 0
    assert agent.releases == []


# -- interleavings of a multithreaded server ---------------------------------------------------


def test_a_flush_on_one_thread_cannot_end_a_lease_handed_out_again_on_another(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    """Worst interleaving: the agent counts a new hand-out, then gets the old release.

    Thread 1's request is answered after the agent counted the second hand-out of the window; thread
    2 flushes the release of the old wrapper in between, so the release reaches the agent after
    the hand-out but before thread 1 has even seen the answer. Without counts the agent ends the
    lease and thread 1's new wrapper is stale on arrival.
    """
    agent.answer = lambda request: "window" if request["method"] == "element.resolve" else "page"
    first = resolve_window(client)
    page = find_page(client, first)
    window_id = first.ref.object_id
    del first
    gc.collect()
    assert client.pending_releases == 1  # the window's ID is queued, not yet sent

    gate, counted = threading.Event(), threading.Event()
    agent.answer = "window"
    agent.hold_answers = gate
    agent.after_hand_out = lambda request: counted.set()
    found: dict[str, Any] = {}

    def hand_out_again() -> None:
        try:
            found["match"] = client.query_find(
                locator(page.ref), timeout_ms=1000, deadline=deadline()
            ).match
        except Exception as error:
            found["error"] = error

    worker = threading.Thread(target=hand_out_again, daemon=True)
    worker.start()
    assert counted.wait(WATCHDOG)  # the agent has counted the window a second time
    assert client.flush_releases() == 1  # thread 2: the old release reaches the agent now
    gate.set()  # and only now does thread 1 see its answer
    worker.join(WATCHDOG)
    assert not worker.is_alive() and "error" not in found, found
    assert found["match"].object_id == window_id  # the same ID, and its lease is still live
    wrapper = WpfElement(client, found.pop("match"), 42)
    assert wrapper.state().enabled
    assert agent.stale == []
    assert agent.releases == [[(window_id, 1)]]
    assert agent.outstanding("window") >= 1
    del wrapper
    settle(client)


def test_the_flush_in_a_request_that_follows_its_own_hand_out_is_harmless(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    """The ordering of the live bug, run in the client's own request path, many times over."""
    agent.answer = "window"
    for _ in range(50):
        window = resolve_window(client)
        assert window.state().enabled
        del window
    settle(client)
    assert agent.stale == [] and agent.over_released == 0


def test_hand_outs_and_flushes_race_across_threads_without_a_stale_handle(
    agent: HandOutAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Collections hold the GIL: give every release the full request time rather than racing a
    # starved reader thread, as the stress test of the queue does.
    monkeypatch.setattr(client_module, "_RELEASE_BATCH_TIMEOUT", 2.0)
    monkeypatch.setattr(client_module, "_RELEASE_FLUSH_BUDGET", 1000.0)
    agent.answer = lambda request: "window" if request["method"] == "element.resolve" else "page"
    client = agent.client(request_timeout=2.0)
    failures: list[BaseException] = []
    stop = threading.Event()

    def worker() -> None:
        try:
            for _ in range(100):
                window = resolve_window(client)
                page = find_page(client, window)
                assert page.state().enabled
                assert window.state().enabled
                del window, page
        except BaseException as error:
            failures.append(error)

    def flusher() -> None:
        try:
            while not stop.is_set():
                gc.collect(1)
                client.flush_releases()
                time.sleep(0.002)
        except BaseException as error:
            failures.append(error)

    workers = [threading.Thread(target=worker, daemon=True) for _ in range(3)]
    flushers = [threading.Thread(target=flusher, daemon=True) for _ in range(2)]
    try:
        for thread in (*workers, *flushers):
            thread.start()
        for thread in workers:
            thread.join(WATCHDOG * 4)
        stop.set()
        for thread in flushers:
            thread.join(WATCHDOG)
        assert not any(thread.is_alive() for thread in (*workers, *flushers))
        assert not failures, failures
        assert agent.stale == []
        assert agent.over_released == 0
        settle(client)
        settle(client)
        assert client.release_failures == 0
        assert agent.live == {}  # everything that was handed out has been given back
    finally:
        client.close()


def test_a_stale_handle_is_an_error_not_a_hang(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    agent.answer = "window"
    window = resolve_window(client)
    outcome = client.release([(window.ref.object_id, 1)], deadline=deadline())
    assert outcome.released == 1
    with pytest.raises(InspectorError) as error:
        window.state()
    assert error.value.code == "objectStale"
    window.forget_release()


# -- explicit release and reservations ---------------------------------------------------------


def test_release_refs_gives_each_references_hand_out_back_once(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    agent.answer = "window"
    first, second = resolve_window(client), resolve_window(client)
    assert agent.outstanding("window") == 2
    outcome = client.release_refs([first.ref, second.ref, first.ref], deadline=deadline())
    assert agent.releases == [[("window:1", 2)]]
    assert (outcome.released, outcome.over_released) == (1, 0)
    del first, second
    settle(client)
    assert len(agent.releases) == 1  # the references no longer own anything
    assert client.over_releases == 0


def test_a_failed_explicit_release_is_queued_again_not_lost(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    agent.answer = "window"
    window = resolve_window(client)
    original = agent.transport.handler

    def failing(request: dict[str, Any]) -> object | None:
        if request["method"] == "release":
            return {"id": request["id"], "error": {"code": "internalError", "message": "x"}}
        return original(request)

    agent.transport.handler = failing
    with pytest.raises(InspectorError):
        client.release_refs([window.ref], deadline=deadline())
    assert client.pending_releases == 1
    agent.transport.handler = original
    window.forget_release()  # the queued release is now the only claim on the hand-out
    assert client.flush_releases() == 1
    assert agent.live == {}


def test_a_reservation_nobody_takes_goes_back_to_the_queue(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    agent.answer = "window"
    first = resolve_window(client)
    del first
    gc.collect()
    assert client.pending_releases == 1
    raw = {"match": {**locator_json("window:1", 1)["scope"]["handle"]}}
    client._reserve(raw)  # pyright: ignore[reportPrivateUsage]
    assert client.pending_releases == 0  # set aside for the parser of this answer
    client.own_hand_outs(object())  # the parser found nothing to take it over
    assert client.pending_releases == 1  # so it is queued again, not lost
    assert client.flush_releases() == 1
    assert agent.live == {}


def test_a_parse_that_takes_a_reservation_owns_both_hand_outs(
    agent: HandOutAgent, client: InspectorClient
) -> None:
    agent.answer = "window"
    first = resolve_window(client)
    del first
    gc.collect()
    second = resolve_window(
        client
    )  # the answer re-hands the ID out: the queued release is taken over
    assert client.pending_releases == 0 and agent.releases == []
    window_id = second.ref.object_id
    del second
    settle(client)
    assert agent.releases == [[(window_id, 2)]] and agent.live == {}
