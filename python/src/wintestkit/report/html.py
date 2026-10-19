"""Render portable HTML without remote assets or executable test content."""

from __future__ import annotations

import copy
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

TREE_TEXT_LIMIT = 512 * 1024


def render(results: dict[str, Any], directory: Path | None = None) -> str:
    if directory is not None:
        results = copy.deepcopy(results)
        root = directory.resolve()
        for test in results.get("tests", []):
            if not test.get("treeDump"):
                continue
            try:
                source = (root / test["treeDump"]).resolve()
                if not source.is_relative_to(root):
                    continue
                with source.open("rb") as stream:
                    content = stream.read(TREE_TEXT_LIMIT + 1)
                test["treeText"] = content[:TREE_TEXT_LIMIT].decode("utf-8", "replace")
                test["treeTextTruncated"] = len(content) > TREE_TEXT_LIMIT
            except (OSError, ValueError):
                continue
    template = files("wintestkit.report").joinpath("template.html").read_text(encoding="utf-8")
    data = json.dumps(results, ensure_ascii=False).replace("</", "<\\/").replace("<", "\\u003c")
    return template.replace("__WTK_DATA__", data)


def write_report(directory: Path, results: dict[str, Any], *, html: bool = True) -> Path:
    """Write ``results.json`` and, unless ``html`` is false, the self-contained ``index.html``.

    Returns where the HTML report is (or would be); ``results.json`` is always written first.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    target = directory / "index.html"
    if html:
        target.write_text(render(results, directory), encoding="utf-8")
    return target.resolve()
