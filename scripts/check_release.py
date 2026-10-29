"""Validate release notes and publishing configuration without exposing credentials."""

from __future__ import annotations

import argparse
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = runpy.run_path(str(ROOT / "scripts/bump_version.py"))


def validate_compatibility(
    policy: dict, extension_version: str, python_version: str, protocol: int, schema_protocol: int
) -> None:
    def version(value: object) -> tuple[int, ...]:
        if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
            raise ValueError("Compatibility versions must be stable X.Y.Z releases")
        return tuple(int(part) for part in value.split("."))

    minimum = version(policy["python"]["minimum"])
    maximum = version(policy["python"]["maximumExclusive"])
    if minimum >= maximum:
        raise ValueError("Compatibility minimum must be below maximumExclusive")
    if policy["extensionVersion"] != extension_version:
        raise ValueError("Compatibility extensionVersion does not match the extension manifest")
    python_release, prerelease = VERSIONS["release_version"](python_version)
    channel = policy.get("channel", "stable")
    if channel not in ("stable", "prerelease") or prerelease != (channel == "prerelease"):
        raise ValueError("Compatibility channel must match the Python release channel")
    if not minimum <= python_release < maximum:
        raise ValueError("Released Python version is outside the supported compatibility range")
    version(extension_version)
    protocols = (policy["protocolVersion"], protocol, schema_protocol)
    if any(type(value) is not int or value < 1 for value in protocols) or len(set(protocols)) != 1:
        raise ValueError("Compatibility, backend, and schema protocol versions must match")


def check_compatibility() -> None:
    policy = json.loads((ROOT / "vscode/src/compatibility.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "vscode/package.json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas/rpc.schema.json").read_text(encoding="utf-8"))
    backend = runpy.run_path(str(ROOT / "python/src/wintestkit/protocol.py"))
    package = runpy.run_path(str(ROOT / "python/src/wintestkit/__init__.py"))
    validate_compatibility(
        policy,
        manifest["version"],
        package["__version__"],
        backend["PROTOCOL_VERSION"],
        schema["$defs"]["InitializeResult"]["properties"]["protocolVersion"]["const"],
    )


def check_inspector() -> None:
    versions = {name.replace("\\", "/"): value for name, value in VERSIONS["current"]().items()}
    names = (
        "python/src/wintestkit/__init__.py",
        "inspector-payload/src/wintestkit_inspector/__init__.py",
        "python/pyproject.toml",
    )
    if len({versions[name] for name in names}) != 1 or "<missing>" in (
        versions[name] for name in names
    ):
        raise ValueError("Core, inspector and extra pin versions must match")
    project = tomllib.loads((ROOT / "python/pyproject.toml").read_text(encoding="utf-8"))
    wheel = (
        project.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
    )
    if (
        wheel.get("pure-python", True) is not True
        or wheel.get("tag", "py3-none-any") != "py3-none-any"
    ):
        raise ValueError("Core wheel must be py3-none-any")
    with tempfile.TemporaryDirectory(prefix="wtk-release-wheel-") as directory:
        result = subprocess.run(
            ["uv", "build", "--directory", str(ROOT / "python"), "--wheel", "--out-dir", directory],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise ValueError(f"Core wheel build failed: {result.stderr.strip()}")
        wheels = list(Path(directory).glob("*.whl"))
        if len(wheels) != 1 or not wheels[0].name.endswith("-py3-none-any.whl"):
            raise ValueError("Core wheel must have the py3-none-any tag")
        with zipfile.ZipFile(wheels[0]) as archive:
            if any(
                name.lower().endswith((".dll", ".exe", ".pyd", ".so"))
                for name in archive.namelist()
            ):
                raise ValueError("Core wheel contains binaries")


def release_notes(changelog: str, version: str) -> str:
    VERSIONS["release_version"](version)
    unreleased = re.search(
        r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## |\Z)", changelog, re.MULTILINE | re.DOTALL
    )
    if unreleased and unreleased.group(1).strip():
        raise ValueError(
            "Move all Unreleased changes into a dated candidate section before releasing"
        )
    pattern = rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, changelog, re.MULTILINE | re.DOTALL)
    if not match or not match.group(1).strip():
        raise ValueError(f"vscode/CHANGELOG.md needs a non-empty [{version}] section")
    if not re.fullmatch(
        rf"## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}", match.group(0).splitlines()[0]
    ):
        raise ValueError(f"Release [{version}] needs a dated YYYY-MM-DD heading")
    return match.group(1).strip() + "\n"


def missing_configuration(environment: Mapping[str, str]) -> list[str]:
    missing = []
    for gate in ("PUBLISH_PYPI", "PUBLISH_MARKETPLACE", "PUBLISH_OVSX", "PUBLISH_PUBLIC_VSIX"):
        if environment.get(gate, "") not in ("", "true", "false"):
            missing.append(f"{gate}=true or false (repository variable)")
    if environment.get("PUBLISH_MARKETPLACE") == "true":
        for name in ("AZURE_CLIENT_ID", "AZURE_TENANT_ID"):
            if not environment.get(name, "").strip():
                missing.append(f"{name} (environment secret)")
    if environment.get("PUBLISH_OVSX") == "true" and not environment.get("OVSX_TOKEN", "").strip():
        missing.append("OVSX_TOKEN (environment secret)")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    notes = commands.add_parser("notes")
    notes.add_argument("version")
    notes.add_argument("--output", type=Path, required=True)
    commands.add_parser("config")
    commands.add_parser("compatibility")
    commands.add_parser("inspector")
    args = parser.parse_args()
    if args.command == "inspector":
        try:
            check_inspector()
        except (ValueError, KeyError, TypeError) as error:
            print(f"Inspector release policy is invalid: {error}", file=sys.stderr)
            return 1
        print("Inspector versions and core wheel configuration are consistent.")
    elif args.command == "compatibility":
        try:
            check_compatibility()
        except (ValueError, KeyError, TypeError) as error:
            print(f"Compatibility policy is invalid: {error}", file=sys.stderr)
            return 1
        print("Compatibility policy, release versions, and protocol are consistent.")
    elif args.command == "notes":
        try:
            text = release_notes(
                (ROOT / "vscode/CHANGELOG.md").read_text(encoding="utf-8"), args.version
            )
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        args.output.write_text(text, encoding="utf-8")
    else:
        missing = missing_configuration(os.environ)
        if missing:
            print("Release publishing is not configured:", file=sys.stderr)
            for setting in missing:
                print(f"- {setting}", file=sys.stderr)
            return 1
        print(
            "Required publishing settings are present; registry authorization is checked on upload."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
