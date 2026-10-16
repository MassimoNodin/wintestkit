"""Copy the canonical agent skill (``skills/wintestkit-tests``) to the places that ship it.

The canonical copy is ``skills/wintestkit-tests``. The copies are the packaged data that
``wtk init`` writes into new projects and the Calculator example's own ``.claude`` folder.
A unit test fails when a copy differs from the canonical one.

Usage:
    python scripts/sync_skill.py          # overwrite the copies
    python scripts/sync_skill.py --check  # exit 1 if a copy differs
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "skills/wintestkit-tests"
COPIES = (
    ROOT / "python/src/wintestkit/scaffold/skills/wintestkit-tests",
    ROOT / "examples/calculator-tests/.claude/skills/wintestkit-tests",
)


def files(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = files(SOURCE)
    status = 0
    for copy in COPIES:
        if copy.exists() and files(copy) == expected:
            continue
        if args.check:
            print(f"differs from {SOURCE.relative_to(ROOT)}: {copy.relative_to(ROOT)}")
            status = 1
            continue
        if copy.exists():
            shutil.rmtree(copy)
        shutil.copytree(SOURCE, copy)
        print(f"updated {copy.relative_to(ROOT)}")
    return status


if __name__ == "__main__":
    sys.exit(main())
