"""Failure artifacts: screenshots and a UI tree dump captured when a test fails."""

from __future__ import annotations

import difflib
import hashlib
import logging
import os
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
TREE_TEXT_MAX_BYTES = 512 * 1024
BASELINE_MAX_FILES = 500


def _stable_tree(text: str) -> str:
    """Drop volatile screen coordinates from UI tree text before it is persisted or compared."""
    return re.sub(r" \(-?\d+,-?\d+ \d+x\d+\)", "", text)


@dataclass
class ArtifactSet:
    """Files captured for one test."""

    directory: Path
    screenshots: list[Path] = field(default_factory=lambda: [])
    tree_dump: Path | None = None
    tree_diff: Path | None = None

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

        png = screenshot.capture_window(app.main_window().native_window_handle)
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

            png = screenshot.capture_window(window.native_window_handle)
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

            text = _stable_tree(
                treedump.dump(
                    window,
                    max_depth=TREE_MAX_DEPTH,
                    max_nodes=TREE_MAX_NODES,
                    max_bytes=TREE_TEXT_MAX_BYTES,
                )
            )
            tree_path = directory / "tree.txt"
            tree_path.parent.mkdir(parents=True, exist_ok=True)
            tree_path.write_text(text, encoding="utf-8")
            artifacts.tree_dump = tree_path
        except Exception:
            log.warning("could not dump the UI tree", exc_info=True)
    return artifacts


def capture_tree_text(app: App | None) -> str | None:
    """Return a bounded UI tree for an app, or ``None`` when it is unavailable."""
    if app is None:
        return None
    try:
        from wintestkit.engine import treedump

        text = treedump.dump(
            app.main_window(),
            max_depth=TREE_MAX_DEPTH,
            max_nodes=TREE_MAX_NODES,
            max_bytes=TREE_TEXT_MAX_BYTES,
        )
        return _stable_tree(text)
    except Exception:
        log.warning("could not capture the UI tree baseline", exc_info=True)
        return None


def write_tree_diff(baseline: Path, current: Path, target: Path) -> bool:
    """Write a bounded unified diff between a previous passing tree and this failure."""
    try:
        with baseline.open("rb") as stream:
            before_bytes = stream.read(TREE_TEXT_MAX_BYTES + 1)
        with current.open("rb") as stream:
            after_bytes = stream.read(TREE_TEXT_MAX_BYTES + 1)
        if len(before_bytes) > TREE_TEXT_MAX_BYTES or len(after_bytes) > TREE_TEXT_MAX_BYTES:
            return False
        before, after = before_bytes.decode("utf-8"), after_bytes.decode("utf-8")
        diff = list(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile="last passing UI tree",
                tofile="failing UI tree",
                lineterm="",
            )
        )
        if not diff:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = ("\n".join(diff[:2000]) + "\n").encode("utf-8")[:TREE_TEXT_MAX_BYTES]
        target.write_bytes(encoded.decode("utf-8", "ignore").encode("utf-8"))
        return True
    except (OSError, UnicodeError):
        return False


def baseline_path(report_dir: Path, target: str, nodeid: str) -> Path:
    """Stable per-target and per-test baseline location; one file is retained per pair."""
    key = hashlib.sha256(f"{target}\0{nodeid}".encode()).hexdigest()
    return report_dir / "ui-tree-baselines" / f"{key}.txt"


def store_tree_text(text: str | None, path: Path) -> None:
    """Best-effort bounded baseline store; artifacts never turn a passing test into a failure."""
    try:
        if text is None:
            return
        encoded = text.encode("utf-8")[:TREE_TEXT_MAX_BYTES].decode("utf-8", "ignore").encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
        files = sorted(path.parent.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in files[BASELINE_MAX_FILES:]:
            stale.unlink(missing_ok=True)
    except Exception:
        log.warning("could not store the UI tree baseline", exc_info=True)
