# WPF inspector pipe protocol 2.0

Status: design contract for phase 0; not implemented. Protocol 2.0 replaces 1.0 outright.
Its foundational capabilities are specified in [the inspector plan](wpf-dotnet-attribute-analyzer.md#6-exact-protocol-and-dto-contract)
and [implementation brief §3.2–3.3](wpf-inspector-implementation-brief.md#32-protocol-library-s2-implements-s3s4as4b-consume),
subject to decisions D1–D7 in the [migration plan](wpf-tree-driven-automation.md#3-decisions-owner-2026-10-29).
The decisions below define the phase-0 contract, not evidence of implementation.

## Version, envelope and features

Require protocolMajor `2`, protocolMinor `0`. Protocol 2.0 includes framing, authentication, request and
response envelopes, strict JSON, bootstrap security, ObjectRef, PathSegment, Value, paging,
read, member and binding methods, errors, leases and redaction, except as changed here. Objects are closed (`additionalProperties:false`);
optional fields are absent, not null, unless explicitly stated. The 2.0 `session.hello` has
`{protocolMajor:2,protocolMinor:0,sessionId,token,process}` and returns the existing
`{agentVersion,tfm,architecture,runtimeVersion,features,process}`. A minor is accepted only when required features are present. Requests for
unadvertised features fail `unsupportedTarget`.

The existing six feature identifiers remain unchanged. The new identifiers are `query`,
`geometry`, `actions`, `virtualItems`, `writes`, `hitTest`, `waits`, `events`. A complete 2.0
agent requires the existing six plus `query`, `geometry`, `actions`, `virtualItems`, `hitTest`,
`waits`, and `events`; only `writes` is optional. Advertisement of `writes` does
not enable writes: an empty bootstrap allowlist denies them. Partial phase builds advertise
only implemented features and do not claim complete 2.0 support.

## Common DTOs and bounds

Identifiers are nonempty strings of at most 128 characters; type names and member keys at
most 1,024. Existing path and Value limits apply. All durations are integer milliseconds.
`handle` below is the existing complete ObjectRef, including sessionId, objectId, generation,
type and dispatcherId. Handles are session-bound and stale handles fail `objectStale`.

* `Scope` is exactly one of `{kind:"allRoots"}`, `{kind:"window",handle:ObjectRef}` or
  `{kind:"object",handle:ObjectRef}`. Window and object scopes include the scoped root at
  depth 0. All roots starts each root at depth 0. Traversal is depth-first pre-order, with roots
  in PresentationSource enumeration order. Combined mode visits visual children before logical-only
  children, deduplicating by identity across the traversal; each category follows WPF enumeration
  order. Item searches use their container’s Items enumeration order.
* `Locator` is `{scope:Scope,tree:"visual"|"logical"|"combined",predicates:Predicate[],
  depth:integer,depthMode:"tree"|"peers",index?:integer,limit:integer}`. Predicates are ANDed, 0–32 entries; depth is
  0–256, index is zero-based 0–9999, limit is 1–200. Tree defaults to combined, depth to
  256, limit to 100 when omitted by the caller before serialization. Index selects after
  filtering, in traversal order. A request always carries all required fields. In tree mode depth
  counts tree edges. In peers mode the scope root is peer depth 0; every other object has
  peer depth equal to the number of peer-bearing objects on the path from the root (exclusive)
  to that object (inclusive). Objects at peer depth at most depth are visited and matched,
  including peerless objects; traversal stops below a peer-bearing object at the depth limit.
* A predicate path whose first member is absent on an object's runtime type does not match that object.
* `Predicate` is one of `{kind:"equals",path:PathSegment[],value:Scalar}`,
  `{kind:"regex",path:PathSegment[],pattern:string,flags:string[]}` or
  `{kind:"assignableTo",fullName:string}`. Scalar is a JSON string, boolean or finite
  number; equality is type-aware and never coerces booleans to numbers. Regex pattern is at
  most 1,024 characters, flags are a unique subset of `ignoreCase`, `multiline`, `singleline`;
  Matching uses Python `re.search` semantics on this shared subset: ASCII literals, escaped
  regex metacharacters, `.`, `^`, `$`, ASCII character classes and ranges (including negation),
  groups `(...)` and `(?:...)`, alternation `|`, quantifiers `*`, `+`, `?`, `{m}`,
  `{m,}`, `{m,n}` and lazy forms. Bounds are decimal integers at most 10000, with m ≤ n.
  Input may be Unicode; `ignoreCase` uses ASCII-only folding, `multiline` changes anchors at
  newline boundaries, `singleline` makes dot match newline, and `$` also matches before a
  final newline. Inline flags, shorthand classes, lookaround, backreferences, named groups,
  Unicode categories and other constructs, malformed patterns and flags fail `invalidParams`.
  Validate before matching and implement equivalent anchor and case behavior. `assignableTo` implements `type:Is` using already loaded type
  metadata, never loading a type. Exact type matching uses equality on `type:FullName`.
  The read and element.readBatch methods also accept these single-segment UIA paths; no peer
  yields an unavailable Value, subject to the same redaction rules.
  UIA-equivalent paths use one segment `{kind:"uia",name:...}` with name exactly
  `automation_id`, `name`, `class_name`, or `control_type`. The agent computes automation_id
  from AutomationProperties.AutomationId then x:Name, name and control_type from the peer,
  and class_name from the control’s short runtime `Type.Name` (for example `Button`). Missing
  peers yield unavailable peer-derived values, not guesses. Typed paths use the linked shapes.
  Unreadable predicate values (redacted, truncated, unavailable, getter-failed, unsupported)
  fail the query with `valueUnreadable` (`details.status` and `details.path`, unless the path is
  redacted). Null and nullIntermediate do not match; peer-derived `uia` paths on elements
  with no automation peer do not match and are not errors.
* `ElementState` includes optional `uiaRuntimeId:integer[]` from its automation peer, and is `{handle:ObjectRef,windowHandle:integer|null,bounds:Rect|null,dpi:{x:number,y:number},
  visible:boolean,clipped:boolean,offscreen:boolean,enabled:boolean,focused:boolean,
  isKeyboardFocusable:boolean,parts:PartGeometry[]}`. Each part is
  `{name:string,role:string,bounds:Rect|null}`; name is its template `x:Name`, and role is
  `expanderToggle`, `comboDropDown`, `scrollThumb`, `scrollDecrement`, `scrollIncrement`,
  `scrollTrack`, `treeItemExpander`, `gridColumnHeader`, or `templatePart`. Include all named
  parts found in the applied template (up to 64, scanning at most 4096 visual nodes), including header instances, with semantic roles when
  recognized. Missing parts are absent; null bounds mean no usable geometry. Including parts in
  state gives geometry and visibility one snapshot and deadline. `Rect` is `{x:number,y:number,width:number,height:number}`
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
  Multiple matches select the first in Items order and return a warning as defined below;
  budget exhaustion before finding a match is `limitExceeded`.

## Methods

Every request uses the common envelope. `timeoutMs` where specified is 1–2000 and cannot
exceed the caller's remaining deadline. All methods require their named feature. These shapes
are exact; no implicit sessionId is needed beyond the ObjectRefs and authenticated session.

| Method | Params | Result |
| --- | --- | --- |
| `query.find` | `{locator:Locator,timeoutMs}` | `{match:ObjectRef,warning?:MatchWarning}`; zero gives `notFound`, multiple select the first and warn. `index` explicitly chooses one after filtering. |
| `query.findAll` | `{locator:Locator,timeoutMs}` | `{matches:ObjectRef[],count?:integer,complete:boolean}` in traversal order. Return at most `limit` (at most 200); if more match, return the first `limit` with `complete:false`, never an error merely for exceeding the cap. Include total `count` only when traversal finishes within budget; otherwise omit it and set `complete:false`. |
| `state.get` | `{handle:ObjectRef,timeoutMs}` | `{state:ElementState}` |
| `act.focus`, `act.bringIntoView`, `act.invoke`, `act.toggle`, `act.expand`, `act.collapse`, `act.select`, `act.scrollIntoView` | `{handle:ObjectRef,timeoutMs}` | ActResult |
| `act.setValue` | `{handle:ObjectRef,value:string,timeoutMs}` | ActResult; value at most 4096 Unicode scalar values |
| `act.setRange` | `{handle:ObjectRef,value:number,timeoutMs}` | ActResult; finite value, within peer range |
| `act.scroll` | `{handle:ObjectRef,horizontal:ScrollAmount,vertical:ScrollAmount,timeoutMs}` | ActResult; ScrollAmount is `none`, `smallIncrement`, `smallDecrement`, `largeIncrement`, `largeDecrement` |
| `act.realizeItem` | `{search:ItemSearch,timeoutMs}` | `{outcome:"performed"|"noChange",handle:ObjectRef,warning?:MatchWarning}`. Search data first, then ScrollIntoView and generate only the first match; never realize the other items. |
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

`MatchWarning` is `{code:"multipleMatches",count:integer}`. Count is the number observed
within the search budget, including the chosen match; it may be a lower bound. Once a first
match is found, budget exhaustion returns it rather than an error. Python logs
`selector matches N elements; using the first` for every step with this warning.

`EventKind` is `windowOpened`, `windowClosed`, `treeChanged`; `overflow` is a reserved
notification kind, not subscribable. Notifications are framed as
`{method:"events.event",params:{subscriptionId,sequence,kind,handle?:ObjectRef}}` without a
request id. Sequence starts at 1 and increases monotonically per subscription; delivery is
ordered per subscription. Each subscription buffers at most 1,024 notifications. On overflow,
drop pending buffered notifications and the triggering notification, enqueue one `overflow`
without a handle, and suppress ordinary notifications until it is delivered; the client must
rescan. Sequence gaps indicate dropped notifications. Subscriptions are session-scoped and
removed on detach or disconnect; after reconnect Python resubscribes and rescans. Python uses
window open/close events rather than polling to detect windows.

## Writes, ordering and safety

Protocol 2 bootstrap extends the existing bootstrap with required
`writeAllowlist:{properties:AllowEntry[],methods:AllowEntry[]}`. Each `AllowEntry` is
`{typeFullName:string,memberKey:string}`; exact runtime type and exact public instance member
identity must both match. Both arrays default to empty at configuration translation, contain
at most 128 unique entries each, and are serialized even when empty. No wildcards, overload
inference, static members, dynamic type loading, arbitrary code, scripting, or arbitrary
payloads. Set a dependency property with SetCurrentValue; CLR properties require a public
setter. Calls accept only public instance methods and scalar arguments. A member must resolve
uniquely. Property keys are exact public property names. Method keys follow
`MethodName "(" [ TypeName ( "," TypeName )* ] ")"`: exact CLR metadata names, full CLR type
names, and no whitespace (for example `Refresh(System.Boolean)` or `Reset()`). Generic, array,
nullable, by-reference and other types outside the table cannot match. Null/None is forbidden;
no automatic conversions occur:

| JSON value | Exact CLR parameter/property type |
| --- | --- |
| string | `System.String` |
| boolean | `System.Boolean` |
| integer token in signed 64-bit range | `System.Int64` |
| non-integer number token, finite and representable | `System.Double` |

Other types and out-of-range values fail `invalidParams`. The repository must opt in;
the protected, expiring bootstrap carries the resulting allowlist. Each attempt produces an
audit record, including denied and failed attempts, without argument/property values:
`WriteAudit` is `{operation:"setProperty"|"call",typeFullName:string,memberKey:string,
outcome:"performed"|"denied"|"failed",timestampUtc:string,reason?:string}` (RFC3339). At a
Dispatcher deadline, write the audit immediately with `outcome:"failed",reason:"timeout"`,
even if target code remains hung; never replace it with a late outcome. Successful responses
return it; errors include it as `details.audit`; Python records every audit in the report.
Redaction applies to returned data and diagnostics; a redacted member identifier in audit is
represented by the applicable redaction rule, never the member name.

Use the linked foundational limits and scheduling except where specified here. Query traversal has a 10,000-object/2,000 ms budget,
200 objects or 10 ms per Dispatcher slice, and at most 200 returned matches. Regex matches
have a 50 ms timeout each, additionally bounded by the request deadline; regex timeout is
`regexTimeout`. Limit explicit item enumeration to 10,000 items per request. Writes/calls
are limited to 10 attempts per session per rolling second; excess is `writeRateExceeded` and
is audited.
All act and write work is serialized with other work on its owning Dispatcher: one operation
at a time, at most four active per session, max 16 queued. A running action/getter/call cannot
be safely aborted. At deadline discard late results, mark that Dispatcher unresponsive, reject
later work there with `dispatcherUnavailable`, and do not queue replacement work; other
Dispatchers remain independent. Never abort a thread or terminate the target. For mouse input,
check foreground window ownership and target point before injecting input.

The protocol includes the foundational error codes and `notFound`, `actionUnsupported`,
`regexTimeout`, `valueUnreadable`, `writeDenied`, `writeRateExceeded`. All errors use the existing
`{code,message,details}` envelope and omit sensitive values. `writeDenied`, `writeRateExceeded`, and failed write/call
errors carry `details.audit`. A timeout does not imply cancellation of running target code.

## Existing Python actions

Pattern mode uses peer actions; mouse mode uses real input and geometry from `state.get`.
For whole-element actions the mouse target is the center of current physical-pixel bounds after visibility,
stability and foreground checks. Python uses `state.windowHandle` to verify foreground window
ownership before injecting input; a null or invalid handle or failed check prevents injection. An unavailable or unsafe rectangle fails rather than clicking
another window. For sub-part actions use the center of the corresponding part rectangle, not
the control center; missing, invisible, clipped or unsafe parts fail rather than guessing. `mode=` overrides the repository default `mouse` (D1).

| Existing action/control | Pattern mode | Mouse mode / geometry |
| --- | --- | --- |
| click (Button and common clickable) | `act.invoke`, `act.toggle`, `act.select`, or `act.expand`/`act.collapse` according to supported peer | center, left click |
| double_click, right_click, hover | real input (no corresponding peer verb) | center, double/right click or move |
| focus; press | `act.focus`; press uses real keys | focus target then real keys; center if click needed |
| type, clear (TextBox) | `act.setValue` where supported; keys when explicitly requested | focus target and send keys; center when needed |
| check, uncheck, toggle (CheckBox) | `act.toggle` until requested state, bounded as existing action | center click; verify state |
| select self (RadioButton, ListItem) | `act.select` | center click |
| expand, collapse | `act.expand`, `act.collapse` | click `expanderToggle` or `treeItemExpander` as appropriate |
| select item (ComboBox, ListBox, DataGrid, TreeView, TabControl) | item-data search, `act.realizeItem`, `act.scrollIntoView`, `act.select` | ComboBox: click `comboDropDown` to open, then realize the first matching item and click its bounds; other controls: realize the first item and click its bounds |
| scroll bar | `act.scroll` / `act.setRange` | click `scrollDecrement`, `scrollIncrement` or `scrollTrack`, or drag `scrollThumb`, according to action |
| grid column header | peer action when supported | click the target `gridColumnHeader` part |
| named template part | peer action when supported | click the requested `templatePart` by `x:Name` |
| ensure_visible | `act.bringIntoView` / `act.scrollIntoView`; `act.realizeItem` for data match | same preparation, then element geometry |
| bring_to_front, raise_without_activating, window_is_minimized | existing OS window operations | window HWND, not element click geometry |
| get_text, get_value, is_checked, is_selected, selected_items, item names | reads/query, not act verbs | reads/query; no click geometry |

D4 attaches once per WPF process on launch/attach; D5 propagates agent errors without silent
UIA fallback. D7 switches `auto` to default at the phase 3 parity gate; non-WPF windows and
explicit `backend: uia` keep the UIA backend.

## Resolved decisions (owner, 2026-10-30)

0. Protocol 2.0 replaces 1.0; no backward compatibility constraint.
1. Proposed limits are accepted; write rate is per session.
2. class_name is Type.Name; the shared regex subset and traversal order are specified above.
3. Multiple matches choose the first and produce a bounded-count warning and Python log.
4. Events are required, sequenced and buffered; overflow and reconnect require rescan.
5. Writes use overload-specific allowlists, exact scalar types, no nulls, and timeout/redaction-safe audit.
6. ElementState exposes template-part geometry for actual sub-part mouse input.
7. findAll returns capped results with complete:false and count only after full traversal.
8. Unreadable predicate values fail the query with valueUnreadable; missing peers do not match.
9. ElementState carries an optional uiaRuntimeId so phase 1 can act on WPF matches through UIA.

10. A predicate path whose first member is absent on an object's runtime type does not match that object.

11. depthMode peers counts depth in automation-peer-bearing objects so depth= means the same on the UIA and WPF backends.
