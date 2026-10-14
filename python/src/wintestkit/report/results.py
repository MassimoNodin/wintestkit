"""Accumulate reports from the exact events emitted by the pytest controller."""

from __future__ import annotations

import copy
import os
import platform
import shutil
from pathlib import Path
from typing import Any

from wintestkit import __version__


def environment() -> dict[str, Any]:
    screen = {"width": 0, "height": 0, "scale": 1.0}
    if os.name == "nt":
        import ctypes

        user32 = ctypes.windll.user32
        screen = {
            "width": user32.GetSystemMetrics(0),
            "height": user32.GetSystemMetrics(1),
            "scale": user32.GetDpiForSystem() / 96,
        }
    return {
        "python": platform.python_version(),
        "wintestkit": __version__,
        "windows": platform.version(),
        "machine": platform.node(),
        "screen": screen,
    }


def prepare_directory(directory: Path) -> None:
    """Remove only owned outputs; never follow a linked artifact directory."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "results.json", "artifacts"):
        target = directory / name
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            if target.is_junction():
                target.rmdir()
            else:
                shutil.rmtree(target)


class RunRecorder:
    """One event-driven source of truth for persisted results."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.tests: dict[str, dict[str, Any]] = {}
        self.completed: list[str] = []
        self.started = 0.0
        self.finished = 0.0
        self.summary: dict[str, Any] = {}

    def _relative(self, path: str) -> str:
        return Path(os.path.relpath(Path(path).resolve(), self.directory)).as_posix()

    def record(self, event: dict[str, Any]) -> None:
        kind = event["event"]
        if kind == "session_start":
            self.started = event["time"]
        elif kind == "collected":
            for item in event["tests"]:
                self.tests[item["id"]] = {
                    "id": item["id"],
                    "file": self._relative(item["file"]),
                    "line": item["line"],
                    "name": item["name"],
                    "outcome": "skipped",
                    "duration": 0.0,
                    "steps": [],
                    "screenshots": [],
                    "stdout": "",
                    "stderr": "",
                    "log": "",
                }
        elif kind in ("step", "test_output", "test_end"):
            test = self.tests.get(event["id"])
            if test is None:
                return
            if kind == "step":
                step = copy.deepcopy(event["step"])
                if "screenshot" in step:
                    path = Path(step["screenshot"])
                    step["screenshot"] = (
                        self._relative(str(path)) if path.is_absolute() else path.as_posix()
                    )
                test["steps"].append(step)
            elif kind == "test_output":
                test[event["stream"]] += event["text"]
            else:
                self.completed.append(event["id"])
                for key in ("outcome", "duration", "message", "error", "location"):
                    if key in event:
                        test[key] = copy.deepcopy(event[key])
                if "location" in test:
                    test["location"]["file"] = self._relative(test["location"]["file"])
                test["screenshots"] = [self._relative(path) for path in event["screenshots"]]
                if "artifactsDir" in event:
                    tree = Path(event["artifactsDir"]) / "tree.txt"
                    if tree.is_file():
                        test["treeDump"] = self._relative(str(tree))
        elif kind == "session_end":
            self.finished = event["time"]
            self.summary = copy.deepcopy(event["summary"])

    def results(self) -> dict[str, Any]:
        return {
            "version": 1,
            "startedAt": self.started,
            "finishedAt": self.finished,
            "duration": max(0.0, self.finished - self.started),
            "environment": environment(),
            "summary": self.summary,
            "tests": [self.tests[test_id] for test_id in self.completed],
        }
