"""Failure artifacts: screenshots and a UI tree dump captured when a test fails."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wintestkit.app import App

log = logging.getLogger("wintestkit.artifacts")

_MAX_ID_LENGTH = 120
TREE_MAX_DEPTH = 12
TREE_MAX_NODES = 3000


@dataclass
class ArtifactSet:
    """Files captured for one test."""

    directory: Path
    screenshots: list[Path] = field(default_factory=lambda: [])
    tree_dump: Path | None = None

    def add_screenshot(self, path: Path) -> None:
        if path not in self.screenshots:
            self.screenshots.append(path)


def safe_id(nodeid: str) -> str:
    """A file-system safe, collision-resistant name for a test id."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", nodeid)[:_MAX_ID_LENGTH]
    return f"{cleaned}-{hashlib.sha1(nodeid.encode('utf-8')).hexdigest()[:8]}"


def artifacts_dir(report_dir: Path, nodeid: str) -> Path:
    return report_dir / "artifacts" / safe_id(nodeid)


def relative_to_report(path: Path, report_dir: Path) -> str:
    """``path`` relative to the report directory with forward slashes."""
    try:
        return path.relative_to(report_dir).as_posix()
    except ValueError:
        return path.as_posix()


def capture_step_screenshot(app: App | None, directory: Path, seq: int) -> Path | None:
    """Screenshot of the application's main window after step ``seq``; never raises."""
    if app is None:
        return None
    try:
        from wintestkit.uia import screenshot

        png = screenshot.capture_element(app.main_window())
        if png is None:
            return None
        return screenshot.save(png, directory / "steps" / f"{seq}.png")
    except Exception:
        log.warning("could not capture the step screenshot", exc_info=True)
        return None


def capture_failure(app: App | None, directory: Path) -> ArtifactSet:
    """Capture ``window.png``, ``desktop.png`` and ``tree.txt``.

    Every artifact is captured independently and best effort: one failing does not stop the
    others, and nothing here ever raises.
    """
    artifacts = ArtifactSet(directory)
    window: Any = None
    if app is not None:
        try:
            window = app.main_window()
            from wintestkit.uia import screenshot

            png = screenshot.capture_element(window)
            if png is not None:
                artifacts.add_screenshot(screenshot.save(png, directory / "window.png"))
        except Exception:
            log.warning("could not capture the window screenshot", exc_info=True)
    try:
        from wintestkit.uia import screenshot

        artifacts.add_screenshot(
            screenshot.save(screenshot.capture_screen(), directory / "desktop.png")
        )
    except Exception:
        log.warning("could not capture the desktop screenshot", exc_info=True)
    if window is not None:
        try:
            from wintestkit.engine import treedump

            text = treedump.dump(window, max_depth=TREE_MAX_DEPTH, max_nodes=TREE_MAX_NODES)
            tree_path = directory / "tree.txt"
            tree_path.parent.mkdir(parents=True, exist_ok=True)
            tree_path.write_text(text, encoding="utf-8")
            artifacts.tree_dump = tree_path
        except Exception:
            log.warning("could not dump the UI tree", exc_info=True)
    return artifacts
