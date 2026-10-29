# Owned fixture attach harness

Build the staged payload and verifier from the repository root:

```powershell
./scripts/build_inspector.ps1 -LockedRestore
./scripts/check_inspector.ps1 -Suite Package
$env:DOTNET_ROOT = 'C:\Users\massi\AppData\Local\wintestkit-dev\dotnet'
$env:DOTNET_MULTILEVEL_LOOKUP = '0'
$harness = 'wpf-inspector/tests/Harness/OwnedAttach/bin/Release/net10.0-windows/OwnedAttach.dll'
& "$env:DOTNET_ROOT/dotnet.exe" $harness attach (Get-Location).Path net10 x64 --adverse
```

The harness starts only a published fixture in `tests/Fixtures/WpfFixture/bin/cells/`, with no fixture startup arguments, checks the staged hashes first, and terminates only its own fixture and launcher in `finally`. It creates a random one-use bootstrap file in a protected user-only session directory, checks both ACLs and reparse points, and never puts the token in arguments or reports. It verifies the named-pipe server PID and creation time before authenticating. Hello must match the Agent version, process identity, runtime and architecture within ten seconds; the bootstrap file must be gone. It reads WPF metadata, closes the session, tests that the fixture dispatcher still runs, and checks pre-start, post-start and post-attach fixture file hashes; the pre-start report is written outside the fixture directory. Its JSON control pipe and pinned conflict package files provide additional compatibility evidence; on Framework, native module enumeration does not establish which managed files were mapped. `--bad-token` expects a closed pipe with no response.

`--adverse` opens a second dispatcher, reads the fixture's releasable `Hanging` getter, checks a bounded failure and subsequent rejection on the blocked dispatcher, and verifies a read on the second dispatcher. The fixture control pipe releases the getter even on failure. This is not cancellation of running application code.

For manifest rejection tests, run:

```powershell
$payload = (Resolve-Path 'inspector-payload/src/wintestkit_inspector/payload').Path
$manifest = Get-Content -Raw "$payload/manifest.json" | ConvertFrom-Json
& "$env:DOTNET_ROOT/dotnet.exe" $harness package-negative $payload $manifest.inspectorVersion $manifest.upstreamCommit (Join-Path (Get-Location) 'wpf-inspector/artifacts/verification')
```

This keeps isolated test copies under ignored `artifacts/verification` and checks missing/tampered files, path traversal, version drift, duplicate fields, an unlisted UI file, rehashed wrong-architecture and wrong-framework binaries, a changed native export, and an unsafe launcher configuration. It does not certify a wheel or the full compatibility matrix.
