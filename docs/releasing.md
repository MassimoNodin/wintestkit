# Releasing WinTestKit

The Python package and VS Code extension share one version. GitHub Actions publishes the
wheel and source distribution to PyPI, then the Windows x64 and ARM64 VSIX packages to
Visual Studio Marketplace. Open VSX is optional and disabled by default.

## One-time account setup

### PyPI

1. Sign into PyPI, enable two-factor authentication, and save recovery codes.
2. Confirm you can publish the `wintestkit` project. A missing public project does not
   guarantee that its name is available.
3. For the first release, add a **pending trusted publisher** through your account's
   Publishing settings. For an existing project, use its Publishing settings instead.
4. Enter these values exactly:

   | Field | Value |
   | --- | --- |
   | PyPI project | `wintestkit` |
   | GitHub owner | `MassimoNodin` |
   | Repository | `wintestkit` |
   | Workflow filename | `release.yml` |
   | Environment | `release` |

No PyPI API token is needed. The workflow explicitly requires trusted publishing.
See [PyPI's trusted-publisher setup](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

### Visual Studio Marketplace

1. Sign into Marketplace publisher management and create or obtain access to publisher
   ID `wintestkit`. If unavailable, change `vscode/package.json` before first publication;
   the public extension identifier is `publisher.name`.
2. Create a Microsoft Entra publishing identity. The documented managed-identity route
   uses an Azure user-assigned managed identity and requires access to an Azure subscription.
3. Add a federated credential to that identity for **GitHub Actions / Environment**, using:

   | Field | Value |
   | --- | --- |
   | Issuer | `https://token.actions.githubusercontent.com` |
   | Subject | `repo:MassimoNodin/wintestkit:environment:release` |
   | Audience | `api://AzureADTokenExchange` |

4. Add the identity as a member of the Marketplace publisher with the **Contributor**
   role, following Marketplace's identity authorization instructions. For the documented
   managed-identity route, use its Azure resource ID when authorizing it on the publisher.
5. Under GitHub repository **Settings -> Environments -> release -> Environment secrets**, add:
   - `AZURE_CLIENT_ID`: the identity's client ID, not its principal/object ID.
   - `AZURE_TENANT_ID`: its directory/tenant ID.

There is no client password, Marketplace PAT, or separate Azure DevOps pipeline in this
configuration. GitHub OIDC signs into Azure; the locked `vsce` tool uses that credential.
See the [official Marketplace publishing guide](https://code.visualstudio.com/api/working-with-extensions/publishing-extension).

### GitHub settings

The release environment is named `release`. Set its environment variable
`PUBLISH_PYPI=true`. Restrict deployments to tags matching `v*`. Consider required reviewers
if another maintainer can approve; do not configure a solo-maintainer approval deadlock.

Keep `PUBLISH_OVSX=false` as a **repository variable** unless publishing to Open VSX is
intended. To enable it, obtain the namespace and publisher agreement, add `OVSX_TOKEN` to
the release environment, and set the repository variable to `true`. A repository variable
is required because the workflow decides whether to start that job before entering its
environment.

Protect `master` with the `python` and `extension` GitHub Actions checks, block force pushes
and deletion, and protect `v*` tags against update/deletion. Repository administrators may
have an explicit bypass for recovery; use it deliberately. Normal tag creation is permitted.

The publishing preflight checks that required settings are present, not that an external
account has granted access. The registries validate identity authorization on upload.

## Prepare and validate

Do not publish directly from an unreviewed working tree. Finish any unrelated work first,
then choose a new version and run these commands from the repository root:

```powershell
python scripts/bump_version.py X.Y.Z
python scripts/bump_version.py --check X.Y.Z
python scripts/check_release.py compatibility
```

Move the appropriate `[Unreleased]` entries into a non-empty `## [X.Y.Z] - YYYY-MM-DD`
section in `vscode/CHANGELOG.md`. Keep `[Unreleased]` for future changes. The release notes
check runs even during dry runs, so a missing or empty version section fails early.

```powershell
uv sync --directory python --locked
Push-Location python
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -m "not integration"
Pop-Location
./scripts/check_wheel.ps1
Push-Location vscode
npm ci
npm run lint
npm run typecheck
npm test
npm run package
Pop-Location
```

The wheel check rebuilds `python/dist`, builds a wheel **from the source distribution**,
checks metadata with Twine, installs only the wheel in a temporary environment, checks
dependencies and plugin registration, and runs a non-desktop test through the installed CLI.

Install the candidate VSIX into a clean VS Code profile, select a fresh Python environment,
and complete the real installation and WPF smoke test: setup, launch/attach, Spy, Highlight,
Check, test execution, and reports. Repeat for upgrades when a previous version exists.
ARM64-targeted packaging on an x64 runner is not ARM64 runtime testing; verify that platform
on a real ARM64 machine before claiming it is supported. Review minimum VS Code and Python
version compatibility as part of acceptance testing.

Desktop UI tests need an interactive unlocked Windows session; see [the CI guide](guide/ci.md).
Never expose a privileged self-hosted desktop runner to untrusted public pull requests.
Hosted CI runs non-desktop Python and extension unit checks; it does not replace the real
WPF acceptance test or exercise the extension-host integration harness.

## Dry run and publish

1. Review, commit, and push the changes to `master` through your normal review process.
2. In GitHub Actions, run **Release** on `master` with `dry_run=true`. Alternatively:

   ```powershell
   gh workflow run release.yml --ref master -f dry_run=true
   ```

3. Inspect the workflow artifacts: `python-dist`, `vsix-win32-x64`, `vsix-win32-arm64`,
   and `release-notes`. A dry run validates notes, tests, and packages but deliberately
   does **not** access publishing secrets or upload to registries.
4. Tag the validated commit on `master`:

   ```powershell
   git tag -a vX.Y.Z -m "WinTestKit X.Y.Z"
   git push origin vX.Y.Z
   ```

Tag pushes publish automatically. Manual dispatch with `dry_run=false` also requires
selecting a version tag; a branch dispatch fails rather than silently doing nothing.
Release tags must point to commits reachable from the default branch. Version files,
the tag, and the changelog section must agree. Release runs are serialized.

The tagged commit is validated through the reusable CI workflow. Its tested Python
distributions are reused without rebuilding. Publishing configuration is checked before
any upload. PyPI must succeed before Marketplace starts, so new editor installations can
obtain the corresponding Python backend. The GitHub Release is created after both succeed.

Afterward, verify PyPI files, Marketplace targets, GitHub assets, and a clean public
installation of both packages. The extension identifier is `wintestkit.wintestkit` unless
you changed the publisher. Do not treat a green workflow alone as acceptance testing.

## Compatibility policy

The extension bundles `vscode/src/compatibility.json`. Version 0.1.1 supports stable Python
packages `>=0.1.1,<0.2.0` with RPC protocol `1`. Missing, malformed, development and prerelease
versions are rejected. Post-releases and local builds within the range are supported.

`scripts/bump_version.py` updates the policy's extension version, but deliberately does not
widen its Python bounds. Review those bounds on every release: the minimum must include any
newly required backend APIs; the exclusive maximum must exclude breaking backends. CI and
release dry runs reject bounds that exclude the released Python package, mismatched extension
versions, and protocol drift. These checks enforce declared compatibility, not semantic API
compatibility: maintainers must still test supported backends and classify breaking changes.

For breaking wire changes, increment `python/src/wintestkit/protocol.py`, the initialize-result
constant in `schemas/rpc.schema.json`, and the bundled policy protocol together; regenerate
TypeScript types with `npm run gen:types` in `vscode`. Update the supported range and add
regression tests. Old extension builds cannot retroactively acquire these protections, so
users on earlier versions should update before installing a breaking Python release.

## Recover a partial release

Prefer **Re-run failed jobs** on the original workflow run. Python and Marketplace have
separate publishing jobs, so a Marketplace failure does not require repeating a successful
PyPI upload. Re-running all jobs is also supported: `uv publish --check-url` skips files
already present, and `vsce --skip-duplicate` skips already-published targets. Fix missing
external permissions or credentials before retrying.

Do not replace a published package with different code under the same version. If code
must change after any registry has accepted it, release a new version. Do not move the old
tag. GitHub Release asset upload is recoverable if the final release step was interrupted.
Open VSX failures can be retried independently after the required registries succeed.

For an optional staging rehearsal, configure a separate TestPyPI trusted publisher and a
separate staging environment before using `uv publish --publish-url https://test.pypi.org/legacy/`.
The production workflow never switches registries implicitly and does not use TestPyPI.
