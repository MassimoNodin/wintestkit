"""The system short date format: format a date for typing and parse the text a date picker shows."""

from __future__ import annotations

import ctypes
import datetime
import re
import sys

from wintestkit.errors import ActionError

LOCALE_SSHORTDATE = 0x1F
ISO_FORMAT = "yyyy-MM-dd"

_TOKEN = re.compile(r"y+|M+|d+")


def system_short_date_format() -> str:
    """The user's short date pattern, such as ``dd/MM/yyyy`` (ISO order off Windows)."""
    if sys.platform != "win32":
        return ISO_FORMAT
    buffer = ctypes.create_unicode_buffer(80)
    # LOCALE_NAME_USER_DEFAULT is a null name.
    if not ctypes.windll.kernel32.GetLocaleInfoEx(None, LOCALE_SSHORTDATE, buffer, len(buffer)):  # type: ignore[attr-defined]
        return ISO_FORMAT
    return buffer.value or ISO_FORMAT


def _check_format(pattern: str) -> None:
    for token in _TOKEN.findall(pattern):
        if (token[0] == "M" and len(token) > 2) or (token[0] == "d" and len(token) > 2):
            raise ActionError(
                f"The short date format {pattern!r} uses names, which is not supported"
            )


def format_date(value: datetime.date, pattern: str) -> str:
    """Format ``value`` with a .NET style pattern such as ``dd/MM/yyyy``."""
    _check_format(pattern)

    def one(match: re.Match[str]) -> str:
        token = match.group()
        if token[0] == "y":
            return f"{value.year:04d}" if len(token) > 2 else f"{value.year % 100:02d}"
        number = value.month if token[0] == "M" else value.day
        return f"{number:02d}" if len(token) == 2 else str(number)

    return _TOKEN.sub(one, pattern)


def parse_date(text: str, pattern: str) -> datetime.date | None:
    """The date in ``text``: ISO first, then the digits in the order ``pattern`` gives.

    Returns ``None`` for empty text and raises ``ActionError`` for text that is not a date.
    """
    text = text.strip()
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        pass
    _check_format(pattern)
    order = [token[0] for token in _TOKEN.findall(pattern)]
    numbers = re.findall(r"\d+", text)
    if sorted(order) != ["M", "d", "y"] or len(numbers) != 3:
        raise ActionError(f"Cannot read {text!r} as a date in the format {pattern!r}")
    parts = dict(zip(order, numbers, strict=True))
    year = int(parts["y"])
    if len(parts["y"]) <= 2:
        year += 2000
    try:
        return datetime.date(year, int(parts["M"]), int(parts["d"]))
    except ValueError as exc:
        raise ActionError(f"Cannot read {text!r} as a date in the format {pattern!r}") from exc
