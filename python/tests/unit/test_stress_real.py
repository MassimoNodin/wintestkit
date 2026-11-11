"""Long-running, opt-in WPF resource and latency gates.

Budgets after warm-up: target +10 handles (plan 6.12), +2 threads,
+20 MiB private bytes; Python +20 handles, +2 threads, no sessions or
subscriptions. Query p95 at the end must be at most twice the starting p95.
"""

import ctypes
import os
import statistics
import time
from ctypes import wintypes
from dataclasses import replace

import pytest
from test_inspector_owned_integration import DOTNET, FIXTURE, PAYLOAD
from test_wpf_query_gate_real import config

from wintestkit import runtime
from wintestkit.app import App
from wintestkit.config import load_config
from wintestkit.controls import TextBox
from wintestkit.engine.locator import Locator
from wintestkit.engine.resolve import resolve
from wintestkit.inspector.event_waiter import EventWaiter
from wintestkit.inspector.probe import current_identity
from wintestkit.model import Element, Page

pytest_plugins = ("test_wpf_query_gate_real",)
pytestmark = [
    pytest.mark.stress,
    pytest.mark.skipif(
        os.name != "nt"
        or os.environ.get("WTK_INSPECTOR_REAL") != "1"
        or os.environ.get("WTK_STRESS") != "1",
        reason="requires WTK_INSPECTOR_REAL=1 and WTK_STRESS=1 on Windows",
    ),
]


class MemoryCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
        (name, ctypes.c_size_t)
        for name in (
            "PeakWorkingSetSize",
            "WorkingSetSize",
            "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage",
            "PagefileUsage",
            "PeakPagefileUsage",
            "PrivateUsage",
        )
    ]


class ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("usage", wintypes.DWORD),
        ("thread_id", wintypes.DWORD),
        ("owner_pid", wintypes.DWORD),
        ("base_priority", wintypes.LONG),
        ("delta_priority", wintypes.LONG),
        ("flags", wintypes.DWORD),
    ]


def metrics(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(MemoryCounters),
        wintypes.DWORD,
    ]
    handle = kernel.OpenProcess(0x1000 | 0x10, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        count = wintypes.DWORD()
        memory = MemoryCounters()
        memory.cb = ctypes.sizeof(memory)
        assert kernel.GetProcessHandleCount(handle, ctypes.byref(count))
        assert psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb)
    finally:
        kernel.CloseHandle(handle)
    snapshot = kernel.CreateToolhelp32Snapshot(4, 0)
    assert snapshot != ctypes.c_void_p(-1).value
    try:
        entry = ThreadEntry()
        entry.size = ctypes.sizeof(entry)
        present = kernel.Thread32First(snapshot, ctypes.byref(entry))
        threads = 0
        while present:
            threads += entry.owner_pid == pid
            present = kernel.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return {"handles": count.value, "threads": threads, "private": memory.PrivateUsage}


def sample_floor(pids):
    samples = {label: [] for label in pids}
    for index in range(5):
        for label, pid in pids.items():
            samples[label].append(metrics(pid))
        if index < 4:
            time.sleep(0.2)
    return {
        label: {key: min(sample[key] for sample in values) for key in values[0]}
        for label, values in samples.items()
    }


def check_growth(label, checkpoints, handles=20, period=100):
    positions = list(checkpoints)
    span = positions[-1] - positions[0]
    center = statistics.mean(positions)
    denominator = sum((position - center) ** 2 for position in positions)
    failures = []
    for key, limit, overall in (
        ("handles", handles, handles * span / period),
        ("threads", 1, 2),
        ("private", 20 * 1024 * 1024, 20 * 1024 * 1024),
    ):
        values = [checkpoints[position][key] for position in positions]
        mean = statistics.mean(values)
        slope = (
            sum(
                (position - center) * (value - mean)
                for position, value in zip(positions, values, strict=True)
            )
            / denominator
        )
        projection = slope * (period if key == "handles" else span)
        growth = values[-1] - values[0]
        print(
            f"{label} {key}: checkpoints={list(zip(positions, values, strict=True))}, slope={slope:.6f}, projection={projection:.2f}, growth={growth}",
            flush=True,
        )
        if projection > limit or growth > overall:
            failures.append(
                f"{label} {key}: projection {projection:.2f}/{limit}, growth {growth}/{overall}"
            )
    return failures


def query(scope):
    return resolve(scope, Locator(automation_id="FancyAutomationId"))


def cycle(scope):
    window = scope.app.top_level_windows()[0]
    identity = current_identity(window.process_id)
    client = runtime.attach_managed(
        identity, deadline=time.monotonic() + 20, target_hwnd=window.native_window_handle
    )
    subscription = client.subscribe(
        ["treeChanged", "windowOpened", "windowClosed"], deadline=time.monotonic() + 5
    )
    assert query(scope)
    assert client.unsubscribe(subscription.subscription_id, deadline=time.monotonic() + 5)
    assert not client._subscriptions  # pyright: ignore[reportPrivateUsage]
    runtime.detach_inspector(identity)
    assert not runtime.inspector_sessions()._entries  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    "cycles",
    [
        100,
        pytest.param(
            300,
            marks=pytest.mark.skipif(
                os.environ.get("WTK_STRESS_LONG") != "1", reason="requires WTK_STRESS_LONG=1"
            ),
        ),
    ],
)
def test_attach_detach_stress(owned, cycles):
    scope, path = owned
    with runtime.config_scope(config(path, "agent")):
        for _ in range(5):
            cycle(scope)
        checkpoints = {"target": {}, "python": {}}
        pids = {"target": scope.app.pids[0], "python": os.getpid()}
        for index in range(cycles + 1):
            if index % (cycles // 5) == 0:
                for label, sample in sample_floor(pids).items():
                    checkpoints[label][index] = sample
            if index < cycles:
                cycle(scope)
        failures = check_growth(f"attach {cycles} target", checkpoints["target"], handles=10)
        failures += check_growth(f"attach {cycles} python", checkpoints["python"])
        assert not failures, "\n".join(failures)


def test_launch_close_stress(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(PAYLOAD))
    runtime.reset()
    cfg = load_config(tmp_path, {"inspector.enabled": True, "inspector.attach": "on-launch"})
    with runtime.config_scope(cfg):
        checkpoints = {"target": {}, "python": {}}
        for index in range(105):
            app = App.launch(
                FIXTURE / "WinTestKit.Fixture.exe",
                cwd=FIXTURE,
                env={"DOTNET_ROOT_X64": DOTNET, "DOTNET_MULTILEVEL_LOOKUP": "0"},
                owned_only=True,
            )
            pid = app.pids[0]
            try:
                assert runtime.inspector_sessions()._entries  # pyright: ignore[reportPrivateUsage]
                if index >= 4 and (index - 4) % 20 == 0:
                    checkpoints["target"][index - 4] = sample_floor({"target": pid})["target"]
            finally:
                app.close()
            assert pid not in app.pids
            assert not runtime.inspector_sessions()._entries  # pyright: ignore[reportPrivateUsage]
            if index >= 4 and (index - 4) % 20 == 0:
                checkpoints["python"][index - 4] = sample_floor({"python": os.getpid()})["python"]
        failures = check_growth("launch target", checkpoints["target"], handles=10)
        failures += check_growth("launch python", checkpoints["python"])
        assert not failures, "\n".join(failures)
    runtime.reset()


class StressPage(Page):
    button = Element(automation_id="FancyAutomationId")
    noop_button = Element(automation_id="NestedButton")
    source = TextBox(automation_id="BindingSource")


def latency(scope):
    samples = []
    for _ in range(30):
        start = time.perf_counter()
        assert query(scope)
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return {"p50_ms": statistics.median(samples), "p95_ms": samples[28]}


def test_sustained_actions_stress(owned):
    scope, path = owned
    page = StressPage(scope.app)
    with runtime.config_scope(replace(config(path, "agent"), backend="auto")):
        for _ in range(5):
            assert query(scope)
        client = query(scope).client
        waiter = EventWaiter(client, {"treeChanged"})
        waiter.wait(0.2)
        assert len(client._subscriptions) == 1  # pyright: ignore[reportPrivateUsage]

        def perform(operation):
            if operation == 0:
                assert query(scope)
            elif operation == 1:
                assert query(scope).is_enabled
            elif operation == 2:
                page.noop_button.click(mode="pattern")
            elif operation == 3:
                page.button.click(mode="mouse")
            elif operation == 4:
                page.source.type("stress")
            else:
                page.button.wait_for("visible", timeout=5)
                waiter.wait(0.02)

        for index in range(100):
            perform(index % 6)
        initial_latency = latency(scope)
        checkpoints = {"target": {}, "python": {}}
        pids = {"target": scope.app.pids[0], "python": os.getpid()}
        for label, sample in sample_floor(pids).items():
            checkpoints[label][0] = sample
        for index in range(1000):
            perform(index % 6)
            if index % 200 == 199:
                for label, sample in sample_floor(pids).items():
                    checkpoints[label][index + 1] = sample
        assert len(client._subscriptions) == 1  # pyright: ignore[reportPrivateUsage]
        assert len(runtime.inspector_sessions()._entries) == 1  # pyright: ignore[reportPrivateUsage]
        final_latency = latency(scope)
        print(f"query latency: start={initial_latency}, end={final_latency}", flush=True)
        failures = []
        for label, handle_limit in (("target", 10), ("python", 20)):
            failures += check_growth(
                f"actions {label}", checkpoints[label], handles=handle_limit, period=1000
            )
        waiter.close()
        if client._subscriptions:  # pyright: ignore[reportPrivateUsage]
            failures.append("subscriptions remain after closing waiter")
        if final_latency["p95_ms"] > initial_latency["p95_ms"] * 2:
            failures.append(
                f"query p95 exceeded twice its baseline: {initial_latency} -> {final_latency}"
            )
        assert not failures, "\n".join(failures)
