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
    pixels = bytes([199, 200, 200]) + bytes([200, 200, 200]) * (WINDOW.width * WINDOW.height - 1)

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
    pixels = bytes([199, 200, 200]) + bytes([200, 200, 200]) * (big.width * big.height - 1)
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
    pixels = bytes([199, 200, 200]) + bytes([200, 200, 200]) * (big.width * big.height - 1)
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


def test_peerless_wpf_preview_uses_agent_window_and_bounds(
    monkeypatch: pytest.MonkeyPatch, window_frame: list[int]
) -> None:
    from types import SimpleNamespace

    from wintestkit.backends.element import WpfElement

    element = object.__new__(WpfElement)
    state = SimpleNamespace(
        bounds=SimpleNamespace(x=110, y=55, width=10, height=5), window_handle=7
    )
    monkeypatch.setattr(WpfElement, "as_live", lambda self: self)
    monkeypatch.setattr(WpfElement, "_get_state", lambda self: state)
    result = live_preview.capture_live_preview(element)
    assert window_frame == [1007]
    assert (result["element"]["width"], result["element"]["height"]) == (10, 5)


# -- every selectable Spy row kind ----------------------------------------------------------------


@pytest.fixture
def real_roots(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Window handles are their own roots, as for real top-level windows."""
    captured: list[int] = []
    pixels = bytes([199, 200, 200]) + bytes([200, 200, 200]) * (WINDOW.width * WINDOW.height - 1)

    def frame(hwnd: int, expected_pid: int | None = None) -> tuple[Rect, bytes]:
        captured.append(hwnd)
        return WINDOW, pixels

    monkeypatch.setattr(screenshot, "capture_window_frame", frame)
    monkeypatch.setattr(win32, "root_window", lambda hwnd: 7 if hwnd in (7, 8, 9) else hwnd)
    return captured


def wpf(monkeypatch: pytest.MonkeyPatch, *, bounds: Any, is_window: bool, winforms: bool) -> Any:
    from types import SimpleNamespace

    from wintestkit.backends.element import WpfElement

    element = object.__new__(WpfElement)
    element.ref = SimpleNamespace(is_winforms=winforms)  # type: ignore[assignment]
    state = SimpleNamespace(bounds=bounds, window_handle=8)
    monkeypatch.setattr(WpfElement, "as_live", lambda self: self)
    monkeypatch.setattr(WpfElement, "_get_state", lambda self: state)
    monkeypatch.setattr(
        WpfElement, "native_window_handle", property(lambda self: 7 if is_window else 0)
    )
    return element


@pytest.mark.parametrize("winforms", [False, True])
def test_managed_child_is_cropped_and_outlined(
    monkeypatch: pytest.MonkeyPatch, real_roots: list[int], winforms: bool
) -> None:
    bounds = box(110, 55, 10, 5)
    element = wpf(monkeypatch, bounds=bounds, is_window=False, winforms=winforms)
    result = live_preview.capture_live_preview(element)
    assert real_roots == [7]
    assert (result["element"]["width"], result["element"]["height"]) == (10, 5)
    assert (result["window"]["width"], result["window"]["height"]) == (40, 20)


@pytest.mark.parametrize("winforms", [False, True])
def test_managed_window_is_shown_whole_as_its_element_image(
    monkeypatch: pytest.MonkeyPatch, real_roots: list[int], winforms: bool
) -> None:
    # The managed bounds of a window need not equal its frame (client area, shadow).
    bounds = box(102, 80, 36, 18)
    element = wpf(monkeypatch, bounds=bounds, is_window=True, winforms=winforms)
    result = live_preview.capture_live_preview(element)
    assert result["element"] == result["window"]
    assert (result["element"]["width"], result["element"]["height"]) == (40, 20)
    assert decode(result["element"]).getextrema() == (
        (199, 200),
        (200, 200),
        (200, 200),
    )  # no outline


def test_managed_window_without_a_rectangle_is_still_previewed(
    monkeypatch: pytest.MonkeyPatch, real_roots: list[int]
) -> None:
    element = wpf(monkeypatch, bounds=None, is_window=True, winforms=False)
    assert "element" in live_preview.capture_live_preview(element)


def test_uia_node_in_a_window_is_cropped_and_outlined(real_roots: list[int]) -> None:
    window = Node(WINDOW, hwnd=7)
    node = Node(Rect(110, 55, 10, 5), parent=Node(Rect(100, 50, 40, 20), parent=window))
    result = live_preview.capture_live_preview(node)  # type: ignore[arg-type]
    assert (result["element"]["width"], result["element"]["height"]) == (10, 5)
    assert result["element"] != result["window"]


def test_native_child_window_is_cropped_to_itself(real_roots: list[int]) -> None:
    child = Node(Rect(110, 55, 10, 5), hwnd=9, parent=Node(WINDOW, hwnd=7))
    result = live_preview.capture_live_preview(child)  # type: ignore[arg-type]
    assert real_roots == [7]  # the capture is of its top-level window
    assert (result["element"]["width"], result["element"]["height"]) == (10, 5)


@pytest.mark.parametrize("rect", [WINDOW, Rect(104, 54, 30, 14), None])
def test_top_level_native_window_is_shown_whole(real_roots: list[int], rect: Rect | None) -> None:
    result = live_preview.capture_live_preview(Node(rect, hwnd=7))  # type: ignore[arg-type]
    assert result["element"] == result["window"]
    assert (result["element"]["width"], result["element"]["height"]) == (40, 20)


@pytest.mark.parametrize(
    ("iconic", "visible", "reason"),
    [(True, True, "minimized"), (False, False, "hidden"), (False, True, "protected")],
)
def test_window_that_cannot_be_rendered_says_why(
    monkeypatch: pytest.MonkeyPatch, iconic: bool, visible: bool, reason: str
) -> None:
    monkeypatch.setattr(win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(screenshot, "capture_window_frame", lambda hwnd, pid=None: None)
    monkeypatch.setattr(win32, "IsIconic", lambda hwnd: iconic)
    monkeypatch.setattr(win32, "IsWindowVisible", lambda hwnd: visible)
    result = live_preview.capture_live_preview(Node(None, hwnd=7))  # type: ignore[arg-type]
    assert set(result) == {"reason"}
    assert reason in result["reason"] and "cannot be captured" in result["reason"]


def _process(monkeypatch: pytest.MonkeyPatch, windows: list[int], **facts: Any) -> list[int]:
    from wintestkit.uia import element as uia_element

    shown: list[int] = []
    titles = facts.get("titles", {})
    iconic = facts.get("iconic", set())
    monkeypatch.setattr(win32, "top_level_windows", lambda pids, visible_only=True: windows)
    monkeypatch.setattr(win32, "window_text", lambda hwnd: titles.get(hwnd, ""))
    monkeypatch.setattr(win32, "IsIconic", lambda hwnd: hwnd in iconic)
    monkeypatch.setattr(win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(uia_element, "from_handle", lambda hwnd: Node(None, hwnd=hwnd))

    def frame(hwnd: int, expected_pid: int | None = None) -> tuple[Rect, bytes]:
        shown.append(hwnd)
        return WINDOW, bytes([199, 200, 200]) + bytes([200, 200, 200]) * (
            WINDOW.width * WINDOW.height - 1
        )

    monkeypatch.setattr(screenshot, "capture_window_frame", frame)
    return shown


def test_process_row_without_windows_explains_why(monkeypatch: pytest.MonkeyPatch) -> None:
    _process(monkeypatch, [])
    assert live_preview.capture_process_preview(5) == {
        "reason": "The process has no visible top-level window to capture."
    }


def test_process_row_previews_its_first_titled_unminimized_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown = _process(
        monkeypatch,
        [11, 12, 13, 14],
        titles={12: "Minimized", 13: "Main", 14: "Other"},
        iconic={12},
    )
    result = live_preview.capture_process_preview(5)
    assert shown == [13]
    assert result["element"] == result["window"]
    assert (result["element"]["width"], result["element"]["height"]) == (40, 20)


def test_process_row_with_only_a_minimized_window_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    _process(monkeypatch, [11], titles={11: "Main"}, iconic={11})
    monkeypatch.setattr(screenshot, "capture_window_frame", lambda hwnd, pid=None: None)
    result = live_preview.capture_process_preview(5)
    assert "minimized" in result["reason"]


def test_process_row_failure_becomes_a_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(pids: set[int], visible_only: bool = True) -> list[int]:
        raise OSError("enumeration failed")

    monkeypatch.setattr(win32, "top_level_windows", broken)
    assert "enumeration failed" in live_preview.capture_process_preview(5)["reason"]


def box(x: int, y: int, width: int, height: int) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(x=x, y=y, width=width, height=height)


def test_single_colour_window_is_not_captured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win32, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(
        screenshot,
        "capture_window_frame",
        lambda hwnd, pid=None: (WINDOW, bytes((255, 255, 255)) * (WINDOW.width * WINDOW.height)),
    )
    result = live_preview.capture_live_preview(Node(WINDOW, hwnd=7))  # type: ignore[arg-type]
    assert "single colour" in result["reason"]
