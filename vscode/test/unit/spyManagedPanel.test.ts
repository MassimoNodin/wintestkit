import { describe, expect, it, vi } from "vitest";
import type { ManagedInspector } from "../../src/spy/managedSession";
const mocks = vi.hoisted(() => ({ warning: vi.fn(), clipboard: vi.fn(), save: vi.fn(), write: vi.fn() }));
vi.mock("vscode", () => ({ window: { showWarningMessage: mocks.warning, showSaveDialog: mocks.save }, env: { clipboard: { writeText: mocks.clipboard } }, workspace: { getConfiguration: () => ({ get: () => false, update: vi.fn() }), fs: { writeFile: mocks.write } }, Uri: { file: (path: string) => path } }));
import { ManagedPanel } from "../../src/spy/managedPanel";
function withSpy<T extends object>(inspector: T): ManagedInspector {
  const original = inspector as T & { resolve?: (...args: never[]) => Promise<{ status?: string }>; yieldToUser?: unknown };
  return new Proxy(original, { get(target, prop, receiver) {
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
    const { inspector, send, panel } = make([row("Clr", "clrProperty"), row("Dep", "dependencyProperty"), row("Attached", "attachedProperty"), row("Hidden", "clrProperty", { visibility: "internal", readable: false }), row("Type", "typeMetadata")], async (p) => ok(p));
    panel.select("node");
    await vi.waitFor(() => expect(inspector.spyRead).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(send.mock.calls.at(-1)![0].rows.filter((r: { value?: unknown }) => r.value)).toHaveLength(4));
    const names = inspector.spyRead.mock.calls.flatMap((call) => (call[0] as { paths: { name: string }[][] }).paths.map((path) => path[0].name));
    expect(names).toEqual(["Clr", "Dep", "Attached", "Type"]);
    expect(inspector.read).not.toHaveBeenCalled();
    const rows = send.mock.calls.at(-1)![0].rows as { member: { name: string }; value?: unknown; autoStatus?: string }[];
    expect(rows.find((r) => r.member.name === "Hidden")?.value).toBeUndefined();
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
