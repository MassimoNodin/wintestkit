"""A session the agent dropped for being idle is attached again on the next lookup; any other
end of a session still needs an explicit attach."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from test_inspector_client import IDENTITY, ScriptedTransport, session

from wintestkit import runtime
from wintestkit.config import load_config
from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector import client as client_module
from wintestkit.inspector import probe, sessions
from wintestkit.inspector.client import IDLE_SESSION_SECONDS, InspectorClient
from wintestkit.inspector.models import FEATURES, Session


class Clock:
    """Minutes pass when the test says so."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def wait_until_closed(client: InspectorClient) -> None:
    deadline = time.monotonic() + 3
    while client.session.state == "ready":
        assert time.monotonic() < deadline, "the reader did not notice the closed pipe"
        time.sleep(0.005)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(client_module, "_clock", fake)
    return fake


def new_client() -> tuple[InspectorClient, ScriptedTransport]:
    transport = ScriptedTransport(lambda request: {"id": request["id"], "result": {"ok": True}})
    return InspectorClient(transport, session()), transport


def test_a_pipe_closed_after_the_idle_limit_is_idle_expiry(clock: Clock) -> None:
    client, transport = new_client()
    assert client._request("roots", {}, time.monotonic() + 1) == {"ok": True}  # pyright: ignore[reportPrivateUsage]
    clock.now += 6 * 60  # the test waits six minutes; the agent drops the session
    transport.close()
    wait_until_closed(client)
    assert client.idle_expired and client.session.error == "sessionStale"


def test_the_idle_limit_counts_from_the_last_request(clock: Clock) -> None:
    client, transport = new_client()
    clock.now += IDLE_SESSION_SECONDS - 60
    client._request("roots", {}, time.monotonic() + 1)  # pyright: ignore[reportPrivateUsage]
    clock.now += 120  # two minutes since the request, six since the attach
    transport.close()
    wait_until_closed(client)
    assert not client.idle_expired


def test_a_pipe_lost_while_the_session_is_busy_is_not_idle_expiry(clock: Clock) -> None:
    client, transport = new_client()
    clock.now += 5
    transport.close()
    wait_until_closed(client)
    assert not client.idle_expired


def test_a_detach_is_never_idle_expiry(clock: Clock) -> None:
    client, _ = new_client()
    clock.now += 3600
    client.close()
    assert client.session.state == "detached" and not client.idle_expired


# -- the runtime attaches again behind the lookup ----------------------------------------------------


class Target:
    """One process whose agent can be asked to drop its session, with a counter for attaches."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.attaches = 0
        self.transports: list[ScriptedTransport] = []
        self.alive = True
        monkeypatch.setattr(
            sessions.SessionRegistry,
            "_attach_owned",
            lambda registry, *args, **kwargs: self.attach_owned(registry, *args, **kwargs),
        )
        monkeypatch.setattr(probe, "current_identity", self.current_identity)

    def current_identity(self, pid: int) -> Any:
        if not self.alive:
            raise InspectorUnavailableError("exited", code="processExited")
        return IDENTITY

    def attach_owned(
        self, registry: Any, identity: Any, hwnd: Any, deadline: Any, entry: Any
    ) -> Any:
        if not self.alive:
            raise InspectorUnavailableError("exited", code="processExited")
        self.attaches += 1
        transport = ScriptedTransport(lambda request: {"id": request["id"], "result": {}})
        self.transports.append(transport)
        info = Session(f"s{self.attaches}", identity, "ready", 2, 0, tuple(FEATURES))
        return InspectorClient(
            transport,
            info,
            on_closed=lambda closed: registry._client_closed(identity, entry, closed),
        )

    def drop(self) -> None:
        """The agent closes the pipe of its idle session."""
        self.transports[-1].close()


@pytest.fixture
def target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clock: Clock) -> Any:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"inspector.attach": "on-demand"}))
    yield Target(monkeypatch)
    runtime.close_inspector_sessions()
    runtime.reset()


def lookup() -> InspectorClient:
    return runtime.managed_client_for(IDENTITY.pid, deadline=time.monotonic() + 5, target_hwnd=None)


def test_six_idle_minutes_leave_later_lookups_working(target: Target, clock: Clock) -> None:
    first = lookup()
    assert lookup() is first and target.attaches == 1
    clock.now += 6 * 60  # a long Delay, or a wait that only uses UI Automation
    target.drop()
    wait_until_closed(first)
    second = lookup()
    assert second is not first and second.session.state == "ready" and target.attaches == 2
    assert lookup() is second and target.attaches == 2
    assert runtime.inspector_attached_processes() == (IDENTITY,)
    # And it expires again the same way, any number of times.
    clock.now += 6 * 60
    target.drop()
    wait_until_closed(second)
    assert lookup().session.state == "ready" and target.attaches == 3


def test_a_session_lost_while_busy_still_needs_an_explicit_attach(
    target: Target, clock: Clock
) -> None:
    first = lookup()
    clock.now += 10
    target.drop()
    wait_until_closed(first)
    with pytest.raises(InspectorUnavailableError, match="explicitly attach"):
        lookup()
    assert target.attaches == 1
    runtime.attach_managed(IDENTITY, deadline=time.monotonic() + 5)
    assert target.attaches == 2


def test_an_exited_process_is_not_attached_again_after_idling(target: Target, clock: Clock) -> None:
    first = lookup()
    clock.now += 6 * 60
    target.alive = False
    target.drop()
    wait_until_closed(first)
    for _ in range(2):
        with pytest.raises(InspectorUnavailableError) as error:
            lookup()
        assert error.value.code == "processExited"
    assert target.attaches == 1


def test_manual_attach_mode_never_attaches_on_its_own(
    target: Target, clock: Clock, tmp_path: Path
) -> None:
    runtime.attach_managed(IDENTITY, deadline=time.monotonic() + 5)
    first = lookup()
    runtime.set_config(load_config(tmp_path, {"inspector.attach": "manual"}))
    clock.now += 6 * 60
    target.drop()
    wait_until_closed(first)
    with pytest.raises(InspectorUnavailableError, match="Attach the inspector"):
        lookup()
    assert target.attaches == 1


def test_a_detach_clears_the_expiry_so_it_cannot_be_confused_with_one(
    target: Target, clock: Clock
) -> None:
    first = lookup()
    runtime.detach_inspector(IDENTITY)
    wait_until_closed(first)
    registry = runtime.inspector_sessions()
    assert not registry.expired_by_idle(IDENTITY)
