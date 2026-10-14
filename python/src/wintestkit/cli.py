"""Command-line entry point for WinTestKit."""

from wintestkit import __version__


def main() -> int:
    """Print the package version until the full CLI is implemented."""
    print(f"wintestkit {__version__}")
    return 0
