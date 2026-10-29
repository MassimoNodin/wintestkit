import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from wintestkit import __version__
from wintestkit.errors import InspectorUnavailableError
from wintestkit.inspector import payload


@pytest.fixture
def tree(tmp_path, monkeypatch):
    root = tmp_path / "payload"
    root.mkdir()
    paths = ["x86.exe", "x64.exe", "net48.dll", "net8.dll", "net10.dll", "notice.txt"]
    for path in paths:
        (root / path).write_bytes(path.encode())
    manifest = {
        "schemaVersion": 1,
        "inspectorVersion": __version__,
        "protocolMajor": 1,
        "protocolMinor": 0,
        "sourceCommit": "a",
        "upstreamCommit": "b",
        "signed": False,
        "cells": [
            {"runtime": r, "architecture": a, "verified": False}
            for r in ("net48", "net8", "net10")
            for a in ("x86", "x64")
        ],
        "launchers": {"x86": paths[0], "x64": paths[1]},
        "agents": dict(zip(("net48", "net8", "net10"), paths[2:5], strict=True)),
        "files": [{"path": p, "sha256": hashlib.sha256(p.encode()).hexdigest()} for p in paths],
        "notices": [paths[5]],
    }

    def write():
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    write()
    monkeypatch.setattr(payload.resources, "files", lambda _: tmp_path)
    return SimpleNamespace(root=root, manifest=manifest, write=write)


def test_success_and_status(tree):
    result = payload.load_payload()
    result.verify()
    assert result.launcher_for("x86") == tree.root / "x86.exe"
    assert result.agent_for("net10") == tree.root / "net10.dll"
    status = payload.payload_status()
    assert status == {
        "installed": True,
        "version": __version__,
        "matches": True,
        "signed": False,
        "controller_architecture": payload.platform.machine(),
    }
    (tree.root / "x86.exe").write_bytes(b"tampered")
    with pytest.raises(InspectorUnavailableError, match="hash mismatch"):
        result.verify()
    assert payload.payload_status()["matches"] is False


def test_missing_package(monkeypatch):
    def missing(_):
        raise ModuleNotFoundError("missing")

    monkeypatch.setattr(payload.resources, "files", missing)
    with pytest.raises(InspectorUnavailableError) as exc:
        payload.load_payload()
    assert exc.value.code == "payloadMissing"
    assert payload.payload_status()["installed"] is False


def test_missing_manifest(tree):
    (tree.root / "manifest.json").unlink()
    with pytest.raises(InspectorUnavailableError):
        payload.load_payload()


@pytest.mark.parametrize("change", ["unknown", "malformed", "version", "traversal", "absolute"])
def test_invalid_manifest(tree, change):
    if change == "unknown":
        tree.manifest["extra"] = 1
    if change == "malformed":
        tree.manifest["cells"] = []
    if change == "version":
        tree.manifest["inspectorVersion"] = "9.9.9"
    if change == "traversal":
        tree.manifest["files"][0]["path"] = "../escape"
    if change == "absolute":
        tree.manifest["files"][0]["path"] = "C:/escape"
    tree.write()
    with pytest.raises(InspectorUnavailableError):
        payload.load_payload()


def test_junction_rejected(tree, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    junction = tree.root / "junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)], capture_output=True
    )
    if result.returncode:
        pytest.skip("Creating a Windows junction is not permitted")
    tree.manifest["files"][0]["path"] = "junction/file"
    tree.write()
    with pytest.raises(InspectorUnavailableError, match="reparse"):
        payload.load_payload()


def test_real_staged_payload(monkeypatch):
    package = Path(__file__).resolve().parents[3] / "inspector-payload/src/wintestkit_inspector"
    if not (package / "payload/manifest.json").is_file():
        pytest.skip("No staged inspector payload")
    monkeypatch.setattr(payload.resources, "files", lambda _: package)
    payload.load_payload().verify()
