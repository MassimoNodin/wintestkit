"""Unit tests for the event sinks."""

import json
import socket
import threading
from pathlib import Path

import pytest

from wintestkit.artifacts import artifacts_dir, relative_to_report, safe_id
from wintestkit.events import FileSink, TcpSink, encode_event, open_sink


def test_encode_event_is_compact_utf8_ndjson() -> None:
    line = encode_event({"event": "x", "text": "héllo ✓", "n": 1})
    assert line.endswith(b"\n")
    assert b" " not in line.replace("héllo ✓".encode(), b"")
    assert json.loads(line.decode("utf-8")) == {"event": "x", "text": "héllo ✓", "n": 1}


def test_encode_event_handles_non_json_values() -> None:
    line = encode_event({"path": Path("a/b")})
    assert json.loads(line)["path"] == str(Path("a/b"))


def test_file_sink_truncates_and_flushes_each_event(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "events.ndjson"
    target.parent.mkdir()
    target.write_text("old content\n", encoding="utf-8")
    sink = FileSink(target)
    sink.emit({"event": "a"})
    assert target.read_text(encoding="utf-8") == '{"event":"a"}\n'  # flushed before close
    sink.emit({"event": "b"})
    sink.close()
    sink.close()
    sink.emit({"event": "ignored"})  # closed sinks drop events quietly
    lines = target.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["a", "b"]


def test_file_sink_creates_parent_directories(tmp_path: Path) -> None:
    sink = FileSink(tmp_path / "a" / "b" / "events.ndjson")
    sink.emit({"event": "x"})
    sink.close()
    assert (tmp_path / "a" / "b" / "events.ndjson").exists()


class Server:
    """A tiny TCP server collecting newline-delimited lines."""

    def __init__(self) -> None:
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.lines: list[str] = []
        self.connected = threading.Event()
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        try:
            connection, _ = self.listener.accept()
        except OSError:
            return  # the listener was closed before anyone connected
        self.connected.set()
        buffer = b""
        with connection:
            while chunk := connection.recv(4096):
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self.lines.append(line.decode("utf-8"))
        self.done.set()

    def close(self) -> None:
        self.listener.close()


def test_tcp_sink_sends_events_in_order() -> None:
    server = Server()
    try:
        sink = TcpSink("127.0.0.1", server.port)
        for index in range(50):
            sink.emit({"event": "step", "n": index, "text": "é"})
        sink.close()
        assert server.done.wait(5)
    finally:
        server.close()
    parsed = [json.loads(line) for line in server.lines]
    assert [e["n"] for e in parsed] == list(range(50))
    assert parsed[0]["text"] == "é"


def test_tcp_sink_survives_a_dead_connection(caplog: pytest.LogCaptureFixture) -> None:
    server = Server()
    sink = TcpSink("127.0.0.1", server.port)
    assert server.connected.wait(5)
    server.close()
    # Close the accepted side by shutting the listener and letting the server thread finish.
    sink._socket.shutdown(socket.SHUT_RDWR)  # type: ignore[union-attr]
    sink.emit({"event": "a"})  # must not raise
    sink.emit({"event": "b"})
    sink.close()


def test_tcp_sink_without_a_server_drops_events(caplog: pytest.LogCaptureFixture) -> None:
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()  # nothing listens on this port any more
    sink = TcpSink("127.0.0.1", port)
    sink.emit({"event": "a"})  # no exception
    sink.close()
    assert "could not connect" in caplog.text


def test_open_sink_parses_urls(tmp_path: Path) -> None:
    server = Server()
    try:
        sink = open_sink(f"tcp://127.0.0.1:{server.port}")
        assert isinstance(sink, TcpSink)
        sink.close()
    finally:
        server.close()
    plain = open_sink(str(tmp_path / "plain.ndjson"))
    assert isinstance(plain, FileSink)
    plain.close()
    url = open_sink("file:///" + (tmp_path / "from-url.ndjson").as_posix())
    assert isinstance(url, FileSink)
    assert url.path == tmp_path / "from-url.ndjson"
    url.close()
    encoded = open_sink(
        "file:///" + (tmp_path / "with space.ndjson").as_posix().replace(" ", "%20")
    )
    assert isinstance(encoded, FileSink)
    assert encoded.path.name == "with space.ndjson"
    encoded.close()


def test_open_sink_rejects_bad_tcp_urls() -> None:
    with pytest.raises(ValueError, match="tcp://HOST:PORT"):
        open_sink("tcp://localhost")


# -- artifact naming ------------------------------------------------------------------------------


def test_safe_id_is_filesystem_safe_and_unique() -> None:
    first = safe_id("tests/test_a.py::TestX::test_y[admin/secret]")
    assert first.startswith("tests_test_a.py__TestX__test_y_admin_secret_-")
    assert all(c.isalnum() or c in "._-" for c in first)
    assert safe_id("tests/test_a.py::test_y[a/b]") != safe_id("tests/test_a.py::test_y[a_b]")
    assert safe_id("x") == safe_id("x")


def test_safe_id_truncates_long_ids() -> None:
    long = "tests/" + "very_long_name_" * 30 + "::test"
    result = safe_id(long)
    assert len(result) == 120 + 1 + 8
    assert safe_id(long + "2") != result


def test_artifact_paths(tmp_path: Path) -> None:
    directory = artifacts_dir(tmp_path, "tests/test_a.py::test_x")
    assert directory.parent == tmp_path / "artifacts"
    inside = directory / "steps" / "1.png"
    assert relative_to_report(inside, tmp_path) == f"artifacts/{directory.name}/steps/1.png"
    outside = Path("C:/elsewhere/x.png")
    assert relative_to_report(outside, tmp_path) == "C:/elsewhere/x.png"
