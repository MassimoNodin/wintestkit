# Local Python package installation and update testing

Status: investigation and proposed implementation, 2026-10-19. The first increment now provides a compile-time development build with a Remote/Local wheel selector and explicit wheel installation. Normal builds exclude local installation support. No local feed, publisher or automatic local update discovery is implemented yet.

## Development-only boundary

All further local publishing and update discovery must be compiled into development builds only, never enabled by a workspace setting, environment variable or webview message in a regular VSIX. Production ignores saved development source selections. The development VSIX is explicitly labelled and replaces the regular extension. The baseline below describes behavior before this increment: automatic editable-local detection has now been removed, and the installer now checks workspace trust and acquires its busy lock before resolving arguments. See [development instructions](../development.md#development-only-package-sources) for the implemented selector and its current limits.

## Current behavior

- `vscode/src/python.ts` installs with the selected interpreter using `-m pip install -U wintestkit`. When the current workspace contains `python/pyproject.toml` naming wintestkit, it offers an editable local install instead. This is source development, not release/update testing; it does not work as a reusable feed for other test workspaces.
- `vscode/src/setup/install.ts` captures pip output and serializes installation globally. Failures remain until another attempt starts; they are not scoped to an interpreter or workspace. Concurrent requests can both reach the source-choice prompt before the busy flag is set.
- `vscode/src/settings/testApp.ts` warns only when the installed version is below the extension's version. It does not discover available releases. Installing a newer wheel locally cannot itself trigger an available-update warning in an unchanged VSIX.
- `vscode/src/setup/health.ts` treats any importable package as installed. The minimum-version warning is separate from guided-setup health. `checkWintestkit` imports the package in a fresh process and reads `__version__`; import errors are currently reported as missing.
- Successful installation rechecks setup health, but does not restart an already-running backend. Interpreter-change handling only restarts when the interpreter path changes, not when its installed package changes.
- `python/pyproject.toml` uses Hatchling and derives the distribution version from `python/src/wintestkit/__init__.py`. Requires Python 3.12+, comtypes, Pillow and PyYAML; runtime testing needs Windows and an interactive desktop for UI automation.
- `scripts/bump_version.py` deliberately changes both Python and VSIX versions and accepts only X.Y.Z. It is unsuitable for repeatedly publishing Python-only development builds. `scripts/check_wheel.ps1` already builds and smoke-tests a wheel, but deletes its build output first and destroys its temporary test environment afterward; do not use that output directory as a persistent local feed.

## Recommendation: an explicit local wheel channel

Keep PyPI as the default. Add an opt-in, resource-scoped package source setting (published/local) and a local feed directory. Display the effective source and selected interpreter in the package strip/details. Keep editable installs as a separate development option, never as an implicit substitute for release testing.

A local feed can simply be a directory containing immutable versioned wheels and a small manifest; no package server, credentials or PyPI publication is necessary. A manifest should identify package name, PEP 440 version, wheel basename, SHA-256 and optional build commit. Publish artifacts completely before atomically replacing the manifest. Reject path traversal, unexpected names, incompatible Python/wheel tags and hash mismatches before installation. Do not execute packages just to discover available versions.

Select one exact wheel from that feed and pass its absolute path as an execFile argument to the selected interpreter. Do not use an unqualified `pip install -U wintestkit --find-links ...` alongside PyPI: pip combines candidates without source priority, so a public version can win. Do not use `--extra-index-url` as a local-source preference. Exact wheel selection pins WinTestKit's origin; dependencies may still come from the configured package index. Make that dependency-network behavior explicit.

Provide a separate fully-offline mode only if required: `--no-index --find-links <wheelhouse>` needs compatible wheels for all dependencies too. A wheel-only channel avoids building arbitrary sdists during installation. Missing pip, permissions, externally managed environments, proxy/index failures, unsupported Python, disk space and unavailable feeds must have actionable errors; never silently fall back to PyPI. A uv-created environment may not contain pip: detect that and offer explicit bootstrap or a documented uv installation route, rather than quietly installing into another interpreter.

## Publishing/versioning

Proposed command: a new local publisher that takes an explicit Python version and feed path, stages a copy of the package, changes the staged `__version__`, builds a wheel, validates its metadata/import version, hashes it, then publishes it and the manifest. Include current working-tree source deliberately (the normal need for testing uncommitted changes); record dirty state and do not mutate the checkout or VSIX version. Exclude caches, virtual environments, previous distributions and generated junk from staging. Never overwrite an existing version; a rebuild must get a new identifier.

For repeat testing of the current compatible release, use ordered private builds such as `0.1.1+local.1` then `0.1.1+local.2`. For next-release testing use an explicit development/prerelease channel such as `0.1.2.dev1`; it is earlier than `0.1.2` and must not satisfy a final-release minimum by accident. A future public final release supersedes those development builds. Local identifiers are not for PyPI publication. Keep local artifacts outside the public release pipeline and do not change the current stable-version check without a separate release-policy decision.

The existing numeric splitter is not PEP 440: it collapses alphabetic qualifiers and can equate distinct local labels. Replace it with a PEP 440-capable implementation and test dev/alpha/beta/rc/post/local, epochs, normalized forms and invalid versions. Do not depend on the target environment already having the third-party `packaging` module merely to compare versions; choose a maintained extension-side implementation, or ship an explicitly managed helper. Avoid private pip internals.

## Update warning behavior

Track three separate values: installed, extension minimum, and newest compatible release in the selected channel. A newer local feed build should show, for example, 'Local update available: 0.1.1+local.2' even with the same VSIX. An installed package below the extension minimum remains a compatibility warning. A missing/incompatible feed is a source error, not 'already up to date'. A newer installed package is not automatically downgraded.

Resolve the feed on activation, source/interpreter changes, explicit refresh and debounced directory/manifest changes. Use a modest refresh fallback for network shares or missed events, not constant pip/network probes. Scope cached availability and failures by interpreter, workspace and source; discard stale async responses when any changes. Deduplicate notifications and retain dismissal per candidate version. Only probe/install in a trusted workspace; do not allow a repository setting or manifest to run arbitrary installer commands.

Use the same resolved candidate for the strip, warning and install action. Revalidate it before execution and show a changed-candidate state rather than installing something different silently. The existing Install/Update/Try again button should use the configured channel. Do not add a second competing install button to the tour.

## Runtime safety and recovery

- Acquire the installation lock before prompting/resolving candidates. Remember the target interpreter and source for the entire operation. Prevent another project that uses that interpreter from starting tests or a server while installation is active.
- Stop affected servers before replacement, wait for process exit/file release on Windows, then install. Restart the previously active servers only after verifying the new import/version and refreshing health, discovery and Spy state. Include every project sharing the interpreter, not just the active workspace folder.
- Do not interrupt running tests or an application inspection session silently; ask to stop/wait or defer the update. Preserve the existing app attach/launch lifecycle when restarting the backend.
- A pip failure can leave an altered environment; do not assume rollback. Reprobe the actual installed package after both success and failure. Retain the prior wheel for an explicit rollback action and preserve complete logs while showing a concise reason.
- Switching back to published mode needs an explicit reinstall/downgrade path: pip may retain a private local build it considers newer. Keep same-version force-reinstall an explicit repair action, not the update mechanism; unnecessary dependency reinstalls can break otherwise working environments.
- A higher version does not prove protocol compatibility. Initially restrict local channel use to builds compatible with the current extension and smoke-test the server handshake; a durable solution needs explicit backend protocol compatibility metadata independent of UI/package release numbers.

## Manual local installation available today

In a development checkout, `uv build --directory python` builds the current version into `python/dist`. With the extension's selected Python executable, install the exact resulting wheel using `<python.exe> -m pip install --upgrade <absolute-wheel-path>`. For a changed wheel with the same version, an explicit force-reinstall is needed; prefer unique versions for update testing. This manual path does not add availability warnings. Restart the extension backend after replacement, then recheck setup. Use an isolated test environment, not the development environment or a global Python.

## Acceptance tests before shipping the channel

1. Publish build 1 to a fresh feed; install through the existing strip into a clean Python 3.12+ venv; verify metadata, CLI, pytest plugin and server startup.
2. Publish build 2 without rebuilding the VSIX; verify exactly one new-version warning, the correct source/version, then update and verify the live server uses build 2.
3. Exercise editable-to-wheel, wheel-to-published, intentional rollback and same-version repair; ensure source checkout does not shadow the installed wheel.
4. Cover paths with spaces/non-ASCII, absent or partially copied feeds, malformed manifests, wrong hashes/package names/tags, incompatible Python, missing pip and dependency/network failure.
5. Cover untrusted workspaces, interpreter/source switches during probes, multiple roots sharing an interpreter, double clicks, active tests and a locked backend process.
6. Unit-test source resolution, real PEP 440 ordering, warning/dismissal state, stale-result rejection, install arguments and stop/install/reprobe/restart sequencing. Add integration tests with two real locally built wheels; do not publish to PyPI.

## Scope and primary references

Suggested implementation order: local build/publisher and immutable artifacts; source/candidate resolver plus PEP 440 tests; installer lifecycle/trust fixes; update strip and refresh/dismissal behavior; end-to-end two-wheel test and documentation. A custom HTTP package index is unnecessary for the first version.

- [pip install: local archives, package source selection, no-index and pre-releases](https://pip.pypa.io/en/stable/cli/pip_install/)
- [pip: regular versus editable local project installs](https://pip.pypa.io/en/stable/topics/local-project-installs/)
- [Python packaging: version specifiers and local/development versions](https://packaging.python.org/en/latest/specifications/version-specifiers/)
- [uv: building and publishing packages](https://docs.astral.sh/uv/guides/package/)
