# WPF inspector pipe protocol 2.0

Status: design contract for phase 0; not implemented. This extends the retained protocol 1.0
contract in [the inspector plan](wpf-dotnet-attribute-analyzer.md#6-exact-protocol-and-dto-contract)
and [implementation brief §3.2–3.3](wpf-inspector-implementation-brief.md#32-protocol-library-s2-implements-s3s4as4b-consume),
subject to decisions D1–D7 in the [migration plan](wpf-tree-driven-automation.md#3-decisions-owner-2026-10-29).
The open questions below require resolution before the affected slices are implemented; the
wire choices in this document are the proposed phase-0 contract, not evidence of implementation.

## Version, envelope and features

Use protocolMajor `2`, protocolMinor `0`. Retain the 1.0 framing, authentication, request and
response envelopes, strict JSON, bootstrap security, ObjectRef, PathSegment, Value, paging,
existing methods, errors, leases and redaction. Objects are closed (`additionalProperties:false`);
optional fields are absent, not null, unless explicitly stated. The 2.0 `session.hello` has
`{protocolMajor:2,protocolMinor:0,sessionId,token,process}` and returns the existing
`{agentVersion,tfm,architecture,runtimeVersion,features,process}`. A 1.x hello is rejected
with `unsupportedProtocol` and no values; a 2.0 client refuses a 1.x agent with
`agentVersionMismatch` and directs the user to restart the target. Different majors never
negotiate down. A minor is accepted only when required features are present. Requests for
unadvertised features fail `unsupportedTarget`.

The existing six feature identifiers remain unchanged. The new identifiers are `query`,
`geometry`, `actions`, `virtualItems`, `writes`, `hitTest`, `waits`, `events`. A complete 2.0
agent requires the existing six plus `query`, `geometry`, `actions`, `virtualItems`, `hitTest`,
and `waits`; `writes` and `events` are optional capabilities. Advertisement of `writes` does
not enable writes: an empty bootstrap allowlist denies them. Partial phase builds advertise
only implemented features and do not claim complete 2.0 support.

## Common DTOs and bounds

Identifiers are nonempty strings of at most 128 characters; type names and member keys at
most 1,024. Existing path and Value limits apply. All durations are integer milliseconds.
`handle` below is the existing complete ObjectRef, including sessionId, objectId, generation,
type and dispatcherId. Handles are session-bound and stale handles fail `objectStale`.

* `Scope` is exactly one of `{kind:"allRoots"}`, `{kind:"window",handle:ObjectRef}` or
  `{kind:"object",handle:ObjectRef}`. Window and object scopes include the scoped root at
  depth 0. All roots starts each root at depth 0; combined traversal deduplicates by identity.
* `Locator` is `{scope:Scope,tree:"visual"|"logical"|"combined",predicates:Predicate[],
  depth:integer,index?:integer,limit:integer}`. Predicates are ANDed, 0–32 entries; depth is
  0–256, index is zero-based 0–9999, limit is 1–200. Tree defaults to combined, depth to
  256, limit to 100 when omitted by the caller before serialization. Index selects after
  filtering, in traversal order. A request always carries all required fields.
* `Predicate` is one of `{kind:"equals",path:PathSegment[],value:Scalar}`,
  `{kind:"regex",path:PathSegment[],pattern:string,flags:string[]}` or
  `{kind:"assignableTo",fullName:string}`. Scalar is a JSON string, boolean or finite
  number; equality is type-aware and never coerces booleans to numbers. Regex pattern is at
  most 1,024 characters, flags are a unique subset of `ignoreCase`, `multiline`, `singleline`;
  matching is search semantics. `assignableTo` implements `type:Is` using already loaded type
  metadata, never loading a type. Exact type matching uses equality on `type:FullName`.
  UIA-equivalent paths use one segment `{kind:"uia",name:...}` with name exactly
  `automation_id`, `name`, `class_name`, or `control_type`. The agent computes automation_id
  from AutomationProperties.AutomationId then x:Name, name and control_type from the peer,
  and class_name from WPF type identity. Missing peers yield unavailable values, not guesses.
  Existing typed path segments retain their 1.0 shapes. Redacted, truncated, unavailable and
  getter-failed values cannot silently match; report the relevant failure.
* `ElementState` is `{handle:ObjectRef,windowHandle:integer|null,bounds:Rect|null,dpi:{x:number,y:number},
  visible:boolean,clipped:boolean,offscreen:boolean,enabled:boolean,focused:boolean,
  isKeyboardFocusable:boolean}`. `Rect` is `{x:number,y:number,width:number,height:number}`
  in physical screen pixels, including negative coordinates; width and height are nonnegative.
  `windowHandle` is the native HWND of the element's top-level HwndSource, or null when none.
  DPI values are positive physical dots per inch. Null bounds means no usable screen geometry.
  Visibility accounts for WPF visibility, opacity, ancestor clips and scroll viewport;
  offscreen also accounts for screen intersection. Geometry does not assert foreground ownership.
* `ActResult` is `{outcome:"performed"|"noChange",handle:ObjectRef}`; it never returns a
  control value. Unsupported peer patterns fail `actionUnsupported` rather than reporting success.
* `WaitCondition` is `{kind:"exists"|"visible"|"enabled",locator:Locator}` or
  `{kind:"propertyEquals",locator:Locator,path:PathSegment[],value:Scalar}`.
  `WaitResult` is `{satisfied:boolean,handle?:ObjectRef,state?:ElementState}`; handle and
  state are present on a satisfied condition, absent on timeout. An incomplete search is an
  error, never an unsatisfied result.
* `ItemSearch` is `{container:ObjectRef,match:ItemMatch,maxItems:integer}` where ItemMatch is
  `{kind:"index",index:integer}` or `{kind:"equals",path:PathSegment[],value:Scalar}` or
  `{kind:"regex",path:PathSegment[],pattern:string,flags:string[]}`; maxItems is 1–10000,
  index 0–9999. It enumerates ItemsSource/Items data with this explicit cap, applying the
  same scalar, regex and redaction rules; it must not realize candidates to search them.
  Ambiguous data matches fail `ambiguousMatch`; budget exhaustion is `limitExceeded`.

## Methods

Every request uses the common envelope. `timeoutMs` where specified is 1–2000 and cannot
exceed the caller's remaining deadline. All methods require their named feature. These shapes
are exact; no implicit sessionId is needed beyond the ObjectRefs and authenticated session.

| Method | Params | Result |
| --- | --- | --- |
| `query.find` | `{locator:Locator,timeoutMs}` | `{match:ObjectRef}` for exactly one match; zero gives `notFound`, multiple give `ambiguousMatch` with bounded `{count,handles}` details. `index` explicitly chooses one. |
| `query.findAll` | `{locator:Locator,timeoutMs}` | `{matches:ObjectRef[],count:integer,complete:boolean}` in traversal order. If the result limit prevents establishing the total, return `limitExceeded`, not a misleading count. |
| `state.get` | `{handle:ObjectRef,timeoutMs}` | `{state:ElementState}` |
| `act.focus`, `act.bringIntoView`, `act.invoke`, `act.toggle`, `act.expand`, `act.collapse`, `act.select`, `act.scrollIntoView` | `{handle:ObjectRef,timeoutMs}` | ActResult |
| `act.setValue` | `{handle:ObjectRef,value:string,timeoutMs}` | ActResult; value at most 4096 Unicode scalar values |
| `act.setRange` | `{handle:ObjectRef,value:number,timeoutMs}` | ActResult; finite value, within peer range |
| `act.scroll` | `{handle:ObjectRef,horizontal:ScrollAmount,vertical:ScrollAmount,timeoutMs}` | ActResult; ScrollAmount is `none`, `smallIncrement`, `smallDecrement`, `largeIncrement`, `largeDecrement` |
| `act.realizeItem` | `{search:ItemSearch,timeoutMs}` | `{outcome:"performed"|"noChange",handle:ObjectRef}`. Search data first, then ScrollIntoView and generate only the one match; never realize the other items. |
| `wait.until` | `{condition:WaitCondition,timeoutMs}` | WaitResult. Recheck on relevant layout/property changes until deadline; timeout returns `satisfied:false`. |
| `hitTest` | `{nativeWindowHandle:integer,point:{x:number,y:number},timeoutMs}` | `{handle:ObjectRef}` or `notFound`; point uses physical screen pixels. |
| `write.setProperty` | `{handle:ObjectRef,memberKey:string,value:Scalar,timeoutMs}` | `{audit:WriteAudit}` |
| `write.call` | `{handle:ObjectRef,memberKey:string,arguments:Scalar[],timeoutMs}` | `{audit:WriteAudit}`; at most 16 scalar arguments, no return value |
| `events.subscribe` | `{kinds:EventKind[]}` | `{subscriptionId:string}`; 1–3 unique kinds |
| `events.unsubscribe` | `{subscriptionId:string}` | `{unsubscribed:boolean}` |

For `hitTest`, the agent verifies that the native HWND is live and belongs to the target process,
then maps it through `HwndSource.FromHwnd` on its Dispatcher to the root visual before hit-testing.
A handle that is not a WPF HwndSource of this process fails `mappingFailed`; a valid source with
no hit returns `notFound`.

`EventKind` is `windowOpened`, `windowClosed`, `treeChanged`. Events are notifications
`{method:"events.event",params:{subscriptionId,kind,handle?:ObjectRef}}` without request id;
no values are carried. Subscriptions are session-scoped and removed on detach. Delivery is
best-effort; a client must rescan after a lost connection. The precise buffering/overflow
policy remains an open question below.

## Writes, ordering and safety

Protocol 2 bootstrap extends the existing bootstrap with required
`writeAllowlist:{properties:AllowEntry[],methods:AllowEntry[]}`. Each `AllowEntry` is
`{typeFullName:string,memberKey:string}`; exact runtime type and exact public instance member
identity must both match. Both arrays default to empty at configuration translation, contain
at most 128 unique entries each, and are serialized even when empty. No wildcards, overload
inference, static members, dynamic type loading, arbitrary code, scripting, or arbitrary
payloads. Set a dependency property with SetCurrentValue; CLR properties require a public
setter. Calls accept only public instance methods and scalar arguments. A member must resolve
uniquely and its arguments must match without arbitrary conversion. The repository must opt in;
the protected, expiring bootstrap carries the resulting allowlist. Each attempt produces an
audit record, including denied and failed attempts, without argument/property values:
`WriteAudit` is `{operation:"setProperty"|"call",typeFullName:string,memberKey:string,
outcome:"performed"|"denied"|"failed",timestampUtc:string}` (RFC3339). Successful responses
return it; errors include it as `details.audit`; Python records every audit in the report.
Redaction applies to all returned data, diagnostics and audit identifiers under existing rules.

Retain 1.0 limits and scheduling. Query traversal has a 10,000-object/2,000 ms budget,
200 objects or 10 ms per Dispatcher slice, and at most 200 returned matches. Regex matches
have a 50 ms timeout each, additionally bounded by the request deadline; regex timeout is
`regexTimeout`. Limit explicit item enumeration to 10,000 items per request. Writes/calls
are limited to 10 attempts per session per rolling second; excess is `writeRateExceeded` and
is audited. These numeric choices are phase-0 proposals subject to the open questions below.
All act and write work is serialized with other work on its owning Dispatcher: one operation
at a time, at most four active per session, max 16 queued. A running action/getter/call cannot
be safely aborted. At deadline discard late results, mark that Dispatcher unresponsive, reject
later work there with `dispatcherUnavailable`, and do not queue replacement work; other
Dispatchers remain independent. Never abort a thread or terminate the target. For mouse input,
check foreground window ownership and target point before injecting input.

Keep every 1.0 error code unchanged. Add `notFound`, `ambiguousMatch`, `actionUnsupported`,
`regexTimeout`, `writeDenied`, `writeRateExceeded`. All errors use the existing
`{code,message,details}` envelope and omit sensitive values. `ambiguousMatch` details contain
`count` and at most 5 `handles`; `writeDenied`, `writeRateExceeded`, and failed write/call
errors carry `details.audit`. A timeout does not imply cancellation of running target code.

## Existing Python actions

Pattern mode uses peer actions; mouse mode uses real input and geometry from `state.get`.
The common mouse target is the center of the current physical-pixel bounds after visibility,
stability and foreground checks. Python uses `state.windowHandle` to verify foreground window
ownership before injecting input; a null or invalid handle or failed check prevents injection. An unavailable or unsafe rectangle fails rather than clicking
another window. `mode=` overrides the repository default `mouse` (D1).

| Existing action/control | Pattern mode | Mouse mode / geometry |
| --- | --- | --- |
| click (Button and common clickable) | `act.invoke`, `act.toggle`, `act.select`, or `act.expand`/`act.collapse` according to supported peer | center, left click |
| double_click, right_click, hover | real input (no corresponding peer verb) | center, double/right click or move |
| focus; press | `act.focus`; press uses real keys | focus target then real keys; center if click needed |
| type, clear (TextBox) | `act.setValue` where supported; keys when explicitly requested | focus target and send keys; center when needed |
| check, uncheck, toggle (CheckBox) | `act.toggle` until requested state, bounded as existing action | center click; verify state |
| select self (RadioButton, ListItem) | `act.select` | center click |
| expand, collapse | `act.expand`, `act.collapse` | center click on control; exact expander geometry is unresolved below |
| select item (ComboBox, ListBox, DataGrid, TreeView, TabControl) | item-data search, `act.realizeItem`, `act.scrollIntoView`, `act.select` | realize matching item only, then click its center |
| ensure_visible | `act.bringIntoView` / `act.scrollIntoView`; `act.realizeItem` for data match | same preparation, then element geometry |
| bring_to_front, raise_without_activating, window_is_minimized | existing OS window operations | window HWND, not element click geometry |
| get_text, get_value, is_checked, is_selected, selected_items, item names | reads/query, not act verbs | reads/query; no click geometry |

D4 attaches once per WPF process on launch/attach; D5 propagates agent errors without silent
UIA fallback. D7 switches `auto` to default at the phase 3 parity gate; non-WPF windows and
explicit `backend: uia` keep the UIA backend.

## Open questions requiring owner/design resolution

1. The plans do not fix numeric query, regex, result and write-rate limits; are the proposed
   constants above acceptable, and should write-rate accounting span sessions/processes?
2. The plans do not define exact `class_name` equivalence for WPF, regex dialect/flag parity
   with Python, or traversal ordering across roots and combined visual/logical edges. These
   affect existing locator compatibility and require parity tests and a binding decision.
3. The plans do not specify data-item display-name extraction, matching of duplicate items,
   or how to obtain a stable item handle before realization. The ItemSearch representation
   and ambiguity policy above need validation against real list and grid controls.
4. The plans do not specify event notification framing, ordering, buffering, overflow and
   recovery, or whether events are required for a complete release. The proposed envelope and
   optional capability above need a decision before phase 7.
5. The plans do not define allowlist member-key format for method overloads, permitted scalar
   conversions/nulls, audit treatment when the Dispatcher hangs, or how redacted member names
   are represented in audit records. These must be resolved before enabling writes.
6. The plans do not define actionable sub-geometry for expanders, scrollbars, combo popups,
   or keyboard focus without a peer. Center-point mouse input alone may not preserve parity.
7. Required feature membership and whether `query.findAll` must count beyond its result cap
   are not specified in the plans; the proposed behavior needs owner review.
