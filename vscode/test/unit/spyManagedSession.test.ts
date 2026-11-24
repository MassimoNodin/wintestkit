import { describe, expect, it, vi } from "vitest";
import type { InitializeResult } from "../../src/protocol/generated";
import type { JsonRpcClient } from "../../src/server/jsonrpc";
const mock = vi.hoisted(() => ({ trusted: true, warning: vi.fn(), open: vi.fn() }));
vi.mock("vscode", () => ({ workspace: { get isTrusted() { return mock.trusted; } }, window: { showWarningMessage: mock.warning }, env: { openExternal: mock.open }, Uri: { parse: (url: string) => url } }));
import { ManagedInspector, isManagedNodeId, isManagedSource, managedErrorState, managedFailure, wpfNodeSession } from "../../src/spy/managedSession";
import { parseSpyRequest } from "../../src/spy/messages";
const initialized = (enabled: boolean) => ({ capabilities: enabled ? { managedInspector: true } : undefined }) as InitializeResult;
const facts = { process: { pid: 271, creationTimeUtc: "one" }, executable: "C:/App.exe", runtime: "net8", architecture: "x64", wpfLoaded: true, appUnderTest: false };
const session = { sessionId: "s", process: facts.process, state: "ready", protocolMajor: 1, protocolMinor: 0, features: [] };
function setup() {
  const request = vi.fn<(method: string, params?: unknown) => Promise<unknown>>(async (method: string) => method.endsWith("identify") ? facts : method.endsWith("attach") ? session : { releasedCount: 1 });
  return { request, inspector: new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true)) };
}
describe("managed Spy host", () => {
  it("keeps the proof at the host boundary and binds the exact selection before preparing a single ticket", async () => {
    const object = { sessionId: "s", objectId: "o", generation: 4 };
    const request = vi.fn(async (method: string) => {
      if (method.endsWith("identify")) return { ...facts, appUnderTest: true };
      if (method.endsWith("attach")) return session;
      if (method.endsWith("spySelect")) return { canInvoke: true, mapping: { status: "exact", object } };
      if (method.endsWith("spyPrepareInvoke")) return { ticket: "single-use" };
      return { audit: { outcome: "performed" }, result: {} };
    });
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true), undefined, undefined, "host-secret");
    mock.trusted = true; await inspector.select("node"); await inspector.attach();
    expect(request).toHaveBeenCalledWith("inspect.managed.attach", { process: facts.process, hostCapability: "host-secret" });
    expect(await inspector.bindSpy("node", object as never)).toBe(true);
    const ticket = await inspector.prepareSpy(object as never, "key", [{ type: "System.String", value: "private" }]);
    await inspector.invokeSpy(ticket!);
    expect(request).toHaveBeenCalledWith("inspect.managed.spySelect", { hostCapability: "host-secret", sessionId: "s", nodeId: "node" });
    expect(request).toHaveBeenCalledWith("inspect.managed.spyPrepareInvoke", { hostCapability: "host-secret", sessionId: "s", objectId: "o", generation: 4, memberKey: "key", arguments: [{ type: "System.String", value: "private" }] });
    expect(request).toHaveBeenCalledWith("inspect.managed.spyInvoke", { hostCapability: "host-secret", ticket: "single-use" });
    expect(await inspector.bindSpy("node", { ...object, generation: 5 } as never)).toBe(false);
    await inspector.select(undefined);
    await vi.waitFor(() => expect(request).toHaveBeenCalledWith("inspect.managed.spySelect", { hostCapability: "host-secret" }));
  });
  it("sends method metadata requests with host session identity", async () => {
    const process = { pid: 87010, creationTimeUtc: "methods" };
    const request = vi.fn(async (method: string) => method.endsWith("identify") ? { ...facts, process } : { ...session, process });
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true)); mock.trusted = true; mock.warning.mockResolvedValue("Attach");
    await inspector.select("n"); await inspector.attach();
    await inspector.spyMethods({ objectId: "object", generation: 4, pageSize: 25, pageToken: "token" });
    expect(request).toHaveBeenLastCalledWith("inspect.managed.spyMethods", { sessionId: "s", objectId: "object", generation: 4, pageSize: 25, pageToken: "token" });
    expect(parseSpyRequest({ type: "managedMethods", action: "more" })).toEqual({ type: "managedMethods", action: "more" });
    expect(parseSpyRequest({ type: "managedMethods", action: "more", objectId: "forged" })).toBeUndefined();
  });
  it("requests the styling of an object and keeps the attachment ready when the inspector withholds it", async () => {
    const process = { pid: 87012, creationTimeUtc: "styling" };
    const denied = { message: "denied", data: { code: "accessDenied" } };
    let deny = false;
    const request = vi.fn(async (method: string) => {
      if (method.endsWith("styling")) { if (deny) throw denied; return { applicable: false }; }
      return method.endsWith("identify") ? { ...facts, process } : { ...session, process };
    });
    const log = vi.fn(), inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true), undefined, log); mock.trusted = true; mock.warning.mockResolvedValue("Attach");
    await inspector.select("n"); await inspector.attach();
    expect(await inspector.styling({ objectId: "object", generation: 4 })).toEqual({ applicable: false });
    expect(request).toHaveBeenLastCalledWith("inspect.managed.styling", { sessionId: "s", objectId: "object", generation: 4 });
    deny = true;
    expect(await inspector.styling({ objectId: "object", generation: 4 })).toBeUndefined();
    expect(inspector.state).toBe("ready");
    expect(log.mock.calls[0][0]).toContain("styling withheld for the selected object");
  });
  it("requests events and single resource values with the host session identity, and keeps the attachment ready when they are withheld", async () => {
    const process = { pid: 87013, creationTimeUtc: "events" };
    const denied = { message: "denied", data: { code: "accessDenied" } };
    let deny = false;
    const request = vi.fn(async (method: string) => {
      if (method.endsWith("events") || method.endsWith("resource")) { if (deny) throw denied; return method.endsWith("events") ? { items: [], complete: true, snapshotId: "snap", diagnostics: [] } : { found: false }; }
      return method.endsWith("identify") ? { ...facts, process } : { ...session, process };
    });
    const log = vi.fn(), inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true), undefined, log); mock.trusted = true; mock.warning.mockResolvedValue("Attach");
    await inspector.select("n"); await inspector.attach();
    expect(await inspector.events({ objectId: "object", generation: 4, pageSize: 50, pageToken: "token" })).toMatchObject({ complete: true });
    expect(request).toHaveBeenLastCalledWith("inspect.managed.events", { sessionId: "s", objectId: "object", generation: 4, pageSize: 50, pageToken: "token" });
    expect(await inspector.resource({ objectId: "object", generation: 4, scope: "application", key: "Accent", keyKind: "string", index: 2 })).toEqual({ found: false });
    expect(request).toHaveBeenLastCalledWith("inspect.managed.resource", { sessionId: "s", objectId: "object", generation: 4, scope: "application", key: "Accent", keyKind: "string", index: 2 });
    deny = true;
    expect(await inspector.events({ objectId: "object", generation: 4 })).toBeUndefined();
    expect(await inspector.resource({ objectId: "object", generation: 4, scope: "local", key: "k", keyKind: "type" })).toBeUndefined();
    expect(inspector.state).toBe("ready");
    expect(log.mock.calls[0][0]).toContain("events withheld for the selected object");
  });
  it("keeps the attachment ready when a Methods cursor expires", async () => {
    const process = { pid: 87011, creationTimeUtc: "expired-methods" };
    const request = vi.fn(async (method: string) => {
      if (method.endsWith("spyMethods")) throw { data: { code: "invalidPageToken" } };
      return method.endsWith("identify") ? { ...facts, process } : { ...session, process };
    });
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true)); mock.trusted = true; mock.warning.mockResolvedValue("Attach");
    await inspector.select("n"); await inspector.attach();
    await expect(inspector.spyMethods({ objectId: "object", generation: 4, pageToken: "expired" })).resolves.toBeUndefined();
    expect(inspector.state).toBe("ready");
  });
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
    for (const code of codes) expect(["not enabled", "not installed", "unsupported target", "blocked by policy", "restart required", "attach failed", "mapping unavailable", "detached (idle)", "busy (retrying)"], code).toContain(managedErrorState({ data: { code } }));
  });
  it("requires trust and confirmation, remembers identity, and never attaches on selection", async () => {
    const { inspector, request } = setup(); await inspector.select("n"); expect(request).not.toHaveBeenCalled();
    mock.trusted = false; await inspector.attach(); expect(request).not.toHaveBeenCalled();
    mock.trusted = true; mock.warning.mockResolvedValueOnce(undefined); await inspector.attach(); expect(request).toHaveBeenCalledTimes(1);
    mock.warning.mockResolvedValue("Attach"); await inspector.attach();
    expect(mock.warning.mock.calls.at(-1)?.[0]).toContain("C:/App.exe");
    for (const term of ["271", "net8", "x64", "getters", "until the application exits"]) expect(mock.warning.mock.calls.at(-1)?.[1].detail).toContain(term);
    expect(mock.warning.mock.calls.at(-1)?.[1].modal).toBe(true);
    // The modal's built-in Cancel is the only cancel path.
    expect(mock.warning.mock.calls.at(-1)?.slice(2)).toEqual(["Attach", "Learn more"]);
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
    mock.warning.mockReset().mockResolvedValueOnce("Learn more").mockResolvedValueOnce(undefined);
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

describe("honest managed failures", () => {
  const trustedApp = { ...facts, appUnderTest: true };
  const denied = { message: "Inspector request failed: accessDenied", data: { code: "accessDenied", hint: "Check the inspector payload, target permissions, and application compatibility." } };
  async function attached(handler: (method: string) => unknown, log = vi.fn()) {
    mock.trusted = true;
    const request = vi.fn(async (method: string) => {
      if (method.endsWith("identify")) return trustedApp;
      if (method.endsWith("attach")) return session;
      return handler(method);
    });
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true), undefined, log);
    await inspector.select("node"); await inspector.attach();
    expect(inspector.state).toBe("ready");
    return { inspector, request, log };
  }
  it("keeps the attachment ready when the inspector withholds data about a protected object", async () => {
    // A Border or ContentPresenter has no automation peer of its own, so the agent refuses its binding metadata.
    const { inspector, log } = await attached((method) => { if (method.endsWith("bindings")) throw denied; return { items: [] }; });
    const params = { objectId: "o", generation: 1, memberKeys: ["k"] as [string] };
    expect(await inspector.bindings(params)).toBeUndefined();
    expect(await inspector.bindings(params)).toBeUndefined();
    expect(inspector.state).toBe("ready");
    expect(inspector.failure).toBeUndefined();
    expect(await inspector.members({ objectId: "o", generation: 1 })).toEqual({ items: [] });
    expect(log).toHaveBeenCalledTimes(1);
    expect(log.mock.calls[0][0]).toContain("bindings withheld for the selected object");
    expect(log.mock.calls[0][0]).toContain("accessDenied");
  });
  it("reports the real code, hint and a single log line when a request really fails", async () => {
    const mapping = { message: "Mapping failed", data: { code: "mappingFailed", hint: "Refresh the tree." } };
    const { inspector, log } = await attached((method) => { if (method.endsWith("members")) throw mapping; return {}; });
    await inspector.members({ objectId: "o", generation: 1 }); await inspector.members({ objectId: "o", generation: 1 });
    expect(inspector.state).toBe("mapping unavailable");
    expect(inspector.failure).toMatchObject({ code: "mappingFailed", hint: "Refresh the tree." });
    expect(log).toHaveBeenCalledTimes(1);
    expect(log.mock.calls[0][0]).toContain("mappingFailed: Mapping failed. Refresh the tree.");
  });
  it("blames an access-denied resolve on the attachment and says so", async () => {
    const { inspector, log } = await attached((method) => { if (method.endsWith("resolve")) throw denied; return {}; });
    await inspector.resolve("node");
    expect(inspector.state).toBe("blocked by policy");
    expect(inspector.failure).toMatchObject({ code: "accessDenied", hint: denied.data.hint });
    expect(log).toHaveBeenCalledTimes(1);
  });
  it("names an untrusted workspace instead of a generic policy message, once", async () => {
    mock.trusted = false;
    const request = vi.fn(), log = vi.fn();
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true), undefined, log);
    await inspector.select("node"); await inspector.attach(); await inspector.attach();
    expect(inspector.state).toBe("blocked by policy");
    expect(inspector.failure).toEqual({ code: "workspaceNotTrusted", hint: "Trust this workspace to attach the inspector.", message: "The workspace is not trusted" });
    expect(log).toHaveBeenCalledTimes(1);
    expect(log.mock.calls[0][0]).toContain("workspaceNotTrusted: The workspace is not trusted. Trust this workspace");
    // Choosing another object keeps the reason visible until the next attach attempt.
    await inspector.select("other");
    expect(inspector.failure?.code).toBe("workspaceNotTrusted");
    expect(await inspector.attachTree("node", facts.process)).toBe(false);
    expect(inspector.treeFailure).toEqual({ code: "workspaceNotTrusted", hint: "Trust this workspace to attach the inspector." });
    expect(request).not.toHaveBeenCalled();
    mock.trusted = true;
  });
  it("tells a missing inspector payload from a policy block when the tree cannot attach", async () => {
    mock.trusted = true;
    const log = vi.fn();
    const inspector = new ManagedInspector({ request: vi.fn() } as unknown as JsonRpcClient, initialized(false), undefined, log);
    expect(await inspector.attachTree("node", facts.process)).toBe(false);
    expect(inspector.treeFailure?.code).toBe("payloadMissing");
    expect(inspector.treeFailure?.hint).toContain("wintestkit[inspector]");
    expect(inspector.state).toBe("not installed");
  });
  it("shows the attach error the server returned, distinguishing accessDenied from blockedByPolicy", async () => {
    mock.trusted = true;
    for (const code of ["accessDenied", "blockedByPolicy"]) {
      const log = vi.fn();
      const request = vi.fn(async (method: string) => { if (method.endsWith("identify")) return trustedApp; throw { message: "Denied", data: { code, hint: `hint for ${code}` } }; });
      const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true), undefined, log);
      await inspector.select("node"); await inspector.attach();
      expect(inspector.state).toBe("blocked by policy");
      expect(inspector.failure).toMatchObject({ code, hint: `hint for ${code}` });
      expect(log.mock.calls[0][0]).toContain(`${code}: Denied. hint for ${code}`);
    }
  });
});

describe("when the host can call methods", () => {
  const object = { sessionId: "s", objectId: "o", generation: 4 };
  const attached = async (select: unknown, capability: string | null = "host-secret") => {
    const request = vi.fn(async (method: string) => {
      if (method.endsWith("identify")) return { ...facts, appUnderTest: true };
      if (method.endsWith("attach")) return session;
      if (method.endsWith("spySelect")) return select;
      return { releasedCount: 0 };
    });
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true), undefined, undefined, capability ?? undefined);
    mock.trusted = true; await inspector.select("node"); await inspector.attach();
    return { inspector, request };
  };
  it("is true for the live sequence: attach, resolve, spySelect with the same object", async () => {
    const { inspector } = await attached({ canInvoke: true, mapping: { status: "exact", object } });
    expect(await inspector.bindSpy("node", { ...object } as never)).toBe(true);
  });
  it("is false, never an error, for each way the binding can fail", async () => {
    // The server did not open the session for method calls (attached without the capability).
    expect(await (await attached({ canInvoke: false, mapping: { status: "exact", object } })).inspector.bindSpy("node", object as never)).toBe(false);
    // The mapping is not exact, or maps another object or generation.
    expect(await (await attached({ canInvoke: true, mapping: { status: "ambiguous" } })).inspector.bindSpy("node", object as never)).toBe(false);
    expect(await (await attached({ canInvoke: true, mapping: { status: "exact", object: { ...object, objectId: "x" } } })).inspector.bindSpy("node", object as never)).toBe(false);
    // The host has no capability at all: nothing is even asked.
    const none = await attached({ canInvoke: true, mapping: { status: "exact", object } }, null);
    expect(await none.inspector.bindSpy("node", object as never)).toBe(false);
    expect(none.request).not.toHaveBeenCalledWith("inspect.managed.spySelect", expect.objectContaining({ nodeId: "node" }));
    // Another node is selected by the time the answer arrives.
    const { inspector } = await attached({ canInvoke: true, mapping: { status: "exact", object } });
    expect(await inspector.bindSpy("other", object as never)).toBe(false);
  });
});

describe("detach then attach", () => {
  const wpfNode = (sessionId: string) => `wpf:["${sessionId}","${sessionId}:6:6",6]`;
  function detachable() {
    let count = 0;
    const sessions = () => ({ ...session, sessionId: `s${count}` });
    const request = vi.fn(async (method: string) => {
      if (method.endsWith("identify")) return facts;
      if (method.endsWith("attach")) { count++; return sessions(); }
      if (method.endsWith("detach")) return { detached: true };
      if (method.endsWith("resolve")) return { status: "exact", object: { sessionId: `s${count}`, objectId: "o", generation: 1 } };
      return {};
    });
    const reattached = vi.fn(), log = vi.fn();
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true), undefined, log, undefined, reattached);
    return { request, inspector, reattached, log };
  }
  it("attaches again three times in a row and asks the tree to replace the stale selected handle", async () => {
    mock.trusted = true; mock.warning.mockResolvedValue("Attach");
    const { request, inspector, reattached, log } = detachable();
    await inspector.select("window"); await inspector.attach();
    expect(inspector.sessionInfo?.sessionId).toBe("s1");
    let current = "s1";
    for (let round = 2; round <= 4; round++) {
      await inspector.select(wpfNode(current));
      await inspector.detach();
      expect(inspector.state).toBe("detached (idle)");
      expect(request).toHaveBeenLastCalledWith("inspect.managed.detach", { sessionId: current });
      expect(inspector.sessionInfo).toBeUndefined();
      const attached = await inspector.attach();
      expect(attached?.sessionId).toBe(`s${round}`);
      expect(inspector.state).toBe("ready");
      expect(inspector.failure).toBeUndefined();
      // The old handle belongs to the closed session: it is replaced by the tree, never resolved with the new session.
      expect(inspector.nodeIsStale()).toBe(true);
      expect(reattached).toHaveBeenCalledTimes(round - 1);
      expect(reattached).toHaveBeenLastCalledWith(facts.process);
      request.mockClear();
      expect(await inspector.resolve(wpfNode(current))).toBeUndefined();
      expect(request).not.toHaveBeenCalled();
      expect(inspector.state).toBe("ready");
      // The tree walk gives the same object a node of the new session, which resolves normally.
      current = `s${round}`;
      await inspector.select(wpfNode(current));
      expect(inspector.nodeIsStale()).toBe(false);
      expect((await inspector.resolve(wpfNode(current)))?.status).toBe("exact");
    }
    expect(log).not.toHaveBeenCalled();
  });
  it("does not ask for a tree walk when the selected node was never a handle of another session", async () => {
    mock.trusted = true; mock.warning.mockResolvedValue("Attach");
    const { inspector, reattached } = detachable();
    await inspector.select("window"); await inspector.attach(); await inspector.detach(); await inspector.attach();
    expect(reattached).not.toHaveBeenCalled();
  });
  it("names the executable and PID when the attach fails before identify, from the earlier attach", async () => {
    mock.trusted = true; mock.warning.mockResolvedValue("Attach");
    const log = vi.fn();
    let identifyFails = false;
    const request = vi.fn(async (method: string) => {
      if (method.endsWith("identify")) { if (identifyFails) throw { message: "Inspector session is not ready", data: { code: "sessionStale", hint: "Check the inspector payload." } }; return facts; }
      if (method.endsWith("attach")) return session;
      return { detached: true };
    });
    const inspector = new ManagedInspector({ request } as unknown as JsonRpcClient, initialized(true), undefined, log);
    await inspector.select("window"); await inspector.attach(); await inspector.detach();
    // A handle of the session that was attached, never identified on its own.
    identifyFails = true;
    await inspector.select(wpfNode("s")); await inspector.attach();
    expect(log.mock.calls).toEqual([["Spy .NET attach failed for C:/App.exe (PID 271): sessionStale: Inspector session is not ready. Check the inspector payload."]]);
    // A node the host has never seen, of no known session, honestly stays unknown.
    await inspector.select("never-seen"); await inspector.attach();
    expect(log.mock.calls.at(-1)?.[0]).toContain("for unknown (PID unknown)");
  });
});

describe("managed node ids", () => {
  it("tell WPF and WinForms objects apart from UI Automation elements and read the session from either", () => {
    const wpf = 'wpf:["s1","7",7]', winforms = 'winforms:["s2","9",9]';
    expect(isManagedNodeId(wpf)).toBe(true);
    expect(isManagedNodeId(winforms)).toBe(true);
    expect(isManagedNodeId("42.1234")).toBe(false);
    expect(isManagedNodeId(undefined)).toBe(false);
    expect(wpfNodeSession(wpf)).toBe("s1");
    expect(wpfNodeSession(winforms)).toBe("s2");
    expect(wpfNodeSession("winforms:not json")).toBeUndefined();
    expect(wpfNodeSession("42.1234")).toBeUndefined();
    expect([isManagedSource("wpf"), isManagedSource("winforms"), isManagedSource("uia"), isManagedSource(undefined)]).toEqual([true, true, false, false]);
  });
});
