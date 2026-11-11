"""Tests for selecting a usable desktop-test runtime."""

from pathlib import Path

import pytest
from live_dotnet import live_dotnet_root


def _runtime(root: Path) -> None:
    for framework in ("Microsoft.NETCore.App", "Microsoft.WindowsDesktop.App"):
        (root / "shared" / framework / "10.0.1").mkdir(parents=True)


def test_live_dotnet_prefers_usable_override_then_path(tmp_path, monkeypatch):
    override = tmp_path / "override"
    sdk = tmp_path / "sdk"
    _runtime(override)
    _runtime(sdk)
    monkeypatch.setenv("DOTNET_ROOT", str(override))
    monkeypatch.setattr("live_dotnet.shutil.which", lambda _: str(sdk / "dotnet.exe"))
    assert live_dotnet_root() == str(override)
    (override / "shared" / "Microsoft.WindowsDesktop.App" / "10.0.1").rmdir()
    assert live_dotnet_root() == str(sdk)


def test_live_dotnet_reports_tried_paths(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    monkeypatch.setenv("DOTNET_ROOT", str(missing))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr("live_dotnet.shutil.which", lambda _: None)
    # Isolate the fallback from any real installation on the test machine.
    monkeypatch.setattr("live_dotnet.Path.glob", lambda *_: iter(()))
    with pytest.raises(RuntimeError, match=r"No x64 \.NET 10") as error:
        live_dotnet_root()
    assert str(missing) in str(error.value)
    assert r"C:\Program Files\dotnet" in str(error.value)
