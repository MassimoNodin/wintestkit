import * as vscode from "vscode";
import type { InitializeResult, InspectManagedIdentifyResult, InspectManagedAttachResult, InspectManagedResolveResult, InspectManagedMembersParams, InspectManagedMembersResult, InspectManagedReadParams, InspectManagedReadResult, InspectManagedChildrenParams, InspectManagedChildrenResult, InspectManagedBindingsParams, InspectManagedBindingsResult, InspectManagedReleaseResult } from "../protocol/generated";
import type { JsonRpcClient } from "../server/jsonrpc";

export type ManagedState = "not enabled" | "not installed" | "unsupported target" | "blocked by policy" | "restart required" | "attach failed" | "mapping unavailable" | "detached (idle)" | "ready" | "not attached to this process";
export const MANAGED_INSTALL_HINT = 'pip install "wintestkit[inspector]" or uv pip install "wintestkit[inspector]"';
const confirmed = new Set<string>();
const identityKey = (process: { pid: number; creationTimeUtc: string }) => `${process.pid}:${process.creationTimeUtc}`;
export function isManagedProcessConfirmed(process: { pid: number; creationTimeUtc: string }): boolean {
  return confirmed.has(identityKey(process));
}
const confirmations = new Map<string, Promise<boolean>>();
async function confirmProcess(facts: InspectManagedIdentifyResult): Promise<boolean> {
  const identity = identityKey(facts.process);
  if (confirmed.has(identity)) return true;
  let pending = confirmations.get(identity);
  if (!pending) {
    pending = (async () => {
      if (facts.appUnderTest) return true;
      const message = `Attach the WinTestKit inspector to ${facts.executable}?`;
      const detail = `PID: ${facts.process.pid}\nRuntime: ${facts.runtime ?? "unknown"}\nArchitecture: ${facts.architecture}\n\nWinTestKit loads a small inspector into this application so Spy can show WPF objects, including types, x:Name and properties that Windows UI Automation does not expose. It stays loaded until the application exits and cannot be removed earlier.\n\nReading properties runs the application's own getters. These can be slow, hang the application or have side effects; a timeout cannot safely stop a running getter.\n\nSecurity software, including antivirus, AppLocker or WDAC, may flag or block the inspector. WinTestKit needs the same elevation as the application. Only your Windows user can connect to the inspector, and nothing is sent off the machine.\n\nOnly attach to applications you trust and are allowed to test.`;
      let answer: string | undefined;
      do {
        answer = await vscode.window.showWarningMessage(message, { modal: true, detail }, "Attach", "Learn more", "Cancel");
        if (answer === "Learn more") await vscode.env.openExternal(vscode.Uri.parse("https://github.com/MassimoNodin/wintestkit/blob/master/docs/guide/managed-inspection.md"));
      } while (answer === "Learn more");
      if (answer !== "Attach") return false;
      confirmed.add(identity);
      return true;
    })();
    confirmations.set(identity, pending);
  }
  try { return await pending; } finally { if (confirmations.get(identity) === pending) confirmations.delete(identity); }
}
export type ManagedFailure = { code: string; hint: string; message: string };
export function managedFailure(error: unknown): ManagedFailure {
  const detail = error as { message?: unknown; data?: { code?: unknown; hint?: unknown } } | undefined;
  return { code: typeof detail?.data?.code === "string" && detail.data.code || "attachFailed", hint: typeof detail?.data?.hint === "string" ? detail.data.hint : typeof detail?.message === "string" ? detail.message : "", message: typeof detail?.message === "string" ? detail.message : "Inspector attachment failed" };
}
export function managedErrorState(error: unknown): ManagedState {
  const data = (error as { data?: { code?: string } })?.data;
  switch (data?.code) {
    case "inspectorDisabled": case "notAttached": return "not enabled";
    case "payloadMissing": return "not installed";
    case "unsupportedTarget": case "unsupportedProtocol": return "unsupported target";
    case "accessDenied": case "blockedByPolicy": return "blocked by policy";
    case "agentVersionMismatch": case "payloadMismatch": return "restart required";
    case "mappingFailed": case "objectStale": case "memberAmbiguous": case "memberNotFound": case "limitExceeded": return "mapping unavailable";
    case "processExited": case "sessionStale": return "detached (idle)";
    default: return "attach failed";
  }
}

/** Host-only session state. Never trusts process or session IDs from the webview. */
export class ManagedInspector {
  readonly visible: boolean;
  state: ManagedState = "not enabled";
  failure?: ManagedFailure;
  private lastFailureKey?: string;
  private session?: InspectManagedAttachResult;
  private nodeId?: string;
  private sequence = 0;
  private handles = new Set<string>();
  private releasing: Promise<void> = Promise.resolve();
  get sessionInfo(): InspectManagedAttachResult | undefined { return this.session; }
  constructor(private readonly client: JsonRpcClient, initialized: InitializeResult, private readonly onStale?: (process?: { pid: number; creationTimeUtc: string }) => void, private readonly logFailure?: (line: string) => void) {
    this.visible = initialized.capabilities?.managedInspector === true;
  }
  private fail(error: unknown, facts?: { executable: string; process: { pid: number; creationTimeUtc?: string } }): ManagedFailure {
    const failure = managedFailure(error); this.failure = failure; this.state = managedErrorState(error);
    const sentence = (value: string) => value.replace(/[.\s]+$/, "");
    const key = `${facts?.process.pid ?? "unknown"}:${facts?.process.creationTimeUtc ?? "unknown"}:${failure.code}`;
    if (key !== this.lastFailureKey) this.logFailure?.(`Spy .NET attach failed for ${facts?.executable ?? "unknown"} (PID ${facts?.process.pid ?? "unknown"}): ${failure.code}: ${sentence(failure.message)}. ${failure.hint}`.trim());
    this.lastFailureKey = key;
    return failure;
  }
  private current(sequence: number, nodeId: string | undefined, sessionId?: string): boolean {
    return sequence === this.sequence && nodeId === this.nodeId && sessionId === this.session?.sessionId;
  }
  private remember(value: unknown): void {
    if (!value || typeof value !== "object") return;
    if (Array.isArray(value)) { for (const item of value) this.remember(item); return; }
    const record = value as Record<string, unknown>;
    if (typeof record.objectId === "string" && typeof record.generation === "number") this.handles.add(record.objectId);
    for (const child of Object.values(record)) this.remember(child);
  }
  async select(nodeId?: string): Promise<void> {
    if (nodeId === this.nodeId) return this.releasing;
    this.sequence++;
    this.failure = undefined;
    this.nodeId = nodeId;
    const ids = [...this.handles]; this.handles.clear();
    if (ids.length && this.session) this.releasing = this.releaseIds(this.session.sessionId, ids);
    await this.releasing;
  }
  private async releaseIds(sessionId: string, ids: string[]): Promise<void> {
    for (let i = 0; i < ids.length; i += 256) {
      const objectIds = ids.slice(i, i + 256);
      await this.client.request<InspectManagedReleaseResult>("inspect.managed.release", { sessionId, objectIds }).catch(() => {});
    }
  }
  async attach(): Promise<InspectManagedAttachResult | undefined> {
    if (!this.visible || !this.nodeId) return;
    if (!vscode.workspace.isTrusted) { this.state = "blocked by policy"; return; }
    const seq = this.sequence, node = this.nodeId, oldSession = this.session?.sessionId;
    this.failure = undefined;
    let facts: InspectManagedIdentifyResult | undefined;
    try {
      facts = await this.client.request<InspectManagedIdentifyResult>("inspect.managed.identify", { nodeId: node });
      if (!this.current(seq, node, oldSession)) return;
      if (this.session?.state === "ready" && identityKey(this.session.process) === identityKey(facts.process)) { this.state = "ready"; this.lastFailureKey = undefined; return this.session; }
      if (!await confirmProcess(facts) || !this.current(seq, node, oldSession)) return;
      const session = await this.client.request<InspectManagedAttachResult>("inspect.managed.attach", { process: facts.process });
      if (!this.current(seq, node, oldSession)) { await this.client.request("inspect.managed.detach", { sessionId: session.sessionId }).catch(() => {}); return; }
      if (session.state !== "ready") { this.fail({ message: `Inspector attachment ended in state ${session.state}`, data: { code: session.error || "attachFailed" } }, facts); return; }
      this.session = session; this.state = "ready"; this.lastFailureKey = undefined;
      if (oldSession && oldSession !== session.sessionId) await this.client.request("inspect.managed.detach", { sessionId: oldSession }).catch(() => {});
      return session;
    } catch (error) { if (this.current(seq, node, oldSession)) this.fail(error, facts); return; }
  }
  treeFailure?: { code: string; hint: string };
  async reportTreeFailure(nodeId: string, blocked: { code: string; hint: string }): Promise<void> {
    const facts = await this.client.request<InspectManagedIdentifyResult>("inspect.managed.identify", { nodeId }).catch(() => undefined);
    this.fail({ message: "Inspector attachment failed", data: blocked }, facts?.process ? facts : undefined);
  }
  async attachTree(nodeId: string, process: { pid: number; creationTimeUtc: string }, automatic = false): Promise<boolean> {
    this.treeFailure = undefined;
    if (!this.visible || !vscode.workspace.isTrusted) { this.treeFailure = { code: "blockedByPolicy", hint: "Enable the inspector and trust the workspace." }; return false; }
    if (this.session?.state === "ready" && identityKey(this.session.process) === identityKey(process)) { this.lastFailureKey = undefined; return true; }
    let facts: InspectManagedIdentifyResult | undefined;
    try {
      facts = await this.client.request<InspectManagedIdentifyResult>("inspect.managed.identify", { nodeId });
      if (identityKey(facts.process) !== identityKey(process)) {
        this.treeFailure = { code: "processChanged", hint: "The target process changed. Refresh the object tree and try again." };
        return false;
      }
      if (automatic && !facts.appUnderTest && !isManagedProcessConfirmed(process)) return false;
      if (!await confirmProcess(facts)) return false;
      const result = await this.client.request<InspectManagedAttachResult>("inspect.managed.attach", { process });
      if (result.state === "ready") { this.session = { ...result, process: { ...result.process } }; this.state = "ready"; this.failure = undefined; this.lastFailureKey = undefined; }
      if (result.state !== "ready") { const { code, hint } = this.fail({ message: `Inspector attachment ended in state ${result.state}`, data: { code: result.error || "attachFailed" } }, facts); this.treeFailure = { code, hint }; }
      return result.state === "ready";
    } catch (error) {
      const { code, hint } = this.fail(error, facts ?? { executable: "unknown", process }); this.treeFailure = { code, hint };
      return false;
    }
  }
  async reuseTreeSession(nodeId: string): Promise<void> {
    if (!this.visible || nodeId !== this.nodeId) return;
    const sequence = this.sequence, oldSession = this.session?.sessionId;
    let facts: InspectManagedIdentifyResult | undefined;
    try {
      facts = await this.client.request<InspectManagedIdentifyResult>("inspect.managed.identify", { nodeId });
      if (!this.current(sequence, nodeId, oldSession)) return;
      if (this.session?.state === "ready" && identityKey(this.session.process) === identityKey(facts.process)) return;
      const session = await this.client.request<InspectManagedAttachResult>("inspect.managed.status", { process: facts.process });
      if (!this.current(sequence, nodeId, oldSession)) return;
      if (session.state === "ready" && identityKey(session.process) === identityKey(facts.process)) { this.session = session; this.state = "ready"; this.lastFailureKey = undefined; this.failure = undefined; }
      else if (session.error) this.fail({ message: `Inspector session ended in state ${session.state}`, data: { code: session.error } }, facts);
    } catch (error) { if (this.current(sequence, nodeId, oldSession)) this.fail(error, facts); }
  }
  async keepalive(): Promise<void> {
    const sessionId = this.session?.sessionId;
    if (!sessionId) return;
    try { await this.client.request("inspect.managed.keepalive", { sessionId }); }
    catch (error) {
      if (this.session?.sessionId === sessionId && managedErrorState(error) === "detached (idle)") {
        const process = this.session?.process;
        this.invalidate();
        this.onStale?.(process);
      }
    }
  }
  async detach(): Promise<void> {
    const session = this.session; this.invalidate();
    if (session) await this.client.request("inspect.managed.detach", { sessionId: session.sessionId }).catch(() => {});
  }
  invalidate(): void { this.sequence++; this.session = undefined; this.handles.clear(); this.state = "detached (idle)"; }
  private async call<T>(method: string, params: object): Promise<T | undefined> {
    const sessionId = this.session?.sessionId, node = this.nodeId, seq = this.sequence;
    if (!sessionId || !node) return;
    try {
      const result = await this.client.request<T>(`inspect.managed.${method}`, { ...params, sessionId });
      if (!this.current(seq, node, sessionId)) {
        const old = this.handles; this.handles = new Set(); this.remember(result); const ids = [...this.handles]; this.handles = old;
        if (ids.length) await this.releaseIds(sessionId, ids);
        return;
      }
      this.remember(result); return result;
    } catch (error) { if (this.current(seq, node, sessionId)) { this.state = managedErrorState(error); if (this.state === "detached (idle)") { const process = this.session?.process; this.invalidate(); this.onStale?.(process); } } return; }
  }
  async resolve(nodeId: string): Promise<InspectManagedResolveResult | undefined> {
    if (nodeId !== this.nodeId) return;
    const session = this.session, sequence = this.sequence;
    if (!session) return;
    try {
      const facts = await this.client.request<InspectManagedIdentifyResult>("inspect.managed.identify", { nodeId });
      if (!this.current(sequence, nodeId, session.sessionId)) return;
      if (facts.process.pid !== session.process.pid || facts.process.creationTimeUtc !== session.process.creationTimeUtc) { this.state = "not attached to this process"; return; }
      this.state = "ready";
    } catch (error) { if (this.current(sequence, nodeId, session.sessionId)) this.state = managedErrorState(error); return; }
    const result = await this.call<InspectManagedResolveResult>("resolve", { nodeId });
    if (result && result.status !== "exact") this.state = "mapping unavailable";
    return result;
  }
  members(params: Omit<InspectManagedMembersParams, "sessionId">) { return this.call<InspectManagedMembersResult>("members", params); }
  read(params: Omit<InspectManagedReadParams, "sessionId">) { return this.call<InspectManagedReadResult>("read", params); }
  children(params: Omit<InspectManagedChildrenParams, "sessionId">) { return this.call<InspectManagedChildrenResult>("children", params); }
  bindings(params: Omit<InspectManagedBindingsParams, "sessionId">) { return this.call<InspectManagedBindingsResult>("bindings", params); }
  async release(objectIds: [string, ...string[]]): Promise<InspectManagedReleaseResult | undefined> {
    const result = await this.call<InspectManagedReleaseResult>("release", { objectIds });
    if (result) for (const id of objectIds) this.handles.delete(id);
    return result;
  }
}
