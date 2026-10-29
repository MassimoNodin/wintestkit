import * as vscode from "vscode";
import type { InitializeResult, InspectManagedIdentifyResult, InspectManagedAttachResult, InspectManagedResolveResult, InspectManagedMembersParams, InspectManagedMembersResult, InspectManagedReadParams, InspectManagedReadResult, InspectManagedChildrenParams, InspectManagedChildrenResult, InspectManagedBindingsParams, InspectManagedBindingsResult, InspectManagedReleaseResult } from "../protocol/generated";
import type { JsonRpcClient } from "../server/jsonrpc";

export type ManagedState = "not enabled" | "not installed" | "unsupported target" | "blocked by policy" | "restart required" | "attach failed" | "mapping unavailable" | "detached (idle)" | "ready";
export const MANAGED_INSTALL_HINT = 'pip install "wintestkit[inspector]" or uv pip install "wintestkit[inspector]"';
const confirmed = new Set<string>();
export function managedErrorState(error: unknown): ManagedState {
  const data = (error as { data?: { code?: string } })?.data;
  switch (data?.code) {
    case "notAttached": return "not enabled";
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
  private session?: InspectManagedAttachResult;
  private nodeId?: string;
  private sequence = 0;
  private handles = new Set<string>();
  constructor(private readonly client: JsonRpcClient, initialized: InitializeResult) {
    this.visible = initialized.capabilities?.managedInspector === true;
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
    if (nodeId === this.nodeId) return;
    this.sequence++;
    this.nodeId = nodeId;
    const ids = [...this.handles]; this.handles.clear();
    if (ids.length && this.session) await this.releaseIds(this.session.sessionId, ids);
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
    try {
      const facts = await this.client.request<InspectManagedIdentifyResult>("inspect.managed.identify", { nodeId: node });
      if (!this.current(seq, node, oldSession)) return;
      const identity = `${facts.process.pid}:${facts.process.creationTimeUtc}`;
      if (!confirmed.has(identity)) {
        const answer = await vscode.window.showWarningMessage(`Attach managed inspector to ${facts.executable}\nPID: ${facts.process.pid}\nRuntime: ${facts.runtime ?? "unknown"}\nArchitecture: ${facts.architecture}\n\nThis loads and executes code in the target process. Reading getters can hang the application; timeouts cannot safely stop a running getter.`, { modal: true }, "Attach");
        if (!this.current(seq, node, oldSession) || answer !== "Attach") return;
        confirmed.add(identity);
      }
      const session = await this.client.request<InspectManagedAttachResult>("inspect.managed.attach", { process: facts.process });
      if (!this.current(seq, node, oldSession)) { await this.client.request("inspect.managed.detach", { sessionId: session.sessionId }).catch(() => {}); return; }
      this.session = session; this.state = session.state === "ready" ? "ready" : "attach failed";
      return session;
    } catch (error) { if (this.current(seq, node, oldSession)) this.state = managedErrorState(error); return; }
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
    } catch (error) { if (this.current(seq, node, sessionId)) { this.state = managedErrorState(error); if (this.state === "detached (idle)") this.invalidate(); } return; }
  }
  async resolve(nodeId: string): Promise<InspectManagedResolveResult | undefined> {
    if (nodeId !== this.nodeId) return;
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
