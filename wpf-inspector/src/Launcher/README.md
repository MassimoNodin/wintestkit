# Launcher build

From the repository root, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\build_inspector.ps1 -LockedRestore
```

The script requires Git on `PATH`. It verifies all 34 files in `third_party/snoop.lock.json`, checks for the .NET Framework 4.8 Developer Pack's CLR hosting headers, and builds Protocol, Agent, and the native injectors. It then copies the pinned launcher and shared files into `artifacts/launcher/source/`, checks and applies [`snoop-injector-launcher.patch`](../../third_party/patches/snoop-injector-launcher.patch), and builds the copied project for .NET Framework 4.8. A patch mismatch fails the build. The original Snoop files are not modified.

The patch removes the seven excluded Snoop.Core source imports and the icon, disables upstream broad build imports and automatic cross-architecture builds, and removes JetBrains annotations. `LauncherSupport.cs` supplies the launcher-only Windows process, memory, module, architecture, console, and logging helpers. The injector's native remote-thread transport is retained. The only launcher package is upstream's `CommandLineParser` 2.9.1, pinned and hashed in `packages.lock.json`; the .NET Framework 4.8 reference assemblies come from the installed Developer Pack.

Release outputs are:

- `artifacts/launcher/Release/Win32/Snoop.InjectorLauncher.x86.exe` and `Snoop.GenericInjector.x86.dll`.
- `artifacts/launcher/Release/x64/Snoop.InjectorLauncher.x64.exe` and `Snoop.GenericInjector.x64.dll`.

Each directory also contains the launcher's `CommandLine.dll` dependency and executable configuration. Debug builds use the corresponding `Debug` directories. The script also stages the selected configuration in `inspector-payload/src/wintestkit_inspector/payload/` with a manifest, SHA-256 inventory and notices. It records the local Git commit with a `-dirty` suffix when the checkout has changes and leaves all six compatibility cells unverified. `scripts/check_inspector.ps1 -Suite Package` checks the staged directory; it does not build or validate a wheel.

`BundledAgent.csproj` compiles the existing Agent and Protocol sources together into one strong-named Agent assembly per runtime. The unmodified Snoop CLR host loads the Agent from outside the application's probing paths; a separate Protocol DLL beside it was not resolved in a real .NET 10 target. The bundle requires no target-wide assembly resolver or application-directory changes. The ordinary Agent and Protocol projects still build independently for their existing tests. The bundled project has its own locked build-only Framework reference package and no third-party runtime dependencies.

Development builds are unsigned, including builds with `-Configuration Release`. `-Sign` requires `WTK_SIGN_CERT_THUMBPRINT` and signs each staged EXE and DLL with the installed Windows SDK signing tool; `-Suite Package -RequireSigned` rejects an unsigned payload. Signing and publication remain separate release gates.

The launcher requires an existing `--settingsFile` and no longer creates Snoop UI settings as a fallback. Pass the matching launcher for the target architecture and an absolute agent assembly path. Upstream writes `%APPDATA%\Snoop\SnoopLog.txt`, including paths and injection arguments, and uses a temporary native log. The token is in the protected bootstrap file, never an argument. Launcher exit success does not establish agent readiness; that requires the authenticated pipe handshake. See [`snoop-loader-notes.md`](../../third_party/snoop-loader-notes.md) and the [owned-process harness](../../tests/Harness/OwnedAttach/README.md).
