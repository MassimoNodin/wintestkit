"""Find packaged application frames without including unrelated host windows."""

import pytest

from wintestkit.uia import win32


@pytest.mark.parametrize("visible_only", [True, False])
def test_hosted_windows(monkeypatch: pytest.MonkeyPatch, visible_only: bool) -> None:
    processes = {101: 10, 102: 20, 103: 20, 104: 30, 105: 10, 201: 10, 202: 99}
    enumerated: list[int] = []

    def enumerate_windows(callback, _parameter):
        for handle in range(101, 106):
            callback(handle, 0)
        return True

    def enumerate_children(handle, callback, _parameter):
        enumerated.append(handle)
        callback(201 if handle == 102 else 202, 0)
        return True

    monkeypatch.setattr(win32, "EnumWindows", enumerate_windows)
    monkeypatch.setattr(win32, "EnumChildWindows", enumerate_children)
    monkeypatch.setattr(win32, "window_pid", processes.__getitem__)
    monkeypatch.setattr(win32, "IsWindowVisible", lambda handle: handle != 105)
    monkeypatch.setattr(
        win32,
        "window_class_name",
        lambda handle: "ApplicationFrameWindow" if handle in (102, 103) else "Other",
    )
    assert win32.top_level_windows({10}, visible_only) == (
        [101, 102] if visible_only else [101, 102, 105]
    )
    assert enumerated == [102, 103]
    enumerated.clear()
    assert win32.top_level_windows() == [101, 102, 103, 104]
    assert enumerated == []
    assert win32.top_level_windows(set()) == []
