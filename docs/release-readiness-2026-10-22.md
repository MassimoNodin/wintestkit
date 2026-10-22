# 0.1 prerelease audit - 2026-10-22

Reviewed commit: `95ec65f1806ec097fd0e9125c4123ce5556781ed`.

At the original audit, builds and unit/contract checks passed, but public release
needed the privacy, input-safety, publishing and desktop-acceptance work below.
The audit itself changed no implementation, published no package and installed no
extension. The remediation status below supersedes that original snapshot. This is not an exhaustive
guarantee that no other defects exist.

## Remediation status - 2026-10-22

The original findings below are preserved as the audit record. Implementation is
in the shared checkout, without a commit, push, publication, extension install or
account/settings change. No real synthetic desktop input was used.

| Finding | Current status |
|---|---|
| 1 | Implemented: resolved `IsPassword`, explicit `secret=True`, redacted recorded arguments and sensitive assertion/action errors; regressions added. Source code and screenshot pixels are not redacted. |
| 2 | Implemented: fail closed on activation failure, changed foreground/process ownership, wrong mouse hit window or absent keyboard focus; mocked input regressions. Focus checks cannot eliminate OS-level races. |
| 3 | Implemented: installer probes pip before installation and gives safely quoted, selected-interpreter-specific uv instructions for pip-less environments, without silently bootstrapping or mutating them. |
| 4 | Implemented: canonical Python a/b/rc/dev versions, explicit numeric VSIX version selection, optional prerelease channel, compatibility bounds and installer `--pre`, VSIX/GitHub channel flags. No candidate version selected. |
| 5 | Implemented: independent PyPI, Marketplace, Open VSX and public VSIX opt-ins; public VSIX CI artifacts and release assets withheld by default. Registry jobs build their own extension packages. |
| 6 | Code gates resolved; external setup remains USER-ONLY: migrate `PUBLISH_PYPI` to repository scope and configure/verify the exact PyPI trusted publisher. Azure/Open VSX credentials are unnecessary while those destinations are disabled. |
| 7 | Guard implemented: release notes reject nonempty Unreleased content or an undated candidate. Candidate version/date/notes intentionally remain a release decision, not a fabricated ready-to-publish release. |
| 8 | Implemented: packaging generates bundled third-party notices from dependency license texts, including yaml, Python extension API, smol-toml and Codicons content/code attribution. |
| 9 | Implemented: normalized Windows path comparisons for editor decorations and relocation actions; slash/case regressions. |
| 10 | Implemented: discovery rebuild is deferred during active runs, preserving parameterized runtime items until results finish. |
| 11 | Implemented: retention excludes active reports, including simultaneous projects; temporary excess retention is permitted. |
| 12 | Implemented: test/debug/flow execution requires explicit Save and Run consent for dirty project Python sources; cancellation or failed saves block execution. |
| 13 | Implemented: COM initialization is per calling thread; existing apartments handled explicitly. Non-UI native STA/fresh-worker probe passes. |
| 14 | Implemented: finite socket writes disconnect on backpressure rather than blocking emit/close indefinitely; regressions added. |
| 15 | Implemented: no-report suppresses automatic capture artifacts, including failure/step screenshots, replay, UI trees and object previews. Explicit test-authored captures and event/JUnit outputs are separate. |
| 16 | Stale activation/view/command assumptions and activation types repaired. Compilation/unit checks are not extension-host or installed WPF acceptance; those and ARM64 runtime remain outstanding. |

See [release setup](releasing.md) for exact user-only configuration and candidate
staging steps. Public Python publication must not be confused with private binary
distribution: keep all extension/public-VSIX opt-ins disabled for personal use.

## Fix before public release

1. **Password disclosure.** ID-only password locators record raw typed text because
   redaction recognizes only class_name PasswordBox. Failing password assertions
   also leak expected secrets through errors despite redacted arguments. Both
   reproduced safely with mocked sentinel input. Detect resolved IsPassword or
   explicit sensitivity; propagate redaction through errors and assertions.
   References: python/src/wintestkit/model.py:573, python/src/wintestkit/model.py:994,
   python/src/wintestkit/expect.py:167, python/src/wintestkit/runtime.py:266.
2. **Foreground failure permits mouse input.** bring_to_front false is ignored
   before global coordinate injection. Mocked activation failure still emitted a
   click; no actual wrong-window click was attempted. Fail closed and validate
   the target window before synthetic input.
   References: python/src/wintestkit/engine/actions.py:99,
   python/src/wintestkit/engine/actions.py:131.
3. **Pip-less guided installation fails.** Always invokes -m pip, absent in valid
   uv environments including this repository. Probe returned No module named pip.
   Support another installer/bootstrap path or actionable alternative instructions.
   References: vscode/src/python.ts:107, vscode/src/setup/install.ts:58.

## Publishing gates

4. **Formal prereleases unsupported.** Current packages are 0.1.1. Version/tag
   checks require stable X.Y.Z, compatibility rejects Python alpha/beta/rc/dev
   versions, installation has no prerelease opt-in, and VSIX/GitHub publication
   omit prerelease flags. Decide experimental normal 0.1.x versus formal
   prerelease. For the latter, map Python PEP 440 to VS Code numeric versions plus
   channel metadata; update shared-version assumptions, compatibility and installer.
   References: scripts/bump_version.py:21, scripts/check_release.py:22,
   .github/workflows/release.yml:45, vscode/src/compatibility.ts:14,
   vscode/src/python.ts:107, .github/workflows/release.yml:115,
   .github/workflows/release.yml:171, .github/workflows/release.yml:203.
5. **Publication coupled.** Common preflight requires PyPI enablement and Marketplace
   identity. Marketplace follows PyPI; GitHub releases upload VSIX files. Separate
   publication and credential gates, including artifact uploads, to permit public
   Python/private extension.
   References: scripts/check_release.py:64, scripts/check_release.py:66,
   .github/workflows/release.yml:122, .github/workflows/release.yml:141.
6. **Credentials incomplete.** Read-only GitHub inspection found release-environment
   PUBLISH_PYPI=true, repository PUBLISH_OVSX=false, no repository/release-environment
   secrets, and missing AZURE_CLIENT_ID/AZURE_TENANT_ID. Current preflight blocks
   before PyPI too. Externally verify PyPI trusted publisher/package ownership and
   authorization for Marketplace publisher wintestkit. PyPI metadata 404 does not
   establish package-name availability or publishing authorization.
7. **Notes unstaged.** Substantial Unreleased changes coexist with older 0.1.1
   notes; checker can accept old notes and omit newer work. Choose/date candidate
   notes and align installation docs with actual distribution/channel policy.
   References: vscode/CHANGELOG.md:6, vscode/CHANGELOG.md:120.
8. **Third-party notices incomplete.** Built VSIX includes project MIT and smol-toml
   BSD notices but lacks upstream yaml ISC, Python extension API MIT and Codicons
   license texts/attribution. Include appropriate bundled-code/asset notices,
   respecting Codicons content/code licensing. This is not a legal opinion.
   References: vscode/esbuild.mjs:4, vscode/esbuild.mjs:22, built VSIX contents.

## Fix or explicitly accept for this candidate

9. **Windows paths suppress feedback.** Direct POSIX backend path/native fsPath
   comparison loses decorations and relocation fixes. Normalize and test Windows
   slash/drive-letter shapes.
   References: vscode/src/editor/decorations.ts:148,
   vscode/src/editor/relocationActions.ts:20, python/src/wintestkit/discovery.py:1000.
10. **Refresh loses parameterized results.** Refresh removes runtime items while
    mapper remembers them as created, so later status updates are skipped. An
    in-memory collect/refresh/test-end probe lost its passing event. Preserve
    active items or a run-specific map.
    References: vscode/src/testing/controller.ts:137,
    vscode/src/testing/controller.ts:398, vscode/src/testing/eventMapper.ts:30.
11. **Retention deletes active reports.** Starting B with retention one can delete
    A's running report; mocked filesystem reproduction confirmed. Exclude active
    runs and temporarily exceed retention when necessary.
    References: vscode/src/testing/controller.ts:453,
    vscode/src/testing/controller.ts:461, vscode/src/runHistory.ts:212.
12. **Unsaved discovery/saved execution mismatch.** Discovery consumes dirty buffers
    but subprocess execution reads disk without saving/prompting. New tests can
    fail collection; unsaved assertions may misleadingly pass their old body.
    Save with consent or explicitly warn about saved-only execution.
    References: vscode/src/discovery/store.ts:42, vscode/src/testing/controller.ts:465,
    vscode/src/testing/controller.ts:530.
13. **COM workers uninitialized.** Nonzero process sys.coinit_flags skips COM init
    but marks fresh threads initialized. Native non-UI STA/fresh-worker probe
    returned 0x800401F0 from CoGetApartmentType. Initialize each thread independently
    and handle existing apartments explicitly.
    References: python/src/wintestkit/uia/com.py:50, python/src/wintestkit/uia/com.py:66.
14. **Event emission hangs.** No-timeout sendall holds the lock required by close.
    Connected nonreading loopback receiver reproduced a stall. Use finite writes
    or a bounded sender and disconnect on backpressure.
    References: python/src/wintestkit/events.py:71, python/src/wintestkit/events.py:94.
15. **No-report still screenshots.** Default failure capture reaches full desktop
    even without app fixture. Mocked hook confirmed call; no image taken. Decide
    semantics and gate capture or document/provide an unmistakable no-artifacts
    option. --screenshots off is a current workaround.
    References: python/src/wintestkit/pytest_plugin.py:427,
    python/src/wintestkit/artifacts.py:101.

## Acceptance gap

16. **Stale extension-host tests.** Calls setup webview getChildren, expects obsolete
    Tests section and removed run/debug commands; activation any typing masks
    errors. Suite is loaded but CI does not run the extension-host acceptance path.
    Repair and run; then test installed VSIX plus installed wheel against real WPF.
    References: vscode/test/integration/suite/activation.test.ts:44,
    vscode/test/integration/suite/activation.test.ts:63,
    vscode/test/integration/suite/activation.test.ts:72, vscode/src/extension.ts:106.

Native desktop integration, extension-host integration and ARM64 runtime were not
run. ARM64 packaging success is not runtime verification.

## Original baseline validation completed

- Python 3.13.5 and isolated 3.12/minimum dependencies: each 1,201 passed,
  1 skipped, 14 integration tests deselected. Ruff/Pyright passed.
- Wheel from sdist, strict Twine, clean Python 3.12 install, dependencies,
  CLI/version/doctor and pytest-plugin smoke checks passed.
- Extension: 742 tests/62 files, ESLint, TypeScript and minimum VS Code 1.95 API
  compile probe passed. Generated contracts clean; npm audit zero vulnerabilities.
- x64/ARM64 VSIX builds and stable 0.1.1 version/compatibility checks passed.
- Latest inspected HEAD CI succeeded; no Release workflow run found.

Built artifacts, not uploaded:

- python/dist/wintestkit-0.1.1-py3-none-any.whl
- python/dist/wintestkit-0.1.1.tar.gz
- vscode/dist/wintestkit-win32-x64-0.1.1.vsix
- vscode/dist/wintestkit-win32-arm64-0.1.1.vsix

## Personal-only extension

Keep VSIX locally or in private storage and sideload instead of Marketplace/Open
VSX. Existing x64 build installation command, from repository root:

    code --install-extension .\vscode\dist\wintestkit-win32-x64-0.1.1.vsix

Command not executed. Marketplace prerelease is a channel, not an account allowlist.
Enterprise Private Marketplace exists but is excessive for solo use. Public CI
uploads VSIX artifacts (.github/workflows/ci.yml:91), downloadable by signed-in
readers. Release assets can expose VSIX too. Disable those paths or build privately.
Public MIT source cannot prevent others building and using their own copies.

## Release checklist

- [x] Implement 1-3 and 9-15 with regression coverage.
- [x] Implement explicit version/channel support and independent publication/public-artifact controls.
- [ ] Select actual candidate versions and stage/date its release notes.
- [ ] Verify accounts, trusted publishing and credentials.
- [x] Package third-party notices; prevent stale candidate notes from passing release validation.
- [x] Repair and compile extension-host tests.
- [ ] Run extension-host, clean-install WPF and ARM64 runtime acceptance.
- [ ] Dry-run final workflow; verify staged Python upload/install.
- [ ] Publish selected channels only; retain extension binaries privately.
