"""Validate release notes and publishing configuration without exposing credentials."""

from __future__ import annotations

import argparse
import json
import os
import re
import runpy
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
    if not minimum <= version(python_version) < maximum:
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


def release_notes(changelog: str, version: str) -> str:
    pattern = rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, changelog, re.MULTILINE | re.DOTALL)
    if not match or not match.group(1).strip():
        raise ValueError(f"vscode/CHANGELOG.md needs a non-empty [{version}] section")
    return match.group(1).strip() + "\n"


def missing_configuration(environment: Mapping[str, str]) -> list[str]:
    missing = []
    if environment.get("PUBLISH_PYPI") != "true":
        missing.append("PUBLISH_PYPI=true (environment variable)")
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
    args = parser.parse_args()
    if args.command == "compatibility":
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
