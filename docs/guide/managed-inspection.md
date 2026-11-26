# Managed inspection

The WPF backend uses an injected agent to search and act on the WPF tree and inspect managed
type, member, dependency-property and binding information. Managed `where` keys also work on
`Window` selectors. They require a WPF window with `backend: auto`; the UIA backend rejects
them. Injection requires no application changes, but is **not zero-impact**. Only attach to
applications you are authorized to instrument.

## Reading values

Use `element.get("clr:DataContext.Label")` or `element.get("type:FullName")` to read
managed values, including on peerless elements. Configured property aliases also work. Use
`expect(element).to_have_property(name, expected)` or `element.wait_for_property(name, expected)`
to wait for a value; compiled regular expressions match strings. Unqualified names read UIA
properties instead. `type:Is` is a locator predicate, not a readable value. Redacted members
cannot be read. As with Spy, reading managed properties executes application getters, which can
have side effects.

Spy lists inherited public and non-public static properties and fields alongside instance members. Public static getters and static fields can be read subject to the same redaction and timeout safeguards.

## Compatibility

Framework-dependent WPF targets include .NET Framework 4.8, .NET 8 and .NET 10 on x86
and x64. Check `wtk doctor --agent` on the actual machine and target.

Spy also attaches to WinForms applications on the same runtimes: it lists the control tree and
shows the members of a control. Locators and queries stay WPF only.

Unsupported targets include ARM64, applications with neither a WPF nor a WinForms UI, NativeAOT, trimmed, self-contained or
single-file applications, multiple WPF runtimes or AppDomains in one process, different
users or Windows sessions, protected processes, and mismatched integrity levels. Unlisted
.NET versions are not assumed compatible. Use an interactive Windows desktop.

With the default `backend: auto`, WPF windows use the agent and non-WPF windows use UIA.
Agent failures do not fall back silently: if security software blocks the agent, WPF tests
fail until it is allow-listed. Run `wtk doctor --agent`; use `backend: uia` to opt out.
The default `input_mode: mouse` sends real input on both backends; use `input_mode: pattern`
to request automation-peer or UIA pattern actions instead.

WPF can find hidden descendants of collapsed expanders and peerless elements that UIA may
omit. Peerless elements require mouse actions. DataGrid row/cell reads and counts still use
UIA Grid patterns, and mouse row selection may use a row header or pattern fallback.
A visible irregular region may have no safe click point; unrooted handles may go stale.

## Installation and configuration

Install in the Python environment used by WinTestKit: `pip install 'wintestkit[inspector]'`
or `uv pip install 'wintestkit[inspector]'`. Run `wtk doctor` to check prerequisites.

The inspector stages verified payload files outside the installed package before attaching. The VS Code installer checks for applications holding older installed inspector files and offers to close them before upgrading. If they do not close, you can choose whether to force close them.
Configure shared defaults in `wintestkit.yaml` and machine-specific overrides in
`wintestkit.local.yaml`:

```yaml
inspector:
  enabled: true
  attach: on-launch
  attach_timeout: 10.0
  request_timeout: 2.0
  redact_names: [account]
```

| Key | Default | Allowed values |
|---|---|---|
| `inspector.enabled` | `true` | Boolean |
| `inspector.attach` | `on-launch` | `manual`, `on-demand`, or `on-launch` |
| `inspector.attach_timeout` | `10.0` | Positive seconds, at most 10 |
| `inspector.request_timeout` | `2.0` | Positive seconds, at most 2 |
| `inspector.redact_names` | `[]` | At most 32 nonempty names, each at most 128 Unicode characters |

Redaction names from configuration layers are additive. There are no inspector environment
variable overrides. By default, the inspector attaches after the first WPF window appears.
If the application restarts itself, the new process is attached when a test touches its window.
Set `attach: on-demand` to attach on the first managed query, `enabled: false` to disable
inspection, or `attach: manual` to require explicit attachment.
Review that authorization with your team. Spy requires workspace trust. It attaches automatically
when you expand a WPF window belonging to the configured app under test: an app launched by
WinTestKit, or the executable identified by the workspace's attach settings. Other applications
require consent once per process run; cancelling leaves the window waiting for attachment.

Attaching loads a small inspector into the application so Spy can show WPF types, `x:Name`,
and properties that Windows UI Automation does not expose. It remains loaded until the app exits
and cannot be removed earlier. Reading properties runs the app's own getters: these can be slow,
hang the app, or have side effects. A timeout cannot safely stop a running getter. Antivirus,
AppLocker or WDAC may flag or block the inspector, and WinTestKit needs the same elevation as the
app. Only your Windows user can connect to the inspector; nothing is sent off the machine.
Only attach to applications you trust and are allowed to test. Tests already attach automatically to the app they launch or attach.

## Spy and reading values

In VS Code Spy, trust the workspace. The configured app under test attaches automatically; expanding another WPF app asks for consent once per process run. Cancelling shows UI Automation children and an Attach action in the window properties. WPF windows use the visual tree with paged children (**Load more**); other windows use UI Automation. Labels combine the type and available `x:Name` or AutomationId. The picker can select peerless WPF elements and popup content. If attachment is blocked, Spy shows the error and its fix instead of silently switching to UI Automation.

Hosted native HWND content appears under its WPF host. UI Automation-only elements elsewhere
outside the visual tree, such as provider-created virtualized placeholders or scrollbar parts
without a visual counterpart, are omitted. WPF popup presentation sources appear as separate
root windows.

The panel may show:

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

General shows available identity, geometry and state. WPF shows CLR type and dependency properties, .NET shows managed members, and UI Automation shows properties when a peer is available.
The panel groups managed type, CLR properties, CLR fields, dependency/attached properties,
and bindings. Member listing is lazy: explicitly read or expand a readable member to fetch
its value. Reading visible values prompts about the risk. Value statuses are `ok`, `notRead`,
`notReadable`, `nullIntermediate`, `exception`, `stale`, `redacted`, `truncated`, `cycle`,
`timeout`, and `unsupported`; they indicate respectively a value, no read yet, unreadable
member, null along a path, getter failure, stale object, withheld value, shortened value,
cycle, timed-out operation, or unsupported value. Getter failures can include a sanitized
exception message of up to 512 characters, omitted for protected or redacted reads.

### Binding details

Under **.NET › Bindings**, each bound property has one row whose value reads `kind; status; path`.
Expand it (the chevron, or **Expand** in the row menu) to see every detail of the binding as
rows named `Property.Detail`:

- **Binding options:** `Mode`, `UpdateSourceTrigger`, `Path`, `XPath`, `ElementName`,
  `RelativeSource` (mode, ancestor type and level), `Source` and `Converter` (type names),
  `ConverterParameter`, `ConverterCulture` (`(invariant)` for the invariant culture),
  `StringFormat`, `FallbackValue`, `TargetNullValue`, `Delay`, `BindingGroupName`, `IsAsync`.
- **Validation:** `NotifyOnSourceUpdated`, `NotifyOnTargetUpdated`, `NotifyOnValidationError`,
  `ValidatesOnDataErrors`, `ValidatesOnExceptions`, `ValidatesOnNotifyDataErrors`,
  `ValidationRules` (type names), `UpdateSourceExceptionFilter` (shown as `set` when present).
- **Resolved state:** `DataItem`, `ResolvedSource` and `ResolvedSourcePropertyName`, `HasError`,
  `HasValidationError` and `Error` (the validation error's type and sanitized message).
- **Composite bindings:** a `MultiBinding` shows its converter and `ConverterParameter`, and a
  `PriorityBinding` shows `ActiveBinding` (the index of the child that supplies the value). Their
  children appear as nested `Property.Bindings[0]`, `Property.Bindings[1]`, ... rows, each opening to
  its own details. The tree is limited to 8 levels and 32 bindings.

`DataItem`, `ResolvedSource`, `ConverterParameter`, `FallbackValue` and `TargetNullValue` are values,
serialized like member values: an object comes back as a handle, so Spy expands it with
**Expand** and lists its members and collection items like any other object row. Those object rows
are not members of the selected element, so they have no locator and cannot be shown in the Basic view.

To keep the list readable, Spy leaves out rows that carry no information: empty strings, absent
values, a `Delay` of 0, flags that are `false` (`IsAsync`, `NotifyOn...`, `ValidatesOnDataErrors`,
`ValidatesOnExceptions`, `HasError`, `HasValidationError`), and `ValidatesOnNotifyDataErrors` while it
has its default value `true`. The protocol itself always reports the flags of a `Binding`.

The agent reads what WPF already holds. It does not call converters, read source getters, update the
target or the source, or force the binding to resolve. Redaction applies as it does to reads:

- a bound property or element that is protected (for example a `PasswordBox`) or whose property name
  is redacted withholds the whole request;
- when the binding path or element name matches a redaction rule, `StringFormat`, `FallbackValue`,
  `TargetNullValue`, `ConverterParameter`, `XPath`, `DataItem`, `ResolvedSource` and
  `ResolvedSourcePropertyName` are omitted (for a `MultiBinding` or `PriorityBinding`, when any
  child binding matches);
- a value whose type name matches a rule, or that is a protected object, is omitted on its own.

### Collection items

Expanding a member whose value is an object also asks the agent for that object's items
(the `members.items` request, advertised as the `membersItems` feature; restart a target that
still runs an older agent). Spy lists them as child rows directly under the object, before
its members:

- `Count`, when the collection reports one (a real `Count` member keeps its own row, and the
  items row is then labelled `Count (items)`);
- `[0]`, `[1]`, ... for arrays, lists and other enumerables, or `[key]` for dictionaries;
- a `Load more items` row when more items follow. Pages hold up to 200 items; a plain
  enumerable that does not report a count is re-walked from the start to reach a later page;
- `Enumeration threw <Type>: <message>` when enumerating failed part-way. The items read
  before the failure stay listed, and the message is sanitized and bounded like getter errors.

An item that is an object can be expanded like any other row, and shows its own members and
items. Strings and protected identities (password controls) list no items, and a value that is not enumerable adds no rows. Enumerating runs application code (an
`IEnumerable` can be lazy, slow or have side effects), so Spy only does it when you expand a row,
never in the automatic read. Item rows cannot be read again or copied as locator paths.

Python code can read the same pages with `InspectorClient.items(object_id, generation,
page_size=..., page_token=..., deadline=...)`, and the extension uses the
`inspect.managed.items` request, which takes `sessionId`, `objectId`, `generation`, and optional
`pageSize` and `pageToken`, and returns `kind` (`array`, `list`, `dictionary`, `enumerable` or
`notEnumerable`), `count`, `items`, `nextPageToken`, `complete` and an optional page `error`.

### Style, templates and resources

Selecting a `FrameworkElement` or `FrameworkContentElement` also asks the agent for its styling
(the `members.styling` request, advertised as the `membersStyling` feature; restart a target that
still runs an older agent). Spy shows it under **.NET > Style and template** and **.NET > Resources**:

- **Style:** the style the element uses with its target type and key. The source says how it was
  found: `local` (set on the element, including by an `ItemContainerStyle`), `implicit` (an
  implicit style found for the element's type), `typeLookup` (the element has no `Style`, so the
  agent looks up the default style key, which finds the theme's default style) or `none`. The key is
  the type for an implicit or looked-up style; otherwise it is the `x:Key` when the style sits in a
  resource dictionary on the way from the element to the application (a bounded search of at most
  1024 entries, so a style stored elsewhere has no key).
- **`Setter <Owner.Property>` rows:** one per setter. A value is shown as it is; markup is *named, not
  evaluated*: `{DynamicResource Key}`, `{Binding Path=..., ElementName=...}`, `{MultiBinding}`,
  `{PriorityBinding}` and `{TemplateBinding Property}`. An object value expands like any other row.
  A setter of a property whose name matches a redaction rule shows a redacted value and no
  expression.
- **`BasedOn[n]` rows:** the chain of styles the style is based on (target type and key per level, at
  most 8 levels), each opening to its own setters and triggers.
- **`Triggers[n]` rows:** `Trigger`, `DataTrigger`, `MultiTrigger`, `MultiDataTrigger` and
  `EventTrigger`, each opening to its conditions (a dependency property or binding path, the value
  compared and, for a template trigger, the part named by `SourceName`), its setters and its
  enter/exit action counts. The active state is `active` or `inactive` only for property triggers
  (`Trigger`, and `MultiTrigger` when every condition can be told): the element's current value is
  compared with the condition value, converting text only for enums and primitives. Data triggers
  and event triggers are `unknown`, as is any condition whose value cannot be compared.
- **Templates:** `ControlTemplate`, `ContentTemplate` (`ContentControl` and `ContentPresenter`),
  `ItemTemplate`, `ItemContainerStyle` and `ItemsPanel` rows, each opening to its triggers and, for
  the control and content templates, the named parts the template built on this element
  (`PART_...`; found among the element's own template visuals and confirmed through
  `Template.FindName`, so a template that is not applied yet lists none). A data template shows its
  `DataType`, an items panel the panel type. A `TemplatedParent` row expands to the control whose
  template created the element. A `ContentPresenter` that got its data template through an implicit
  `DataType` lookup has no `ContentTemplate` to show.
- **Resources:** one row per entry in the element's own `Resources`, named by its key (a type key
  by the type name, a `ComponentResourceKey` or `DataTemplateKey` by what it names). The listing
  names keys only, so each row says `(expand to read)`; expanding it reads that one value (the
  `members.resource` request, see below) and shows its text or, for an object, its members and
  items like any other row. Then the `MergedDictionaries` sources (`(inline)` for a dictionary
  without a `Source`) and an **Application resources** row with the entry count that opens to the
  first 100 keys of `Application.Resources`. An element without resources gets none created.

The agent reads framework properties only: it does not call converters, selectors, application
getters or setters, never evaluates `DynamicResource` or binding markup, and never applies a
template or updates the layout. Listing resources does not instantiate them: a dictionary loaded
from compiled XAML creates its resources only when they are looked up, so the listing enumerates the
dictionary's keys and never reads a value or enumerates the dictionary itself. The same goes for
naming the key of the style or template an element uses: the agent only looks at entries the
application has already created. Because no getter runs, the request does not count against the
automatic read budget and Spy sends it right after the members. Lists are capped: 32 setters, triggers, conditions
and template parts per owner, 8 `BasedOn` levels, 200 local resources, 100 application resources,
with a `...Truncated` flag and a total next to each cut list. A password control, and any object that is
not a framework element, returns an empty, not applicable result.

Python code can read the same result with `InspectorClient.styling(object_id, generation,
deadline=...)`, and the extension uses the `inspect.managed.styling` request, which takes
`sessionId`, `objectId` and `generation` and returns `applicable`, `style`, `templates`,
`resources` and `application`. An entry of `resources` or `application` is `key`, `keyKind` (`string`,
`type`, `componentResourceKey` or `other`) and `index`, the key's position in the dictionary's key order.

#### Reading one resource

Reading a resource's value is a request of its own because it is the one thing that can run
application code: looking a deferred resource up creates it in the target (its constructor runs, and
a resource that is not shared is created again). `members.resource` (the `membersStyling` feature)
takes the object handle plus the reference the listing returned, `scope` (`local` for the element's
own `Resources`, `application` for `Application.Current.Resources`), `key`, `keyKind` and the optional
`index`, and returns `found` with `valueType` and a `value` (an object handle for objects, so the
members and items of the value expand through the usual requests). The agent finds the key at `index`
when it still matches, otherwise the first key with the same text and kind; a key that is gone, a
password control and an object that is not a framework element answer `found: false`. A resource
whose key matches a redaction rule is never read: its value is redacted and its type is not named.
Merged dictionaries are not searched, only the dictionary the key was listed in. Python code uses
`InspectorClient.resource(object_id, generation, scope=..., key=..., key_kind=..., index=...,
deadline=...)`, and the extension uses `inspect.managed.resource`.

### Events

Selecting an object also asks the agent for its events (the `members.events` request, advertised as
the `membersEvents` feature; restart a target that still runs an older agent). Spy shows them under
**.NET > Events**, one row per event, after the members and without spending the automatic read
budget, because only metadata and delegate lists are read: **no handler or subscriber is ever
invoked**.

- **Routed events:** every routed event that applies to the object's type, found with
  `EventManager.GetRoutedEventsForOwner` for the type and each base type (class handlers are not
  listed). A row's value is `routed (Bubble), 2 handlers` (or `Tunnel`, `Direct`). Each event has the
  type that owns it (the first level of the hierarchy that does), the handler type and the
  routing strategy. The instance handlers come from the internal `EventHandlersStore` of
  `UIElement`, `ContentElement` and `UIElement3D`, read by reflection: handlers added in code
  (`+=`, `AddHandler`) and in XAML (`Click="OnClick"`) are listed with the declaring type and name of
  the method they call, and whether they also take events another handler marked handled
  (`handledEventsToo`).
- **CLR events:** the events the type and its base types declare, instance and static, public and
  not (explicit interface events included). A row's value is `CLR, 1 subscriber`. The subscribers
  come from the event's backing delegate field when it can be found (a field named like the event, or
  with `Event` added), each as the declaring type and name of the method it calls, with a static event
  marked. An event written with its own `add` and `remove` accessors, or one the framework keeps in
  a private store, has no field to read.
- **Wrappers are listed once:** a CLR event that only wraps a routed event of the same name and
  handler type (`Button.Click` over `ButtonBase.ClickEvent`) is not listed as a CLR event. The routed
  entry stands for it, so each event appears once.
- **Unknown handlers:** when the framework's private state, or a backing field, cannot be read, the
  row says `handlers unknown` instead of guessing, and the answer never fails because of it. A
  password control lists its event names and nothing about who listens, the same as for its other
  data.
- **Open a row** to see one row per handler or subscriber, `<DeclaringType>.<Method>`, marked
  `handledEventsToo` where it applies. A lambda is a method of the compiler's closure class, so it
  shows that class and a generated method name. At most 32 handlers or subscribers are listed per
  event, with the total and a note when the list was cut.
- **Order:** events somebody handles come first, then the rest, each group by name. Events with
  no handlers stay in the list.

Search and the collapsible **Events** heading work like those of the other sub-groups. Events are
paged like members (up to 200 per page, `pageSize` and `pageToken`); Spy loads up to ten pages. On
the wire a routed event names its list `handlersKnown`, `handlerCount`, `handlersTruncated` and
`handlers`, and a CLR event `subscribersKnown`, `subscriberCount`, `subscribersTruncated` and
`subscribers`, with `kind` (`routed` or `clr`) telling them apart. Python code reads the same page with
`InspectorClient.events(object_id, generation, page_size=..., page_token=..., deadline=...)`, and the
extension uses the `inspect.managed.events` request, which takes `sessionId`, `objectId`, `generation`,
`pageSize` and `pageToken`.

Reading getters, property descriptors, or creating automation peers can execute application
code, change state, or hang the UI. Timeouts bound waiting; they do **not** sandbox code or
stop a getter already executing. Use a disposable test process and avoid unsafe members.
Detach ends the session; it does not unload the injected agent. Restart the target to remove it.

## Redaction

Built-in case-insensitive name rules include `password`, `passwd`, `pwd`, `secret`, `token`,
`credential`, `connectionstring`, `apikey`, and `privatekey`; password controls receive
additional protection. Only password fields are protected objects: a `PasswordBox`, any part of
its template, an element whose own automation peer reports `IsPassword`, and a WinForms text box
with password characters. Other elements, including windows and panels without an automation
peer, are not protected, so their bindings, text and member values are readable unless a
redaction name matches. Add application-specific names with `redact_names`. Matching names
may over-redact benign values, while name-based rules cannot identify every secret. Do not
put secrets in locator `where` clauses, logs, or test data merely because redaction exists.
Non-secret type identity and permitted base members of protected controls remain available;
redaction does not hide every property of a sensitive control.

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

Agent queries search the combined WPF tree, including elements without UIA peers.
The agent returns at most 200 matches: if traversal
is incomplete with fewer than 200, the query raises a limit error; 200 incomplete matches
are returned because ambiguity is already evident. Managed keys require `backend: auto` and a WPF window; they are not supported by the UIA
backend. Equality and regular expressions use the
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

For help investigating an error, [save and review local diagnostics](diagnostics.md).

| Error code | Action |
|---|---|
| `invalidParams`, `invalidPageToken` | Correct the request or refresh the view and retry. |
| `unsupportedProtocol`, `unsupportedTarget` | Use compatible components and a supported target. |
| `accessDenied`, `blockedByPolicy` | Check account, session and integrity; ask your security administrator about a security-product block. Never disable protection to attach. |
| `authenticationFailed` | Retry attachment; investigate local session security if it persists. |
| `payloadMissing`, `payloadMismatch` | Install or repair the matching inspector payload. |
| `injectionFailed` | See `%APPDATA%\Snoop\SnoopLog.txt` and run `wtk doctor --agent`. |
| `injectionStalled` | Retry; restart the application if needed and check security software. |
| `bootstrapRejected` | Retry the attachment; restart the application if it continues to fail. |
| `agentNotStarted` | Restart the application and retry; run `wtk doctor --agent` if needed. |
| `agentVersionMismatch` | Restart the target after upgrading, then attach again. |
| `alreadyAttached` | Another WinTestKit session owns the agent; close that session or restart the application. |
| `inspectorDisabled` | Set `[tool.wintestkit.inspector] enabled = true` in the project config. |
| `notAttached` | Explicitly attach to the target. |
| `attachFailed` | Check target compatibility, permissions and `wtk doctor`. |
| `processExited`, `processReused`, `sessionStale`, `objectStale` | Reselect the live process or element and reattach. |
| `mappingFailed` | Select a UIA element with a supported, unambiguous peer. |
| `memberAmbiguous`, `memberNotFound` | Reinspect the element and use the observed member identity. |
| `dispatcherUnavailable`, `timeout`, `busy` | The application UI thread is busy. Reads queue at background priority and are raised to normal priority after 250 ms, so a UI thread that keeps itself busy at normal priority can still be read within the 500 ms queue limit. The attachment remains ready; allow the UI to respond and retry the selection. Dispatcher diagnostics include queue and execution times and whether the request was raised. A timeout cannot stop running code. |
| `limitExceeded` | Narrow the locator or request fewer paths. |
| `cancelled` | Retry if the operation is still needed. |
| `internalError` | Collect non-sensitive diagnostics and report the failure. |
## Writes and method calls

Managed writes and method calls are denied by default. To permit specific members, add
an allowlist to the repository's `wintestkit.yaml` (or the shared `pyproject.toml`):

```yaml
inspector:
  writes:
    allow:
      - MyApp.Views.Editor.IsModified
      - MyApp.Views.Editor.SetTitle(System.String)
      - MyApp.Views.Editor.Reset()
```

Use the exact runtime type and property name, or the exact method signature with fully
qualified parameter types and no spaces. Properties inherited by that runtime type may
be listed. Wildcards, generic and array signatures, duplicate entries, and more than
128 properties or 128 methods are rejected. Local configuration cannot enable or replace
this repository policy. Policy changes require a new inspector session; the runtime closes
the old session when the configured policy changes.

Allowlisting grants permission, not a guarantee that a member is writable: the agent
still checks the member, protected identities, redaction rules, and rate limits. Write
attempts are audited without argument or property values. Use the narrowest list possible.

Use `backend: auto` and a WPF element, for example `page.editor.set_property("IsModified", True)`
or `page.editor.call("SetTitle", "Draft")`. `call()` returns the method result (or `None` for void); redacted results raise `ActionError`. Plain arguments map `str` to `System.String`, `bool` to `System.Boolean`, `int` to `System.Int64`, `float` to `System.Double`, and `decimal.Decimal` to `System.Decimal`. Use `Int32`, `Int64`, `Single`, `Double`, `Decimal`, `Enum`, and `Null` from `wintestkit` for explicit types. For example, `call("Overload", Int32(1))` requires `Overload(System.Int32)` in the allowlist; `Enum("Ns.Choice", "First")` requires `TakeEnum(Ns.Choice)`. Pass `Null("System.String")` for null references; nullable value types use ``Null("System.Nullable`1[System.Int32]")`` and the identical spelling in the allowlist. Python enum members and bare `None` are not accepted. Decimal values travel as strings; enum integers must fit in signed 64 bits. Flags enums permit combinations; other enum values must be defined.

| Python argument | CLR type or behavior |
| --- | --- |
| `str`, `bool`, `int`, `float` | `System.String`, `System.Boolean`, `System.Int64`, `System.Double` |
| `decimal.Decimal` | `System.Decimal` |
| `Int32(v)`, `Int64(v)` | `System.Int32`, `System.Int64` |
| `Single(v)`, `Double(v)` | `System.Single`, `System.Double` |
| `Decimal(v)` | `System.Decimal` from a decimal or string |
| `Enum(type, name_or_integer)` | Exact declared enum type |
| `Null(type)` | Null reference or nullable value of the declared type |

Dependency properties, including CLR wrappers of dependency properties, use
`SetCurrentValue` to preserve bindings; ordinary CLR properties use their public setter.
Protected identities (including password controls), redacted names, static, generic,
ref/out and params methods, and unsupported types are denied even if listed. The agent
admits at most 10 write attempts per rolling second per session; denied attempts count too.
The HTML report and `wtk report` show each step's audit and a write summary, without values.
A client failure without an agent audit is recorded as `clientFailure` with an unknown type
and redacted member; the outcome of a request whose response was lost may be unknown.

Pure method calls: public instance methods directly marked with an attribute named `PureAttribute` may be called without an allowlist entry. Signature, redaction, deadline and rate limits still apply; property setters always require an allowlist entry. The attribute is the author's claim, not proof: a method can still have side effects. Value-free audits identify authorization as `pure` or `allowlist`; denied attempts omit it.

Attached properties appear when locally set or exposed by the WPF descriptor provider. In addition, commonly used framework attached properties and public static attached-property fields in application assemblies appear when their effective value source is not Default, including values supplied by styles, templates, or inheritance. Discovery scans are bounded; an incomplete scan reports a discovery diagnostic.
