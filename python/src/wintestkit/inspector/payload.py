"""Locate and validate the optional inspector distribution."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, cast

from wintestkit import __version__
from wintestkit.errors import InspectorUnavailableError


def _mismatch(message: str) -> InspectorUnavailableError:
    return InspectorUnavailableError(message, code="payloadMismatch")


def _object(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(cast(dict[str, Any], value)) != keys:
        raise _mismatch("Invalid inspector manifest fields")
    return cast(dict[str, Any], value)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate manifest key")
        result[key] = value
    return result


def _path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise _mismatch("Invalid inspector payload path")
    posix = PurePosixPath(value)
    if (
        posix.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or any(part in (".", "..") for part in value.split("/"))
        or ":" in value
    ):
        raise _mismatch("Invalid inspector payload path")
    candidate = root
    for part in posix.parts:
        candidate = candidate / part
        try:
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise _mismatch("Inspector payload contains a reparse point")
        except FileNotFoundError:
            pass
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise _mismatch("Inspector payload path escapes its root")
    return candidate


@dataclass(frozen=True)
class Payload:
    root: Path
    manifest: Mapping[str, Any]
    inspector_version: str
    signed: bool

    def launcher_for(self, architecture: Literal["x86", "x64"]) -> Path:
        return _path(self.root, self.manifest["launchers"][architecture])

    def agent_for(self, runtime: Literal["net48", "net8", "net10"]) -> Path:
        return _path(self.root, self.manifest["agents"][runtime])

    def verify(self) -> None:
        for entry in self.manifest["files"]:
            path = _path(self.root, entry["path"])
            digest = hashlib.sha256()
            try:
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError as error:
                raise _mismatch(f"Cannot read inspector payload file: {path}") from error
            if digest.hexdigest() != entry["sha256"]:
                raise _mismatch(f"Inspector payload hash mismatch: {path}")


def load_payload() -> Payload:
    try:
        root = Path(str(resources.files("wintestkit_inspector") / "payload"))
    except ModuleNotFoundError as error:
        raise InspectorUnavailableError(
            f"Install wintestkit[inspector]=={__version__}", code="payloadMissing"
        ) from error
    try:
        manifest_path = _path(root, "manifest.json")
        manifest = _object(
            json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_pairs),
            {
                "schemaVersion",
                "inspectorVersion",
                "protocolMajor",
                "protocolMinor",
                "sourceCommit",
                "upstreamCommit",
                "signed",
                "cells",
                "launchers",
                "agents",
                "files",
                "notices",
            },
        )
        if manifest["inspectorVersion"] != __version__:
            raise _mismatch(
                f"Inspector version mismatch; reinstall wintestkit[inspector]=={__version__}"
            )
        if (
            type(manifest["schemaVersion"]) is not int
            or manifest["schemaVersion"] != 1
            or type(manifest["protocolMajor"]) is not int
            or manifest["protocolMajor"] != 1
            or type(manifest["protocolMinor"]) is not int
            or manifest["protocolMinor"] != 0
            or type(manifest["signed"]) is not bool
            or not all(
                isinstance(manifest[k], str) and manifest[k]
                for k in ("sourceCommit", "upstreamCommit")
            )
        ):
            raise _mismatch("Invalid inspector manifest metadata")
        launchers = _object(manifest["launchers"], {"x86", "x64"})
        agents = _object(manifest["agents"], {"net48", "net8", "net10"})
        cells = manifest["cells"]
        if not isinstance(cells, list) or len(cast(list[Any], cells)) != 6:
            raise _mismatch("Invalid inspector cells")
        cells = cast(list[Any], cells)
        seen: set[tuple[str, str]] = set()
        for cell in cells:
            cell = _object(cell, {"runtime", "architecture", "verified"})
            if (
                cell["runtime"] not in agents
                or cell["architecture"] not in launchers
                or type(cell["verified"]) is not bool
            ):
                raise _mismatch("Invalid inspector cell")
            seen.add((cell["runtime"], cell["architecture"]))
        if len(seen) != 6:
            raise _mismatch("Duplicate inspector cell")
        files = manifest["files"]
        notices = manifest["notices"]
        if not isinstance(files, list) or not files or not isinstance(notices, list) or not notices:
            raise _mismatch("Invalid inspector files or notices")
        files = cast(list[Any], files)
        notices = cast(list[Any], notices)
        paths: set[str] = set()
        for entry in files:
            entry = _object(entry, {"path", "sha256"})
            _path(root, entry["path"])
            if (
                entry["path"] in paths
                or not isinstance(entry["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            ):
                raise _mismatch("Invalid inspector file digest")
            paths.add(entry["path"])
        for value in [*launchers.values(), *agents.values(), *notices]:
            _path(root, value)
            if value not in paths:
                raise _mismatch("Inspector referenced file is not listed")
        return Payload(root, manifest, manifest["inspectorVersion"], manifest["signed"])
    except InspectorUnavailableError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise _mismatch(f"Invalid inspector payload manifest: {error}") from error


def payload_status() -> dict[str, object]:
    status: dict[str, object] = {
        "installed": False,
        "version": None,
        "matches": False,
        "signed": False,
        "controller_architecture": platform.machine(),
    }
    try:
        payload = load_payload()
        status.update(installed=True, version=payload.inspector_version, signed=payload.signed)
        payload.verify()
        status["matches"] = True
    except Exception:
        pass
    return status
