from __future__ import annotations

from wintestkit.artifacts import baseline_path, write_tree_diff


def test_baseline_is_partitioned_by_target_and_test(tmp_path):
    a = baseline_path(tmp_path, "app-one", "test_a")
    assert a != baseline_path(tmp_path, "app-two", "test_a")
    assert a != baseline_path(tmp_path, "app-one", "test_b")


def test_diff_is_bounded_and_omitted_when_no_change(tmp_path):
    previous, current, diff = (tmp_path / name for name in ("previous", "current", "diff"))
    previous.write_text("Window\n  Button Save\n", encoding="utf-8")
    current.write_text("Window\n  Button Cancel\n", encoding="utf-8")
    assert write_tree_diff(previous, current, diff)
    assert "Button Save" in diff.read_text(encoding="utf-8")
    current.write_text("Window\n  Button Save\n", encoding="utf-8")
    assert not write_tree_diff(previous, current, diff)
    previous.write_text("x" * (512 * 1024 + 1), encoding="utf-8")
    assert not write_tree_diff(previous, current, diff)
