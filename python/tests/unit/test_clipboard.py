"""The clipboard helpers on a fake Win32 layer: nothing here touches the real clipboard."""

from __future__ import annotations

import ctypes
from types import SimpleNamespace
from typing import Any

import pytest

from wintestkit import clipboard, runtime
from wintestkit.errors import ClipboardError


class FakeClipboard:
    """The system clipboard: one text, who holds it, and how many opens fail first."""

    def __init__(self) -> None:
        self.text: str | None = None
        self.opened = False
        self.busy = 0
        self.open_calls = 0
        self.holder_name: str | None = None
        self.fail_write = False
        self.fail_read = False

    def open(self) -> bool:
        self.open_calls += 1
        if self.busy > 0:
            self.busy -= 1
            return False
        assert not self.opened
        self.opened = True
        return True

    def close(self) -> None:
        assert self.opened
        self.opened = False

    def read_text(self) -> str | None:
        assert self.opened
        if self.fail_read:
            raise OSError(5, "denied")
        return self.text

    def write_text(self, text: str) -> None:
        assert self.opened
        if self.fail_write:
            raise OSError(5, "denied")
        self.text = text

    def empty(self) -> None:
        assert self.opened
        self.text = None

    def holder(self) -> str | None:
        return self.holder_name


class Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def board(monkeypatch: pytest.MonkeyPatch) -> FakeClipboard:
    fake = FakeClipboard()
    clock = Clock()
    monkeypatch.setattr(clipboard, "_backend", fake)
    monkeypatch.setattr(clipboard, "_clock", clock.monotonic)
    monkeypatch.setattr(clipboard, "_sleep", clock.sleep)
    fake.clock = clock  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def steps() -> Any:
    runtime.reset()
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    yield records
    runtime.reset()


@pytest.mark.parametrize(
    "text",
    ["plain", "", "café üß", "日本語", "emoji \U0001f600", "a\r\nb\nc\t d"],
)
def test_text_round_trips_exactly(board: FakeClipboard, text: str) -> None:
    clipboard.set_text(text)
    assert board.text == text
    assert clipboard.get_text() == text
    assert not board.opened


def test_reads_and_writes_are_report_steps(board: FakeClipboard, steps: list[Any]) -> None:
    clipboard.set_text("Order 42")
    assert clipboard.get_text() == "Order 42"
    clipboard.clear()
    assert [(r.action, r.target) for r in steps] == [
        ("clipboard.set_text", "clipboard"),
        ("clipboard.get_text", "clipboard"),
        ("clipboard.clear", "clipboard"),
    ]
    assert steps[0].args == {"length": 8, "text": "Order 42"}
    assert steps[1].args == {"length": 8, "text": "Order 42"}
    assert all(record.status == "passed" for record in steps)


def test_long_text_is_shortened_in_the_report_only(board: FakeClipboard, steps: list[Any]) -> None:
    text = "x" * 500
    clipboard.set_text(text)
    assert clipboard.get_text() == text
    for record in steps:
        assert record.args["length"] == 500
        assert record.args["text"] == "x" * 200 + "..."


def test_secret_text_stays_out_of_the_report(board: FakeClipboard, steps: list[Any]) -> None:
    clipboard.set_text("hunter2", secret=True)
    assert clipboard.get_text(secret=True) == "hunter2"
    assert [record.args["text"] for record in steps] == ["***", "***"]
    assert "hunter2" not in repr([record.to_dict() for record in steps])


def test_an_empty_clipboard_is_a_clear_error(board: FakeClipboard, steps: list[Any]) -> None:
    with pytest.raises(ClipboardError, match="holds no text"):
        clipboard.get_text()
    assert not board.opened
    assert steps[0].status == "failed"
    assert steps[0].error is not None and steps[0].error["type"] == "ClipboardError"


def test_clear_removes_the_text(board: FakeClipboard) -> None:
    clipboard.set_text("something")
    clipboard.clear()
    assert board.text is None
    with pytest.raises(ClipboardError, match="holds no text"):
        clipboard.get_text()


def test_a_holder_that_lets_go_is_waited_for(board: FakeClipboard) -> None:
    board.busy = 3
    clipboard.set_text("later")
    assert board.open_calls == 4 and board.text == "later"
    assert len(board.clock.sleeps) == 3  # type: ignore[attr-defined]


def test_a_holder_that_never_lets_go_fails_after_the_timeout(board: FakeClipboard) -> None:
    board.busy = 10**6
    board.holder_name = "manager.exe (pid 77)"
    with pytest.raises(ClipboardError, match=r"locked by manager\.exe \(pid 77\) for 0\.5s"):
        clipboard.get_text(timeout=0.5)
    clock: Clock = board.clock  # type: ignore[attr-defined]
    assert 0.5 <= clock.now - 100.0 < 0.6
    assert not board.opened


def test_timeout_zero_tries_once(board: FakeClipboard) -> None:
    board.busy = 1
    with pytest.raises(ClipboardError, match="another process"):
        clipboard.set_text("x", timeout=0)
    assert board.open_calls == 1 and board.text is None


def test_a_refused_write_or_read_is_a_clipboard_error_and_closes_it(board: FakeClipboard) -> None:
    board.fail_write = True
    with pytest.raises(ClipboardError, match="could not be set"):
        clipboard.set_text("x")
    assert not board.opened
    board.fail_read = True
    with pytest.raises(ClipboardError, match="could not be read"):
        clipboard.get_text()
    assert not board.opened


def test_invalid_text_is_refused_before_the_clipboard_is_touched(board: FakeClipboard) -> None:
    with pytest.raises(TypeError, match="must be a str"):
        clipboard.set_text(42)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="NUL"):
        clipboard.set_text("a\0b")
    assert board.open_calls == 0


# -- the Win32 layer, with its functions replaced --------------------------------------------------


class FakeUser32:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.open_ok = True
        self.set_ok = True
        self.format_available = True
        self.data_handle = 0
        self.open_window = 0

    def CreateWindowExW(self, *args: Any) -> int:
        self.calls.append(("create",))
        return 900

    def DestroyWindow(self, hwnd: int) -> int:
        self.calls.append(("destroy", hwnd))
        return 1

    def OpenClipboard(self, owner: int) -> int:
        self.calls.append(("open", owner))
        return int(self.open_ok)

    def CloseClipboard(self) -> int:
        self.calls.append(("close",))
        return 1

    def EmptyClipboard(self) -> int:
        self.calls.append(("empty",))
        return 1

    def SetClipboardData(self, fmt: int, handle: int) -> int:
        self.calls.append(("set", fmt))
        self.stored = handle
        return int(self.set_ok)

    def IsClipboardFormatAvailable(self, fmt: int) -> int:
        return int(self.format_available)

    def GetClipboardData(self, fmt: int) -> int:
        return self.data_handle

    def GetOpenClipboardWindow(self) -> int:
        return self.open_window

    def GetWindowThreadProcessId(self, hwnd: int, pid: Any) -> int:
        pid._obj.value = 77
        return 1


class FakeKernel32:
    """Memory blocks as ctypes buffers, so the real ``memmove`` and ``wstring_at`` run."""

    def __init__(self) -> None:
        self.blocks: dict[int, Any] = {}
        self.freed: list[int] = []
        self.locks = 0
        self.unlocks = 0

    def GlobalAlloc(self, flags: int, size: int) -> int:
        buffer = ctypes.create_string_buffer(size)
        address = ctypes.addressof(buffer)
        self.blocks[address] = buffer
        self.flags = flags
        return address

    def GlobalLock(self, handle: int) -> int:
        self.locks += 1
        return handle

    def GlobalUnlock(self, handle: int) -> int:
        self.unlocks += 1
        return 1

    def GlobalFree(self, handle: int) -> int:
        self.freed.append(handle)
        return 0


def win32_layer() -> tuple[clipboard._Win32Clipboard, FakeUser32, FakeKernel32]:  # pyright: ignore[reportPrivateUsage]
    layer = object.__new__(clipboard._Win32Clipboard)  # pyright: ignore[reportPrivateUsage]
    user, kernel = FakeUser32(), FakeKernel32()
    layer._user32 = user  # type: ignore[assignment]  # pyright: ignore[reportAttributeAccessIssue]
    layer._kernel32 = kernel  # type: ignore[assignment]  # pyright: ignore[reportAttributeAccessIssue]
    layer._owner = None  # pyright: ignore[reportAttributeAccessIssue]
    return layer, user, kernel


def test_win32_write_stores_utf16_text_with_an_owner_window() -> None:
    layer, user, kernel = win32_layer()
    assert layer.open()
    layer.write_text("café \U0001f600")
    layer.close()
    assert [call[0] for call in user.calls] == [
        "create",
        "open",
        "empty",
        "set",
        "close",
        "destroy",
    ]
    assert ("open", 900) in user.calls and ("set", clipboard.CF_UNICODETEXT) in user.calls
    assert kernel.flags == clipboard.GMEM_MOVEABLE
    block = kernel.blocks[user.stored]
    assert bytes(block).startswith("café \U0001f600".encode("utf-16-le") + b"\x00\x00")
    assert kernel.freed == [] and kernel.locks == kernel.unlocks == 1


def test_win32_failed_set_frees_the_memory_and_reports() -> None:
    layer, user, kernel = win32_layer()
    user.set_ok = False
    layer.open()
    with pytest.raises(OSError, match="could not set"):
        layer.write_text("x")
    assert kernel.freed == [user.stored]


def test_win32_open_held_elsewhere_releases_the_owner_window() -> None:
    layer, user, _ = win32_layer()
    user.open_ok = False
    assert layer.open() is False
    assert user.calls[-1] == ("destroy", 900)
    layer.close()  # never opened: nothing else to destroy


def test_win32_read_returns_none_without_text_and_the_text_otherwise() -> None:
    layer, user, kernel = win32_layer()
    user.format_available = False
    assert layer.read_text() is None
    user.format_available = True
    block = ctypes.create_string_buffer("hi ü\U0001f600".encode("utf-16-le") + b"\x00\x00")
    user.data_handle = ctypes.addressof(block)
    assert layer.read_text() == "hi ü\U0001f600"
    assert kernel.locks == kernel.unlocks == 1


def test_win32_holder_names_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    from wintestkit.uia import win32

    layer, user, _ = win32_layer()
    assert layer.holder() is None
    user.open_window = 5
    monkeypatch.setattr(win32, "list_processes", lambda: [(77, "manager.exe")])
    assert layer.holder() == "manager.exe (pid 77)"
    monkeypatch.setattr(win32, "list_processes", lambda: [])
    assert layer.holder() == "pid 77"


def test_the_default_backend_is_the_win32_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clipboard, "_backend", None)
    built = SimpleNamespace(marker=True)
    monkeypatch.setattr(clipboard, "_Win32Clipboard", lambda: built)
    assert clipboard._system() is built  # pyright: ignore[reportPrivateUsage]
    assert clipboard._system() is built  # pyright: ignore[reportPrivateUsage]
