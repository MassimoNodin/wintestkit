"""Tests for event-assisted polling wakeups."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import cast

import pytest

from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector.client import EventSubscription, InspectorClient
from wintestkit.inspector.event_waiter import EventWaiter
from wintestkit.inspector.models import EventsEventParams


class FakeClient:
    def __init__(self, *, events: bool = True) -> None:
        self.session = SimpleNamespace(features=("events",) if events else ())
        self.subscription = EventSubscription("sub")
        self.subscribed = threading.Event()
        self.subscribe_count = 0
        self.unsubscribe_count = 0
        self.fail_subscribe = False

    def subscribe(self, kinds: tuple[str, ...], *, deadline: float) -> EventSubscription:
        assert kinds == ("treeChanged",)
        assert deadline > time.monotonic()
        self.subscribe_count += 1
        if self.fail_subscribe:
            raise InspectorUnavailableError("closed", code="sessionStale")
        self.subscribed.set()
        return self.subscription

    def unsubscribe(self, subscription_id: str, *, deadline: float) -> bool:
        assert subscription_id == "sub"
        assert deadline > time.monotonic()
        self.unsubscribe_count += 1
        self.subscription.closed.set()
        return True

    def emit(self, sequence: int, kind: str = "treeChanged") -> None:
        self.subscription.receive(EventsEventParams("sub", sequence, kind))


def waiter(client: FakeClient) -> EventWaiter:
    return EventWaiter(cast(InspectorClient, client), {"treeChanged"})


@pytest.mark.parametrize("result", ["event", "rescan", "timeout"])
def test_poll_rechecks_after_wakeup(result: str) -> None:
    from wintestkit.engine import waits

    calls = []

    def poll() -> str | None:
        calls.append(1)
        waits.set_waker(lambda remaining: result)
        return "found" if len(calls) == 2 else None

    assert waits.wait_until(poll, 1, description="item") == "found"
    assert len(calls) == 2


def test_poll_preserves_fake_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    from wintestkit.engine import waits

    now = [0.0]
    monkeypatch.setattr(waits, "_clock", lambda: now[0])
    monkeypatch.setattr(waits, "_sleep", lambda delay: now.__setitem__(0, now[0] + delay))

    def poll() -> str | None:
        waits.set_waker(lambda remaining: pytest.fail("unexpected waiter"))
        return "found" if now[0] >= 0.1 else None

    assert waits.wait_until(poll, 1, description="item") == "found"
    assert now[0] == 0.1


def test_registry_owns_one_waiter_and_closes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from wintestkit.inspector import sessions
    from wintestkit.inspector.models import ProcessIdentity, Session

    identity = ProcessIdentity(42, "2025-01-01T00:00:00Z")
    session = Session("session", identity, "ready", 2, 0, ("events",))
    client = SimpleNamespace(session=session, close=lambda: None)
    registry = sessions.SessionRegistry()
    registry._entries[identity] = sessions._Entry(session, client=client)
    closed = []

    class FakeWaiter:
        def __init__(self, client: object, kinds: set[str]) -> None:
            assert kinds == {"windowOpened", "windowClosed", "treeChanged"}

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(sessions, "EventWaiter", FakeWaiter)
    first = registry.event_waiter(client)
    assert first is not None and registry.event_waiter(client) is first
    registry.remove(identity)
    assert closed == [True]


def test_registry_skips_clients_without_events() -> None:
    from wintestkit.inspector.sessions import SessionRegistry

    client = SimpleNamespace(session=SimpleNamespace(features=()))
    assert SessionRegistry().event_waiter(client) is None


def test_event_wakes_before_fallback() -> None:
    client = FakeClient()
    with waiter(client) as event_waiter, ThreadPoolExecutor() as executor:
        result = executor.submit(event_waiter.wait, 2.0, fallback=1.0)
        assert client.subscribed.wait(1)
        client.emit(1)
        assert result.result(timeout=0.5) == "event"


def test_nonmatching_event_does_not_wake() -> None:
    client = FakeClient()
    with waiter(client) as event_waiter, ThreadPoolExecutor() as executor:
        result = executor.submit(event_waiter.wait, 1.0, fallback=0.2, matches=lambda event: False)
        assert client.subscribed.wait(1)
        client.emit(1)
        assert result.result(timeout=1) == "timeout"


@pytest.mark.parametrize("sequence,kind", [(2, "treeChanged"), (1, "overflow")])
def test_gap_or_overflow_requests_rescan(sequence: int, kind: str) -> None:
    client = FakeClient()
    with waiter(client) as event_waiter, ThreadPoolExecutor() as executor:
        result = executor.submit(event_waiter.wait, 1.0)
        assert client.subscribed.wait(1)
        client.emit(sequence, kind)
        assert result.result(timeout=1) == "rescan"


def test_rescan_is_consumed_before_fallback() -> None:
    client = FakeClient()
    with waiter(client) as event_waiter:
        client.emit(2)
        assert event_waiter.wait(1) == "rescan"
        start = time.monotonic()
        assert event_waiter.wait(1, fallback=0.1) == "timeout"
        assert time.monotonic() - start >= 0.08


def test_separate_gaps_each_request_rescan() -> None:
    client = FakeClient()
    with waiter(client) as event_waiter:
        client.emit(2)
        client.emit(4)
        assert event_waiter.wait(1) == "rescan"
        assert event_waiter.wait(1) == "rescan"
        assert event_waiter.wait(0.05) == "timeout"


def test_gap_arriving_during_wait_requests_rescan() -> None:
    client = FakeClient()
    with waiter(client) as event_waiter, ThreadPoolExecutor() as executor:
        assert event_waiter.wait(0.01) == "timeout"
        result = executor.submit(event_waiter.wait, 1.0)
        client.emit(2)
        assert result.result(timeout=0.5) == "rescan"
        assert event_waiter.wait(0.05) == "timeout"


def test_overflow_notification_is_reported_once() -> None:
    client = FakeClient()
    with waiter(client) as event_waiter:
        client.emit(1, "overflow")
        assert event_waiter.wait(1) == "rescan"
        start = time.monotonic()
        assert event_waiter.wait(1, fallback=0.1) == "timeout"
        assert time.monotonic() - start >= 0.08


def test_fallback_bounds_wait() -> None:
    client = FakeClient()
    with waiter(client) as event_waiter:
        start = time.monotonic()
        assert event_waiter.wait(1, fallback=0.1) == "timeout"
        assert 0.08 <= time.monotonic() - start < 0.8


def test_without_events_sleeps_without_subscribing() -> None:
    client = FakeClient(events=False)
    with waiter(client) as event_waiter:
        start = time.monotonic()
        assert event_waiter.wait(1, fallback=0.1) == "timeout"
        assert time.monotonic() - start >= 0.08
        assert client.subscribe_count == 0


def test_close_is_idempotent() -> None:
    client = FakeClient()
    event_waiter = waiter(client)
    assert client.subscribe_count == 0
    assert event_waiter.wait(0.01) == "timeout"
    event_waiter.close()
    event_waiter.close()
    assert client.subscribe_count == 1
    assert client.unsubscribe_count == 1


def test_session_closes_mid_wait_then_sleeps() -> None:
    client = FakeClient()
    with waiter(client) as event_waiter, ThreadPoolExecutor() as executor:
        result = executor.submit(event_waiter.wait, 2.0, fallback=1.0)
        assert client.subscribed.wait(1)
        client.subscription.closed.set()
        assert result.result(timeout=0.5) == "timeout"
        start = time.monotonic()
        assert event_waiter.wait(1, fallback=0.1) == "timeout"
        assert time.monotonic() - start >= 0.08
        assert client.subscribe_count == 1


def test_closed_session_during_subscribe_disables_events() -> None:
    client = FakeClient()
    client.fail_subscribe = True
    with waiter(client) as event_waiter:
        assert event_waiter.wait(1) == "timeout"
        assert event_waiter.wait(0.01) == "timeout"
        assert client.subscribe_count == 1


def test_concurrent_waits_share_one_subscription() -> None:
    client = FakeClient()
    with waiter(client) as event_waiter, ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(event_waiter.wait, 1.0)
        second = executor.submit(event_waiter.wait, 1.0)
        assert client.subscribed.wait(1)
        client.emit(1)
        client.emit(2)
        assert first.result(timeout=1) == "event"
        assert second.result(timeout=1) == "event"
        assert client.subscribe_count == 1
