"""Event sinks: how the pytest plugin streams run events (NDJSON) to an editor or a file."""

from __future__ import annotations

import contextlib
import json
import logging
import re
import socket
import threading
from pathlib import Path
from typing import IO, Any, Protocol
from urllib.parse import unquote, urlparse

log = logging.getLogger("wintestkit.events")

CONNECT_TIMEOUT = 5.0


class EventSink(Protocol):
    """Receives protocol ``RunEvent`` dictionaries."""

    def emit(self, event: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


def encode_event(event: dict[str, Any]) -> bytes:
    """One NDJSON line (compact JSON, UTF-8, trailing newline)."""
    text = json.dumps(event, separators=(",", ":"), ensure_ascii=False, default=str)
    return (text + "\n").encode("utf-8")


class FileSink:
    """Writes events to a file (truncated at start), flushing after every event."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._file: IO[bytes] | None = self.path.open("wb")

    def emit(self, event: dict[str, Any]) -> None:
        with self._lock:
            if self._file is None:
                return
            try:
                self._file.write(encode_event(event))
                self._file.flush()
            except OSError:
                log.warning("could not write to the event file %s", self.path, exc_info=True)
                self._file = None

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None


class TcpSink:
    """Sends events to a TCP server (the editor). A broken connection never fails the run."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._socket: socket.socket | None = None
        try:
            connection = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
            connection.settimeout(None)
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._socket = connection
        except OSError:
            log.warning("could not connect to the event server %s:%d", host, port, exc_info=True)

    def emit(self, event: dict[str, Any]) -> None:
        with self._lock:
            if self._socket is None:
                return
            try:
                self._socket.sendall(encode_event(event))
            except OSError:
                log.warning("lost the connection to the event server; dropping events")
                self._close_locked()

    def _close_locked(self) -> None:
        if self._socket is not None:
            with contextlib.suppress(OSError):
                self._socket.close()
            self._socket = None

    def close(self) -> None:
        with self._lock:
            self._close_locked()


def _file_url_to_path(url_path: str) -> str:
    """``/C:/dir/x.ndjson`` (from ``file:///C:/dir/x.ndjson``) becomes ``C:/dir/x.ndjson``."""
    path = unquote(url_path)
    if re.match(r"^/[A-Za-z]:", path):
        path = path[1:]
    return path


def open_sink(url: str) -> EventSink:
    """Open a sink for ``tcp://host:port``, ``file:///C:/x.ndjson`` or a plain file path."""
    parsed = urlparse(url)
    if parsed.scheme == "tcp":
        if not parsed.hostname or parsed.port is None:
            raise ValueError(f"invalid event URL {url!r}: expected tcp://HOST:PORT")
        return TcpSink(parsed.hostname, parsed.port)
    if parsed.scheme == "file":
        return FileSink(_file_url_to_path(parsed.path))
    return FileSink(url)
