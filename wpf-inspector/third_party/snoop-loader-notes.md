# Pinned Snoop loader findings

Archive SHA-256: `9688b7d5e9f945a5bc93e96bd45bfc66bec6c4d4910d85c7da1c1e127078192c`. The inventory and individual hashes are in `snoop.lock.json`.

`InjectorLauncherCommandLineOptions` declares `-t, --targetPID` (required, Int32), `-h, --targetHwnd` (optional, Int32), `-a, --assembly` (required), `-c, --className` (required), `-m, --methodName` (required), `-s, --settingsFile` (optional), `-v, --verbose`, `-d, --debug`, and `--attachConsoleToParent`. HWND defaults to zero. The PID path constructs a ProcessWrapper directly and does not validate HWND ownership.

The launcher selects `Snoop.GenericInjector.<architecture>.dll` beside its assembly. A mismatched launcher attempts redirection to an architecture-substituted executable name. ProcessWrapper inspects modules: absence of coreclr.dll selects `net462`; coreclr product major >= 6 selects `net6.0-windows`, major 4 selects `net462`, other versions throw. Native Executor selects the corresponding executor. Framework uses CLRCreateInstance and the v4.0.30319 host. .NET obtains GetCLRRuntimeHost from the loaded coreclr.dll, not hostfxr. Both use ICLRRuntimeHost.ExecuteInDefaultAppDomain.

The settings pathname is sent in a `<|>`-delimited remote buffer alongside the assembly, class and method; the host invokes the standard public static `int Method(string)` convention. Native code passes a null return-value pointer and returns the hosting HRESULT, not the managed return value. CreateRemoteThread executes the native export and managed method on a remote thread, not a WPF Dispatcher thread. Additional remote threads load and free the DLL.

Main returns 1 on parsing errors and caught failures, 0 after InjectIntoProcess returns, or the redirected launcher's exit code. A missing remote export logs and returns without throwing, allowing Main to return 0. It truncates `%APPDATA%\Snoop\SnoopLog.txt` at launch and logs paths, PID, arguments including the settings pathname, and exceptions. A temporary native log is normally deleted after being copied to the persistent log. Omitting settingsFile also creates a transient Snoop UI settings file.

## Differences from brief 3.7 and the plan

1. All six long option spellings match; `--targetHwnd` is optional to the parser. Upstream does not verify HWND ownership.
2. HWND is signed Int32, not pointer-sized; values outside Int32 cannot be parsed. The PID injection path does not use it for a window hook.
3. Execution uses CreateRemoteThread, not a window hook on the target UI thread. Entry must not assume a Dispatcher thread.
4. The .NET path uses loaded coreclr's GetCLRRuntimeHost and ExecuteInDefaultAppDomain, not hostfxr. Compatibility requires empirical testing.
5. The settings pathname appears in persistent logs and a temporary log is created; the brief's argument array does not mention these side effects.
6. Exit 0 does not establish invocation or readiness; the missing-export branch can report success. The managed return value is not propagated.
7. A mismatched launcher tries an architecture-named sibling, but the brief selects the matching launcher directly and its per-architecture directories do not provide such a sibling.
8. The upstream project directly imports seven Snoop.Core source files and an icon, despite the explicit exclusion of Snoop.Core. The unmodified project cannot build from the permitted inventory. A reviewed boundary or patch is needed.
