"""Integration tests for the tree dump."""

import json

import pytest
from support import DemoProcess

from wintestkit.engine import treedump
from wintestkit.uia import element

pytestmark = pytest.mark.integration


def test_dump_contains_the_expected_structure(demo_process: DemoProcess) -> None:
    window = element.from_handle(demo_process.hwnd)
    text = treedump.dump(window)
    lines = text.splitlines()
    assert lines[0].startswith('Window "WTK Demo" [class=Window] (')
    assert any(
        line == '  Group "Credentials" [class=GroupBox]' or line.startswith('  Group "Credentials"')
        for line in lines
    )
    sign_in = [line for line in lines if 'Button "Sign in"' in line]
    assert sign_in
    assert sign_in[0].startswith("    ")  # nested below the group
    status = [line for line in lines if "id=StatusText" in line]
    assert status
    assert 'Text "Ready"' in status[0]


def test_dump_marks_disabled_elements(demo_process: DemoProcess) -> None:
    window = element.from_handle(demo_process.hwnd)
    text = treedump.dump(window)
    continue_line = next(line for line in text.splitlines() if 'Button "Continue"' in line)
    assert continue_line.endswith(" disabled")


def test_depth_and_node_limits(demo_process: DemoProcess) -> None:
    window = element.from_handle(demo_process.hwnd)
    shallow = treedump.dump(window, max_depth=1)
    assert all(not line.startswith("    ") for line in shallow.splitlines())
    limited = treedump.dump(window, max_nodes=5)
    lines = limited.splitlines()
    assert len(lines) == 6
    assert lines[-1] == "… (truncated at 5 nodes)"
    nodes = list(treedump.walk(window, max_depth=50, max_nodes=7))
    assert len(nodes) == 7
    assert nodes[0][0] == 0
    assert all(depth <= 50 for depth, _ in nodes)


def test_json_dump(demo_process: DemoProcess) -> None:
    window = element.from_handle(demo_process.hwnd)
    data = treedump.dump_json(window, max_depth=2, max_nodes=100)
    json.dumps(data)
    assert data["info"]["name"] == "WTK Demo"
    assert data["info"]["controlType"] == "Window"
    names = [child["info"]["name"] for child in data["children"]]
    assert "Credentials" in names
    for child in data["children"]:
        for grandchild in child["children"]:
            assert grandchild["children"] == []  # max_depth=2 stops expanding here
    capped = treedump.dump_json(window, max_depth=10, max_nodes=3)

    def count(node: dict[str, object]) -> int:
        children = node["children"]
        assert isinstance(children, list)
        return 1 + sum(count(c) for c in children)

    assert count(capped) == 3
