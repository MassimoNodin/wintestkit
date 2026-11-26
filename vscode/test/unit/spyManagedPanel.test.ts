import { describe, expect, it, vi } from "vitest";
import type { ManagedInspector } from "../../src/spy/managedSession";
const mocks = vi.hoisted(() => ({ warning: vi.fn(), clipboard: vi.fn(), save: vi.fn(), write: vi.fn() }));
vi.mock("vscode", () => ({ window: { showWarningMessage: mocks.warning, showSaveDialog: mocks.save }, env: { clipboard: { writeText: mocks.clipboard } }, workspace: { getConfiguration: () => ({ get: () => false, update: vi.fn() }), fs: { writeFile: mocks.write } }, Uri: { file: (path: string) => path } }));
import { ManagedPanel, RESOURCE_PROMPT } from "../../src/spy/managedPanel";
function withSpy<T extends object>(inspector: T): ManagedInspector {
  const original = inspector as T & { resolve?: (...args: never[]) => Promise<{ status?: string }>; yieldToUser?: unknown };
  return new Proxy(original, { get(target, prop, receiver) {
    if (prop === "items" && !("items" in target)) return async () => ({ kind: "notEnumerable", count: null, items: [], nextPageToken: null, complete: true });
    if (prop === "clearSpy") return async () => {};
    if (prop === "bindSpy") return async () => false;
    if (prop === "yieldToUser" && !target.yieldToUser) return async () => 0;
    if (prop === "resolve" && target.resolve) return async (...args: never[]) => { const result = await target.resolve!(...args); return result && { status: "exact", ...result }; };
    return Reflect.get(target, prop, receiver);
  } }) as unknown as ManagedInspector;
}

it("loads method pages lazily, retries, and rejects stale selection results", async () => {
  let finish!: (value: unknown) => void;
  const page = (items: unknown[], nextToken?: string) => ({ items, complete: !nextToken, nextToken, snapshotId: "snapshot", diagnostics: [] });
  const inspector = { visible: true, state: "ready", sessionInfo: { sessionId: "s" }, select: vi.fn(), resolve: vi.fn(async (node: string) => ({ object: { objectId: node, generation: 3 } })), members: vi.fn(async () => page([])), bindings: vi.fn(), spyMethods: vi.fn<(params: { objectId: string; generation: number; pageToken?: string }) => Promise<unknown>>() };
  inspector.spyMethods.mockResolvedValueOnce(page([{ name: "First" }], "next")).mockResolvedValueOnce(undefined).mockResolvedValueOnce(page([{ name: "Second" }])).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; })).mockResolvedValueOnce(page([{ name: "New" }]));
  const send = vi.fn(), panel = new ManagedPanel(withSpy(inspector), send);
  panel.select("first"); await vi.waitFor(() => expect(inspector.members).toHaveBeenCalled());
  expect(inspector.spyMethods).not.toHaveBeenCalled();
  await panel.handle({ type: "managedMethods", action: "activate" });
  expect(inspector.spyMethods).toHaveBeenCalledWith({ objectId: "first", generation: 3 });
  await panel.handle({ type: "managedMethods", action: "more" });
  expect(send.mock.calls.at(-1)![0].methods.status).toBe("error");
  await panel.handle({ type: "managedMethods", action: "retry" });
  expect(inspector.spyMethods).toHaveBeenLastCalledWith({ objectId: "first", generation: 3 });
  expect(send.mock.calls.at(-1)![0].methods.items).toEqual([{ name: "Second" }]);
  panel.select("old"); await vi.waitFor(() => expect(inspector.spyMethods).toHaveBeenCalledTimes(4));
  panel.select("new"); await vi.waitFor(() => expect(inspector.spyMethods).toHaveBeenCalledTimes(5));
  finish(page([{ name: "Stale" }])); await Promise.resolve();
  expect(send.mock.calls.at(-1)![0].methods.items).toEqual([{ name: "New" }]);
});

describe("managed panel host", () => {
  it("publishes capability and does not attach when selecting a node", () => {
    const inspector = { visible: false, state: "not enabled", select: vi.fn(), attach: vi.fn() };
    const send = vi.fn();
    const panel = new ManagedPanel(withSpy(inspector), send);
    panel.select("node");
    expect(inspector.select).toHaveBeenCalledWith("node");
    expect(inspector.attach).not.toHaveBeenCalled();
    expect(send).toHaveBeenLastCalledWith(expect.objectContaining({ visible: false, state: "not enabled" }));
  });
  it("discards a resolve response after selection changes", async () => {
    let finish!: (value: unknown) => void;
    const inspector = { visible: true, state: "ready", select: vi.fn(), attach: vi.fn(async () => ({})), resolve: vi.fn(() => new Promise((resolve) => { finish = resolve; })) };
    const send = vi.fn();
    const panel = new ManagedPanel(withSpy(inspector), send);
    panel.select("first");
    const pending = panel.handle({ type: "managedAttach" });
    await Promise.resolve();
    panel.select("second");
    finish({ status: "exact", object: { objectId: "old" } });
    await pending;
    expect(send).toHaveBeenLastCalledWith(expect.objectContaining({ object: undefined, rows: [] }));
  });
});

describe("managed panel scoped operations", () => {
  const member = (name: string) => ({ memberKey: name, name, category: "clrProperty", declaringType: "T", declaredType: "T", visibility: "public", readable: true, attributes: [], pathSegment: { kind: "property", name } });
  const root = { objectId: "root", generation: 1, type: { fullName: "T", assemblyName: "A", baseTypes: [] } };
  const child = { objectId: "child", generation: 2, type: root.type };
  const page = (items: unknown[], nextToken?: string) => ({ items, complete: !nextToken, nextToken, diagnostics: [], snapshotId: "snapshot" });
  function fixture() {
    const inspector = { visible: true, state: "ready", sessionInfo: { sessionId: "s", process: { pid: 4, creationTimeUtc: "date" }, protocolMajor: 1, protocolMinor: 0 }, select: vi.fn(async () => {}), attach: vi.fn(async () => {}), resolve: vi.fn(async () => ({ object: root })), members: vi.fn(async (params: { objectId: string; pageToken?: string }) => params.objectId === "root" ? page([member("Parent")]) : params.pageToken ? page([member("Later")]) : page([member("Child")], "next")), read: vi.fn(async (params: { objectId: string }) => ({ values: [{ value: params.objectId === "root" ? { status: "ok", kind: "object", object: child } : { status: "redacted", kind: "unavailable", redactionRule: "secret" } }] })), bindings: vi.fn() };
    const send = vi.fn(); const panel = new ManagedPanel(withSpy(inspector), send); panel.select("node"); return { panel, inspector, send };
  }
  it("expands and paginates the child without reading child getters", async () => {
    const { panel, inspector, send } = fixture(); await vi.waitFor(() => expect(inspector.members).toHaveBeenCalled()); await panel.handle({ type: "managedExpand", memberKey: "Parent" }); expect(inspector.read).toHaveBeenCalledTimes(1); expect(inspector.members).toHaveBeenLastCalledWith({ objectId: "child", generation: 2 }); const row = send.mock.calls.at(-1)?.[0].rows[0]; await panel.handle({ type: "managedRead", memberKey: "Child", scope: row.id }); expect(inspector.read).toHaveBeenLastCalledWith(expect.objectContaining({ objectId: "child", generation: 2 })); await panel.handle({ type: "managedLoadMore", group: row.id }); expect(inspector.members).toHaveBeenLastCalledWith({ objectId: "child", generation: 2, pageToken: "next" }); expect(send.mock.calls.at(-1)?.[0].rows[0].children).toHaveLength(2);
  });
  it("shows collection pages and expands nested item handles", async () => {
    const { panel, inspector, send } = fixture();
    const nested = { ...child, objectId: "nested" };
    const first = { kind: "dictionary", count: 2, items: [{ index: null, key: { scalar: "key" }, value: { status: "ok", kind: "object", object: nested } }], nextPageToken: "next-items", complete: false };
    const second = { kind: "dictionary", count: 2, items: [{ index: 1, key: null, value: { status: "ok", kind: "integer", scalar: 9 } }], nextPageToken: null, complete: true, error: { type: "Oops", message: "bad" } };
    const items = vi.fn(async (params: { objectId: string; pageToken?: string }) => params.objectId === "nested" ? { kind: "notEnumerable", count: null, items: [], nextPageToken: null, complete: true } : params.pageToken ? second : first);
    Object.assign(inspector, { items });
    await vi.waitFor(() => expect(inspector.members).toHaveBeenCalled());
    await panel.handle({ type: "managedExpand", memberKey: "Parent" });
    let row = send.mock.calls.at(-1)![0].rows[0];
    expect(row.children.map((entry: { member: { name: string } }) => entry.member.name)).toEqual(["Count", "[key]", "Child"]);
    expect(row.itemPage.nextToken).toBe(true);
    expect(row.children[1].value.object).toEqual(nested);
    expect(row.children[0].value.scalar).toBe(2);
    const item = row.children[1];
    await panel.handle({ type: "managedExpand", memberKey: item.member.memberKey, scope: row.id });
    expect(inspector.members).toHaveBeenLastCalledWith({ objectId: "nested", generation: 2 });
    await panel.handle({ type: "managedLoadMore", group: "items:" + row.id });
    row = send.mock.calls.at(-1)![0].rows[0];
    // The second page and its error land after the first page's items and before the members.
    expect(row.children.map((entry: { member: { name: string } }) => entry.member.name)).toEqual(["Count", "[key]", "[1]", "Enumeration threw Oops: bad", "Child"]);
    expect(row.children[3]).toMatchObject({ item: true, text: "" });
    expect(row.itemPage.nextToken).toBe(false);
    await panel.handle({ type: "managedLoadMore", group: row.id });
    row = send.mock.calls.at(-1)![0].rows[0];
    expect(row.children.map((entry: { member: { name: string } }) => entry.member.name)).toEqual(["Count", "[key]", "[1]", "Enumeration threw Oops: bad", "Child", "Later"]);
    expect(items).toHaveBeenCalledWith({ objectId: "child", generation: 2, pageToken: "next-items" });
  });
  it("shows no item rows for an object that is not a collection and keeps a real Count property apart", async () => {
    const { panel, inspector, send } = fixture();
    const items = vi.fn().mockResolvedValueOnce({ kind: "notEnumerable", count: null, items: [], nextPageToken: null, complete: true }).mockResolvedValueOnce({ kind: "list", count: 1, items: [{ index: 0, key: null, value: { status: "ok", kind: "string", scalar: "a" } }], nextPageToken: null, complete: true });
    Object.assign(inspector, { items });
    inspector.members.mockImplementation(async (params: { objectId: string }) => params.objectId === "root" ? page([member("Parent")]) : page([member("Count")]));
    await vi.waitFor(() => expect(inspector.members).toHaveBeenCalled());
    await panel.handle({ type: "managedExpand", memberKey: "Parent" });
    let row = send.mock.calls.at(-1)![0].rows[0];
    expect(row.children.map((entry: { member: { name: string } }) => entry.member.name)).toEqual(["Count"]);
    expect(row.itemPage).toEqual({ nextToken: false });
    await panel.handle({ type: "managedExpand", memberKey: "Parent" });
    row = send.mock.calls.at(-1)![0].rows[0];
    expect(row.children.map((entry: { member: { name: string } }) => entry.member.name)).toEqual(["Count (items)", "[0]", "Count"]);
  });
  it("requires the warning before reading visible members", async () => {
    const { panel, inspector } = fixture(); await vi.waitFor(() => expect(inspector.members).toHaveBeenCalled()); mocks.warning.mockResolvedValueOnce(undefined).mockResolvedValueOnce("Read"); await panel.handle({ type: "managedReadVisible", memberKeys: ["Parent"] }); expect(inspector.read).not.toHaveBeenCalled(); await panel.handle({ type: "managedReadVisible", memberKeys: ["Parent"] }); await panel.handle({ type: "managedReadVisible", memberKeys: ["Parent"] }); expect(inspector.read).toHaveBeenCalledTimes(2);
  });
  it("resolves a new selection without attaching", async () => {
    const { panel, inspector } = fixture(); await vi.waitFor(() => expect(inspector.members).toHaveBeenCalled()); panel.select("next"); await vi.waitFor(() => expect(inspector.resolve).toHaveBeenCalledWith("next")); expect(inspector.attach).not.toHaveBeenCalled();
  });
  it("exports only metadata and refuses redacted values", async () => {
    const { panel, inspector, send } = fixture(); await vi.waitFor(() => expect(inspector.members).toHaveBeenCalled()); await panel.handle({ type: "managedExpand", memberKey: "Parent" }); const row = send.mock.calls.at(-1)?.[0].rows[0]; await panel.handle({ type: "managedRead", memberKey: "Child", scope: row.id }); mocks.clipboard.mockClear(); await panel.handle({ type: "managedCopy", kind: "value", memberKey: "Child", scope: row.id }); expect(mocks.clipboard).not.toHaveBeenCalled(); mocks.save.mockResolvedValue("file"); await panel.handle({ type: "managedCopy", kind: "export" }); const output = JSON.parse(mocks.write.mock.calls.at(-1)![1].toString()); expect(output).toMatchObject({ protocolVersion: { major: 1, minor: 0 }, process: { pid: 4 }, complete: false }); expect(output.timestamp).toBeTruthy(); expect(JSON.stringify(output)).not.toContain("secret");
  });
});


describe("automatic getter selection", () => {
  it("asks before reads, paginates and continues after a timeout", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const member = (name: string) => ({ memberKey: name, name, category: "clrProperty", declaringType: "T", declaredType: "T", visibility: "public", readable: true, attributes: [], pathSegment: { kind: "property", name } });
    const inspector = { visible: true, state: "ready", sessionInfo: { sessionId: "s" }, select: vi.fn(), resolve: vi.fn(async () => ({ object: { objectId: "root", generation: 1 } })), members: vi.fn(async (p: { pageToken?: string }) => p.pageToken ? { items: [member("Slow"), member("Later")], complete: true } : { items: [member("Null"), member("Throw")], nextToken: "next", complete: false }), bindings: vi.fn(), spyRead: vi.fn(async (p: { paths: { name: string }[][] }) => ({ result: { values: p.paths.map(([{ name }]) => ({ value: name === "Null" ? { status: "ok", kind: "null" } : name === "Throw" ? { status: "exception", kind: "unavailable" } : name === "Slow" ? { status: "timeout", kind: "unavailable" } : { status: "ok", kind: "string", scalar: "later" } })) } })) };
    const send = vi.fn(); const panel = new ManagedPanel(withSpy(inspector), send); panel.select("node");
    await vi.waitFor(() => expect(inspector.spyRead).toHaveBeenCalledTimes(2));
    expect(mocks.warning).toHaveBeenCalledTimes(1); expect(inspector.members).toHaveBeenCalledTimes(2);
    const [message, options, ...buttons] = mocks.warning.mock.calls[0] as [string, { modal: boolean; detail: string }, ...string[]];
    expect(message).toBe("Automatically read public WPF getters in Spy?");
    expect(options.modal).toBe(true); expect(options.detail).toContain("side effects");
    expect(buttons).toEqual(["Read automatically", "Read automatically and don't ask again"]);
    const rows = send.mock.calls.at(-1)![0].rows;
    expect(rows.map((r: { value?: { status: string; kind: string }; autoStatus?: string }) => r.value?.kind === "null" ? "null" : r.value?.status || r.autoStatus)).toEqual(["null", "exception", "timeout", "ok"]);
  });
});

it("reads exact shadowed private fields through the Spy route", async () => {
  mocks.warning.mockReset().mockResolvedValue("Read automatically");
  const field = (type: string) => ({ memberKey: `clrField|A|${type}|same`, name: "same", category: "clrField", declaringType: type, declaredType: "System.Int32", visibility: "private", readable: false, reason: "nonPublic", attributes: [], pathSegment: { kind: "field", name: "same", memberKey: `clrField|A|${type}|same`, declaringType: type } });
  const spyRead = vi.fn<(params: Parameters<ManagedInspector["spyRead"]>[0]) => Promise<unknown>>()
    .mockImplementation(async (p) => ({ result: { values: p.paths.map(() => ({ value: { status: "ok", kind: "integer", scalar: 1 } })) } }));
  const inspector = { visible: true, state: "ready", sessionInfo: { sessionId: "s" }, select: vi.fn(), resolve: vi.fn(async () => ({ object: { objectId: "root", generation: 1 } })), members: vi.fn(async () => ({ items: [field("Base"), field("Derived")], complete: true })), bindings: vi.fn(), read: vi.fn(), spyRead };
  const send = vi.fn(); const panel = new ManagedPanel(withSpy(inspector), send); panel.select("node");
  await vi.waitFor(() => expect(inspector.spyRead).toHaveBeenCalledTimes(1));
  expect(inspector.spyRead.mock.calls[0][0].paths.map((path) => path[0])).toMatchObject([{ memberKey: "clrField|A|Base|same", declaringType: "Base" }, { memberKey: "clrField|A|Derived|same", declaringType: "Derived" }]);
  await panel.handle({ type: "managedRead", memberKey: "clrField|A|Base|same" });
  expect(inspector.spyRead).toHaveBeenCalledTimes(2); expect(inspector.read).not.toHaveBeenCalled();
  expect(inspector.spyRead.mock.calls[1][0].paths[0][0]).toMatchObject({ memberKey: "clrField|A|Base|same", declaringType: "Base" });
  expect(send.mock.calls.at(-1)![0].rows).toHaveLength(2);
});

describe("automatic reading reaches every public value", () => {
  const pathSegment = (kind: string, name: string) => kind === "dependency" ? { kind, name, ownerType: "T", ownerAssembly: "A" } : { kind, name };
  const row = (name: string, category: string, extra: Record<string, unknown> = {}) => ({ memberKey: `${category}:${name}`, name, category, declaringType: "T", declaredType: "T", visibility: "public", readable: true, attributes: [], pathSegment: pathSegment(category === "dependencyProperty" || category === "attachedProperty" ? "dependency" : category === "typeMetadata" ? "type" : "property", name), ...extra });
  const make = (items: unknown[], spyRead: (p: { paths: { name: string }[][] }) => Promise<unknown>) => {
    const inspector = { visible: true, state: "ready", sessionInfo: { sessionId: "s" }, select: vi.fn(), resolve: vi.fn(async () => ({ object: { objectId: "root", generation: 1 } })), members: vi.fn(async () => ({ items, complete: true })), bindings: vi.fn(), spyRead: vi.fn(spyRead), read: vi.fn() };
    const send = vi.fn(), panel = new ManagedPanel(withSpy(inspector), send);
    return { inspector, send, panel };
  };
  const ok = (p: { paths: { name: string }[][] }) => ({ result: { values: p.paths.map(([{ name }]) => ({ value: { status: "ok", kind: "string", scalar: name } })) } });

  it("reads CLR, dependency and attached properties and type facts without a click, and nothing that is not public or readable", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make([row("Clr", "clrProperty"), row("Static", "staticProperty"), row("StaticField", "staticField", { visibility: "private", readable: false, reason: "nonPublic", pathSegment: { kind: "field", name: "StaticField", memberKey: "staticField:StaticField", declaringType: "T" } }), row("Dep", "dependencyProperty"), row("Attached", "attachedProperty"), row("Hidden", "clrProperty", { visibility: "internal", readable: false }), row("Type", "typeMetadata")], async (p) => ok(p));
    panel.select("node");
    await vi.waitFor(() => expect(inspector.spyRead).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(send.mock.calls.at(-1)![0].rows.filter((r: { value?: unknown }) => r.value)).toHaveLength(6));
    const names = inspector.spyRead.mock.calls.flatMap((call) => (call[0] as { paths: { name: string }[][] }).paths.map((path) => path[0].name));
    expect(names).toEqual(["Clr", "Static", "StaticField", "Dep", "Attached", "Type"]);
    expect(inspector.read).not.toHaveBeenCalled();
    const rows = send.mock.calls.at(-1)![0].rows as { member: { name: string }; value?: unknown; autoStatus?: string }[];
    expect(rows.find((r) => r.member.name === "Hidden")?.value).toBeUndefined();
  });

  it("requests all binding keys in batches of 32", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const items = Array.from({ length: 70 }, (_, index) => row(`Dep${index}`, "dependencyProperty"));
    const { inspector, panel } = make(items, async (params) => ok(params));
    panel.select("node");
    await vi.waitFor(() => expect(inspector.bindings).toHaveBeenCalledTimes(3));
    expect(inspector.bindings.mock.calls.map((call) => (call[0] as { memberKeys: string[] }).memberKeys.length)).toEqual([32, 32, 6]);
  });

  it("reads remaining rows after the automatic budget expires", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    try {
      mocks.warning.mockReset().mockResolvedValue("Read automatically");
      let calls = 0;
      const { send, panel } = make([row("Stuck", "clrProperty")], async (params) => ++calls === 1 ? new Promise(() => {}) : ok(params));
      panel.select("node"); await vi.advanceTimersByTimeAsync(5100);
      expect(send.mock.calls.at(-1)![0].readRemaining).toBe(true);
      await panel.handle({ type: "managedReadRemaining" });
      expect(send.mock.calls.at(-1)![0].rows[0].value.scalar).toBe("Stuck");
      expect(send.mock.calls.at(-1)![0].readRemaining).toBe(false);
    } finally { vi.useRealTimers(); }
  });

  it("marks every row it could not read in the whole-object budget as timed out, never leaving it unread", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    try {
      mocks.warning.mockReset().mockResolvedValue("Read automatically");
      const { send, panel } = make([row("Stuck", "clrProperty"), row("After", "dependencyProperty"), row("Last", "attachedProperty")], () => new Promise(() => {}));
      panel.select("node");
      await vi.advanceTimersByTimeAsync(5100);
      const rows = send.mock.calls.at(-1)![0].rows as { value?: unknown; autoStatus?: string }[];
      expect(rows.map((r) => r.value ? "value" : r.autoStatus)).toEqual(["timed out", "timed out", "timed out"]);
    } finally { vi.useRealTimers(); }
  });

  it("says a row was declined, not left unread, when the user refuses automatic reading", async () => {
    mocks.warning.mockReset().mockResolvedValue(undefined);
    const { inspector, send, panel } = make([row("Clr", "clrProperty"), row("Dep", "dependencyProperty")], async (p) => ok(p));
    panel.select("node");
    await vi.waitFor(() => expect(send.mock.calls.at(-1)![0].rows.map((r: { autoStatus?: string }) => r.autoStatus)).toEqual(["declined", "declined"]));
    expect(inspector.spyRead).not.toHaveBeenCalled();
  });

  it("shows a getter the server timed out in that row only and carries on", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { send, panel } = make([row("Slow", "dependencyProperty"), row("Fast", "clrProperty")], async (p) => ({ result: { values: p.paths.map(([{ name }]) => ({ value: name === "Slow" ? { status: "timeout", kind: "unavailable" } : { status: "ok", kind: "string", scalar: "fast" } })) } }));
    panel.select("node");
    await vi.waitFor(() => expect(send.mock.calls.at(-1)![0].rows.map((r: { value?: { status: string } }) => r.value?.status)).toEqual(["timeout", "ok"]));
    // One slow getter is not a busy UI thread: nothing is read again by itself.
    expect(send.mock.calls.at(-1)![0].busyRead).toBe(false);
  });

  it("reads timed-out values again when Spy retries a busy selection", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    let busy = true;
    const { send, panel } = make([row("Fast", "clrProperty"), row("Type", "typeMetadata")], async (p) => busy ? { status: "timed out", busy: true } : ok(p));
    panel.select("node");
    await vi.waitFor(() => expect(send.mock.calls.at(-1)![0].busyRead).toBe(true));
    busy = false;
    const { inspector } = (panel as unknown as { inspector: { spyRead: { mock: { calls: { paths: { name: string }[][] }[][] } } } });
    const before = inspector.spyRead.mock.calls.length;
    expect(await panel.retryBusy()).toBe(true);
    const last = send.mock.calls.at(-1)![0];
    expect(last.rows.map((r: { value?: { status: string } }) => r.value?.status)).toEqual(["ok", "ok"]);
    // The type facts are read before the other rows.
    expect(inspector.spyRead.mock.calls[before][0].paths.map(([{ name }]) => name)).toEqual(["Type", "Fast"]);
    expect(last.busyRead).toBe(false);
  });

  it("marks a whole batch the request failed for as timed out and carries on with the next", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const items = Array.from({ length: 30 }, (_, index) => row("P" + index, "clrProperty"));
    const { inspector, send, panel } = make(items, async (p) => p.paths[0][0].name === "P0" ? { status: "timed out" } : ok(p));
    panel.select("node");
    await vi.waitFor(() => expect(inspector.spyRead).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(send.mock.calls.at(-1)![0].rows.filter((r: { value?: unknown; autoStatus?: string }) => r.value || r.autoStatus)).toHaveLength(30));
    const rows = send.mock.calls.at(-1)![0].rows as { value?: unknown; autoStatus?: string }[];
    expect(rows.map((r) => r.value ? "value" : r.autoStatus)).toEqual([...Array(25).fill("timed out"), ...Array(5).fill("value")]);
  });
});

describe("binding objects", () => {
  const dependency = { memberKey: "dp:Text", name: "Text", category: "dependencyProperty", declaringType: "T", declaredType: "System.String", visibility: "public", readable: true, attributes: [], pathSegment: { kind: "dependency", name: "Text", ownerType: "T", ownerAssembly: "A" } };
  const handle = (objectId: string) => ({ status: "ok", kind: "object", declaredType: "System.Object", runtimeType: "App.Source", object: { objectId, generation: 1 } });
  const text = (scalar: string) => ({ status: "ok", kind: "string", declaredType: "System.Object", runtimeType: "System.String", scalar });
  const binding = {
    memberKey: "dp:Text", kind: "multiBinding", status: "Active", mode: "Default", updateSourceTrigger: "Default", converterParameter: handle("param"), fallbackValue: text("fb"),
    children: [{ memberKey: "dp:Text", kind: "binding", status: "Active", mode: "OneWay", updateSourceTrigger: "Default", path: "Name", dataItem: handle("item"), resolvedSource: handle("source"), resolvedSourcePropertyName: "Name" }],
  };
  const make = () => {
    const members = vi.fn(async (params: { objectId: string }) => params.objectId === "root"
      ? { items: [dependency], complete: true }
      : { items: [{ ...dependency, memberKey: "clr:Name", name: "Name", category: "clrProperty", pathSegment: { kind: "property", name: "Name" } }], complete: true });
    const inspector = { visible: true, state: "ready", sessionInfo: { sessionId: "s" }, select: vi.fn(), resolve: vi.fn(async () => ({ object: { objectId: "root", generation: 1 } })), members, bindings: vi.fn(async () => ({ bindings: [binding] })), read: vi.fn(), spyRead: vi.fn(async (p: { paths: unknown[] }) => ({ result: { values: p.paths.map(() => ({ value: text("x") })) } })) };
    const send = vi.fn(), panel = new ManagedPanel(withSpy(inspector), send);
    return { inspector, send, panel };
  };
  const last = (send: ReturnType<typeof vi.fn>) => send.mock.calls.at(-1)![0] as { bindings: unknown[]; bindingObjects: { id: string; item: boolean; binding: { memberKey: string; path: number[]; field: string }; member: { memberKey: string; name: string }; children?: { member: { name: string } }[] }[] };

  it("publishes an object row for every object a binding holds, nested children included", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await vi.waitFor(() => expect(inspector.bindings).toHaveBeenCalled());
    await vi.waitFor(() => expect(last(send).bindingObjects).toHaveLength(3));
    const rows = last(send).bindingObjects;
    expect(rows.map((row) => [row.binding.path.join("/"), row.binding.field, row.member.name])).toEqual([["", "converterParameter", "ConverterParameter"], ["0", "dataItem", "DataItem"], ["0", "resolvedSource", "ResolvedSource"]]);
    expect(rows.every((row) => row.item && row.binding.memberKey === "dp:Text" && row.member.memberKey === `binding:${row.id}`)).toBe(true);
    expect(last(send).bindings).toHaveLength(1);
  });

  it("expands a binding object through the member and item flow in the binding scope", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await vi.waitFor(() => expect(last(send).bindingObjects).toHaveLength(3));
    const dataItem = last(send).bindingObjects.find((row) => row.binding.field === "dataItem")!;
    await panel.handle({ type: "managedExpand", memberKey: dataItem.member.memberKey, scope: "bindings" });
    expect(inspector.members).toHaveBeenLastCalledWith({ objectId: "item", generation: 1 });
    expect(last(send).bindingObjects.find((row) => row.id === dataItem.id)!.children?.map((child) => child.member.name)).toEqual(["Name"]);
    // The children of an expanded binding object expand in their own scope, like any member row.
    const child = last(send).bindingObjects.find((row) => row.id === dataItem.id)!.children![0] as unknown as { id: string; member: { memberKey: string } };
    expect(child.member.memberKey).toBe("clr:Name");
  });

  it("drops the binding objects when the selection or the refresh clears the bindings", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await vi.waitFor(() => expect(last(send).bindingObjects).toHaveLength(3));
    inspector.bindings.mockResolvedValue({ bindings: [] });
    await panel.handle({ type: "managedRefresh" });
    await vi.waitFor(() => expect(last(send).bindingObjects).toHaveLength(0));
    panel.select("other");
    expect(last(send).bindingObjects).toHaveLength(0);
  });

  it("ignores an expand request for an unknown binding object", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await vi.waitFor(() => expect(last(send).bindingObjects).toHaveLength(3));
    const calls = inspector.members.mock.calls.length;
    await panel.handle({ type: "managedExpand", memberKey: "binding:missing", scope: "bindings" });
    expect(inspector.members.mock.calls.length).toBe(calls);
  });
});

describe("styling rows", () => {
  const dependency = { memberKey: "dp:Text", name: "Text", category: "dependencyProperty", declaringType: "T", declaredType: "System.String", visibility: "public", readable: true, attributes: [], pathSegment: { kind: "dependency", name: "Text", ownerType: "T", ownerAssembly: "A" } };
  const handle = (objectId: string) => ({ status: "ok", kind: "object", declaredType: "System.Object", runtimeType: "App.Thing", object: { objectId, generation: 1 } });
  const text = (scalar: string) => ({ status: "ok", kind: "string", declaredType: "System.Object", runtimeType: "System.String", scalar });
  const level = { setterCount: 1, settersTruncated: false, setters: [{ property: "Tag", owner: "T", kind: "value", value: handle("setter") }], triggerCount: 1, triggersTruncated: false, triggers: [{ kind: "trigger", active: "unknown", conditions: [{ property: "T.Flag", value: handle("condition"), active: "unknown" }], setterCount: 0, settersTruncated: false, setters: [], enterActions: 0, exitActions: 0 }] };
  const styling = {
    applicable: true,
    style: { source: "local", ...level, basedOn: [{ key: "Base", ...level }], basedOnTruncated: false },
    templates: { controlTemplate: { kind: "controlTemplate", triggerCount: 0, triggersTruncated: false, triggers: [], partsTruncated: false, parts: [{ name: "PART_Root", type: "Border", element: handle("part") }] }, templatedParent: handle("owner") },
    resources: { count: 2, truncated: false, entries: [{ key: "Title", keyKind: "string", index: 0 }, { key: "Brush", keyKind: "string", index: 1 }], mergedTruncated: false, mergedDictionaries: [] },
    application: { count: 1, truncated: false, entries: [{ key: "AppBrush", keyKind: "string", index: 0 }], mergedTruncated: false, mergedDictionaries: [] },
  };
  type Sent = { styling?: unknown; stylingObjects: { id: string; item: boolean; styling: { slot: string }; member: { memberKey: string; name: string }; children?: { member: { name: string } }[] }[] };
  const last = (send: ReturnType<typeof vi.fn>) => send.mock.calls.at(-1)![0] as Sent;
  const make = (result: unknown = styling) => {
    const members = vi.fn(async (params: { objectId: string }) => params.objectId === "root" ? { items: [dependency], complete: true } : { items: [{ ...dependency, memberKey: "clr:Name", name: "Name", category: "clrProperty", pathSegment: { kind: "property", name: "Name" } }], complete: true });
    const styled = vi.fn(async (): Promise<unknown> => result);
    const inspector = { visible: true, state: "ready", sessionInfo: { sessionId: "s" }, select: vi.fn(), resolve: vi.fn(async () => ({ object: { objectId: "root", generation: 1 } })), members, bindings: vi.fn(async () => ({ bindings: [] })), styling: styled, events: vi.fn(async () => ({ items: [], complete: true })), resource: vi.fn(async () => ({ found: true, valueType: "System.String", value: text("Hello") })), read: vi.fn(), spyRead: vi.fn(async (p: { paths: unknown[] }) => ({ result: { values: p.paths.map(() => ({ value: text("v") })) } })) };
    const send = vi.fn(), panel = new ManagedPanel(withSpy(inspector), send);
    return { inspector, send, panel };
  };

  it("loads the styling of the selected object after its members and publishes a slot row for every object in it", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await vi.waitFor(() => expect(last(send).stylingObjects.length).toBeGreaterThan(0));
    expect(inspector.styling).toHaveBeenCalledWith({ objectId: "root", generation: 1 });
    expect(inspector.members.mock.invocationCallOrder[0]).toBeLessThan(inspector.styling.mock.invocationCallOrder[0]);
    expect(last(send).styling).toEqual(styling);
    expect(last(send).stylingObjects.map((row) => row.styling.slot)).toEqual([
      "style.setters.0.value", "style.triggers.0.conditions.0.value", "style.basedOn.0.setters.0.value", "style.basedOn.0.triggers.0.conditions.0.value",
      "templates.controlTemplate.parts.0.element", "templates.templatedParent", "resources.entries.0", "resources.entries.1", "application.entries.0",
    ]);
    expect(last(send).stylingObjects.every((row) => row.item && row.member.memberKey === `styling:${row.id}`)).toBe(true);
  });

  it("does not wait for the styling, and it does not spend the getter budget", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    inspector.styling.mockImplementation(() => new Promise(() => {}));
    panel.select("node");
    await vi.waitFor(() => expect(inspector.spyRead).toHaveBeenCalled());
    await vi.waitFor(() => expect(send.mock.calls.at(-1)![0].rows.some((row: { value?: unknown }) => row.value)).toBe(true));
    expect(last(send).styling).toBeUndefined();
  });

  it("shows nothing for an object without styling, or when the request fails", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const plain = make({ applicable: false });
    plain.panel.select("node");
    await vi.waitFor(() => expect(plain.inspector.styling).toHaveBeenCalled());
    await vi.waitFor(() => expect(plain.inspector.spyRead).toHaveBeenCalled());
    expect(last(plain.send).styling).toBeUndefined();
    expect(last(plain.send).stylingObjects).toEqual([]);
    const failed = make();
    failed.inspector.styling.mockRejectedValue(new Error("boom"));
    failed.panel.select("node");
    await vi.waitFor(() => expect(failed.inspector.styling).toHaveBeenCalled());
    await vi.waitFor(() => expect(failed.inspector.spyRead).toHaveBeenCalled());
    expect(last(failed.send).styling).toBeUndefined();
  });

  it("expands a styling object through the member and item flow in the styling scope", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await vi.waitFor(() => expect(last(send).stylingObjects).toHaveLength(9));
    const owner = last(send).stylingObjects.find((row) => row.styling.slot === "templates.templatedParent")!;
    await panel.handle({ type: "managedExpand", memberKey: owner.member.memberKey, scope: "styling" });
    expect(inspector.members).toHaveBeenLastCalledWith({ objectId: "owner", generation: 1 });
    expect(last(send).stylingObjects.find((row) => row.id === owner.id)!.children?.map((child) => child.member.name)).toEqual(["Name"]);
    const child = last(send).stylingObjects.find((row) => row.id === owner.id)!.children![0] as unknown as { id: string };
    // The members of an expanded object live under that row and are found by their own id.
    await panel.handle({ type: "managedExpand", memberKey: "clr:Name", scope: child.id });
    const calls = inspector.members.mock.calls.length;
    await panel.handle({ type: "managedExpand", memberKey: "styling:missing", scope: "styling" });
    expect(inspector.members.mock.calls.length).toBe(calls);
  });

  it("drops the styling when the selection changes or the panel refreshes, and ignores a late answer", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await vi.waitFor(() => expect(last(send).stylingObjects).toHaveLength(9));
    inspector.styling.mockResolvedValue({ applicable: false });
    await panel.handle({ type: "managedRefresh" });
    await vi.waitFor(() => expect(last(send).styling).toBeUndefined());
    expect(last(send).stylingObjects).toHaveLength(0);
    let finish!: (value: unknown) => void;
    inspector.styling.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    panel.select("other");
    await vi.waitFor(() => expect(inspector.styling).toHaveBeenCalledTimes(3));
    panel.select("third");
    finish(styling);
    await Promise.resolve();
    expect(last(send).styling).toBeUndefined();
    expect(last(send).stylingObjects).toHaveLength(0);
  });
});

describe("resource rows", () => {
  const text = (scalar: string) => ({ status: "ok", kind: "string", declaredType: "System.Object", runtimeType: "System.String", scalar });
  const handle = (objectId: string) => ({ status: "ok", kind: "object", declaredType: "System.Object", runtimeType: "App.Thing", object: { objectId, generation: 1 } });
  const listing = {
    applicable: true,
    resources: { count: 2, truncated: false, entries: [{ key: "Title", keyKind: "string", index: 0 }, { key: "Brush", keyKind: "type", index: 1 }], mergedTruncated: false, mergedDictionaries: [] },
    application: { count: 1, truncated: false, entries: [{ key: "AppBrush", keyKind: "string", index: 0 }], mergedTruncated: false, mergedDictionaries: [] },
  };
  type ResourceRow = { id: string; item: boolean; text?: string; value?: { object?: { objectId: string } }; valueType?: string; styling: { slot: string }; resource?: { scope: string; key: string; keyKind: string; index: number }; member: { memberKey: string; name: string }; children?: { member: { name: string } }[] };
  type Sent = { stylingObjects: ResourceRow[] };
  const last = (send: ReturnType<typeof vi.fn>) => send.mock.calls.at(-1)![0] as Sent;
  const make = () => {
    const resource = vi.fn(async (params: { key: string }): Promise<unknown> => params.key === "Title" ? { found: true, valueType: "System.String", value: text("Hello") } : { found: true, valueType: "App.Thing", value: handle("brush") });
    const members = vi.fn(async (params: { objectId: string }) => ({ items: [{ memberKey: params.objectId === "root" ? "dp:Text" : "clr:Name", name: params.objectId === "root" ? "Text" : "Name", category: "clrProperty", declaringType: "T", declaredType: "System.String", visibility: "public", readable: true, attributes: [], pathSegment: { kind: "property", name: "Name" } }], complete: true }));
    const inspector = { visible: true, state: "ready", sessionInfo: { sessionId: "s" }, select: vi.fn(), resolve: vi.fn(async () => ({ object: { objectId: "root", generation: 1 } })), members, bindings: vi.fn(async () => ({ bindings: [] })), styling: vi.fn(async () => listing), events: vi.fn(async () => ({ items: [], complete: true })), resource, read: vi.fn(), spyRead: vi.fn(async (p: { paths: unknown[] }) => ({ result: { values: p.paths.map(() => ({ value: text("v") })) } })) };
    const send = vi.fn(), panel = new ManagedPanel(withSpy(inspector), send);
    return { inspector, send, panel };
  };
  const rowFor = (send: ReturnType<typeof vi.fn>, slot: string) => last(send).stylingObjects.find((row) => row.styling.slot === slot)!;
  const loaded = async (send: ReturnType<typeof vi.fn>) => { await vi.waitFor(() => expect(last(send).stylingObjects.length).toBe(3)); };

  it("lists every resource without a value and never asks for one while listing", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await loaded(send);
    expect(last(send).stylingObjects.map((row) => [row.styling.slot, row.member.name, row.text, row.value])).toEqual([
      ["resources.entries.0", "Title", RESOURCE_PROMPT, undefined],
      ["resources.entries.1", "Brush", RESOURCE_PROMPT, undefined],
      ["application.entries.0", "AppBrush", RESOURCE_PROMPT, undefined],
    ]);
    expect(rowFor(send, "resources.entries.1").resource).toEqual({ scope: "local", key: "Brush", keyKind: "type", index: 1 });
    expect(rowFor(send, "application.entries.0").resource).toEqual({ scope: "application", key: "AppBrush", keyKind: "string", index: 0 });
    expect(RESOURCE_PROMPT).toBe("(expand to read)");
    expect(inspector.resource).not.toHaveBeenCalled();
  });

  it("reads a scalar resource when its row is expanded, and only that one", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await loaded(send);
    const row = rowFor(send, "resources.entries.0");
    await panel.handle({ type: "managedExpand", memberKey: row.member.memberKey, scope: "styling" });
    expect(inspector.resource).toHaveBeenCalledTimes(1);
    expect(inspector.resource).toHaveBeenCalledWith({ objectId: "root", generation: 1, scope: "local", key: "Title", keyKind: "string", index: 0 });
    const read = rowFor(send, "resources.entries.0");
    expect(read.text).toBeUndefined();
    expect(read.value).toMatchObject({ kind: "string", scalar: "Hello" });
    expect(read.valueType).toBe("System.String");
    expect(rowFor(send, "resources.entries.1").text).toBe(RESOURCE_PROMPT);
    // A value that was read is not read again.
    await panel.handle({ type: "managedExpand", memberKey: row.member.memberKey, scope: "styling" });
    expect(inspector.resource).toHaveBeenCalledTimes(1);
  });

  it("reads an object resource and then shows its members through the member flow", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await loaded(send);
    const row = rowFor(send, "resources.entries.1");
    await panel.handle({ type: "managedExpand", memberKey: row.member.memberKey, scope: "styling" });
    expect(inspector.resource).toHaveBeenLastCalledWith({ objectId: "root", generation: 1, scope: "local", key: "Brush", keyKind: "type", index: 1 });
    expect(inspector.members).toHaveBeenLastCalledWith({ objectId: "brush", generation: 1 });
    const read = rowFor(send, "resources.entries.1");
    expect(read.value?.object?.objectId).toBe("brush");
    expect(read.children?.map((child) => child.member.name)).toEqual(["Name"]);
  });

  it("reads an application resource with the application scope", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await loaded(send);
    await panel.handle({ type: "managedExpand", memberKey: rowFor(send, "application.entries.0").member.memberKey, scope: "styling" });
    expect(inspector.resource).toHaveBeenLastCalledWith({ objectId: "root", generation: 1, scope: "application", key: "AppBrush", keyKind: "string", index: 0 });
  });

  it("says why a resource has no value, and reads it again on the next expansion", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await loaded(send);
    const key = rowFor(send, "resources.entries.0").member.memberKey;
    inspector.resource.mockResolvedValueOnce({ found: false });
    await panel.handle({ type: "managedExpand", memberKey: key, scope: "styling" });
    expect(rowFor(send, "resources.entries.0").text).toBe("(not found: the resource is gone)");
    inspector.resource.mockResolvedValueOnce(undefined);
    await panel.handle({ type: "managedExpand", memberKey: key, scope: "styling" });
    expect(rowFor(send, "resources.entries.0").text).toBe("(unavailable)");
    await panel.handle({ type: "managedExpand", memberKey: key, scope: "styling" });
    expect(rowFor(send, "resources.entries.0").value).toMatchObject({ scalar: "Hello" });
    expect(inspector.resource).toHaveBeenCalledTimes(3);
  });

  it("ignores a resource that arrives after the selection changed, and one that is already being read", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await loaded(send);
    const row = rowFor(send, "resources.entries.0");
    let finish!: (value: unknown) => void;
    inspector.resource.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const first = panel.handle({ type: "managedExpand", memberKey: row.member.memberKey, scope: "styling" });
    await vi.waitFor(() => expect(inspector.resource).toHaveBeenCalledTimes(1));
    await panel.handle({ type: "managedExpand", memberKey: row.member.memberKey, scope: "styling" });
    expect(inspector.resource).toHaveBeenCalledTimes(1);
    panel.select("other");
    finish({ found: true, valueType: "System.String", value: text("late") });
    await first;
    expect(last(send).stylingObjects.find((item) => item.value)).toBeUndefined();
  });
});

describe("event rows", () => {
  const dependency = { memberKey: "dp:Text", name: "Text", category: "dependencyProperty", declaringType: "T", declaredType: "System.String", visibility: "public", readable: true, attributes: [], pathSegment: { kind: "dependency", name: "Text", ownerType: "T", ownerAssembly: "A" } };
  const routed = { kind: "routed", name: "Click", declaringType: "System.Windows.Controls.Primitives.ButtonBase", handlerType: "System.Windows.RoutedEventHandler", strategy: "bubble", handlersKnown: true, handlerCount: 1, handlersTruncated: false, handlers: [{ declaringType: "Demo.Window", method: "OnClick", handledEventsToo: false }] };
  const clr = { kind: "clr", name: "Changed", declaringType: "Demo.Model", handlerType: "System.EventHandler", isStatic: false, subscribersKnown: false, subscriberCount: 0, subscribersTruncated: false, subscribers: [] };
  const page = (items: unknown[], nextToken?: string) => ({ items, complete: !nextToken, nextToken, snapshotId: "snap", diagnostics: [] });
  type Sent = { events: { name: string }[] };
  const last = (send: ReturnType<typeof vi.fn>) => send.mock.calls.at(-1)![0] as Sent;
  const make = () => {
    const events = vi.fn(async (): Promise<unknown> => page([routed, clr]));
    const inspector = { visible: true, state: "ready", sessionInfo: { sessionId: "s" }, select: vi.fn(), resolve: vi.fn(async (node: string) => ({ object: { objectId: node, generation: 1 } })), members: vi.fn(async () => ({ items: [dependency], complete: true })), bindings: vi.fn(async () => ({ bindings: [] })), styling: vi.fn(async () => ({ applicable: false })), events, read: vi.fn(), spyRead: vi.fn(async (p: { paths: unknown[] }) => ({ result: { values: p.paths.map(() => ({ value: { status: "ok", kind: "string", declaredType: "", runtimeType: "", scalar: "v" } })) } })) };
    const send = vi.fn(), panel = new ManagedPanel(withSpy(inspector), send);
    return { inspector, send, panel };
  };

  it("loads the events of the selected object after its members and publishes them in the agent's order", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    panel.select("node");
    await vi.waitFor(() => expect(last(send).events.length).toBe(2));
    expect(inspector.events).toHaveBeenCalledWith({ objectId: "node", generation: 1 });
    expect(inspector.members.mock.invocationCallOrder[0]).toBeLessThan(inspector.events.mock.invocationCallOrder[0]);
    expect(last(send).events).toEqual([routed, clr]);
  });

  it("follows the pages to the end, and no further than the page limit", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    inspector.events.mockResolvedValueOnce(page([routed], "t1")).mockResolvedValueOnce(page([clr]));
    panel.select("node");
    await vi.waitFor(() => expect(last(send).events.length).toBe(2));
    expect(inspector.events).toHaveBeenNthCalledWith(2, { objectId: "node", generation: 1, pageToken: "t1" });
    const endless = make();
    let counter = 0;
    endless.inspector.events.mockImplementation(async () => page([{ ...routed, name: "E" + counter }], "t" + ++counter));
    endless.panel.select("node");
    await vi.waitFor(() => expect(last(endless.send).events.length).toBe(10));
    expect(endless.inspector.events).toHaveBeenCalledTimes(10);
  });

  it("does not wait for the events, and does not spend the getter budget on them", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    inspector.events.mockImplementation(() => new Promise(() => {}));
    panel.select("node");
    await vi.waitFor(() => expect(inspector.spyRead).toHaveBeenCalled());
    await vi.waitFor(() => expect(send.mock.calls.at(-1)![0].rows.some((row: { value?: unknown }) => row.value)).toBe(true));
    expect(last(send).events).toEqual([]);
  });

  it("shows no events when the request fails, and drops them with the selection and the refresh", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const failed = make();
    failed.inspector.events.mockRejectedValue(new Error("boom"));
    failed.panel.select("node");
    await vi.waitFor(() => expect(failed.inspector.events).toHaveBeenCalled());
    await vi.waitFor(() => expect(failed.inspector.spyRead).toHaveBeenCalled());
    expect(last(failed.send).events).toEqual([]);
    const { inspector, send, panel } = make();
    panel.select("node");
    await vi.waitFor(() => expect(last(send).events.length).toBe(2));
    inspector.events.mockResolvedValue(page([]));
    await panel.handle({ type: "managedRefresh" });
    await vi.waitFor(() => expect(inspector.events).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(last(send).events).toEqual([]));
    panel.select("other");
    expect(last(send).events).toEqual([]);
  });

  it("ignores events that arrive after the selection changed", async () => {
    mocks.warning.mockReset().mockResolvedValue("Read automatically");
    const { inspector, send, panel } = make();
    let finish!: (value: unknown) => void;
    inspector.events.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    panel.select("first");
    await vi.waitFor(() => expect(inspector.events).toHaveBeenCalledTimes(1));
    panel.select("second");
    await vi.waitFor(() => expect(inspector.events).toHaveBeenCalledTimes(2));
    finish(page([{ ...routed, name: "Stale" }]));
    await Promise.resolve();
    await vi.waitFor(() => expect(last(send).events.map((event) => event.name)).toEqual(["Click", "Changed"]));
  });
});
