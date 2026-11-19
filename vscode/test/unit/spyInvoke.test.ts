import { describe, expect, it, vi } from "vitest";
import type { ManagedInspector } from "../../src/spy/managedSession";
import { RpcNumber, JsonRpcClient } from "../../src/server/jsonrpc";
import { parseSpyRequest } from "../../src/spy/messages";
const mocks = vi.hoisted(() => ({ warning: vi.fn() }));
vi.mock("vscode", () => ({ window: { showWarningMessage: mocks.warning }, workspace: { getConfiguration: () => ({ get: () => false }) } }));
import { ManagedPanel } from "../../src/spy/managedPanel";

const method = { key: "key", name: "Run", declaringType: "App.Type", returnType: "System.Void", visibility: "private", isStatic: false, parameters: [{ name: "large", type: "System.Int64", isOut: false }, { name: "amount", type: "System.Decimal", isOut: false }, { name: "mode", type: "App.Mode", isOut: false }, { name: "text", type: "System.String", isOut: false }, { name: "flag", type: "System.Boolean", isOut: false }] };
const message = { type: "managedInvoke" as const, memberKey: "key", arguments: [{ kind: "value", text: "9223372036854775807" }, { kind: "value", text: "12.3400" }, { kind: "enum", text: "First, Second" }, { kind: "null", text: "" }, { kind: "value", text: "true" }] };
async function fixture() {
  const object = { sessionId: "s", objectId: "o", generation: 1 };
  const inspector = { visible: true, state: "ready", sessionInfo: { sessionId: "s", process: { pid: 42 } }, select: vi.fn(), clearSpy: vi.fn(async () => {}), bindSpy: vi.fn(async () => true), resolve: vi.fn(async () => ({ status: "exact", object })), members: vi.fn(async () => ({ items: [], complete: true })), spyMethods: vi.fn(async () => ({ items: [method], complete: true })), prepareSpy: vi.fn<ManagedInspector["prepareSpy"]>().mockResolvedValue("ticket"), invokeSpy: vi.fn(async () => ({ audit: { outcome: "performed" }, result: { status: "ok", kind: "string", scalar: "done" } })), auditInvocation: vi.fn() };
  const send = vi.fn(), panel = new ManagedPanel(inspector as unknown as ManagedInspector, send);
  panel.select("node"); await vi.waitFor(() => expect(inspector.members).toHaveBeenCalled());
  await panel.handle({ type: "managedMethods", action: "activate" });
  mocks.warning.mockReset(); return { panel, inspector, send };
}
describe("Spy invocation", () => {
  it("requires confirmation and derives signature and process from host state", async () => {
    const { panel, inspector } = await fixture(); mocks.warning.mockResolvedValue(undefined);
    await panel.handle(message); expect(inspector.prepareSpy).not.toHaveBeenCalled();
    expect(mocks.warning.mock.calls[0][1]).toMatchObject({ modal: true, detail: expect.stringContaining("App.Type.Run") });
    expect(mocks.warning.mock.calls[0][1].detail).toContain("PID: 42");
  });
  it("validates typed values and submits once after confirmation", async () => {
    const { panel, inspector, send } = await fixture(); mocks.warning.mockResolvedValue("Invoke");
    await panel.handle(message);
    expect(inspector.prepareSpy).toHaveBeenCalledTimes(1);
    expect(inspector.prepareSpy.mock.calls[0][2]).toEqual([{ type: "System.Int64", value: new RpcNumber("9223372036854775807") }, { type: "System.Decimal", value: "12.3400" }, { type: "App.Mode", enum: "First, Second" }, { type: "System.String", null: true }, { type: "System.Boolean", value: true }]);
    expect(inspector.invokeSpy).toHaveBeenCalledWith("ticket"); expect(inspector.auditInvocation).toHaveBeenCalledWith("performed");
    expect(send.mock.calls.at(-1)?.[0].methods.invocation.text).toBe("Result: done");
    await panel.handle({ ...message, arguments: [{ kind: "value", text: "9223372036854775808" }, ...message.arguments.slice(1)] });
    expect(inspector.prepareSpy).toHaveBeenCalledTimes(1);
  });
  it("suppresses duplicates and stale prepared tickets after selection changes", async () => {
    const { panel, inspector, send } = await fixture(); mocks.warning.mockResolvedValue("Invoke");
    let finish!: (ticket: string) => void;
    inspector.prepareSpy.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const pending = panel.handle(message); await vi.waitFor(() => expect(inspector.prepareSpy).toHaveBeenCalled());
    await panel.handle(message); expect(inspector.prepareSpy).toHaveBeenCalledTimes(1);
    panel.select("other"); finish("ticket"); await pending;
    expect(inspector.invokeSpy).not.toHaveBeenCalled(); expect(send.mock.calls.at(-1)?.[0].methods.invocation).toBeUndefined();
  });
  it("refuses invocation when the inspector is no longer ready", async () => {
    const { panel, inspector, send } = await fixture(); mocks.warning.mockResolvedValue("Invoke");
    let finish!: (ticket: string) => void;
    inspector.prepareSpy.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const pending = panel.handle(message); await vi.waitFor(() => expect(inspector.prepareSpy).toHaveBeenCalled());
    inspector.state = "mapping unavailable"; finish("ticket"); await pending;
    expect(inspector.invokeSpy).not.toHaveBeenCalled();
    expect(send.mock.calls.at(-1)?.[0].methods.canInvoke).toBe(false);
    mocks.warning.mockClear(); await panel.handle(message); expect(mocks.warning).not.toHaveBeenCalled();
  });
  it("invalidates a pending confirmation when managed data is refreshed", async () => {
    const { panel, inspector } = await fixture();
    let confirm!: (answer: string) => void;
    mocks.warning.mockImplementationOnce(() => new Promise((resolve) => { confirm = resolve; }));
    const pending = panel.handle(message);
    const refresh = panel.handle({ type: "managedRefresh" });
    confirm("Invoke"); await pending; await refresh;
    expect(inspector.prepareSpy).not.toHaveBeenCalled();
    expect(inspector.clearSpy).toHaveBeenCalled();
  });
  it("ignores a late capability binding for a superseded selection", async () => {
    const { panel, inspector, send } = await fixture();
    let finish!: (canInvoke: boolean) => void;
    inspector.bindSpy.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    panel.select("superseded");
    await vi.waitFor(() => expect(inspector.bindSpy).toHaveBeenCalledWith("superseded", expect.anything()));
    inspector.bindSpy.mockResolvedValueOnce(false);
    panel.select("read-only");
    await vi.waitFor(() => expect(send.mock.calls.at(-1)?.[0].methods).toMatchObject({ status: "ready", canInvoke: false }));
    finish(true);
    await Promise.resolve();
    await panel.handle(message);
    expect(mocks.warning).not.toHaveBeenCalled();
  });
  it("discards confirmation and invocation results after the selection changes", async () => {
    const { panel, inspector, send } = await fixture();
    let confirm!: (answer: string) => void;
    mocks.warning.mockImplementationOnce(() => new Promise((resolve) => { confirm = resolve; }));
    const first = panel.handle(message); panel.select("other"); confirm("Invoke"); await first;
    expect(inspector.prepareSpy).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(inspector.resolve).toHaveBeenCalledWith("other"));
    await panel.handle({ type: "managedMethods", action: "activate" });
    let finish!: (result: Awaited<ReturnType<typeof inspector.invokeSpy>>) => void;
    inspector.invokeSpy.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    mocks.warning.mockResolvedValue("Invoke"); const second = panel.handle(message);
    await vi.waitFor(() => expect(inspector.invokeSpy).toHaveBeenCalled());
    panel.select("third"); finish({ audit: { outcome: "performed" }, result: { status: "ok", kind: "string", scalar: "stale" } }); await second;
    expect(JSON.stringify(send.mock.calls.at(-1))).not.toContain("stale");
    expect(send.mock.calls.at(-1)?.[0].methods.invoking).toBe(false);
  });
  it("rejects forged message fields and preserves numeric JSON text", async () => {
    expect(parseSpyRequest({ ...message, sessionId: "forged" })).toBeUndefined();
    const write = vi.fn(); const client = new JsonRpcClient(write);
    const pending = client.request("inspect.managed.spyPrepareInvoke", { arguments: [{ type: "System.Int64", value: new RpcNumber("9223372036854775807") }] });
    expect(write.mock.calls[0][0]).toContain('"value":9223372036854775807');
    client.dispose(); await expect(pending).rejects.toThrow();
  });
});
