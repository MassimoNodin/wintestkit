"""Test log entries and explicit pictures."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from wintestkit import runtime

_logger = logging.getLogger("wintestkit")


def _entry(level: str, text: str, details: dict[str, Any], **extra: Any) -> None:
    if level == "warning":
        _logger.warning("%s", text)
    elif level == "error":
        _logger.error("%s", text)
    elif runtime.current_test() is None:
        _logger.info("%s", text)
    if runtime.current_test() is not None:
        secret = bool(details.pop("secret", False))
        runtime.emit_log(
            {
                "level": level,
                "text": text,
                "details": runtime.redact_details(details, secret),
                "timestamp": time.time(),
                **extra,
            }
        )


def message(text: str, **details: Any) -> None:
    """Record an informational message."""
    _entry("info", text, details)


def warning(text: str, **details: Any) -> None:
    """Record a warning without changing the test outcome."""
    _entry("warning", text, details)


def error(text: str, **details: Any) -> None:
    """Record an error: the test fails when it ends, but it carries on until then.

    Every error is listed in the failure message and in the report. Use it where a check inside
    your own code found a problem that should not stop the rest of the test.
    """
    from wintestkit import soft

    soft.record(text, source="log.error", details=details)


def checkpoint(text: str, **details: Any) -> None:
    """Record a check that passed, as a step of the test (the counterpart of ``error``)."""
    with runtime.step("checkpoint", text, "", details):
        pass


def report_error(text: str, source: str, details: dict[str, Any]) -> None:
    """Write the log entry of a soft error (``soft.record`` calls this)."""
    _entry("error", text, {**details, "source": source})


def picture(target: Any = None, name: str = "picture") -> None:
    """Capture a picture when its target can be inspected safely."""
    if runtime.current_test() is None:
        _logger.info("%s", name)
        return
    extra: dict[str, Any] = {}
    try:
        from wintestkit import artifacts
        from wintestkit.backends.element import uia_of
        from wintestkit.model import BoundWindow, is_password_locator
        from wintestkit.object_previews import picture_target_is_safe
        from wintestkit.uia import screenshot

        if target is None:
            image = screenshot.capture_screen()
        else:
            locator = getattr(target, "locator", None)
            if locator is not None and is_password_locator(locator):
                raise ValueError("sensitive target")
            element = uia_of(target.resolve())
            bounds = element.rect
            if bounds is None or not picture_target_is_safe(element, bounds):
                raise ValueError("sensitive or unavailable target")
            image = (
                screenshot.capture_window(element.native_window_handle)
                if isinstance(target, BoundWindow) and element.native_window_handle
                else screenshot.capture_element(element)
            )
        if image is None:
            raise ValueError("picture unavailable")
        config = runtime.get_config()
        directory = artifacts.artifacts_dir(config.report_dir, runtime.current_test() or "")
        path = screenshot.save(image, directory / "pictures" / (uuid.uuid4().hex + ".webp"))
        extra["picture"] = artifacts.relative_to_report(path, config.report_dir)
    except Exception:
        extra["skipped"] = True
    _entry("info", name, {}, **extra)
