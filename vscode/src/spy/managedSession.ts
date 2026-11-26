import * as vscode from "vscode";
import type { InitializeResult, InspectManagedIdentifyResult, InspectManagedAttachResult, InspectManagedResolveResult, InspectManagedMembersParams, InspectManagedMembersResult, InspectManagedReadParams, InspectManagedReadResult, InspectManagedChildrenParams, InspectManagedChildrenResult, InspectManagedBindingsParams, InspectManagedBindingsResult, InspectManagedReleaseResult } from "../protocol/generated";
import type { JsonRpcClient } from "../server/jsonrpc";
import type { InspectManagedItemsParams, InspectManagedItemsResult } from "../protocol/generated";
import type { InspectManagedStylingParams, InspectManagedStylingResult } from "../protocol/generated";
import type { InspectManagedEventsParams, InspectManagedEventsResult, InspectManagedResourceParams, InspectManagedResourceResult } from "../protocol/generated";
import type { InspectManagedSpyMethodsParams, InspectManagedSpyMethodsResult } from "../protocol/generated";

export type ManagedState = "not enabled" | "not installed" | "unsupported target" | "blocked by policy" | "restart required" | "attach failed" | "mapping unavailable" | "detached (idle)" | "ready" | "busy (retrying)" | "not attached to this process";
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
        answer = await vscode.window.showWarningMessage(message, { modal: true, detail }, "Attach", "Learn more");
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
/** True for an object of the target's WPF or WinForms tree, as opposed to a UI Automation element. */
export function isManagedSource(source: unknown): boolean { return source === "wpf" || source === "winforms"; }
/** True for the node id of a WPF or WinForms object: "wpf:[...]" or "winforms:[...]". */
export function isManagedNodeId(nodeId: string | undefined): boolean { return !!nodeId && (nodeId.startsWith("wpf:") || nodeId.startsWith("winforms:")); }
/** The session a managed node id was issued by: `wpf:["<sessionId>","<objectId>",<generation>]` (or `winforms:`). */
export function wpfNodeSession(nodeId: string | undefined): string | undefined {
  if (!nodeId || !isManagedNodeId(nodeId)) return;
  try { const parts: unknown = JSON.parse(nodeId.slice(nodeId.indexOf(":") + 1)); return Array.isArray(parts) && typeof parts[0] === "string" ? parts[0] : undefined; } catch { return; }
}
export type ManagedFailure = { code: string; hint: string; message: string; reason?: string; timings?: string; method?: string };
export function managedFailure(error: unknown): ManagedFailure {
  const detail = error as { message?: unknown; data?: { code?: unknown; hint?: unknown; method?: unknown; details?: Record<string, unknown> } } | undefined;
  const diagnostic = detail?.data?.details;
  const failure: ManagedFailure = { code: typeof detail?.data?.code === "string" && detail.data.code || "attachFailed", hint: typeof detail?.data?.hint === "string" ? detail.data.hint : typeof detail?.message === "string" ? detail.message : "", message: typeof detail?.message === "string" ? detail.message : "Inspector attachment failed" };
  if (typeof diagnostic?.reason === "string") failure.reason = diagnostic.reason;
  if (typeof detail?.data?.method === "string") failure.method = detail.data.method;
  if (diagnostic) failure.timings = ["queuedMs", "ranMs", "runningForMs", "escalated"].filter(key => diagnostic[key] !== undefined).map(key => `${key}=${String(diagnostic[key])}`).join(" ");
  return failure;
}
export function managedErrorState(error: unknown): ManagedState {
  const data = (error as { data?: { code?: string } })?.data;
  switch (data?.code) {
    case "inspectorDisabled": case "notAttached": return "not enabled";
    case "payloadMissing": return "not installed";
    case "unsupportedTarget": case "unsupportedProtocol": return "unsupported target";
    case "accessDenied": case "blockedByPolicy": case "workspaceNotTrusted": return "blocked by policy";
    case "agentVersionMismatch": case "payloadMismatch": return "restart required";
    case "timeout": case "dispatcherUnavailable": case "busy": return "busy (retrying)";
    case "mappingFailed": case "objectStale": case "memberAmbiguous": case "memberNotFound": case "limitExceeded": return "mapping unavailable";
    case "processExited": case "sessionStale": return "detached (idle)";
    default: return "attach failed";
  }
}

const WORKSPACE_NOT_TRUSTED = { code: "workspaceNotTrusted", hint: "Trust this workspace to attach the inspector." };
const INSPECTOR_MISSING = { code: "payloadMissing", hint: `The inspector payload is missing or invalid. Install it with ${MANAGED_INSTALL_HINT}.` };
// Requests about one object. Access denied there means the inspector withholds that object's data, not that the session is blocked.
const OBJECT_REQUESTS = new Set(["members", "spyMethods", "read", "children", "bindings", "styling", "resource", "events"]);

/** Host-only session state. Never trusts process or session IDs from the webview. */
export class ManagedInspector {
  readonly visible: boolean;
  state: ManagedState = "not enabled";
  failure?: ManagedFailure;
  private lastFailureKey?: string;
  private readonly stallCounts = new Map<string, { count: number; last: number; description: string }>();
  private lastWithheldKey?: string;
  private executable = "unknown";
  /** What identify and attach told the host about each node and session, so a failure before identify still names its target. */
  private targets = new Map<string, { executable: string; process: { pid: number; creationTimeUtc: string } }>();
  private session?: InspectManagedAttachResult;
  private nodeId?: string;
  private sequence = 0;
  private handles = new Set<string>();
  private releasing: Promise<void> = Promise.resolve();
  get sessionInfo(): InspectManagedAttachResult | undefined { return this.session; }
  get targetLabel(): string { return `${this.executable} (PID ${this.session?.process.pid ?? "unknown"})`; }
  private spyQueue: Promise<unknown> = Promise.resolve();
  constructor(private readonly client: JsonRpcClient, initialized: InitializeResult, private readonly onStale?: (process?: { pid: number; creationTimeUtc: string }) => void, private readonly logFailure?: (line: string) => void, private readonly capability?: string, private readonly onReattached?: (process?: { pid: number; creationTimeUtc: string }) => void, private readonly pickedCall?: <T>(nodeId: string, call: (id: string) => Promise<T>) => Promise<T>) {
    this.visible = initialized.capabilities?.managedInspector === true;
  }
  private requestPicked<T>(nodeId: string, call: (id: string) => Promise<T>): Promise<T> {
    return this.pickedCall ? this.pickedCall(nodeId, call) : call(nodeId);
  }
  private fail(error: unknown, facts?: { executable: string; process: { pid: number; creationTimeUtc?: string } }, request?: string): ManagedFailure {
    const failure = managedFailure(error); this.failure = failure; this.state = managedErrorState(error);
    facts ??= this.targetOf(this.nodeId) ?? (this.session ? { executable: this.executable, process: this.session.process } : undefined);
    const known = facts && facts.executable !== "unknown" ? facts : this.targetOf(this.nodeId) ?? facts;
    const sentence = (value: string) => value.replace(/[.\s]+$/, "");
    const method = failure.method || request || "unknown";
    const key = `${facts?.process.pid ?? "unknown"}:${facts?.process.creationTimeUtc ?? "unknown"}:${failure.code}:${failure.reason ?? "unknown"}:${method}`;
    if (this.session && ["timeout", "dispatcherUnavailable", "busy"].includes(failure.code)) {
      const now = Date.now(), previous = this.stallCounts.get(key);
      const description = `Spy .NET ${method} request to ${facts?.executable ?? this.executable} (PID ${facts?.process.pid ?? this.session.process.pid}): ${failure.code}, reason=${failure.reason ?? "unknown"} ${failure.timings ?? ""}. ${failure.hint}`;
      if (!previous) { this.logFailure?.(description); this.stallCounts.set(key, { count: 0, last: now, description }); }
      else { previous.count++; if (now - previous.last >= 30000) { this.logFailure?.(`${description} Repeated ${previous.count} times.`); previous.count = 0; previous.last = now; } }
    } else if (key !== this.lastFailureKey) {
      if (request) this.logFailure?.(`Spy .NET ${request} request failed for ${known?.executable ?? "an unknown process"} (PID ${facts?.process.pid ?? "unknown"}): ${failure.code}: ${sentence(failure.message)}. ${failure.hint}`.trim());
      else this.logFailure?.(`Spy .NET attach failed for ${facts?.executable ?? "unknown"} (PID ${facts?.process.pid ?? "unknown"}): ${failure.code}: ${sentence(failure.message)}. ${failure.hint}`.trim());
    }
    this.lastFailureKey = key;
    return failure;
  }
  private flushStalls(): void {
    for (const stall of this.stallCounts.values()) if (stall.count) this.logFailure?.(`${stall.description} Repeated ${stall.count} times.`);
    this.stallCounts.clear();
  }
  private rememberTarget(key: string, facts: { executable: string; process: { pid: number; creationTimeUtc: string } }): void {
    this.targets.delete(key); this.targets.set(key, { executable: facts.executable, process: facts.process });
    if (this.targets.size > 1024) this.targets.delete(this.targets.keys().next().value as string);
  }
  /** The process a node belongs to when the host has seen it before: by its own identify, or by the session its handle came from. */
  private targetOf(nodeId: string | undefined): { executable: string; process: { pid: number; creationTimeUtc: string } } | undefined {
    if (!nodeId) return;
    const known = this.targets.get(`node:${nodeId}`);
    if (known) return known;
    const sessionId = wpfNodeSession(nodeId);
    return sessionId ? this.targets.get(`session:${sessionId}`) : undefined;
  }
  /** True when the selected node is a WPF handle of a session other than the current one (it was detached or replaced). */
  nodeIsStale(): boolean {
    const sessionId = wpfNodeSession(this.nodeId);
    return !!sessionId && !!this.session && sessionId !== this.session.sessionId;
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
    void this.clearSpy();
    // Without a session the last attach failure is still the honest reason; the next attach clears it.
    if (this.session) { this.failure = undefined; this.lastFailureKey = undefined; this.state = "ready"; }
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
    if (!vscode.workspace.isTrusted) { this.fail({ message: "The workspace is not trusted", data: WORKSPACE_NOT_TRUSTED }); return; }
    const seq = this.sequence, node = this.nodeId, oldSession = this.session?.sessionId;
    this.failure = undefined;
    let facts: InspectManagedIdentifyResult | undefined;
    try {
      facts = await this.requestPicked(node, (id) => this.client.request<InspectManagedIdentifyResult>("inspect.managed.identify", { nodeId: id }));
      this.executable = facts.executable; this.rememberTarget(`node:${node}`, facts);
      if (!this.current(seq, node, oldSession)) return;
      if (this.session?.state === "ready" && identityKey(this.session.process) === identityKey(facts.process)) { this.state = "ready"; this.lastFailureKey = undefined; return this.session; }
      if (!await confirmProcess(facts) || !this.current(seq, node, oldSession)) return;
      const session = await this.client.request<InspectManagedAttachResult>("inspect.managed.attach", { process: facts.process, ...(this.capability ? { hostCapability: this.capability } : {}) });
      if (!this.current(seq, node, oldSession)) return;
      if (session.state !== "ready") { this.fail({ message: `Inspector attachment ended in state ${session.state}`, data: { code: session.error || "attachFailed" } }, facts); return; }
      this.session = session; this.state = "ready"; this.lastFailureKey = undefined;
      this.rememberTarget(`session:${session.sessionId}`, { executable: facts.executable, process: facts.process });
      // The selected node is a handle of the session that was detached: the tree walks again so it and its handles are new.
      if (this.nodeIsStale()) this.onReattached?.(session.process);
      return session;
    } catch (error) { if (this.current(seq, node, oldSession)) this.fail(error, facts ?? this.targetOf(node)); return; }
  }
  treeFailure?: { code: string; hint: string; message?: string };
  async reportTreeFailure(nodeId: string, blocked: { code: string; hint: string }): Promise<void> {
    const facts = await this.requestPicked(nodeId, (id) => this.client.request<InspectManagedIdentifyResult>("inspect.managed.identify", { nodeId: id })).catch(() => undefined);
    this.fail({ message: "Inspector attachment failed", data: blocked }, facts?.process ? facts : this.targetOf(nodeId));
  }
  async attachTree(nodeId: string, process: { pid: number; creationTimeUtc: string }, automatic = false): Promise<boolean> {
    this.treeFailure = undefined;
    const unavailable = !vscode.workspace.isTrusted ? WORKSPACE_NOT_TRUSTED : !this.visible ? INSPECTOR_MISSING : undefined;
    if (unavailable) { const { code, hint } = this.fail({ message: unavailable.hint, data: unavailable }, { executable: this.executable, process }); this.treeFailure = { code, hint }; return false; }
    if (this.session?.state === "ready" && identityKey(this.session.process) === identityKey(process)) { this.lastFailureKey = undefined; return true; }
    let facts: InspectManagedIdentifyResult | undefined;
    try {
      facts = await this.requestPicked(nodeId, (id) => this.client.request<InspectManagedIdentifyResult>("inspect.managed.identify", { nodeId: id }));
      this.executable = facts.executable; this.rememberTarget(`node:${nodeId}`, facts);
      if (identityKey(facts.process) !== identityKey(process)) {
        this.treeFailure = { code: "processChanged", hint: "The target process changed. Refresh the object tree and try again." };
        return false;
      }
      if (automatic && !facts.appUnderTest && !isManagedProcessConfirmed(process)) return false;
      if (!await confirmProcess(facts)) return false;
      const result = await this.client.request<InspectManagedAttachResult>("inspect.managed.attach", { process, ...(this.capability ? { hostCapability: this.capability } : {}) });
      if (result.state === "ready") { this.session = { ...result, process: { ...result.process } }; this.state = "ready"; this.failure = undefined; this.lastFailureKey = undefined; this.rememberTarget(`session:${result.sessionId}`, { executable: facts.executable, process: facts.process }); }
      if (result.state !== "ready") { const { code, hint } = this.fail({ message: `Inspector attachment ended in state ${result.state}`, data: { code: result.error || "attachFailed" } }, facts); this.treeFailure = { code, hint }; }
      return result.state === "ready";
    } catch (error) {
      const { code, hint, message } = this.fail(error, facts ?? { executable: this.targetOf(nodeId)?.executable ?? "unknown", process }); this.treeFailure = message === hint ? { code, hint } : { code, hint, message };
      return false;
    }
  }
  async reuseTreeSession(nodeId: string): Promise<void> {
    if (!this.visible || nodeId !== this.nodeId) return;
    const sequence = this.sequence, oldSession = this.session?.sessionId;
    let facts: InspectManagedIdentifyResult | undefined;
    try {
      facts = await this.requestPicked(nodeId, (id) => this.client.request<InspectManagedIdentifyResult>("inspect.managed.identify", { nodeId: id }));
      this.rememberTarget(`node:${nodeId}`, facts);
      if (!this.current(sequence, nodeId, oldSession)) return;
      if (this.session?.state === "ready" && identityKey(this.session.process) === identityKey(facts.process)) return;
      const session = await this.client.request<InspectManagedAttachResult>("inspect.managed.status", { process: facts.process });
      if (!this.current(sequence, nodeId, oldSession)) return;
      if (session.state === "ready" && identityKey(session.process) === identityKey(facts.process)) { this.session = session; this.state = "ready"; this.lastFailureKey = undefined; this.failure = undefined; }
      else if (session.error) this.fail({ message: `Inspector session ended in state ${session.state}`, data: { code: session.error } }, facts);
    } catch (error) { if (this.current(sequence, nodeId, oldSession)) this.fail(error, facts ?? this.targetOf(nodeId)); }
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
  invalidate(): void { this.flushStalls(); this.sequence++; void this.clearSpy(); this.session = undefined; this.handles.clear(); this.state = "detached (idle)"; }
  private ordered<T>(action: () => Promise<T>): Promise<T> {
    const result = this.spyQueue.then(action, action);
    this.spyQueue = result.catch(() => undefined);
    return result;
  }
  clearSpy(): Promise<void> {
    if (!this.capability) return Promise.resolve();
    return this.ordered(async () => { await this.client.request("inspect.managed.spySelect", { hostCapability: this.capability }).catch(() => undefined); });
  }
  async bindSpy(nodeId: string, object: import("../protocol/generated").ObjectRef): Promise<boolean> {
    const sessionId = this.session?.sessionId, seq = this.sequence;
    if (!this.capability || !sessionId || nodeId !== this.nodeId) return false;
    return this.ordered(async () => {
      if (!this.current(seq, nodeId, sessionId)) return false;
      try {
        const result = await this.client.request<import("../protocol/generated").InspectManagedSpySelectResult>("inspect.managed.spySelect", { hostCapability: this.capability, sessionId, nodeId });
        const mapped = result.mapping?.object;
        return this.current(seq, nodeId, sessionId) && result.canInvoke && result.mapping?.status === "exact" && !!mapped && mapped.sessionId === object.sessionId && mapped.objectId === object.objectId && mapped.generation === object.generation;
      } catch { return false; }
    });
  }
  prepareSpy(object: import("../protocol/generated").ObjectRef, memberKey: string, args: unknown[]): Promise<string | undefined> {
    const sessionId = this.session?.sessionId, node = this.nodeId, seq = this.sequence;
    if (!this.capability || !sessionId || !node) return Promise.resolve(undefined);
    return this.ordered(async () => {
      if (!this.current(seq, node, sessionId)) return;
      const result = await this.client.request<{ ticket: string }>("inspect.managed.spyPrepareInvoke", { hostCapability: this.capability, sessionId, objectId: object.objectId, generation: object.generation, memberKey, arguments: args });
      return this.current(seq, node, sessionId) ? result.ticket : undefined;
    });
  }
  invokeSpy(ticket: string): Promise<import("../protocol/generated").InspectManagedSpyInvokeResult | undefined> {
    const sessionId = this.session?.sessionId, node = this.nodeId, seq = this.sequence;
    if (!this.capability || !sessionId || !node) return Promise.resolve(undefined);
    return this.ordered(async () => {
      if (!this.current(seq, node, sessionId)) return;
      return this.client.request<import("../protocol/generated").InspectManagedSpyInvokeResult>("inspect.managed.spyInvoke", { hostCapability: this.capability, ticket });
    });
  }
  auditInvocation(outcome: string): void { this.logFailure?.(`Spy method invocation: ${outcome}`); }
  private async call<T>(method: string, params: object): Promise<T | undefined> {
    const sessionId = this.session?.sessionId, node = this.nodeId, seq = this.sequence;
    if (!sessionId || !node) return;
    try {
      const request = (id: string) => this.client.request<T>(`inspect.managed.${method}`, { ...params, ...(method === "resolve" ? { nodeId: id } : {}), sessionId });
      const result = method === "resolve" && node ? await this.requestPicked(node, request) : await request(node ?? "");
      if (!this.current(seq, node, sessionId)) {
        const old = this.handles; this.handles = new Set(); this.remember(result); const ids = [...this.handles]; this.handles = old;
        if (ids.length) await this.releaseIds(sessionId, ids);
        return;
      }
      this.flushStalls();
      this.remember(result);
      if (["timeout", "dispatcherUnavailable", "busy"].includes(this.failure?.code ?? "")) { this.state = "ready"; this.failure = undefined; this.lastFailureKey = undefined; }
      return result;
    } catch (error) {
      if (this.current(seq, node, sessionId) && !(method === "spyMethods" && managedFailure(error).code === "invalidPageToken")) this.callFailed(method, error);
      return;
    }
  }
  private callFailed(method: string, error: unknown): void {
    const session = this.session; if (!session) return;
    const code = managedFailure(error).code;
    if (code === "accessDenied" && OBJECT_REQUESTS.has(method)) {
      const key = `${session.sessionId}:${method}:${code}`;
      if (key !== this.lastWithheldKey) this.logFailure?.(`Spy .NET ${method} withheld for the selected object (PID ${session.process.pid}): ${code}: the inspector does not return this data for protected elements, such as elements without an automation peer. The attachment is still ready.`);
      this.lastWithheldKey = key;
      return;
    }
    this.fail(error, { executable: this.targetOf(this.nodeId)?.executable ?? this.executable, process: session.process }, method);
    if (this.state === "detached (idle)") { const process = session.process; this.invalidate(); this.onStale?.(process); }
  }
  async resolve(nodeId: string): Promise<InspectManagedResolveResult | undefined> {
    if (nodeId !== this.nodeId) return;
    const session = this.session, sequence = this.sequence;
    if (!session) return;
    // A handle from a detached session cannot be mapped by the new one; the tree walk that follows Attach replaces it.
    if (this.nodeIsStale()) return;
    try {
      const facts = await this.requestPicked(nodeId, (id) => this.client.request<InspectManagedIdentifyResult>("inspect.managed.identify", { nodeId: id }));
      this.rememberTarget(`node:${nodeId}`, facts);
      if (!this.current(sequence, nodeId, session.sessionId)) return;
      if (facts.process.pid !== session.process.pid || facts.process.creationTimeUtc !== session.process.creationTimeUtc) { this.state = "not attached to this process"; return; }
      this.state = "ready";
    } catch (error) { if (this.current(sequence, nodeId, session.sessionId)) this.fail(error, { executable: this.targetOf(nodeId)?.executable ?? this.executable, process: session.process }, "identify"); return; }
    const result = await this.call<InspectManagedResolveResult>("resolve", { nodeId });
    if (result && result.status !== "exact") this.state = "mapping unavailable";
    return result;
  }
  members(params: Omit<InspectManagedMembersParams, "sessionId">) { return this.call<InspectManagedMembersResult>("members", params); }
  items(params: Omit<InspectManagedItemsParams, "sessionId">) { return this.call<InspectManagedItemsResult>("items", params); }
  /** The Style, templates and resources of an object. No application code runs, so it is not part of the getter budget. */
  styling(params: Omit<InspectManagedStylingParams, "sessionId">) { return this.call<InspectManagedStylingResult>("styling", params); }
  /** The routed and CLR events of an object and who handles them. Only metadata is read, so it is not part of the getter budget either. */
  events(params: Omit<InspectManagedEventsParams, "sessionId">) { return this.call<InspectManagedEventsResult>("events", params); }
  /** One resource value, created on demand: the styling listing names keys only, because reading a deferred resource creates it in the application. */
  resource(params: Omit<InspectManagedResourceParams, "sessionId">) { return this.call<InspectManagedResourceResult>("resource", params); }
  spyMethods(params: Omit<InspectManagedSpyMethodsParams, "sessionId">) { return this.call<InspectManagedSpyMethodsResult>("spyMethods", params); }
  read(params: Omit<InspectManagedReadParams, "sessionId">) { return this.call<InspectManagedReadResult>("read", params); }
  /** Wait while a user action (picker, refresh, tree expand, keepalive...) is in flight; resolves with the time waited. */
  yieldToUser(maxMs: number): Promise<number> { return this.client.foregroundIdle(maxMs); }
  /** Reads one to 32 paths. `background` marks the automatic read, which user actions take precedence over. */
  async spyRead(params: Omit<InspectManagedReadParams, "sessionId">, background = false): Promise<{ result?: InspectManagedReadResult; status?: string; busy?: boolean }> {
    const sessionId = this.session?.sessionId, node = this.nodeId, seq = this.sequence;
    if (!sessionId || !node) return { status: "unavailable" };
    try {
      const result = await this.client.request<InspectManagedReadResult>("inspect.managed.spyRead", { ...params, sessionId }, background ? 10_000 : 30_000, { background });
      if (!this.current(seq, node, sessionId)) { const old = this.handles; this.handles = new Set(); this.remember(result); const ids = [...this.handles]; this.handles = old; if (ids.length) await this.releaseIds(sessionId, ids); return { status: "unavailable" }; }
      this.remember(result);
      // Only a value read proves the UI thread answers again; a read whose getters all timed out does not.
      const answered = result.values.some((entry) => entry.value.status !== "timeout");
      if (answered) this.flushStalls();
      if (answered && ["timeout", "dispatcherUnavailable", "busy"].includes(this.failure?.code ?? "")) { this.state = "ready"; this.failure = undefined; this.lastFailureKey = undefined; }
      return { result };
    } catch (error) { const busy = ["timeout", "dispatcherUnavailable", "busy"].includes(managedFailure(error).code); return { status: busy ? "timed out" : "unavailable", busy }; }
  }
  children(params: Omit<InspectManagedChildrenParams, "sessionId">) { return this.call<InspectManagedChildrenResult>("children", params); }
  bindings(params: Omit<InspectManagedBindingsParams, "sessionId">) { return this.call<InspectManagedBindingsResult>("bindings", params); }
  async release(objectIds: [string, ...string[]]): Promise<InspectManagedReleaseResult | undefined> {
    const result = await this.call<InspectManagedReleaseResult>("release", { objectIds });
    if (result) for (const id of objectIds) this.handles.delete(id);
    return result;
  }
}
