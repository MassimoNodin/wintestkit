"""Set the WinTestKit version in the Python package and the VS Code extension.

Usage:
    python scripts/bump_version.py 0.2.0     # update every version
    python scripts/bump_version.py --check 0.2.0  # exit 1 unless every version equals 0.2.0
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "python/src/wintestkit/__init__.py"
INSPECTOR_INIT = ROOT / "inspector-payload/src/wintestkit_inspector/__init__.py"
PYPROJECT = ROOT / "python/pyproject.toml"
EXTRA_VERSION = re.compile(r'wintestkit-inspector==([^"\]]+)')
PACKAGE = ROOT / "vscode/package.json"
LOCK = ROOT / "vscode/package-lock.json"
POLICY = ROOT / "vscode/src/compatibility.json"
PYTHON_VERSION = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:(a|b|rc)(0|[1-9]\d*)|\.dev(0|[1-9]\d*))?$"
)
INIT_VERSION = re.compile(r'^__version__ = "([^"]*)"$', re.MULTILINE)


def release_version(version: str) -> tuple[tuple[int, ...], bool]:
    match = PYTHON_VERSION.fullmatch(version)
    if not match:
        raise ValueError("Expected canonical X.Y.Z, X.Y.ZaN, X.Y.ZbN, X.Y.ZrcN or X.Y.Z.devN")
    return tuple(int(part) for part in match.group(1, 2, 3)), bool(match.group(4) or match.group(6))


def expected_versions(version: str, extension_version: str | None = None) -> dict[str, str]:
    _, prerelease = release_version(version)
    if prerelease and extension_version is None:
        raise ValueError("Prereleases require an explicit --extension-version X.Y.Z")
    numeric = extension_version or version
    _, numeric_prerelease = release_version(numeric)
    if numeric_prerelease:
        raise ValueError("Extension version must be numeric X.Y.Z")
    return {
        name: version
        if name
        in {
            str(INIT.relative_to(ROOT)),
            str(INSPECTOR_INIT.relative_to(ROOT)),
            str(PYPROJECT.relative_to(ROOT)),
        }
        else numeric
        for name in current()
    }


def current() -> dict[str, str]:
    """The version recorded in each file."""
    match = INIT_VERSION.search(INIT.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    versions = {
        str(INIT.relative_to(ROOT)): match.group(1) if match else "<missing>",
        str(PACKAGE.relative_to(ROOT)): json.loads(PACKAGE.read_text(encoding="utf-8"))["version"],
        str(LOCK.relative_to(ROOT)): lock["version"],
        f"{LOCK.relative_to(ROOT)} (root package)": lock["packages"][""]["version"],
        str(POLICY.relative_to(ROOT)): json.loads(POLICY.read_text(encoding="utf-8"))[
            "extensionVersion"
        ],
    }
    for path, pattern in ((INSPECTOR_INIT, INIT_VERSION), (PYPROJECT, EXTRA_VERSION)):
        if path.exists():
            found = pattern.search(path.read_text(encoding="utf-8"))
            versions[str(path.relative_to(ROOT))] = found.group(1) if found else "<missing>"
    return versions


def _set_json_version(path: Path, version: str, *, lock: bool) -> None:
    # Edit textually so the file keeps its exact formatting; only the leading entries change.
    text = path.read_text(encoding="utf-8")
    count = 2 if lock else 1
    text = re.sub(r'("version":\s*")[^"]*(")', rf"\g<1>{version}\g<2>", text, count=count)
    path.write_text(text, encoding="utf-8", newline="")


def bump(version: str, extension_version: str | None = None) -> None:
    expected = expected_versions(version, extension_version)
    numeric = expected[str(PACKAGE.relative_to(ROOT))]
    _, prerelease = release_version(version)
    init = INIT.read_text(encoding="utf-8")
    INIT.write_text(
        INIT_VERSION.sub(f'__version__ = "{version}"', init, count=1), encoding="utf-8", newline=""
    )
    if INSPECTOR_INIT.exists():
        inspector = INSPECTOR_INIT.read_text(encoding="utf-8")
        INSPECTOR_INIT.write_text(
            INIT_VERSION.sub(f'__version__ = "{version}"', inspector, count=1),
            encoding="utf-8",
            newline="",
        )
    if PYPROJECT.exists():
        project = PYPROJECT.read_text(encoding="utf-8")
        PYPROJECT.write_text(
            EXTRA_VERSION.sub(f"wintestkit-inspector=={version}", project, count=1),
            encoding="utf-8",
            newline="",
        )
    _set_json_version(PACKAGE, numeric, lock=False)
    _set_json_version(LOCK, numeric, lock=True)
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    policy["extensionVersion"] = numeric
    if prerelease:
        policy["channel"] = "prerelease"
    else:
        policy.pop("channel", None)
    POLICY.write_text(
        json.dumps(policy, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="canonical Python version (a leading 'v' is ignored)")
    parser.add_argument("--extension-version", help="numeric X.Y.Z; required for prereleases")
    parser.add_argument("--check", action="store_true", help="only verify the versions")
    args = parser.parse_args(argv)
    version = args.version.removeprefix("v")
    numeric = args.extension_version
    try:
        expected = expected_versions(version, numeric)
    except ValueError as error:
        parser.error(str(error))
    if not args.check:
        bump(version, numeric)
    mismatched = {name: found for name, found in current().items() if found != expected[name]}
    for name, found in mismatched.items():
        print(f"{name}: {found} (expected {expected[name]})", file=sys.stderr)
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if policy.get("channel", "stable") != (
        "prerelease" if release_version(version)[1] else "stable"
    ):
        print("Compatibility channel does not match the Python release", file=sys.stderr)
        return 1
    if not mismatched and not args.check:
        print(f"Version set to {version}")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
