import { describe, expect, it, vi } from "vitest";
import type { InitializeResult } from "../../src/protocol/generated";
import type { JsonRpcClient } from "../../src/server/jsonrpc";
const mock = vi.hoisted(() => ({ trusted: true, warning: vi.fn() }));
vi.mock("vscode", () => ({ workspace: { get isTrusted() { return mock.trusted; } }, window: { showWarningMessage: mock.warning } }));
import { ManagedInspector, managedErrorState } from "../../src/spy/managedSession";
import { parseSpyRequest } from "../../src/spy/messages";
const initialized = (enabled: boolean) => ({ capabilities: enabled ? { managedInspector: true } : undefined }) as InitializeResult;
const facts = { process: { pid: 271, creationTimeUtc: "one" }, executable: "C:/App.exe", runtime: "net8", architecture: "x64", wpfLoaded: true };
const session = { sessionId: "s", process: facts.process, state: "ready", protocolMajor: 1, protocolMinor: 0, features: [] };
function setup() {
  const request = vi.fn<(method: string, params?: unknown) => Promise<unknown>>(async (method: string) => method.endsWith("identify") ? facts : method.endsWith("attach") ? session : { releasedCount: 1 });
  return { request, inspector: new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true)) };
}
describe("managed Spy host", () => {
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
    for (const term of ["271", "net8", "x64", "getter", "process"]) expect(mock.warning.mock.calls.at(-1)?.[0]).toContain(term);
    expect(mock.warning.mock.calls.at(-1)?.[1]).toEqual({ modal: true });
    await inspector.detach(); const prompts = mock.warning.mock.calls.length; await inspector.attach(); expect(mock.warning).toHaveBeenCalledTimes(prompts);
    await inspector.detach();
    request.mockImplementationOnce(async () => ({ ...facts, process: { ...facts.process, creationTimeUtc: "two" } }));
    await inspector.attach(); expect(mock.warning).toHaveBeenCalledTimes(prompts + 1);
  });
  it("releases selection handles and discards a late response", async () => {
    const { inspector, request } = setup(); mock.trusted = true; mock.warning.mockResolvedValue("Attach"); await inspector.select("n"); await inspector.attach();
    request.mockImplementationOnce(async () => facts).mockImplementationOnce(async () => ({ status: "exact", object: { objectId: "o", generation: 1 } })); await inspector.resolve("n");
    await inspector.select("next"); expect(request).toHaveBeenCalledWith("inspect.managed.release", { sessionId: "s", objectIds: ["o"] });
    let finish!: (value: unknown) => void; request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const pending = inspector.resolve("next"); await inspector.select("third"); finish(facts); expect(await pending).toBeUndefined();
  });
  it("rejects malformed managed messages", () => {
    expect(parseSpyRequest({ type: "managedAttach" })).toEqual({ type: "managedAttach" });
    for (const value of [{ type: "managedAttach", pid: 1 }, { type: "managedRead" }, { type: "managedRead", memberKey: 1 }, { type: "managedReadVisible", memberKeys: Array(33).fill("x") }, { type: "managedCopy", kind: "bad" }, { type: "managedDetach", sessionId: "x" }]) expect(parseSpyRequest(value)).toBeUndefined();
  });
  it("checks the selected process identity before resolving", async () => {
    const { inspector, request } = setup(); mock.trusted = true; mock.warning.mockResolvedValue("Attach"); await inspector.select("one"); await inspector.attach(); await inspector.select("two"); request.mockImplementationOnce(async () => ({ ...facts, process: { ...facts.process, creationTimeUtc: "reused" } })); expect(await inspector.resolve("two")).toBeUndefined(); expect(inspector.state).toBe("not attached to this process"); expect(request.mock.calls.filter((call) => call[0] === "inspect.managed.attach")).toHaveLength(1); expect(request.mock.calls.filter((call) => call[0] === "inspect.managed.resolve")).toHaveLength(0);
  });
});
