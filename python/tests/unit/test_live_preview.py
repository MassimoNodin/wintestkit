"""Live Spy previews: the element crop and its window with the element outlined, never saved."""

import base64
from io import BytesIO
from typing import Any

import pytest
from PIL import Image

from wintestkit import live_preview
from wintestkit.uia import screenshot, win32
from wintestkit.uia.element import Rect

WINDOW = Rect(100, 50, 40, 20)


class Node:
    def __init__(self, rect: Rect | None, hwnd: int = 0, parent: "Node | None" = None) -> None:
        self.rect = rect
        self.native_window_handle = hwnd
        self._parent = parent

    def as_live(self) -> "Node":
        return self

    def parent(self) -> "Node | None":
        return self._parent


def decode(image: dict[str, Any]) -> Image.Image:
    picture = Image.open(BytesIO(base64.b64decode(image["data"])))
    assert picture.size == (image["width"], image["height"])
    return picture.convert("RGB")


@pytest.fixture
def window_frame(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    captured: list[int] = []
    pixels = bytes([200, 200, 200]) * (WINDOW.width * WINDOW.height)

    def frame(hwnd: int, expected_pid: int | None = None) -> tuple[Rect, bytes]:
        captured.append(hwnd)
        return WINDOW, pixels

    monkeypatch.setattr(screenshot, "capture_window_frame", frame)
    monkeypatch.setattr(win32, "root_window", lambda hwnd: hwnd + 1000)
    return captured


def test_preview_pairs_the_element_crop_with_its_outlined_window(window_frame: list[int]) -> None:
    window = Node(WINDOW, hwnd=7)
    button = Node(Rect(110, 55, 10, 5), parent=window)
    result = live_preview.capture_live_preview(button)  # type: ignore[arg-type]
    assert window_frame == [1007]  # the top-level ancestor of the nearest window handle
    crop, context = decode(result["element"]), decode(result["window"])
    assert crop.size == (10, 5)
    assert context.size == (WINDOW.width, WINDOW.height)
    assert crop.getpixel((5, 2)) == pytest.approx((200, 200, 200), abs=4)  # clean, no outline
    assert context.getpixel((10, 5))[0] > 200  # outline starts at the element's corner
    assert context.getpixel((10, 5))[1] < 80
    assert context.getpixel((35, 18)) == pytest.approx((200, 200, 200), abs=4)


def test_preview_clips_an_element_that_extends_past_its_window(window_frame: list[int]) -> None:
    window = Node(WINDOW, hwnd=7)
    wide = Node(Rect(130, 60, 100, 100), parent=window)
    result = live_preview.capture_live_preview(wide)  # type: ignore[arg-type]
    assert (result["element"]["width"], result["element"]["height"]) == (10, 10)


def test_captures_keep_their_real_size_so_text_stays_sharp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A full-screen window on a 3440x1440 monitor used to be shrunk to 1600 px, which blurred it.
    big = Rect(0, 0, 3440, 1408)
    pixels = bytes([200, 200, 200]) * (big.width * big.height)
    monkeypatch.setattr(screenshot, "capture_window_frame", lambda hwnd, pid=None: (big, pixels))
    monkeypatch.setattr(win32, "root_window", lambda hwnd: hwnd)
    child = Node(Rect(1000, 400, 800, 200), parent=Node(big, hwnd=3))
    result = live_preview.capture_live_preview(child)  # type: ignore[arg-type]
    assert (result["window"]["width"], result["window"]["height"]) == (3440, 1408)
    assert (result["element"]["width"], result["element"]["height"]) == (800, 200)
    context = decode(result["window"])
    outline = round(max(big.width, big.height) / live_preview._OUTLINE_STEP)
    assert outline > live_preview._OUTLINE_WIDTH
    # The outline grows with the window, so it is still a visible box in a scaled-down panel.
    assert context.getpixel((1000 + outline - 1, 500))[0] > 200
    assert context.getpixel((1000 + outline - 1, 500))[1] < 80
    assert context.getpixel((1000 + outline + 2, 500)) == pytest.approx((200, 200, 200), abs=4)


def test_captures_past_the_edge_limit_are_scaled_down_with_the_outline_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_preview, "MAX_EDGE", 1600)
    big = Rect(0, 0, 3200, 800)
    pixels = bytes([200, 200, 200]) * (big.width * big.height)
    monkeypatch.setattr(screenshot, "capture_window_frame", lambda hwnd, pid=None: (big, pixels))
    monkeypatch.setattr(win32, "root_window", lambda hwnd: hwnd)
    window = Node(big, hwnd=3)
    child = Node(Rect(1600, 400, 800, 200), parent=window)
    result = live_preview.capture_live_preview(child)  # type: ignore[arg-type]
    assert (result["window"]["width"], result["window"]["height"]) == (1600, 400)
    assert (result["element"]["width"], result["element"]["height"]) == (800, 200)
    context = decode(result["window"])
    assert context.getpixel((801, 200))[0] > 200  # outline scaled with the window
    assert context.getpixel((801, 200))[1] < 80


@pytest.mark.parametrize(
    ("node", "reason"),
    [
        (Node(None, hwnd=7), "no on-screen rectangle"),
        (Node(Rect(1000, 1000, 5, 5), hwnd=7), "outside its window"),
        (Node(Rect(110, 55, 5, 5)), "does not belong to a window"),
    ],
)
def test_unavailable_previews_explain_why(window_frame: list[int], node: Node, reason: str) -> None:
    result = live_preview.capture_live_preview(node)  # type: ignore[arg-type]
    assert set(result) == {"reason"}
    assert reason in result["reason"]


def test_minimized_or_blank_windows_have_no_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "root_window", lambda hwnd: hwnd)
    node = Node(Rect(110, 55, 5, 5), hwnd=7)
    monkeypatch.setattr(screenshot, "capture_window_frame", lambda hwnd, pid=None: None)
    assert "cannot be captured" in live_preview.capture_live_preview(node)["reason"]  # type: ignore[arg-type]
    monkeypatch.setattr(
        screenshot,
        "capture_window_frame",
        lambda hwnd, pid=None: (WINDOW, bytes(WINDOW.width * WINDOW.height * 3)),
    )
    assert "blank" in live_preview.capture_live_preview(node)["reason"]  # type: ignore[arg-type]


def test_an_unexpected_failure_becomes_a_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(hwnd: int, pid: int | None = None) -> None:
        raise OSError("device lost")

    monkeypatch.setattr(win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(screenshot, "capture_window_frame", broken)
    result = live_preview.capture_live_preview(Node(Rect(110, 55, 5, 5), hwnd=7))  # type: ignore[arg-type]
    assert "device lost" in result["reason"]
