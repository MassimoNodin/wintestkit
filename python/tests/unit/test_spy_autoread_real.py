"""Live Properties auto-read: a big control is read in full while the user keeps working.

The Properties sidebar reads every eligible row of the selected object without a click (CLR
properties, fields, dependency and attached properties; about 190 rows for a ScrollViewer). The
host sends that as batches over the single stdio channel. Whatever the read is doing, user actions
(starting the picker, refreshing the roots, the coverage badges, the keepalive) must be answered
quickly, and the whole read must finish in seconds with every row resolved.
"""

import base64
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import Future
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

import pytest
from test_spy_properties_real import PEERED, attached, find, pages, select_like_the_host

pytest_plugins = ("test_wpf_query_gate_real",)
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.name != "nt" or os.environ.get("WTK_INSPECTOR_REAL") != "1",
        reason="requires owned Windows fixture",
    ),
]

CAPABILITY = base64.b64encode(bytes(range(32))).decode("ascii")
# The batch the host sends. WTK_AUTOREAD_BATCH=1 reproduces the old one-request-per-row read.
BATCH = int(os.environ.get("WTK_AUTOREAD_BATCH", "25"))
USER_ACTION_LIMIT = 1.0
TOTAL_LIMIT = 10.0
STATUSES = {"ok", "timeout", "exception", "redacted", "truncated", "unsupported", "cycle"}


class Pipe:
    """The real `python -m wintestkit serve --stdio`, usable from several threads at once.

    The extension host never waits for one answer before sending the next request, so neither does
    this: every request gets its own future and the reader thread completes them as lines arrive.
    """

    def __init__(self, path: Path) -> None:
        (path / "pyproject.toml").write_text(
            "[tool.wintestkit.inspector]\nenabled = true\n", encoding="utf-8"
        )
        env = {**os.environ, "WINTESTKIT_SPY_HOST_CAPABILITY": CAPABILITY, "PYTHONUTF8": "1"}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "wintestkit", "serve", "--stdio"],
            cwd=path,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._lock = threading.Lock()
        self._futures: dict[int, Future[dict[str, Any]]] = {}
        self._sequence = 0
        self.requests: dict[str, int] = {}
        threading.Thread(target=self._pump, daemon=True).start()
        self.call("initialize", {"root": str(path)})

    def _pump(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            message = json.loads(line)
            future = self._futures.pop(message["id"], None) if "id" in message else None
            if future is not None:
                future.set_result(message)

    def call(self, method: str, params: dict[str, Any], timeout: float = 60) -> dict[str, Any]:
        return self.send(method, params).result(timeout=timeout)

    def send(self, method: str, params: dict[str, Any]) -> Future[dict[str, Any]]:
        assert self.process.stdin is not None
        future: Future[dict[str, Any]] = Future()
        with self._lock:
            self._sequence += 1
            request_id = self._sequence
            self._futures[request_id] = future
            self.requests[method] = self.requests.get(method, 0) + 1
            line = json.dumps(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
            self.process.stdin.write((line + "\n").encode())
            self.process.stdin.flush()
        return future

    def timed(self, method: str, params: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        started = time.perf_counter()
        response = self.call(method, params)
        return time.perf_counter() - started, response

    def close(self) -> None:
        with suppress(Exception):
            self.call("shutdown", {}, timeout=10)
        self.process.kill()
        self.process.wait(timeout=10)


def result(pipe: Pipe, method: str, params: dict[str, Any]) -> Any:
    response = pipe.call(method, params)
    assert "result" in response, (method, response)
    return response["result"]


def auto_eligible(member: dict[str, Any]) -> bool:
    """The rows ManagedPanel reads without a click (managedPanel.ts `autoEligible`)."""
    segment = member.get("pathSegment")
    if not segment:
        return False
    category = member["category"]
    public = member["readable"] and member["visibility"] == "public"
    field = (
        category == "clrField"
        and member.get("reason") == "nonPublic"
        and segment["kind"] == "field"
        and bool(segment.get("memberKey"))
        and bool(segment.get("declaringType"))
    )
    if not (public or field):
        return False
    return category == "clrField" or (
        member["visibility"] == "public"
        and (
            (category == "clrProperty" and segment["kind"] == "property")
            or (
                category in ("dependencyProperty", "attachedProperty")
                and segment["kind"] == "dependency"
            )
        )
    )


class AutoRead:
    """What the host's auto-read does: batches of rows, in order, until every row has an outcome."""

    def __init__(self, pipe: Pipe, base: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        self.pipe, self.base, self.rows = pipe, base, rows
        self.outcomes: dict[str, int] = {}
        self.unresolved: list[str] = []
        self.batch_times: list[float] = []
        self.elapsed = 0.0
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        started = time.perf_counter()
        try:
            for offset in range(0, len(self.rows), BATCH):
                chunk = self.rows[offset : offset + BATCH]
                took, response = self.pipe.timed(
                    "inspect.managed.spyRead",
                    {**self.base, "paths": [[row["pathSegment"]] for row in chunk]},
                )
                self.batch_times.append(took)
                if "error" in response:
                    code = response["error"].get("data", {}).get("code", response["error"])
                    if code == "timeout":
                        # The host marks these rows "(timed out)".
                        self.outcomes["timed out"] = self.outcomes.get("timed out", 0) + len(chunk)
                    else:
                        self.unresolved += [f"{row['name']}: {code}" for row in chunk]
                    continue
                values = response["result"]["values"]
                assert len(values) == len(chunk), (len(values), len(chunk))
                for row, item in zip(chunk, values, strict=True):
                    assert item["path"] == [row["pathSegment"]], row["name"]
                    status = item["value"]["status"]
                    self.outcomes[status] = self.outcomes.get(status, 0) + 1
                    if status not in STATUSES:
                        self.unresolved.append(f"{row['name']}: {status}")
        finally:
            self.elapsed = time.perf_counter() - started
            self.done.set()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def probe(
    pipe: Pipe, session_id: str, window: dict[str, Any], read: AutoRead, *, uia: bool = True
) -> dict[str, list[float]]:
    """User actions fired while the read runs; the latency of each answer.

    ``uia=False`` leaves out the requests that need the application's UI thread to answer.
    """
    latencies: dict[str, list[float]] = {
        "spy.start": [],
        "inspect.roots": [],
        "inspect.coverage": [],
        "inspect.managed.keepalive": [],
    }
    cycle = 0
    while not read.done.is_set():
        cycle += 1
        if cycle <= 4:
            # The picker holds global input hooks, so it is stopped again right away.
            took, response = pipe.timed(
                "spy.start", {"sessionId": f"probe{cycle}", "tree": "visual"}
            )
            assert "result" in response, response
            pipe.call("spy.stop", {})
            latencies["spy.start"].append(took)
        if uia:
            took, response = pipe.timed("inspect.roots", {})
            assert "result" in response, response
            latencies["inspect.roots"].append(took)
            took, response = pipe.timed("inspect.coverage", {"nodeIds": [window["nodeId"]]})
            assert "result" in response, response
            latencies["inspect.coverage"].append(took)
        took, response = pipe.timed("inspect.managed.keepalive", {"sessionId": session_id})
        assert "result" in response, response
        latencies["inspect.managed.keepalive"].append(took)
        read.done.wait(0.2)
    return latencies


def report(read: AutoRead, latencies: dict[str, list[float]], pipe: Pipe) -> str:
    lines = [
        f"rows={len(read.rows)} batch={BATCH} spyRead requests={pipe.requests['inspect.managed.spyRead']}"
        f" total={read.elapsed:.2f}s batch median={statistics.median(read.batch_times) * 1000:.0f}ms"
        f" max={max(read.batch_times) * 1000:.0f}ms outcomes={read.outcomes}"
    ]
    for method, values in latencies.items():
        if values:
            lines.append(
                f"{method}: n={len(values)} median={statistics.median(values) * 1000:.0f}ms"
                f" p95={percentile(values, 0.95) * 1000:.0f}ms max={max(values) * 1000:.0f}ms"
            )
    return "\n".join(lines)


@contextmanager
def selected_scroll_viewer(
    pipe: Pipe, pid: int
) -> Iterator[tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]]:
    with attached(pipe, pid) as (window, session):  # type: ignore[arg-type]
        node = find(pipe, window, {PEERED})[PEERED]  # type: ignore[arg-type]
        ref = select_like_the_host(pipe, session, node)  # type: ignore[arg-type]
        base = {
            "sessionId": session["sessionId"],
            "objectId": ref["objectId"],
            "generation": ref["generation"],
        }
        members = pages(pipe, "inspect.managed.members", base)  # type: ignore[arg-type]
        yield window, session, base, [m for m in members if auto_eligible(m)]


def test_auto_read_keeps_user_actions_responsive(
    owned: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    scope, path = owned
    pipe = Pipe(path)
    try:
        with selected_scroll_viewer(pipe, scope.app.main_window().process_id) as (
            window,
            session,
            base,
            rows,
        ):
            categories = {row["category"] for row in rows}
            assert {"clrProperty", "dependencyProperty", "attachedProperty"} <= categories
            assert len(rows) > 150, len(rows)
            read = AutoRead(pipe, base, rows)
            read.start()
            latencies = probe(pipe, session["sessionId"], window, read)
            read.thread.join(timeout=120)
            summary = report(read, latencies, pipe)
            with capsys.disabled():
                print("\n" + summary)
            assert not read.unresolved, read.unresolved
            assert sum(read.outcomes.values()) == len(rows), summary
            assert read.elapsed < TOTAL_LIMIT, summary
            assert latencies["spy.start"], "the read finished before spy.start could be measured"
            for method, values in latencies.items():
                assert max(values) < USER_ACTION_LIMIT, f"{method}\n{summary}"
    finally:
        pipe.close()


def test_auto_read_with_a_busy_application(owned: Any, capsys: pytest.CaptureFixture[str]) -> None:
    """The application's UI thread is blocked half of the time: reads time out, nothing else waits."""
    from test_wpf_query_gate_real import _fixture_scenario

    scope, path = owned
    pid = scope.app.main_window().process_id
    pipe = Pipe(path)
    stop = threading.Event()

    def block() -> None:
        while not stop.is_set():
            _fixture_scenario(pid, "sleepDispatcher", 0)
            stop.wait(1.5)

    blocker = threading.Thread(target=block, daemon=True)
    try:
        with selected_scroll_viewer(pipe, pid) as (window, session, base, rows):
            read = AutoRead(pipe, base, rows)
            blocker.start()
            read.start()
            latencies = probe(pipe, session["sessionId"], window, read, uia=False)
            read.thread.join(timeout=180)
            stop.set()
            blocker.join(timeout=10)
            summary = report(read, latencies, pipe)
            with capsys.disabled():
                print("\nbusy application\n" + summary)
            assert not read.unresolved, read.unresolved
            assert sum(read.outcomes.values()) == len(rows), summary
            for method, values in latencies.items():
                if values:
                    assert max(values) < USER_ACTION_LIMIT, f"{method}\n{summary}"
    finally:
        stop.set()
        pipe.close()


def test_a_burst_of_reads_does_not_queue_user_actions(
    owned: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every row is requested at once, as a host that never waits would: the answers come last."""
    scope, path = owned
    pipe = Pipe(path)
    try:
        with selected_scroll_viewer(pipe, scope.app.main_window().process_id) as (
            _window,
            session,
            base,
            rows,
        ):
            started = time.perf_counter()
            pending = [
                pipe.send("inspect.managed.spyRead", {**base, "paths": [[row["pathSegment"]]]})
                for row in rows
            ]
            latencies: dict[str, list[float]] = {"spy.start": [], "inspect.managed.keepalive": []}
            while not all(future.done() for future in pending):
                took, response = pipe.timed("spy.start", {"sessionId": "burst", "tree": "visual"})
                assert "result" in response, response
                pipe.call("spy.stop", {})
                latencies["spy.start"].append(took)
                took, response = pipe.timed(
                    "inspect.managed.keepalive", {"sessionId": session["sessionId"]}
                )
                assert "result" in response, response
                latencies["inspect.managed.keepalive"].append(took)
                time.sleep(0.2)
            elapsed = time.perf_counter() - started
            summary = "\n".join(
                f"{method}: n={len(values)} max={max(values) * 1000:.0f}ms"
                for method, values in latencies.items()
            )
            with capsys.disabled():
                print(f"\nburst of {len(rows)} reads answered in {elapsed:.2f}s\n{summary}")
            for method, values in latencies.items():
                assert values and max(values) < USER_ACTION_LIMIT, f"{method}\n{summary}"
            assert all("result" in future.result() for future in pending)
    finally:
        pipe.close()
