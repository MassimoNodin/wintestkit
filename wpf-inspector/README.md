# WinTestKit WPF inspector

The inspector is in development. It provides an optional managed-object inspector for WPF targets alongside WinTestKit's existing UI Automation support. See the [implementation plan](../docs/plans/wpf-dotnet-attribute-analyzer.md) for the architecture and release gates.

The intended layout contains `src/Protocol` for the wire codec, `src/Agent` for the in-process inspector, `src/Launcher` for the attach transport, `protocol` for schemas and fixtures, and `tests` for unit, integration, and target fixtures. `third_party` holds the pinned launcher source; `artifacts` contains generated output.

Use the SDK pinned in `global.json` to build and test from the repository root:

```powershell
$env:DOTNET_ROOT = 'C:\Users\massi\AppData\Local\wintestkit-dev\dotnet'
$env:DOTNET_MULTILEVEL_LOOKUP = '0'
& "$env:DOTNET_ROOT\dotnet.exe" build wpf-inspector/WinTestKit.Inspector.sln -c Release
& "$env:DOTNET_ROOT\dotnet.exe" test wpf-inspector/WinTestKit.Inspector.sln -c Release --filter Category=Unit
```

Agent and Protocol have no third-party runtime dependencies in the target process. This avoids assembly binding conflicts with packages already loaded by the application and avoids requiring binding redirects or downloads during attachment.
# Protocol metadata representation

Dependency metadata represents `isAttached` as the closed strings `true`, `false`,
or `unknown`; the last value means attachment could not be determined. Attribute
argument literals use `{kind, value}` objects, with at most one array level.
