import { describe, expect, it, vi } from "vitest";
import type { InitializeResult } from "../../src/protocol/generated";
import type { JsonRpcClient } from "../../src/server/jsonrpc";
const mock = vi.hoisted(() => ({ trusted: true, warning: vi.fn(), open: vi.fn() }));
vi.mock("vscode", () => ({ workspace: { get isTrusted() { return mock.trusted; } }, window: { showWarningMessage: mock.warning }, env: { openExternal: mock.open }, Uri: { parse: (url: string) => url } }));
import { ManagedInspector, managedErrorState, managedFailure } from "../../src/spy/managedSession";
import { parseSpyRequest } from "../../src/spy/messages";
const initialized = (enabled: boolean) => ({ capabilities: enabled ? { managedInspector: true } : undefined }) as InitializeResult;
const facts = { process: { pid: 271, creationTimeUtc: "one" }, executable: "C:/App.exe", runtime: "net8", architecture: "x64", wpfLoaded: true, appUnderTest: false };
const session = { sessionId: "s", process: facts.process, state: "ready", protocolMajor: 1, protocolMinor: 0, features: [] };
function setup() {
  const request = vi.fn<(method: string, params?: unknown) => Promise<unknown>>(async (method: string) => method.endsWith("identify") ? facts : method.endsWith("attach") ? session : { releasedCount: 1 });
  return { request, inspector: new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true)) };
}
describe("managed Spy host", () => {
  it("logs server-blocked tree failures once per process and code", async () => {
    const request = vi.fn(async () => facts), log = vi.fn();
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true), undefined, log);
    const blocked = { code: "inspectorDisabled", hint: "Set [tool.wintestkit.inspector] enabled = true in the project config." };
    await inspector.reportTreeFailure("n", blocked);
    await inspector.reportTreeFailure("n", blocked);
    expect(log.mock.calls).toEqual([["Spy .NET attach failed for C:/App.exe (PID 271): inspectorDisabled: Inspector attachment failed. Set [tool.wintestkit.inspector] enabled = true in the project config."]]);
  });
  it("hides absent capability and maps server codes", () => {
    expect(new ManagedInspector({} as JsonRpcClient, initialized(false)).visible).toBe(false);
    for (const [code, state] of Object.entries({ notAttached: "not enabled", payloadMissing: "not installed", unsupportedTarget: "unsupported target", blockedByPolicy: "blocked by policy", agentVersionMismatch: "restart required", attachFailed: "attach failed", mappingFailed: "mapping unavailable", sessionStale: "detached (idle)" })) expect(managedErrorState({ data: { code } })).toBe(state);
  });
  it("maps every protocol error code to a Spy state", () => {
    const codes = ["invalidParams", "unsupportedProtocol", "unsupportedTarget", "accessDenied", "authenticationFailed", "payloadMissing", "payloadMismatch", "alreadyAttached", "notAttached", "attachFailed", "blockedByPolicy", "agentVersionMismatch", "processExited", "processReused", "sessionStale", "objectStale", "mappingFailed", "memberAmbiguous", "memberNotFound", "dispatcherUnavailable", "timeout", "busy", "limitExceeded", "invalidPageToken", "cancelled", "internalError"];
    for (const code of codes) expect(["not enabled", "not installed", "unsupported target", "blocked by policy", "restart required", "attach failed", "mapping unavailable", "detached (idle)"], code).toContain(managedErrorState({ data: { code } }));
  });
  it("requires trust and confirmation, remembers identity, and never attaches on selection", async () => {
    const { inspector, request } = setup(); await inspector.select("n"); expect(request).not.toHaveBeenCalled();
    mock.trusted = false; await inspector.attach(); expect(request).not.toHaveBeenCalled();
    mock.trusted = true; mock.warning.mockResolvedValueOnce(undefined); await inspector.attach(); expect(request).toHaveBeenCalledTimes(1);
    mock.warning.mockResolvedValue("Attach"); await inspector.attach();
    expect(mock.warning.mock.calls.at(-1)?.[0]).toContain("C:/App.exe");
    for (const term of ["271", "net8", "x64", "getters", "until the application exits"]) expect(mock.warning.mock.calls.at(-1)?.[1].detail).toContain(term);
    expect(mock.warning.mock.calls.at(-1)?.[1].modal).toBe(true);
    expect(mock.warning.mock.calls.at(-1)?.slice(2)).toEqual(["Attach", "Learn more", "Cancel"]);
    await inspector.detach(); const prompts = mock.warning.mock.calls.length; await inspector.attach(); expect(mock.warning).toHaveBeenCalledTimes(prompts);
    await inspector.detach();
    request.mockImplementationOnce(async () => ({ ...facts, process: { ...facts.process, creationTimeUtc: "two" } }));
    await inspector.attach(); expect(mock.warning).toHaveBeenCalledTimes(prompts + 1);
  });
  it("automatically attaches the app under test only for the identified process run", async () => {
    const process = { pid: 87003, creationTimeUtc: "first" };
    let identified = { ...facts, process, appUnderTest: true };
    const request = vi.fn(async (method: string) => method.endsWith("identify") ? identified : { ...session, process });
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true));
    mock.trusted = true; mock.warning.mockReset();
    expect(await inspector.attachTree("window", process)).toBe(true);
    expect(mock.warning).not.toHaveBeenCalled();
    identified = { ...identified, process: { ...process, creationTimeUtc: "second" }, appUnderTest: false };
  });
  it("opens the explanation and leaves attachment cancelled", async () => {
    const process = { pid: 87004, creationTimeUtc: "first" };
    const request = vi.fn(async () => ({ ...facts, process }));
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true));
    mock.warning.mockReset().mockResolvedValueOnce("Learn more").mockResolvedValueOnce("Cancel");
    mock.open.mockReset();
    expect(await inspector.attachTree("window", process)).toBe(false);
    expect(mock.open).toHaveBeenCalledWith(expect.stringContaining("managed-inspection.md"));
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("confirms tree attachment once per process run", async () => {
    const process = { pid: 87002, creationTimeUtc: "first" };
    const request = vi.fn(async (method: string) => method.endsWith("identify") ? { ...facts, process } : { ...session, process });
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true));
    mock.trusted = true; mock.warning.mockReset().mockResolvedValue("Attach");
    const attached = await Promise.all([inspector.attachTree("window1", process), inspector.attachTree("window2", process)]);
    expect(attached).toEqual([true, true]);
    expect(mock.warning).toHaveBeenCalledTimes(1);
    process.creationTimeUtc = "second";
    expect(await inspector.attachTree("window3", process)).toBe(true);
    expect(mock.warning).toHaveBeenCalledTimes(2);
    expect(request).toHaveBeenCalledWith("inspect.managed.attach", { process });
  });
  it("reuses a tree session for WPF selection without attaching again", async () => {
    const process = { pid: 88900, creationTimeUtc: "run" };
    const request = vi.fn(async (method: string) => method.endsWith("identify") ? { ...facts, process } : method.endsWith("attach") ? { ...session, process } : { status: "exact", object: { objectId: "wpf", generation: 1 } });
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true));
    mock.trusted = true; mock.warning.mockReset().mockResolvedValue("Attach");
    expect(await inspector.attachTree("window", process)).toBe(true);
    await inspector.select("wpf"); expect(await inspector.resolve("wpf")).toMatchObject({ status: "exact" });
    await inspector.attach(); await inspector.attachTree("window", process);
    expect(request.mock.calls.filter(([method]) => method.endsWith("attach"))).toHaveLength(1);
    expect(mock.warning).toHaveBeenCalledTimes(1);
  });
  it("adopts an existing server session for a WPF node", async () => {
    const process = { pid: 88901, creationTimeUtc: "run" };
    const request = vi.fn(async (method: string) => method.endsWith("identify") ? { ...facts, process } : method.endsWith("status") ? { ...session, process } : { status: "exact" });
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true));
    mock.warning.mockClear(); await inspector.select("wpf"); await inspector.reuseTreeSession("wpf");
    expect(inspector.sessionInfo?.sessionId).toBe("s"); expect(await inspector.resolve("wpf")).toMatchObject({ status: "exact" });
    expect(request.mock.calls.some(([method]) => method.endsWith("attach"))).toBe(false);
    expect(mock.warning).not.toHaveBeenCalled();
  });
  it("releases selection handles and discards a late response", async () => {
    const { inspector, request } = setup(); mock.trusted = true; mock.warning.mockResolvedValue("Attach"); await inspector.select("n"); await inspector.attach();
    request.mockImplementationOnce(async () => facts).mockImplementationOnce(async () => ({ status: "exact", object: { objectId: "o", generation: 1 } })); await inspector.resolve("n");
    await inspector.select("next"); expect(request).toHaveBeenCalledWith("inspect.managed.release", { sessionId: "s", objectIds: ["o"] });
    let finish!: (value: unknown) => void; request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const pending = inspector.resolve("next"); await inspector.select("third"); finish(facts); expect(await pending).toBeUndefined();
  });
  it("reattaches a previously approved process after invalidation without another prompt", async () => {
    const process = { pid: 88910, creationTimeUtc: "run" };
    const request = vi.fn(async (method: string) => method.endsWith("identify") ? { ...facts, process } : { ...session, process });
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true));
    mock.trusted = true; mock.warning.mockReset().mockResolvedValue("Attach");
    expect(await inspector.attachTree("window", process)).toBe(true);
    inspector.invalidate();
    expect(await inspector.attachTree("window", process)).toBe(true);
    expect(mock.warning).toHaveBeenCalledTimes(1);
    expect(request.mock.calls.filter(([method]) => method.endsWith("attach"))).toHaveLength(2);
  });
  it("keeps only attached sessions alive and invalidates a stale session once", async () => {
    const { request, inspector } = setup();
    await inspector.keepalive();
    expect(request).not.toHaveBeenCalled();
    mock.trusted = true; mock.warning.mockResolvedValue("Attach");
    await inspector.select("n"); await inspector.attach();
    await inspector.keepalive();
    expect(request).toHaveBeenLastCalledWith("inspect.managed.keepalive", { sessionId: "s" });
    request.mockRejectedValueOnce({ data: { code: "sessionStale" } });
    await inspector.keepalive();
    expect(inspector.sessionInfo).toBeUndefined();
    const count = request.mock.calls.length;
    await inspector.keepalive();
    expect(request).toHaveBeenCalledTimes(count);
  });
  it("rejects malformed managed messages", () => {
    expect(parseSpyRequest({ type: "managedAttach" })).toEqual({ type: "managedAttach" });
    for (const value of [{ type: "managedAttach", pid: 1 }, { type: "managedRead" }, { type: "managedRead", memberKey: 1 }, { type: "managedReadVisible", memberKeys: Array(33).fill("x") }, { type: "managedCopy", kind: "bad" }, { type: "managedDetach", sessionId: "x" }]) expect(parseSpyRequest(value)).toBeUndefined();
  });
  it("checks the selected process identity before resolving", async () => {
    const { inspector, request } = setup(); mock.trusted = true; mock.warning.mockResolvedValue("Attach"); await inspector.select("one"); await inspector.attach(); await inspector.select("two"); request.mockImplementationOnce(async () => ({ ...facts, process: { ...facts.process, creationTimeUtc: "reused" } })); expect(await inspector.resolve("two")).toBeUndefined(); expect(inspector.state).toBe("not attached to this process"); expect(request.mock.calls.filter((call) => call[0] === "inspect.managed.attach")).toHaveLength(1); expect(request.mock.calls.filter((call) => call[0] === "inspect.managed.resolve")).toHaveLength(0);
  });
});


it("extracts errors and logs each attachment attempt once", async () => {
  expect(managedFailure({ message: "reason", data: { code: "alreadyAttached", hint: "hint" } })).toEqual({ code: "alreadyAttached", hint: "hint", message: "reason" });
  expect(managedFailure({ message: "reason", data: { code: "newCode", hint: "hint" } }).code).toBe("newCode");
  expect(managedFailure({ message: "reason" }).code).toBe("attachFailed");
  const log = vi.fn();
  const request = vi.fn(async (method: string) => { if (method.endsWith("identify")) return { ...facts, appUnderTest: true }; throw { message: "An inspector is already attached to this process", data: { code: "alreadyAttached", hint: "Close the other session." } }; });
  const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true), undefined, log);
  await inspector.select("n"); await inspector.attach(); await inspector.attach();
  expect(log.mock.calls).toEqual(Array(1).fill(["Spy .NET attach failed for C:/App.exe (PID 271): alreadyAttached: An inspector is already attached to this process. Close the other session."]));
});


it("logs again after a different error, process, or successful session", async () => {
  let process = { pid: 99001, creationTimeUtc: "one" };
  let code = "inspectorDisabled";
  let ready = false;
  const log = vi.fn();
  const request = vi.fn(async (method: string) => {
    if (method.endsWith("identify")) return { ...facts, process, appUnderTest: true };
    if (ready) return { ...session, process };
    throw { message: "failure", data: { code } };
  });
  const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true), undefined, log);
  await inspector.select("n");
  await inspector.reuseTreeSession("n"); await inspector.reuseTreeSession("n");
  expect(log).toHaveBeenCalledTimes(1);
  code = "alreadyAttached"; await inspector.reuseTreeSession("n");
  process = { ...process, creationTimeUtc: "two" }; await inspector.reuseTreeSession("n");
  expect(log).toHaveBeenCalledTimes(3);
  ready = true; await inspector.reuseTreeSession("n");
  inspector.invalidate(); ready = false; await inspector.reuseTreeSession("n");
  expect(log).toHaveBeenCalledTimes(4);
});
