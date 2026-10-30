# Managed inspection

> **Preview:** This feature is not yet released; compatibility and release gates remain open.

The optional WPF inspector complements UI Automation (UIA) with managed type, member,
dependency-property and binding information. It instruments the running process using the
Snoop loader; it requires no application changes, but is **not zero-impact**. Prefer UIA
locators where possible. Only attach to applications you are authorized to instrument.

## Compatibility

The intended framework-dependent WPF cells are .NET Framework 4.8, .NET 8 and .NET 10,
each on x86 and x64. **No cell is marked verified in the compatibility manifest.** Partial
owned-fixture integration checks exercised .NET 10 x64 attachment, mapping, reads, redaction
and locators; they do not establish the complete matrix or release gates. Other fixture UIA
checks are also partial, and the test machine lacked the .NET 10 x86 runtime. See the
[verification notes](../plans/wpf-inspector-implementation-brief.md#s8-managed-locator-verification-2026-10-29).

Unsupported targets include ARM64, non-WPF, NativeAOT, trimmed, self-contained or
single-file applications, multiple WPF runtimes or AppDomains in one process, different
users or Windows sessions, protected processes, and mismatched integrity levels. Unlisted
.NET versions are not assumed compatible. Use an interactive Windows desktop.

## Installation and configuration

Install in the Python environment used by WinTestKit: `pip install 'wintestkit[inspector]'`
or `uv pip install 'wintestkit[inspector]'`. Run `wtk doctor` to check prerequisites.
Configure shared defaults in `wintestkit.yaml` and machine-specific overrides in
`wintestkit.local.yaml`:

```yaml
inspector:
  enabled: true
  attach: manual
  attach_timeout: 10.0
  request_timeout: 2.0
  query: agent
  redact_names: [account]
```

| Key | Default | Allowed values |
|---|---|---|
| `inspector.enabled` | `false` | Boolean |
| `inspector.attach` | `manual` | `manual` or `on-demand` |
| `inspector.attach_timeout` | `10.0` | Positive seconds, at most 10 |
| `inspector.request_timeout` | `2.0` | Positive seconds, at most 2 |
| `inspector.query` | `agent` | `agent` or `postfilter` |
| `inspector.redact_names` | `[]` | At most 32 nonempty names, each at most 128 Unicode characters |

Redaction names from configuration layers are additive. There are no inspector environment
variable overrides. Committing `enabled: true` and `attach: on-demand` in shared configuration
authorizes managed queries, including headless tests, to attach when needed; it does not attach
just because the application starts or UIA is queried. `manual` requires explicit attachment.
Review that authorization with your team. Spy still requires workspace trust and confirmation.

## Spy and reading values

In VS Code Spy, select a target element, trust the workspace, then attach in the managed
panel. Confirm the displayed executable, PID, runtime, architecture and execution warning.
Confirmation is remembered for that process identity. The panel may show:

| State | What to do |
|---|---|
| `not enabled` | Enable the inspector in configuration. |
| `not installed` | Install the inspector extra in the selected interpreter. |
| `unsupported target` | Check the target and compatibility above. |
| `blocked by policy` | Trust the workspace if appropriate, or ask your security administrator. |
| `restart required` | Restart the target after an upgrade; check the installed payload. |
| `attach failed` | Check the error, target identity and `wtk doctor`. |
| `mapping unavailable` | Reselect the element and check its UIA peer and member identity. |
| `detached (idle)` | Select a live target and attach again. |
| `ready` | Select an element and inspect it. |
| `not attached to this process` | Attach to the selected element's process. |

The panel groups managed type, CLR properties, CLR fields, dependency/attached properties,
and bindings. Member listing is lazy: explicitly read or expand a readable member to fetch
its value. Reading visible values prompts about the risk. Value statuses are `ok`, `notRead`,
`notReadable`, `nullIntermediate`, `exception`, `stale`, `redacted`, `truncated`, `cycle`,
`timeout`, and `unsupported`; they indicate respectively a value, no read yet, unreadable
member, null along a path, getter failure, stale object, withheld value, shortened value,
cycle, timed-out operation, or unsupported value.

Reading getters, property descriptors, or creating automation peers can execute application
code, change state, or hang the UI. Timeouts bound waiting; they do **not** sandbox code or
stop a getter already executing. Use a disposable test process and avoid unsafe members.
Detach ends the session; it does not unload the injected agent. Restart the target to remove it.

## Redaction

Built-in case-insensitive name rules include `password`, `passwd`, `pwd`, `secret`, `token`,
`credential`, `connectionstring`, `apikey`, and `privatekey`; password controls receive
additional protection. Add application-specific names with `redact_names`. Matching names
may over-redact benign values, while name-based rules cannot identify every secret. Do not
put secrets in locator `where` clauses, logs, or test data merely because redaction exists.

## Managed locators

Use qualified keys observed in Spy, for example:

```python
# pseudo-code
Element(automation_id='Order', where={'type:FullName': 'Example.OrderView'})
Element(where={'type:Is': 'Example.BaseView'})
Element(automation_id='Order', where={'clr:DataContext.Status': 'Ready'})
Element(automation_id='Order', where={'field:State': 'Ready'})
Element(automation_id='Order', where={'dp:PresentationFramework|System.Windows.FrameworkElement::Tag': 'Ready'})
```

`type:` accepts `Name`, `FullName`, `AssemblyName`, `AssemblyQualifiedName`, or `BaseTypes`.
`type:Is` matches a loaded type or a derived type by its exact full name and requires an agent query.
`clr:` traverses properties separated by dots; `field:` starts with a field and continues
with properties. Escape a literal dot as `\.` and a backslash as `\\` in the key (double
backslashes again in ordinary Python string literals). `dp:` uses
`assembly|owner-type::property` followed optionally by slash-separated property segments;
escape literal slashes as `\/` and backslashes as `\\` in those segments. Paths allow at
most eight segments and 1,024 UTF-8 bytes; whitespace, indexers and method calls are not
supported. Do not guess paths or dependency owners.

Agent queries search the combined WPF tree, then map results to UIA peers in traversal order.
Matches without a UIA peer are skipped. The agent returns at most 200 matches: if traversal
is incomplete with fewer than 200, the query raises a limit error; 200 incomplete matches
are returned because ambiguity is already evident. Unsupported locators fall back to the
UIA postfilter, which is capped at 1,000 candidates. Set `inspector.query: postfilter` to
force that path. Equality and regular expressions use the
normal `where` matching rules; managed scalar comparison distinguishes booleans from numbers
and supports enum names or integer values. Redacted, unsupported or ambiguous values cannot
be treated as ordinary matches. See [property matching](property-matching.md).

## CLI

```powershell
wtk inspect --managed --json
wtk inspect --managed --read-managed 'type:FullName' --json
```

`--managed` explicitly attaches temporarily and lists metadata even in manual mode;
`--read-managed` explicitly reads a qualified path, can be repeated up to 32 times, and
requires `--managed`. `--json` emits JSON. Inspection may expose sensitive data: protect output.

## Troubleshooting

| Error code | Action |
|---|---|
| `invalidParams`, `invalidPageToken` | Correct the request or refresh the view and retry. |
| `unsupportedProtocol`, `unsupportedTarget` | Use compatible components and a supported target. |
| `accessDenied`, `blockedByPolicy` | Check account, session and integrity; ask your security administrator about a security-product block. Never disable protection to attach. |
| `authenticationFailed` | Retry attachment; investigate local session security if it persists. |
| `payloadMissing`, `payloadMismatch` | Install or repair the matching inspector payload. |
| `agentVersionMismatch` | Restart the target after upgrading, then attach again. |
| `alreadyAttached`, `notAttached` | Detach or explicitly attach as appropriate. |
| `attachFailed` | Check target compatibility, permissions and `wtk doctor`. |
| `processExited`, `processReused`, `sessionStale`, `objectStale` | Reselect the live process or element and reattach. |
| `mappingFailed` | Select a UIA element with a supported, unambiguous peer. |
| `memberAmbiguous`, `memberNotFound` | Reinspect the element and use the observed member identity. |
| `dispatcherUnavailable`, `timeout`, `busy` | Allow the UI to respond; avoid slow getters and retry. A timeout cannot stop running code. |
| `limitExceeded` | Narrow the locator or request fewer paths. |
| `cancelled` | Retry if the operation is still needed. |
| `internalError` | Collect non-sensitive diagnostics and report the failure. |
