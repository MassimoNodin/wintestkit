# Releasing WinTestKit

## Distribution policy: public Python and public pre-release extension

The intended 0.1 prerelease is a public Python package on PyPI and a public **pre-release**
VS Code extension on the Visual Studio Marketplace (the pre-release channel opts users in;
it is not an access control). Open VSX and raw VSIX downloads (Actions artifacts and GitHub
Release assets) are optional and disabled by default. Everything is opt-in per gate, so a
private-only setup remains possible by leaving the extension gates unset.

All four gates must be **repository Actions variables**, with the exact lowercase value
`true` to enable them. Unset or `false` means disabled:

| Repository variable | 0.1 prerelease setup | Effect when true |
| --- | --- | --- |
| `PUBLISH_PYPI` | `true` after trusted publisher setup | Publish Python distributions using PyPI OIDC |
| `PUBLISH_MARKETPLACE` | `true` after Marketplace setup | Publish both VSIX Windows targets to Marketplace |
| `PUBLISH_OVSX` | `false` (optional later) | Publish both VSIX Windows targets to Open VSX |
| `PUBLISH_PUBLIC_VSIX` | unset or `false` | Upload VSIX Actions artifacts and attach VSIX GitHub Release assets |

These are independent: PyPI never requires Azure or Open VSX credentials, extension
registries do not depend on PyPI publication, and neither extension registry implicitly
permits public VSIX artifact uploads. Enabling either extension registry still makes the
extension public through that registry. Each enabled extension destination packages from
the checked source in its own job; no private VSIX is passed through Actions artifacts.
CI always checks/builds/packages the extension, even when it withholds the VSIX artifact.
Python distributions, test results and release notes remain ordinary CI artifacts.
A successful tagged release creates a GitHub Release with Python assets, but includes
VSIX assets only with the public VSIX gate. This gate does not delete historical uploads.

### Verified configuration and required user migration

Read-only inspection on **2026-10-22** confirmed the local remote and GitHub repository:
`MassimoNodin/wintestkit`, default branch `master`, public repository. The checked-in
workflow is `.github/workflows/release.yml` and publishing jobs use environment `release`.
The Python project is `wintestkit`. No candidate version has been selected or bumped.

At inspection, `PUBLISH_PYPI=true` existed only in the **release environment**, while
`PUBLISH_OVSX=false` was a repository variable. The new job-level PyPI gate cannot read
an environment-only variable before the job starts. **User action required:** add
`PUBLISH_PYPI=true` under repository **Settings -> Secrets and variables -> Actions ->
Variables**, after completing PyPI authorization. Remove the environment-only duplicate
(or leave it unset) so all gates have one repository-scoped source of truth. Add
`PUBLISH_MARKETPLACE=true` there only after completing the Marketplace setup below; keep
`PUBLISH_PUBLIC_VSIX` unset/false and retain `PUBLISH_OVSX=false` unless you opt into them.
Do not define environment-scoped copies of gate variables, which could disagree with
job-level repository gates. This change does not modify settings or perform publication.

## Required user account setup: PyPI

1. Sign into PyPI, enable two-factor authentication and save recovery codes.
2. Confirm ownership/permission for the `wintestkit` project. A public 404 or a successful
   local build does not prove name availability or publishing authorization.
3. For a new project, add a **pending trusted publisher** in your account's Publishing
   settings; for an existing project, add it in that project's Publishing settings.
4. Enter the exact values matching this repository/workflow:

   | PyPI trusted-publisher field | Exact value |
   | --- | --- |
   | PyPI project name (pending publisher) | `wintestkit` |
   | GitHub owner | `MassimoNodin` |
   | GitHub repository name | `wintestkit` |
   | Workflow filename (not path or display name) | `release.yml` |
   | Environment name | `release` |

The environment field is required for this configuration because the publishing job
uses that exact environment. Its OIDC subject includes `environment:release`. The job
requests `id-token: write` and invokes `uv publish --trusted-publishing always`. No PyPI
API token is used, and PyPI publication does not depend on the Marketplace or Open VSX.
Only the user can confirm external account ownership and trusted-publisher registration;
local preflight cannot prove authorization without an actual registry operation.

Official reference: [PyPI trusted publishers](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

### GitHub release environment: user action

Keep/create environment `release` and permit version tags (`v*`). Consider protection and
required reviewers without creating a solo-maintainer approval deadlock. Protect `master`
and immutable release tags as appropriate. The workflow requires tags reachable from the
default branch and serializes releases. No repository settings are changed by these scripts.

## Version and channel contract

Stable releases default to the existing shared `X.Y.Z` Python/extension version. An
explicit numeric `--extension-version` is also supported for stable releases. Accepted
formal Python prereleases are canonical `X.Y.ZaN`, `X.Y.ZbN`, `X.Y.ZrcN` and `X.Y.Z.devN`,
with nonnegative numeric components and no leading zeroes (except zero itself). Combined
pre/dev, post, local and alternate spellings are not release candidates for these helpers.
Tags are `v` followed by the **Python** version; changelog sections also use that version.

VSIX versions remain numeric `X.Y.Z`. A formal prerelease requires the maintainer to choose
an explicit numeric version: `bump_version.py PYTHON_VERSION --extension-version VSIX_VERSION`.
There is no automatic mapping and this change does not choose a candidate. Manifest,
lockfile/root package and `compatibility.json.extensionVersion` must agree numerically.
`compatibility.json.channel` is `"prerelease"` for formal prereleases; stable bumps remove
it, preserving compatibility with older policies where absence means stable.

**Collision decision required before selecting a candidate:** Marketplace cannot publish
the same numeric version as both prerelease and stable. Choose unused, monotonically
increasing numeric VSIX versions and reserve a distinct later version for the next stable
release. Pass `--extension-version` for stable releases too when necessary to avoid a
numeric rollback; stable Python and VSIX versions may differ when explicitly chosen. Do not
reuse `0.1.1` as both a prerelease and stable VSIX. No candidate is selected here.

`vsce package` and registry publication pass `--pre-release` for the prerelease channel;
GitHub Releases use `--prerelease`. The Python artifact keeps its canonical PEP 440 version.
The Python release tuple must lie within the policy's stable `minimum` (inclusive) and
`maximumExclusive` bounds, and the explicit channel must match the released Python version.
Bumping never widens those bounds. Protocol versions must still agree across policy,
backend and schema; API compatibility must also be tested, not merely declared.

Official reference: [VS Code prerelease extensions](https://code.visualstudio.com/api/working-with-extensions/publishing-extension#prerelease-extensions).

## Prepare and validate: no publication

After the user selects candidate versions, run from the repository root. Replace the
uppercase placeholders; these commands are templates, not a chosen version:

~~~powershell
python scripts/bump_version.py PYTHON_VERSION --extension-version VSIX_VERSION
python scripts/bump_version.py --check PYTHON_VERSION --extension-version VSIX_VERSION
python scripts/check_release.py compatibility
python scripts/check_release.py notes PYTHON_VERSION --output release-notes.md
uv run --directory python pytest tests/unit/test_release.py
~~~

For stable releases, `--extension-version` may be omitted and defaults to Python's version.
A leading `v` is accepted by the bump CLI; release notes require the canonical version.
Move **all** substantive `[Unreleased]` entries into a nonempty
`## [PYTHON_VERSION] - YYYY-MM-DD` section. Leaving newer Unreleased work while selecting
older notes is an error, not a silent fallback. Current Unreleased work intentionally
remains unstaged until the user selects/dates the candidate; a release dry run will block.
The checker does not stage files in Git or choose a release date.

Use the normal full unit/build checks described in `docs/development.md` before releasing.
A manual Release workflow dispatch defaults to `dry_run=true` and builds/validates without
registry publication. Public VSIX artifacts are still withheld unless explicitly enabled.
Dry runs do not validate registry credentials, ownership or external authorization.

### Local VSIX build and installation

From `vscode/`, with the locked dependencies and an already selected version/channel:

~~~powershell
npm ci
npm run build
npm exec --no -- vsce package --target win32-x64 -o dist/
code --install-extension "PATH_TO_LOCALLY_BUILT_VSIX"
~~~

For an ARM64 host use `--target win32-arm64`. For a policy with `channel: "prerelease"`,
add `--pre-release` to `vsce package`. Install only from a trusted local/private source.
A local build is for acceptance testing before publication; the published pre-release is
installed from the Marketplace (Extensions view -> WinTestKit -> **Switch to Pre-Release
Version**).

After the chosen Python version is actually published, install it in your selected test
interpreter. Stable: `python -m pip install "wintestkit>=MINIMUM,<MAXIMUM"`. Formal
prerelease: `python -m pip install --pre "wintestkit==PYTHON_VERSION"`. In a pip-less uv
environment use `uv pip install --python PATH_TO_PYTHON --prerelease allow "wintestkit==PYTHON_VERSION"`.
Replace placeholders with the chosen policy/version. An exact pin avoids choosing an
unrelated prerelease. Until publication, use a locally built wheel instead. The extension's
prerelease channel authorizes prerelease installation; a stable extension does not silently
opt into it. Neither a local build nor a successful dry run proves PyPI availability.

## Publishing is a later, explicit user action

No helper here pushes, tags or publishes when validating. Once the candidate and notes
are approved, the user may commit/push and create/push the corresponding immutable version
tag through their usual process. Tag pushes invoke Release. Manual `dry_run=false` also
requires selecting a version tag, never a branch. Verify the selected four repository
gates before triggering either route. Enabled registries publish independently after CI.

After any actual publication, verify PyPI files and a clean installation using the chosen
channel. Check only the extension destinations explicitly enabled. Never replace different
code under a version already accepted by a registry or move an existing release tag.
Re-run failed jobs for partial publication: `uv publish --check-url` and registry
`--skip-duplicate` support retries. GitHub asset recovery uses the original tag. Withholding
future VSIX uploads does not remove previously published registry versions or assets;
removal would be a separate explicit user action.

## Extension accounts

The Marketplace is required for the public pre-release extension. Open VSX and public
VSIX downloads are optional. None of them is a prerequisite for PyPI.

### Visual Studio Marketplace (required for the public pre-release)

Create the publisher first: sign in at https://marketplace.visualstudio.com/manage with a
Microsoft account and create publisher ID `wintestkit` (the ID is permanent and must match
`publisher` in `vscode/package.json`; if it is taken, choose another and change the manifest).

Obtain authorization for publisher `wintestkit` (the manifest publisher, not a claim of
account ownership). Follow the official Marketplace guide to create/authorize an Entra
publishing identity, such as a user-assigned managed identity. For its GitHub environment
federation use issuer `https://token.actions.githubusercontent.com`, subject
`repo:MassimoNodin/wintestkit:environment:release` and audience `api://AzureADTokenExchange`.
Authorize that identity on the Marketplace publisher with Contributor access. For the
managed-identity route use its Azure resource ID when granting publisher membership.
Add environment secrets `AZURE_CLIENT_ID` and `AZURE_TENANT_ID`, then explicitly enable
the **repository** variable `PUBLISH_MARKETPLACE=true`. No client password or Marketplace
PAT is used by the current OIDC workflow. Azure is never a PyPI prerequisite.

### Open VSX (optional)

Obtain namespace `wintestkit` ownership and accept the publisher agreement, create a
publisher token, add `OVSX_TOKEN` as a `release` environment secret, then explicitly set
the **repository** variable `PUBLISH_OVSX=true`. No Azure identity or PyPI enablement is
required for this independent job. Keep the token out of source and chat.

For public downloadable VSIX files, separately opt into repository variable
`PUBLISH_PUBLIC_VSIX=true`. This requires no registry account but exposes the extension
through Actions artifacts and GitHub Release assets, including artifact uploads on CI.
