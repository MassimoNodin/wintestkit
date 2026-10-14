"""Render portable HTML without remote assets or executable test content."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any


def render(results: dict[str, Any]) -> str:
    template = files("wintestkit.report").joinpath("template.html").read_text(encoding="utf-8")
    data = json.dumps(results, ensure_ascii=False).replace("</", "<\\/").replace("<", "\\u003c")
    return template.replace("__WTK_DATA__", data)


def write_report(directory: Path, results: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    target = directory / "index.html"
    target.write_text(render(results), encoding="utf-8")
    return target.resolve()
