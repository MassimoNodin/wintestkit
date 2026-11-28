"""Opt-in live check that counted hand-outs keep a handle valid while it is handed out again.

Against the owned WPF fixture and the real agent: the same object is looked up over and over (as an
alternating application-scope and page-scope lookup does), each lookup's wrapper dies right
after use, and the releases of the dead wrappers must never end the lease of the live one. Needs
the desktop, so it only runs when ``WTK_INSPECTOR_REAL=1``.
"""

from __future__ import annotations

import gc
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from live_dotnet import live_dotnet_root

from wintestkit.backends.element import WpfElement
from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector.client import InspectorClient
from wintestkit.inspector.paths import PathSegment
from wintestkit.inspector.probe import identify
from wintestkit.inspector.sessions import SessionRegistry

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "wpf-inspector/tests/Fixtures/WpfFixture/bin/cells/net10.0-windows-x64"
PAYLOAD = ROOT / "inspector-payload/src"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
        reason="requires explicitly enabled owned Windows fixture",
    ),
]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.syspath_prepend(str(PAYLOAD))
    environment = os.environ.copy()
    environment["DOTNET_ROOT_X64"] = live_dotnet_root()
    environment["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    target = subprocess.Popen(
        [str(FIXTURE / "WinTestKit.Fixture.exe")],
        cwd=FIXTURE,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    registry = SessionRegistry()
    try:
        until = time.monotonic() + 15
        while True:
            assert target.poll() is None, "Owned fixture exited during startup"
            try:
                facts = identify(target.pid)
                if facts.wpf_loaded and facts.runtime == "net10":
                    break
            except (OSError, InspectorUnavailableError):
                pass
            assert time.monotonic() < until, "Owned fixture did not become ready"
            time.sleep(0.1)
        yield registry.attach(facts.identity, target_hwnd=None, deadline=time.monotonic() + 10)
    finally:
        registry.close_all()
        if target.poll() is None:
            target.terminate()
        target.wait(timeout=5)


def lookup(client: InspectorClient) -> WpfElement:
    """One fresh lookup of the first root, as a page-scope lookup resolves its window."""
    roots = client.roots(deadline=time.monotonic() + 2)
    assert roots.items
    return WpfElement(client, roots.items[0].object_ref, 0)


def test_the_same_object_handed_out_again_and_again_is_never_stale(client: InspectorClient) -> None:
    held = lookup(client)
    for _ in range(20):
        fresh = lookup(client)  # the same ID: the agent hands an ID out again while its lease lives
        assert fresh.ref.object_id == held.ref.object_id
        assert client.read(
            fresh.ref.object_id,
            fresh.ref.generation,
            [[PathSegment("type", "FullName")]],
            deadline=time.monotonic() + 2,
        )
        del fresh
        gc.collect()  # the dead wrapper's hand-out is queued and sent after the next request
    assert client.over_releases == 0
    assert client.state_get(held.ref, timeout_ms=2000, deadline=time.monotonic() + 2)
    del held
    gc.collect()
    client.flush_releases()
    assert client.release_failures == 0 and client.over_releases == 0


def test_lookups_on_several_threads_while_releases_are_sent_never_go_stale(
    client: InspectorClient,
) -> None:
    failures: list[BaseException] = []

    def work() -> None:
        try:
            for _ in range(40):
                element = lookup(client)
                client.state_get(element.ref, timeout_ms=2000, deadline=time.monotonic() + 2)
                del element
        except BaseException as error:
            failures.append(error)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert not failures, failures
    gc.collect()
    client.flush_releases()
    assert client.release_failures == 0 and client.over_releases == 0
