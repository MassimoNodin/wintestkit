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
PACKAGE = ROOT / "vscode/package.json"
LOCK = ROOT / "vscode/package-lock.json"
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
INIT_VERSION = re.compile(r'^__version__ = "([^"]*)"$', re.MULTILINE)


def current() -> dict[str, str]:
    """The version recorded in each file."""
    match = INIT_VERSION.search(INIT.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    return {
        str(INIT.relative_to(ROOT)): match.group(1) if match else "<missing>",
        str(PACKAGE.relative_to(ROOT)): json.loads(PACKAGE.read_text(encoding="utf-8"))["version"],
        str(LOCK.relative_to(ROOT)): lock["version"],
        f"{LOCK.relative_to(ROOT)} (root package)": lock["packages"][""]["version"],
    }


def _set_json_version(path: Path, version: str, *, lock: bool) -> None:
    # Edit textually so the file keeps its exact formatting; only the leading entries change.
    text = path.read_text(encoding="utf-8")
    count = 2 if lock else 1
    text = re.sub(r'("version":\s*")[^"]*(")', rf"\g<1>{version}\g<2>", text, count=count)
    path.write_text(text, encoding="utf-8", newline="")


def bump(version: str) -> None:
    init = INIT.read_text(encoding="utf-8")
    INIT.write_text(
        INIT_VERSION.sub(f'__version__ = "{version}"', init, count=1), encoding="utf-8", newline=""
    )
    _set_json_version(PACKAGE, version, lock=False)
    _set_json_version(LOCK, version, lock=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="X.Y.Z (a leading 'v' is ignored)")
    parser.add_argument("--check", action="store_true", help="only verify the versions")
    args = parser.parse_args(argv)
    version = args.version.removeprefix("v")
    if not VERSION.match(version):
        parser.error(f"invalid version {args.version!r}; expected X.Y.Z")
    if not args.check:
        bump(version)
    mismatched = {name: found for name, found in current().items() if found != version}
    for name, found in mismatched.items():
        print(f"{name}: {found} (expected {version})", file=sys.stderr)
    if not mismatched and not args.check:
        print(f"Version set to {version}")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
