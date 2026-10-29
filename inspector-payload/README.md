# WinTestKit inspector payload

This Windows-only data distribution is installed by `wintestkit[inspector]`.
Run `scripts/build_inspector.ps1` from the repository root before building its wheel.
The package version is a literal updated alongside the core version by
`scripts/bump_version.py`; this also allows independent source distribution builds.
The sdist places the inspector sources and build scripts under `rebuild/` because
Hatch cannot package sibling paths as normal project files. To rebuild from an sdist,
copy `rebuild/wpf-inspector` and `rebuild/scripts` into a matching repository checkout,
then run the build script there; it also requires the core Python sources and build tools.
