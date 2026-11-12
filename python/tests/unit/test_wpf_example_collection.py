"""Keep the WPF example importable without starting the desktop fixture."""

import subprocess
import sys
from pathlib import Path


def test_wpf_example_collects() -> None:
    example = Path(__file__).resolve().parents[3] / "examples" / "wpf-fixture-tests"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=example,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 tests collected" in result.stdout
