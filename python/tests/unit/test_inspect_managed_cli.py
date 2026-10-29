"""Standalone managed inspection owns and closes its registry (fake transport)."""

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fakes import FakeApp, FakeElement
from test_managed_server import IDENTITY, FakeClient

from wintestkit import runtime
from wintestkit.cli import main
from wintestkit.commands import common
from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector import probe, sessions
from wintestkit.inspector.models import Page


class CliRegistry:
    instances: ClassVar[list["CliRegistry"]] = []
    failure: BaseException | None = None
    fail_operation = "attach"

    def __init__(self, *, request_timeout: float) -> None:
        self.timeout = request_timeout
        self.client = FakeClient()
        self.closed = False
        self.__class__.instances.append(self)
        if self.failure is not None and self.fail_operation != "attach":

            def fail(*args: Any, **kwargs: Any) -> Any:
                raise self.failure  # type: ignore[misc]

            setattr(self.client, self.fail_operation, fail)

    def attach(self, *args: Any, **kwargs: Any) -> FakeClient:
        if self.failure is not None and self.fail_operation == "attach":
            raise self.failure
        return self.client

    def close_all(self) -> None:
        self.closed = True
        self.client.close()


def _identity(pid: int) -> Any:
    return IDENTITY


def _element_identity(node: Any) -> tuple[tuple[int, ...], None]:
    return (1, 2), None


def _unexpected_probe(pid: int) -> Any:
    pytest.fail("unexpected probe")


@pytest.fixture
def cli_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    CliRegistry.instances.clear()
    CliRegistry.failure = None
    CliRegistry.fail_operation = "attach"
    (tmp_path / "wintestkit.yaml").write_text(
        "inspector:\n  enabled: true\n  attach: manual\n  request_timeout: 0.4\n",
        encoding="utf-8",
    )
    window = FakeElement("Window", "Demo")

    def app(cfg: Any) -> FakeApp:
        return FakeApp([window])

    monkeypatch.setattr(common, "attach_app", app)
    monkeypatch.setattr(probe, "current_identity", _identity)
    monkeypatch.setattr(runtime, "managed_element_identity", _element_identity)
    monkeypatch.setattr(sessions, "SessionRegistry", CliRegistry)
    return tmp_path


def test_managed_metadata_is_lazy_and_read_is_explicit(
    cli_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(cli_project), "inspect", "--managed", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["managed"]["mapping"]["status"] == "exact"
    assert data["managed"]["members"]["items"] == [] and "read" not in data["managed"]
    registry = CliRegistry.instances[-1]
    assert registry.timeout == 0.4 and registry.closed
    assert [name for name, _ in registry.client.calls] == ["resolve", "members"]
    assert (
        main(
            [
                "--root",
                str(cli_project),
                "inspect",
                "--managed",
                "--read-managed",
                "type:Name",
                "--json",
            ]
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["managed"]["read"]["values"][0]["value"]["scalar"] == "Window"
    assert CliRegistry.instances[-1].closed
    assert [name for name, _ in CliRegistry.instances[-1].client.calls] == [
        "resolve",
        "members",
        "read",
    ]


def test_managed_cli_fetches_metadata_pages_before_detaching(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def members(self: FakeClient, object_id: str, generation: int, **kwargs: Any) -> Page[Any]:
        self.calls.append(("members", kwargs))
        if kwargs.get("page_token") is None:
            return Page((), False, "snapshot", (), "next")
        return Page((), True, "snapshot", ())

    monkeypatch.setattr(FakeClient, "members", members)
    assert main(["--root", str(cli_project), "inspect", "--managed", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["managed"]
    assert len(data["memberPages"]) == 2 and data["memberPages"][-1]["complete"]
    assert CliRegistry.instances[-1].closed


def test_managed_cli_rejects_repeated_page_tokens_and_still_detaches(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def members(self: FakeClient, object_id: str, generation: int, **kwargs: Any) -> Page[Any]:
        return Page((), False, "snapshot", (), "same")

    monkeypatch.setattr(FakeClient, "members", members)
    assert main(["--root", str(cli_project), "inspect", "--managed"]) != 0
    assert "pagination did not finish" in capsys.readouterr().err
    assert CliRegistry.instances[-1].closed


@pytest.mark.parametrize("operation", ["attach", "resolve", "members", "read"])
def test_cleanup_after_managed_failures(
    cli_project: Path, capsys: pytest.CaptureFixture[str], operation: str
) -> None:
    CliRegistry.failure = InspectorUnavailableError(
        "Install wintestkit[inspector] or use a supported WPF target", code="payloadMissing"
    )
    CliRegistry.fail_operation = operation
    args = ["--root", str(cli_project), "inspect", "--managed"]
    if operation == "read":
        args += ["--read-managed", "type:Name"]
    assert main(args) != 0
    assert "Install wintestkit[inspector]" in capsys.readouterr().err
    assert CliRegistry.instances[-1].closed


def test_cleanup_on_keyboard_interrupt(cli_project: Path) -> None:
    CliRegistry.failure = KeyboardInterrupt()
    CliRegistry.fail_operation = "members"
    assert main(["--root", str(cli_project), "inspect", "--managed"]) == 130
    assert CliRegistry.instances[-1].closed


def test_read_requires_opt_in_and_uia_only_never_probes(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(cli_project), "inspect", "--read-managed", "type:Name"]) == 2
    assert "requires --managed" in capsys.readouterr().err
    monkeypatch.setattr(probe, "current_identity", _unexpected_probe)
    assert main(["--root", str(cli_project), "inspect", "--json"]) == 0
    assert "managed" not in json.loads(capsys.readouterr().out)
    assert not CliRegistry.instances


def test_extra_redaction_blocks_cli_before_attachment(
    cli_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (cli_project / "wintestkit.local.yaml").write_text(
        "inspector:\n  redact_names: [account]\n", encoding="utf-8"
    )
    assert main(["--root", str(cli_project), "inspect", "--managed"]) != 0
    assert "cannot be enforced" in capsys.readouterr().err
    assert not CliRegistry.instances
