import { describe, expect, it, vi } from "vitest";
import type { ManagedInspector } from "../../src/spy/managedSession";
const mocks = vi.hoisted(() => ({ warning: vi.fn(), clipboard: vi.fn(), save: vi.fn(), write: vi.fn() }));
vi.mock("vscode", () => ({ window: { showWarningMessage: mocks.warning, showSaveDialog: mocks.save }, env: { clipboard: { writeText: mocks.clipboard } }, workspace: { fs: { writeFile: mocks.write } }, Uri: { file: (path: string) => path } }));
import { ManagedPanel } from "../../src/spy/managedPanel";

describe("managed panel host", () => {
  it("publishes capability and does not attach when selecting a node", () => {
    const inspector = { visible: false, state: "not enabled", select: vi.fn(), attach: vi.fn() };
    const send = vi.fn();
    const panel = new ManagedPanel(inspector as unknown as ManagedInspector, send);
    panel.select("node");
    expect(inspector.select).toHaveBeenCalledWith("node");
    expect(inspector.attach).not.toHaveBeenCalled();
    expect(send).toHaveBeenLastCalledWith(expect.objectContaining({ visible: false, state: "not enabled" }));
  });
  it("discards a resolve response after selection changes", async () => {
    let finish!: (value: unknown) => void;
    const inspector = { visible: true, state: "ready", select: vi.fn(), attach: vi.fn(async () => ({})), resolve: vi.fn(() => new Promise((resolve) => { finish = resolve; })) };
    const send = vi.fn();
    const panel = new ManagedPanel(inspector as unknown as ManagedInspector, send);
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
    const send = vi.fn(); const panel = new ManagedPanel(inspector as unknown as ManagedInspector, send); panel.select("node"); return { panel, inspector, send };
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
