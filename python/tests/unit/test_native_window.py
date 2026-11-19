"""Decoding of window styles, the reader over a fake backend, and the server's `window` field."""

from pathlib import Path
from typing import Any

import pytest
from rpc_support import FakeWindowBackend, make_server, request

from wintestkit.uia.native_window import (
    NativeWindowReader,
    RawWindow,
    class_style_table,
    decode_ex_style,
    decode_style,
)

WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_TABSTOP = 0x00010000


def names(found: list[tuple[str, int]]) -> list[str]:
    return [name for name, _ in found]


@pytest.mark.parametrize(
    ("style", "class_name", "expected"),
    [
        (0x50010000, "Edit", ["WS_CHILD", "WS_VISIBLE", "WS_TABSTOP", "ES_LEFT"]),
        # A button: the type is an enumeration in the low bits, flags sit above it.
        (
            0x50012003,
            "Button",
            ["WS_CHILD", "WS_VISIBLE", "WS_TABSTOP", "BS_AUTOCHECKBOX", "BS_MULTILINE"],
        ),
        (0x50000000, "Button", ["WS_CHILD", "WS_VISIBLE", "BS_PUSHBUTTON"]),
        (0x50000007, "Button", ["WS_CHILD", "WS_VISIBLE", "BS_GROUPBOX"]),
        # A multiline read-only edit with both scroll bars.
        (
            0x50B10844,
            "Edit",
            [
                "WS_CHILD",
                "WS_VISIBLE",
                "WS_BORDER",
                "WS_VSCROLL",
                "WS_HSCROLL",
                "WS_TABSTOP",
                "ES_LEFT",
                "ES_MULTILINE",
                "ES_AUTOVSCROLL",
                "ES_READONLY",
            ],
        ),
        (0x50000100, "Static", ["WS_CHILD", "WS_VISIBLE", "SS_LEFT", "SS_NOTIFY"]),
        (0x5000C000, "Static", ["WS_CHILD", "WS_VISIBLE", "SS_LEFT", "SS_WORDELLIPSIS"]),
        (
            0x50010203,
            "ComboBox",
            ["WS_CHILD", "WS_VISIBLE", "WS_TABSTOP", "CBS_DROPDOWNLIST", "CBS_HASSTRINGS"],
        ),
        (
            0x50010041,
            "ListBox",
            ["WS_CHILD", "WS_VISIBLE", "WS_TABSTOP", "LBS_NOTIFY", "LBS_HASSTRINGS"],
        ),
        # A top-level window: bits 16 and 17 are the maximise and minimise boxes.
        (
            0x14CF0000,
            "Notepad",
            [
                "WS_VISIBLE",
                "WS_CLIPSIBLINGS",
                "WS_CAPTION",
                "WS_SYSMENU",
                "WS_THICKFRAME",
                "WS_MINIMIZEBOX",
                "WS_MAXIMIZEBOX",
            ],
        ),
        (
            0x90C800C4,
            "#32770",
            [
                "WS_POPUP",
                "WS_VISIBLE",
                "WS_CAPTION",
                "WS_SYSMENU",
                "DS_3DLOOK",
                "DS_SETFONT",
                "DS_MODALFRAME",
            ],
        ),
        # Only one of the two caption bits.
        (0x10800000, "Anything", ["WS_VISIBLE", "WS_BORDER"]),
        (0x10400000, "Anything", ["WS_VISIBLE", "WS_DLGFRAME"]),
        # WinForms control classes decode like the system class they wrap.
        (
            0x56010080,
            "WindowsForms10.EDIT.app.0.141b42a_r8_ad1",
            [
                "WS_CHILD",
                "WS_VISIBLE",
                "WS_CLIPSIBLINGS",
                "WS_CLIPCHILDREN",
                "WS_TABSTOP",
                "ES_LEFT",
                "ES_AUTOHSCROLL",
            ],
        ),
        (
            0x50010001,
            "WindowsForms10.BUTTON.app.0.2bf8098_r6_ad1",
            ["WS_CHILD", "WS_VISIBLE", "WS_TABSTOP", "BS_DEFPUSHBUTTON"],
        ),
    ],
)
def test_style_names(style: int, class_name: str, expected: list[str]) -> None:
    found, remainder = decode_style(style, class_name)
    assert names(found) == expected
    assert remainder == 0


def test_every_name_reports_the_bits_it_stands_for() -> None:
    found, _ = decode_style(0x50012003, "Button")
    assert dict(found) == {
        "WS_CHILD": WS_CHILD,
        "WS_VISIBLE": WS_VISIBLE,
        "WS_TABSTOP": WS_TABSTOP,
        "BS_AUTOCHECKBOX": 3,
        "BS_MULTILINE": 0x2000,
    }


def test_unknown_bits_are_returned_as_a_remainder() -> None:
    # 0x0400 is no button style we name, and the type nibble 0xF is no defined button type.
    found, remainder = decode_style(WS_CHILD | WS_VISIBLE | 0xF, "Button")
    assert names(found) == ["WS_CHILD", "WS_VISIBLE"]
    assert remainder == 0xF
    # A class we have no table for keeps its whole low word as the remainder.
    found, remainder = decode_style(WS_CHILD | 0x1234, "SomeCustomControl")
    assert names(found) == ["WS_CHILD"]
    assert remainder == 0x1234
    # The remainder holds only what no name claimed.
    assert decode_style(0, "Static")[1] == 0


def test_style_decoding_ignores_bits_beyond_32() -> None:
    assert decode_style(-1 & 0xFFFFFFFF, "")[0] == decode_style(-1, "")[0]
    assert decode_ex_style(1 << 40) == ([], 0)


@pytest.mark.parametrize(
    ("ex_style", "expected", "remainder"),
    [
        (0, [], 0),
        (0x00000200, ["WS_EX_CLIENTEDGE"], 0),
        (0x00040100, ["WS_EX_WINDOWEDGE", "WS_EX_APPWINDOW"], 0),
        (
            0x08080088,
            ["WS_EX_TOPMOST", "WS_EX_TOOLWINDOW", "WS_EX_LAYERED", "WS_EX_NOACTIVATE"],
            0,
        ),
        (0x00000002, [], 0x2),
        (0x00030000, ["WS_EX_CONTROLPARENT", "WS_EX_STATICEDGE"], 0),
        (0x00000203, ["WS_EX_DLGMODALFRAME", "WS_EX_CLIENTEDGE"], 0x2),
    ],
)
def test_extended_style_names(ex_style: int, expected: list[str], remainder: int) -> None:
    found, unknown = decode_ex_style(ex_style)
    assert names(found) == expected
    assert unknown == remainder


@pytest.mark.parametrize(
    ("class_name", "known"),
    [
        ("Button", True),
        ("BUTTON", True),
        ("SysListView32", True),
        ("#32770", True),
        ("WindowsForms10.COMBOBOX.app.0.1", True),
        ("Notepad", False),
        ("", False),
    ],
)
def test_class_tables(class_name: str, known: bool) -> None:
    assert bool(class_style_table(class_name)) is known


class StubBackend:
    def __init__(self, raw: RawWindow | None) -> None:
        self.raw = raw
        self.reads: list[int] = []

    def read(self, hwnd: int) -> RawWindow | None:
        self.reads.append(hwnd)
        return self.raw


def test_reader_shapes_the_payload() -> None:
    raw = RawWindow(
        class_name="Edit",
        style=0x50B10844,
        ex_style=0x200,
        text="hello",
        control_id=15,
        process_id=100,
        thread_id=200,
        owner=7,
        parent=9,
        rect=(10, 20, 310, 220),
        client_rect=(0, 0, 296, 196),
        visible=True,
        enabled=False,
        dpi=144,
    )
    backend = StubBackend(raw)
    window = NativeWindowReader(backend).read(0x30A4A)
    assert backend.reads == [0x30A4A]
    assert window is not None
    assert window["handle"] == 0x30A4A
    assert window["className"] == "Edit"
    assert window["rawStyle"] == 0x50B10844
    assert window["rawExStyle"] == 0x200
    assert {"name": "ES_READONLY", "value": 0x800} in window["styles"]
    assert window["exStyles"] == [{"name": "WS_EX_CLIENTEDGE", "value": 0x200}]
    assert window["text"] == "hello"
    assert (window["controlId"], window["processId"], window["threadId"]) == (15, 100, 200)
    assert (window["owner"], window["parent"]) == (7, 9)
    assert window["rect"] == {"left": 10, "top": 20, "width": 300, "height": 200}
    assert window["clientRect"] == {"left": 0, "top": 0, "width": 296, "height": 196}
    assert (window["visible"], window["enabled"], window["topmost"], window["dpi"]) == (
        True,
        False,
        False,
        144,
    )
    assert "unknownStyle" not in window
    assert "unknownExStyle" not in window


def test_reader_reports_remainders_and_topmost() -> None:
    raw = RawWindow(class_name="Custom", style=WS_CHILD | 0x40, ex_style=0x8 | 0x2)
    window = NativeWindowReader(StubBackend(raw)).read(5)
    assert window is not None
    assert window["unknownStyle"] == 0x40
    assert window["unknownExStyle"] == 0x2
    assert window["topmost"] is True
    # Unreadable values are left out rather than invented.
    for key in ("text", "processId", "threadId", "rect", "clientRect", "visible", "dpi"):
        assert key not in window


def test_enabled_falls_back_to_the_disabled_style() -> None:
    disabled = NativeWindowReader(StubBackend(RawWindow(style=0x08000000))).read(1)
    enabled = NativeWindowReader(StubBackend(RawWindow(style=0))).read(1)
    assert disabled is not None and disabled["enabled"] is False
    assert enabled is not None and enabled["enabled"] is True


def test_control_id_only_for_child_windows() -> None:
    top = NativeWindowReader(StubBackend(RawWindow(style=0x10000000, control_id=5))).read(1)
    child = NativeWindowReader(StubBackend(RawWindow(style=WS_CHILD, control_id=0))).read(1)
    assert top is not None and "controlId" not in top
    assert child is not None and child["controlId"] == 0


def test_password_text_is_never_returned() -> None:
    raw = RawWindow(class_name="Edit", style=WS_CHILD | 0x20, text="hunter2")
    window = NativeWindowReader(StubBackend(raw)).read(1)
    assert window is not None
    assert "text" not in window
    wrapped = RawWindow(class_name="WindowsForms10.EDIT.app.0.1", style=WS_CHILD | 0x20, text="x")
    assert "text" not in (NativeWindowReader(StubBackend(wrapped)).read(1) or {})
    # 0x20 on a button is BS_LEFTTEXT, not a password.
    button = RawWindow(class_name="Button", style=WS_CHILD | 0x20, text="Label")
    assert (NativeWindowReader(StubBackend(button)).read(1) or {})["text"] == "Label"


def test_long_text_is_cut() -> None:
    raw = RawWindow(class_name="Edit", text="x" * 5000)
    window = NativeWindowReader(StubBackend(raw)).read(1)
    assert window is not None
    assert len(window["text"]) == 2001
    assert window["text"].endswith("…")


def test_zero_and_stale_handles_have_no_window() -> None:
    backend = StubBackend(None)
    reader = NativeWindowReader(backend)
    assert reader.read(0) is None
    assert backend.reads == []
    assert reader.read(123) is None


def properties_params(server: Any, output: Any) -> dict[str, Any]:
    root = request(server, output, "inspect.roots")["result"][0]
    child = request(server, output, "inspect.children", {"nodeId": root["nodeId"]})["result"][0]
    return {"nodeId": child["nodeId"]}


@pytest.mark.parametrize("full", [False, True])
def test_server_returns_the_window_with_every_properties_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, full: bool
) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    params = {**properties_params(server, output), **({"full": True} if full else {})}
    result = request(server, output, "inspect.properties", params)["result"]
    window = result["window"]
    assert window["handle"] == button.native_window_handle
    assert window["className"] == "Button"
    assert window["text"] == "OK"
    assert [style["name"] for style in window["styles"]][-1] == "BS_DEFPUSHBUTTON"


def test_server_omits_the_window_for_nodes_without_a_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, output, button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    params = properties_params(server, output)
    button.native_window_handle = 0
    assert "window" not in request(server, output, "inspect.properties", params)["result"]


def test_server_survives_a_reader_that_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        def read(self, hwnd: int) -> RawWindow | None:
            raise OSError("access denied")

    server, output, _button = make_server(tmp_path, monkeypatch)
    request(server, output, "initialize", {"root": str(tmp_path)})
    server.window_reader = NativeWindowReader(Broken())
    result = request(server, output, "inspect.properties", properties_params(server, output))
    assert "error" not in result
    assert "window" not in result["result"]
    assert result["result"]["info"]["name"] == "OK"


def test_the_fake_backend_reads_any_handle() -> None:
    assert FakeWindowBackend().read(7) is not None


def test_the_win32_backend_reads_the_desktop_window_without_opening_anything() -> None:
    from wintestkit.uia import win32

    desktop = int(win32.GetDesktopWindow())
    window = NativeWindowReader(win32.Win32WindowBackend()).read(desktop)
    assert window is not None
    assert window["className"] == "#32769"
    assert window["handle"] == desktop
    assert window["visible"] is True
    assert window["rect"]["width"] > 0
    assert window["parent"] == 0
    assert "WS_VISIBLE" in [style["name"] for style in window["styles"]]
    assert isinstance(window["processId"], int)


def test_the_win32_backend_returns_none_for_a_handle_that_is_not_a_window() -> None:
    from wintestkit.uia import win32

    assert win32.Win32WindowBackend().read(0x7FFF0) is None
