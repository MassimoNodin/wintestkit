import * as vscode from "vscode";
import type { ManagedPath, Member, ObjectRef, Value, InspectManagedMembersResult, ManagedBindingInfo, BindingInfo } from "../protocol/generated";
import type { ManagedRequest } from "./messages";
import type { InspectManagedItemsResult, InspectManagedStylingResult, MemberEvent } from "../protocol/generated";
import type { MethodMetadata, InspectManagedSpyMethodsResult } from "../protocol/generated";
import { ManagedInspector, MANAGED_INSTALL_HINT } from "./managedSession";
import { RpcNumber } from "../server/jsonrpc";

function argumentsFor(method: MethodMetadata, input: { kind: string; text: string }[]): object[] | undefined {
  if (method.unsupportedReason || method.parameters.length > 16 || input.length !== method.parameters.length) return;
  try { return method.parameters.map((parameter, index) => {
    const { kind, text } = input[index], type = parameter.type;
    if (parameter.isOut || text.length > 4096) throw new Error();
    if (type === "System.String") { if (kind === "null" && text === "") return { type, null: true }; if (kind === "value") return { type, value: text }; }
    else if (type === "System.Boolean" && kind === "value" && (text === "true" || text === "false")) return { type, value: text === "true" };
    else if (type === "System.Decimal" && kind === "value" && /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(text)) return { type, value: text };
    else if (["System.Int32", "System.Int64", "System.Single", "System.Double"].includes(type) && kind === "value") {
      if (type === "System.Int32" || type === "System.Int64") {
        if (!/^-?(?:0|[1-9]\d*)$/.test(text)) throw new Error();
        const n = BigInt(text), limit = type === "System.Int32" ? 2147483648n : 9223372036854775808n;
        if (n < -limit || n >= limit) throw new Error();
      } else if (!Number.isFinite(Number(text)) || (type === "System.Single" && !Number.isFinite(Math.fround(Number(text))))) throw new Error();
      return { type, value: new RpcNumber(text) };
    } else if (kind === "enum" && text.length > 0) return { type, enum: text };
    throw new Error();
  }); } catch { return; }
}

// The automatic read: rows per request, the reading time one object may take, how long it waits for a user action.
export const AUTO_BATCH = 25;
export const AUTO_BUDGET_MS = 5000;
export const AUTO_YIELD_MS = 2000;
let panelSequence = 0;
type Row = { id: string; member: Member; autoStatus?: string; value?: Value; children?: Row[]; page?: InspectManagedMembersResult; itemPage?: InspectManagedItemsResult; item?: boolean; text?: string; binding?: { memberKey: string; path: number[]; field: BindingValueField }; styling?: { slot: string }; resource?: { scope: "local" | "application"; key: string; keyKind: "string" | "type" | "componentResourceKey" | "other"; index: number }; valueType?: string; reading?: boolean };
/** What a resource row says until it is expanded: the listing names keys only, and reading a value creates a deferred resource in the application. */
export const RESOURCE_PROMPT = "(expand to read)";
/** The most event pages the Spy loads for one object (200 events each). */
const EVENT_PAGES = 10;
/** The scope of the object rows that bindings hold (DataItem, ResolvedSource, converter parameter, fallback values): they belong to no member. */
export const BINDING_SCOPE = "bindings";
/** The scope of the object rows that the style, templates and resources hold: they belong to no member. */
export const STYLING_SCOPE = "styling";
/** The keys of a styling result whose value is a Value; the slot of an object is the path of keys and indexes that leads to it. */
const STYLING_VALUE_KEYS = new Set(["value", "element", "templatedParent"]);
/** The binding fields whose values are objects the Spy can expand. */
export const BINDING_VALUE_FIELDS = { converterParameter: "ConverterParameter", fallbackValue: "FallbackValue", targetNullValue: "TargetNullValue", dataItem: "DataItem", resolvedSource: "ResolvedSource" } as const;
export type BindingValueField = keyof typeof BINDING_VALUE_FIELDS;
export class ManagedPanel {
  private epoch = 0;
  private disposed = false;
  private node?: string;
  private object?: ObjectRef;
  private rows: Row[] = [];
  private page?: InspectManagedMembersResult;
  private methods: MethodMetadata[] = [];
  private methodsPage?: InspectManagedSpyMethodsResult;
  private methodsStatus: "idle" | "loading" | "ready" | "error" = "idle";
  private methodsActive = false;
  private canInvoke = false;
  private invoking = false;
  private invocation?: { key: string; text: string };
  private bindings: ManagedBindingInfo[] = [];
  private bindingRows: Row[] = [];
  private styling?: InspectManagedStylingResult;
  private stylingRows: Row[] = [];
  private events: MemberEvent[] = [];
  private warned = false;
  private rowSequence = 0;
  private autoConsent?: boolean;
  private consentPending?: Promise<boolean>;
  private autoRun = 0;
  private autoBudget = AUTO_BUDGET_MS;
  private makeRows(items: Member[]): Row[] { return items.map((member) => ({ id: String(++this.rowSequence), member })); }
  constructor(private inspector: ManagedInspector, private send: (message: unknown) => void) { this.publish(); }
  private publish(): void { const rows = (items: Row[]): unknown[] => items.map(({ page, itemPage, children, ...row }) => ({ ...row, ...(itemPage ? { itemPage: { nextToken: !!itemPage.nextPageToken } } : {}), ...(children ? { children: rows(children) } : {}), ...(page ? { page: { complete: page.complete, nextToken: !!page.nextToken } } : {}) })); this.send({ type: "managedPanel", visible: this.inspector.visible, state: this.inspector.state, failure: this.inspector.failure, install: MANAGED_INSTALL_HINT, object: this.object, rows: rows(this.rows), page: this.page && { complete: this.page.complete, nextToken: !!this.page.nextToken, diagnostics: this.page.diagnostics }, methods: { status: this.methodsStatus, items: this.methods, canInvoke: this.canInvoke && this.inspector.state === "ready", invoking: this.invoking, invocation: this.invocation, page: this.methodsPage && { complete: this.methodsPage.complete, nextToken: !!this.methodsPage.nextToken, diagnostics: this.methodsPage.diagnostics } }, bindings: this.bindings, bindingObjects: rows(this.bindingRows), styling: this.styling, stylingObjects: rows(this.stylingRows), events: this.events, readRemaining: this.rows.some((row) => this.autoEligible(row) && !row.value && row.autoStatus === "timed out"), sequence: ++panelSequence }); }
  select(node?: string, wpf = false): void { if (this.node === node && !wpf) return; this.node = node; const epoch = ++this.epoch; this.canInvoke = false; void this.inspector.clearSpy(); this.object = undefined; this.rows = []; this.page = undefined; this.clearMethods(); this.bindings = []; this.bindingRows = []; this.clearStyling(); const selected = this.inspector.select(node); this.publish(); void Promise.resolve(selected).then(async () => { if (epoch !== this.epoch || !node) return; if (wpf) await this.inspector.reuseTreeSession(node); if (epoch !== this.epoch) return; if (!this.inspector.sessionInfo) { this.publish(); return; } const mapping = await this.inspector.resolve(node); if (epoch !== this.epoch) return; this.object = mapping?.status === "exact" ? mapping.object : undefined; if (this.object) await this.loadSelection(epoch, node, this.object); else this.publish(); }); }
  dispose(): void { this.disposed = true; this.epoch++; this.canInvoke = false; void this.inspector.clearSpy(); this.object = undefined; this.rows = []; this.clearStyling(); }
  private async loadSelection(epoch: number, node: string, object: ObjectRef): Promise<void> {
    const canInvoke = await this.inspector.bindSpy(node, object);
    if (epoch !== this.epoch || this.object !== object) return;
    this.canInvoke = canInvoke;
    if (canInvoke) this.publish();
    if (this.methodsActive) void this.loadMethods(epoch);
    await this.loadAutomatic(epoch);
  }
  private clearMethods(): void { this.methods = []; this.methodsPage = undefined; this.methodsStatus = "idle"; this.invocation = undefined; }
  private async loadMethods(epoch: number, append = false): Promise<void> {
    const object = this.object; if (!object || this.methodsStatus === "loading" || (append && !this.methodsPage?.nextToken)) return;
    const token = append ? this.methodsPage?.nextToken : undefined;
    this.methodsStatus = "loading"; this.publish();
    let page: InspectManagedSpyMethodsResult | undefined;
    try { page = await this.inspector.spyMethods({ objectId: object.objectId, generation: object.generation, ...(token ? { pageToken: token } : {}) }); } catch { page = undefined; }
    if (epoch !== this.epoch || object !== this.object) return;
    if (!page) { this.methodsStatus = "error"; this.publish(); return; }
    this.methods = [...(append ? this.methods : []), ...page.items]; this.methodsPage = page; this.methodsStatus = "ready"; this.publish();
  }
  private async consent(): Promise<boolean> {
    if (this.autoConsent !== undefined) return this.autoConsent;
    if (!this.consentPending) this.consentPending = (async () => {
      const config = vscode.workspace.getConfiguration("wintestkit.spy");
      if (config.get<boolean>("suppressGetterWarning", false)) return true;
      // The modal's built-in Cancel is the only cancel path; a second "Cancel" button would show twice.
      const answer = await vscode.window.showWarningMessage("Automatically read public WPF getters in Spy?", { modal: true, detail: "Getters execute application code, can have side effects or hang the application. A timeout cannot stop a running getter." }, "Read automatically", "Read automatically and don't ask again");
      if (answer === "Read automatically and don't ask again") await config.update("suppressGetterWarning", true, vscode.ConfigurationTarget.Global);
      return answer === "Read automatically" || answer === "Read automatically and don't ask again";
    })();
    this.autoConsent = await this.consentPending;
    return this.autoConsent;
  }
  /** Stops the automatic read now: no further batch is sent and the rows keep what was read so far. */
  pauseAutoRead(): void { this.autoRun++; }
  /** Continues a paused read with the rest of the object's time budget; does nothing if there is nothing left to read. */
  resumeAutoRead(): void { if (this.object && this.autoConsent && !this.disposed && this.rows.some((row) => this.autoPending(row))) void this.loadAutomatic(this.epoch, true); }
  private autoPending(row: Row): boolean { return this.autoEligible(row) && !row.value && !row.autoStatus; }
  private async loadAutomatic(epoch: number, resume = false): Promise<void> {
    if (!resume) { this.autoBudget = AUTO_BUDGET_MS; const startedAt = Date.now(); await this.within(this.load(epoch, false, startedAt + this.autoBudget), startedAt + this.autoBudget); this.autoBudget -= Date.now() - startedAt; }
    if (epoch !== this.epoch || !this.object) return;
    const allowed = await this.consent();
    if (epoch !== this.epoch) return;
    if (!allowed) { for (const row of this.rows) if (this.autoPending(row)) row.autoStatus = "declined"; this.publish(); return; }
    // A low-priority queue: one request per batch of rows, and a user action in flight always goes first.
    // The server limits each getter to 250 ms; the whole object gets 5 s of reading time, waiting for the user not counted.
    const run = ++this.autoRun;
    const live = (): boolean => epoch === this.epoch && run === this.autoRun && !!this.object && !this.disposed;
    // A cancelled read leaves its rows as they are: the ones read keep their values, the rest stay unread.
    const cancelled = (): void => { if (epoch === this.epoch && !this.disposed) this.publish(); };
    const spend = async <T>(work: Promise<T>): Promise<T | undefined> => { const startedAt = Date.now(); try { return await this.within(work, startedAt + Math.max(0, this.autoBudget)); } finally { this.autoBudget -= Date.now() - startedAt; } };
    let pages = 0, published = 0;
    while (pages++ < 100) {
      for (let batch = this.rows.filter((row) => this.autoPending(row)).slice(0, AUTO_BATCH); batch.length; batch = this.rows.filter((row) => this.autoPending(row)).slice(0, AUTO_BATCH)) {
        await this.inspector.yieldToUser(AUTO_YIELD_MS);
        if (!live()) { cancelled(); return; }
        if (this.autoBudget <= 0) { for (const row of batch) row.autoStatus = "timed out"; continue; }
        const object = this.object!;
        const response = await spend(this.inspector.spyRead({ objectId: object.objectId, generation: object.generation, paths: batch.map((row) => [row.member.pathSegment!]) as [ManagedPath, ...ManagedPath[]] }, true));
        if (!live()) { cancelled(); return; }
        const values = response?.result?.values;
        batch.forEach((row, index) => { const value = values?.length === batch.length ? values[index]?.value : undefined; if (value) row.value = value; else row.autoStatus = response?.status || "timed out"; });
        // The sidebar redraws on every snapshot; a few per second is enough to watch values arrive.
        if (Date.now() - published >= 150) { published = Date.now(); this.publish(); }
      }
      if (!this.page?.nextToken || this.autoBudget <= 0) break;
      const previous = this.page.nextToken;
      await spend(this.load(epoch, true, Date.now() + Math.max(0, this.autoBudget)));
      if (!live()) { cancelled(); return; }
      if (this.page?.nextToken === previous) break;
    }
    for (const row of this.rows) if (this.autoPending(row)) row.autoStatus = "timed out";
    this.publish();
  }
  private async within<T>(promise: Promise<T>, deadline: number): Promise<T | undefined> {
    let cancel = () => {};
    try { return await Promise.race([promise, new Promise<undefined>((resolve) => { const timer = setTimeout(() => resolve(undefined), Math.max(0, deadline - Date.now())); cancel = () => clearTimeout(timer); })]); }
    finally { cancel(); }
  }
  private canRead(row: Row): boolean { const m = row.member; return !!m.pathSegment && ((m.readable && m.visibility === "public") || ((m.category === "clrField" || m.category === "staticField") && m.reason === "nonPublic" && m.pathSegment.kind === "field" && !!m.pathSegment.memberKey && !!m.pathSegment.declaringType)); }
  // Every readable value is read without a click: CLR properties, dependency and attached properties, fields, type facts.
  // What the inspector cannot read (non-public properties, indexers, write-only ones) is never queued; the sidebar says why.
  private autoEligible(row: Row): boolean {
    const { category, visibility, pathSegment } = row.member;
    if (!this.canRead(row)) return false;
    return category === "clrField" || category === "staticField" || (category === "typeMetadata" && pathSegment?.kind === "type") || (visibility === "public" && (((category === "clrProperty" || category === "staticProperty") && pathSegment?.kind === "property") || ((category === "dependencyProperty" || category === "attachedProperty") && pathSegment?.kind === "dependency")));
  }
  private async load(epoch: number, append = false, deadline = Infinity): Promise<void> {
    const object = this.object; if (!object) return;
    const page = await this.inspector.members({ objectId: object.objectId, generation: object.generation, ...(append && this.page?.nextToken ? { pageToken: this.page.nextToken } : {}) });
    if (epoch !== this.epoch || Date.now() >= deadline) return;
    if (!page) { this.publish(); return; }
    this.page = page; this.rows = [...(append ? this.rows : []), ...this.makeRows(page.items)];
    const keys = page.items.filter((m) => m.category === "dependencyProperty" || m.category === "attachedProperty").map((m) => m.memberKey);
    if (!append) { this.bindings = []; this.bindingRows = []; }
    for (let index = 0; index < keys.length && Date.now() < deadline; index += 32) {
      const request = this.inspector.bindings({ objectId: object.objectId, generation: object.generation, memberKeys: keys.slice(index, index + 32) as [string, ...string[]] });
      const result = deadline === Infinity ? await request : await this.within(request, deadline);
      if (epoch !== this.epoch || Date.now() >= deadline) return;
      if (result) { this.bindings.push(...result.bindings); this.collectBindingRows(result.bindings); }
    }
    this.publish();
    // The style, templates and resources run no application getter, so they neither wait for nor spend the automatic read's budget.
    if (!append) { void this.loadStyling(epoch, object); void this.loadEvents(epoch, object); }
  }
  /** The style, resources and events load after the members and are dropped with them. */
  private clearStyling(): void { this.styling = undefined; this.stylingRows = []; this.events = []; }
  // Events are metadata and delegate lists: no application code runs, so they neither wait for nor spend the automatic read's budget.
  // The agent sorts events that somebody handles first, then the rest by name; the pages keep that order.
  private async loadEvents(epoch: number, object: ObjectRef): Promise<void> {
    const events: MemberEvent[] = [];
    let token: string | undefined;
    for (let pages = 0; pages < EVENT_PAGES; pages++) {
      let page: Awaited<ReturnType<ManagedInspector["events"]>>;
      try { page = await this.inspector.events({ objectId: object.objectId, generation: object.generation, ...(token ? { pageToken: token } : {}) }); } catch { page = undefined; }
      if (epoch !== this.epoch || this.object !== object || this.disposed) return;
      if (!page) break;
      events.push(...page.items);
      if (!page.nextToken || page.nextToken === token) break;
      token = page.nextToken;
    }
    this.events = events;
    this.publish();
  }
  // One resource value, read when its row is expanded. The row shows RESOURCE_PROMPT until then, and what went wrong if the read did not give a value.
  private async loadResource(row: Row, epoch: number): Promise<void> {
    const object = this.object, resource = row.resource;
    if (!object || !resource || row.value || row.reading) return;
    row.reading = true;
    try {
      const result = await this.inspector.resource({ objectId: object.objectId, generation: object.generation, scope: resource.scope, key: resource.key, keyKind: resource.keyKind, index: resource.index });
      if (epoch !== this.epoch || this.object !== object || this.disposed) return;
      if (result?.found && result.value) { row.value = result.value; row.text = undefined; row.valueType = result.valueType; row.member.declaredType = result.value.declaredType; }
      else row.text = result ? "(not found: the resource is gone)" : "(unavailable)";
    } finally { row.reading = false; }
  }
  private async loadStyling(epoch: number, object: ObjectRef): Promise<void> {
    let result: InspectManagedStylingResult | undefined;
    try { result = await this.inspector.styling({ objectId: object.objectId, generation: object.generation }); } catch { result = undefined; }
    if (epoch !== this.epoch || this.object !== object || this.disposed) return;
    this.clearStyling();
    if (result?.applicable) { this.styling = result; this.collectStylingRows(result); }
    this.publish();
  }
  // Objects in the style, the templates and the resources (setter values, template parts, resources, the templated parent) become synthetic rows,
  // so the member and item flow can expand them. A row's slot is the path of the value in the result, which the sidebar builds the same way.
  private collectStylingRows(result: InspectManagedStylingResult): void {
    const visit = (node: unknown, path: string): void => {
      if (Array.isArray(node)) { node.forEach((item, index) => visit(item, path ? `${path}.${index}` : String(index))); return; }
      if (!node || typeof node !== "object") return;
      for (const [key, child] of Object.entries(node as Record<string, unknown>)) {
        const here = path ? `${path}.${key}` : key, value = child as Value | undefined;
        if (STYLING_VALUE_KEYS.has(key) && value && typeof value === "object" && typeof value.status === "string" && typeof value.kind === "string") {
          if (value.status !== "ok" || !value.object) continue;
          const id = String(++this.rowSequence);
          this.stylingRows.push({ id, item: true, styling: { slot: here }, value, member: { memberKey: `styling:${id}`, name: key, category: "clrProperty", declaredType: value.declaredType, declaringType: "", visibility: "public", readable: false, attributes: [] } });
        } else visit(child, here);
      }
    };
    visit(result, "");
    // A resource has a row from the start, with no value: its value is read when the row is expanded.
    const resources = (scope: "local" | "application", info: InspectManagedStylingResult["resources"], where: string): void => {
      info?.entries.forEach((entry, index) => {
        const id = String(++this.rowSequence);
        this.stylingRows.push({ id, item: true, text: RESOURCE_PROMPT, styling: { slot: `${where}.entries.${index}` }, resource: { scope, key: entry.key, keyKind: entry.keyKind, index: entry.index }, member: { memberKey: `styling:${id}`, name: entry.key, category: "clrProperty", declaredType: "System.Object", declaringType: "", visibility: "public", readable: false, attributes: [] } });
      });
    };
    resources("local", result.resources, "resources");
    resources("application", result.application, "application");
  }
  private findId(id: string, rows?: Row[]): Row | undefined {
    if (!rows) return this.findId(id, this.rows) ?? this.findId(id, this.bindingRows) ?? this.findId(id, this.stylingRows);
    for (const row of rows) { if (row.id === id) return row; const child = row.children && this.findId(id, row.children); if (child) return child; }
    return undefined;
  }
  // Binding values that are objects (DataItem, ResolvedSource, parameters) become synthetic rows, so the member and item flow can expand them.
  private collectBindingRows(infos: ManagedBindingInfo[]): void {
    for (const info of infos) {
      const base = this.rows.find((row) => row.member.memberKey === info.memberKey)?.member;
      if (!base) continue;
      const visit = (binding: ManagedBindingInfo | BindingInfo, path: number[]): void => {
        for (const [field, label] of Object.entries(BINDING_VALUE_FIELDS) as [BindingValueField, string][]) {
          const value = binding[field];
          if (value?.status !== "ok" || !value.object) continue;
          const id = String(++this.rowSequence);
          this.bindingRows.push({ id, item: true, binding: { memberKey: info.memberKey, path, field }, value, member: { ...base, memberKey: `binding:${id}`, name: label, declaredType: value.declaredType, declaringType: "", readable: false, pathSegment: undefined } });
        }
        binding.children?.forEach((child, index) => visit(child, [...path, index]));
      };
      visit(info, []);
    }
  }
  private async loadChild(row: Row, epoch: number, append = false): Promise<void> {
    const object = row.value?.object; if (!object) return;
    const page = await this.inspector.members({ objectId: object.objectId, generation: object.generation, ...(append && row.page?.nextToken ? { pageToken: row.page.nextToken } : {}) });
    if (epoch !== this.epoch || !page) return;
    row.page = page; row.children = [...(append ? row.children || [] : []), ...this.makeRows(page.items)];
    if (!append) await this.loadItems(row, epoch);
  }
  private async loadItems(row: Row, epoch: number, append = false): Promise<void> {
    const object = row.value?.object; if (!object) return;
    const page = await this.inspector.items({ objectId: object.objectId, generation: object.generation, ...(append && row.itemPage?.nextPageToken ? { pageToken: row.itemPage.nextPageToken } : {}) });
    if (epoch !== this.epoch || !page) return;
    row.itemPage = page;
    if (page.kind === "notEnumerable") return;
    // Item rows are synthetic: they have no member of their own, so they cannot be read again, only expanded.
    const children = row.children ||= [], taken = new Set(children.map((child) => child.member.name)), fresh: Row[] = [];
    const add = (wanted: string, value: Value, text?: string) => {
      // Row names key the sidebar's rows, so two dictionary keys that print alike stay apart.
      let name = wanted; for (let copy = 2; taken.has(name); copy++) name = `${wanted} (${copy})`; taken.add(name);
      const id = String(++this.rowSequence);
      fresh.push({ id, item: true, ...(text !== undefined ? { text } : {}), member: { ...row.member, memberKey: `item:${id}`, name, declaredType: value.declaredType, declaringType: "", readable: false, pathSegment: undefined }, value });
    };
    // A collection can have a real Count property; the synthetic row must not share its name.
    if (!append && page.count != null) add(taken.has("Count") ? "Count (items)" : "Count", { status: "ok", kind: "integer", declaredType: "System.Int32", runtimeType: "System.Int32", scalar: page.count });
    for (const item of page.items) add(`[${item.key ? String(item.key.scalar ?? (item.key.runtimeType || item.key.kind)) : item.index ?? "?"}]`, item.value);
    if (page.error) add(`Enumeration threw ${page.error.type}${page.error.message ? ": " + page.error.message : ""}`, { status: "ok", kind: "unavailable", declaredType: "", runtimeType: "" }, "");
    // Count and items stay in front of the members, in order, so Load more members appends after them.
    children.splice(append ? children.filter((child) => child.item).length : 0, 0, ...fresh);
  }
  private async read(keys: string[], expand: boolean, scope?: string): Promise<void> {
    const synthetic = scope === BINDING_SCOPE ? this.bindingRows : scope === STYLING_SCOPE ? this.stylingRows : undefined, parent = scope && !synthetic ? this.findId(scope) : undefined;
    const object = synthetic ? this.object : scope ? parent?.value?.object : this.object, epoch = this.epoch; if (!object) return;
    const available = synthetic ?? (scope ? parent?.children || [] : this.rows);
    const item = keys.length === 1 ? available.find((row) => row.member.memberKey === keys[0] && row.item) : undefined;
    if (item) { if (item.resource && !item.value) await this.loadResource(item, epoch); if (epoch !== this.epoch) return; if (expand && item.value?.object) await this.loadChild(item, epoch); this.publish(); return; }
    const rows = keys.map((key) => available.find((row) => row.member.memberKey === key)).filter((row): row is Row => !!row && this.canRead(row));
    if (!rows.length) return;
    for (const row of rows) {
      const path = [row.member.pathSegment!] as [NonNullable<Member["pathSegment"]>];
      const response = (row.member.category === "clrField" || row.member.category === "staticField")
        ? await this.inspector.spyRead({ objectId: object.objectId, generation: object.generation, paths: [path] })
        : { result: await this.inspector.read({ objectId: object.objectId, generation: object.generation, paths: [path] }) };
      if (epoch !== this.epoch) return;
      row.value = response.result?.values[0]?.value; row.autoStatus = response.status; row.children = undefined; row.page = undefined;
    }
    if (expand && rows[0].value?.object) await this.loadChild(rows[0], epoch);
    this.publish();
  }
  async handle(message: ManagedRequest): Promise<void> {
    if (message.type === "managedReadRemaining") {
      const epoch = this.epoch, object = this.object, run = ++this.autoRun;
      if (!object || !await this.consent() || epoch !== this.epoch || run !== this.autoRun) return;
      const remaining = this.rows.filter((row) => this.autoEligible(row) && !row.value && row.autoStatus === "timed out");
      for (let index = 0; index < remaining.length; index += AUTO_BATCH) {
        if (epoch !== this.epoch || run !== this.autoRun || this.disposed) return;
        const batch = remaining.slice(index, index + AUTO_BATCH);
        const response = await this.inspector.spyRead({ objectId: object.objectId, generation: object.generation, paths: batch.map((row) => [row.member.pathSegment!]) as [ManagedPath, ...ManagedPath[]] }, true);
        if (epoch !== this.epoch || run !== this.autoRun || this.disposed) return;
        const values = response?.result?.values;
        batch.forEach((row, offset) => { const value = values?.length === batch.length ? values[offset]?.value : undefined; if (value) { row.value = value; row.autoStatus = undefined; } else row.autoStatus = response?.status || "timed out"; });
        this.publish();
      }
      return;
    }
    if (message.type === "managedInvoke") { await this.invoke(message); return; }
    if (message.type === "managedDetach") { this.epoch++; this.canInvoke = false; this.object = undefined; this.rows = []; this.page = undefined; this.clearMethods(); this.clearStyling(); this.warned = false; await this.inspector.detach(); this.publish(); return; }
    if (message.type === "managedAttach") { const epoch = ++this.epoch; this.canInvoke = false; void this.inspector.clearSpy(); this.clearMethods(); this.clearStyling(); await this.inspector.attach(); if (epoch !== this.epoch) return; if (this.inspector.state === "ready" && this.node) { const node = this.node; const mapping = await this.inspector.resolve(node); if (epoch !== this.epoch) return; this.object = mapping?.status === "exact" ? mapping.object : undefined; if (this.object) await this.loadSelection(epoch, node, this.object); } if (epoch === this.epoch) this.publish(); return; }
    if (message.type === "managedRefresh") { const epoch = ++this.epoch; this.canInvoke = false; void this.inspector.clearSpy(); this.rows = []; this.page = undefined; this.clearMethods(); this.bindings = []; this.bindingRows = []; this.clearStyling(); this.publish(); if (this.object && this.node) await this.loadSelection(epoch, this.node, this.object); return; }
    if (message.type === "managedMethods") { this.methodsActive = message.action !== "deactivate"; if (message.action === "activate" && this.methodsStatus === "idle") await this.loadMethods(this.epoch); else if (message.action === "retry" && this.methodsStatus === "error") await this.loadMethods(this.epoch); else if (message.action === "more" && this.methodsStatus === "ready") await this.loadMethods(this.epoch, true); return; }
    if (message.type === "managedLoadMore" && message.group.startsWith("items:")) { const row = this.findId(message.group.slice(6)); if (row?.itemPage?.nextPageToken) await this.loadItems(row, this.epoch, true); this.publish(); return; }
    if (message.type === "managedLoadMore") { const row = this.findId(message.group); if (row?.page?.nextToken) { await this.loadChild(row, this.epoch, true); this.publish(); } else if (this.page?.nextToken) await this.load(this.epoch, true); return; }
    if (message.type === "managedRead" || message.type === "managedExpand") { await this.read([message.memberKey], message.type === "managedExpand", message.scope); return; }
    if (message.type === "managedReadVisible") { const epoch = this.epoch; if (!this.warned) { const answer = await vscode.window.showWarningMessage("Reading getters executes application code and can hang the application. Name-based redaction cannot identify every secret.", { modal: true }, "Read"); if (answer !== "Read" || epoch !== this.epoch) return; this.warned = true; } const scopes = new Map<string, string[]>(); message.memberKeys.slice(0, 32).forEach((key, index) => { const scope = message.scopes?.[index] || ""; scopes.set(scope, [...(scopes.get(scope) || []), key]); }); for (const [scope, keys] of scopes) { if (epoch !== this.epoch) return; await this.read(keys, false, scope || undefined); } return; }
    if (message.type === "managedCopy") {
      if (message.kind === "export") {
        const session = this.inspector.sessionInfo, epoch = this.epoch; if (!session || !this.object) return;
        const uri = await vscode.window.showSaveDialog({ defaultUri: vscode.Uri.file("managed-metadata.json"), filters: { JSON: ["json"] } });
        if (!uri || epoch !== this.epoch || this.inspector.sessionInfo?.sessionId !== session.sessionId || !this.object) return;
        const metadata = (rows: Row[]): unknown[] => rows.map((row) => { const member = { ...row.member, attributes: [] }; return { member, ...(row.children ? { children: metadata(row.children), complete: row.page?.complete ?? false } : {}) }; });
        const complete = (rows: Row[]): boolean => rows.every((row) => !row.children || (!!row.page?.complete && complete(row.children)));
        await vscode.workspace.fs.writeFile(uri, Buffer.from(JSON.stringify({ protocolVersion: { major: session.protocolMajor, minor: session.protocolMinor }, process: session.process, timestamp: new Date().toISOString(), complete: !!this.page?.complete && complete(this.rows), type: this.object.type, rows: metadata(this.rows) }, null, 2), "utf8"));
      } else if (message.memberKey) {
        const row = message.scope ? this.findId(message.scope)?.children?.find((item) => item.member.memberKey === message.memberKey) : this.rows.find((item) => item.member.memberKey === message.memberKey);
        if (message.kind === "value" && row && this.canRead(row) && row.value?.status === "ok" && row.value.scalar !== undefined && !["object", "array", "unavailable"].includes(row.value.kind)) await vscode.env.clipboard.writeText(String(row.value.scalar));
      }
    }
  }
  private async invoke(message: Extract<ManagedRequest, { type: "managedInvoke" }>): Promise<void> {
    const object = this.object, session = this.inspector.sessionInfo, epoch = this.epoch;
    const matches = this.methods.filter((item) => item.key === message.memberKey);
    const method = matches.length === 1 ? matches[0] : undefined;
    const args = method && argumentsFor(method, message.arguments);
    if (this.invoking || !this.canInvoke || this.inspector.state !== "ready" || this.methodsStatus !== "ready" || !object || !session || !method) return;
    if (!args) { this.invocation = { key: method.key, text: "Invalid arguments. Check the value and type of each argument." }; this.publish(); return; }
    this.invoking = true; this.invocation = undefined; this.publish();
    const current = () => epoch === this.epoch && this.object === object && this.inspector.sessionInfo?.sessionId === session.sessionId && this.inspector.state === "ready" && this.canInvoke && this.methods.includes(method);
    try {
      const signature = `${method.returnType} ${method.declaringType}.${method.name}(${method.parameters.map((p) => `${p.type} ${p.name}`).join(", ")})`;
      const answer = await vscode.window.showWarningMessage("Invoke this method in the target application?", { modal: true, detail: `${signature}\n${method.visibility}; ${method.isStatic ? "static" : "instance"}\nProcess PID: ${session.process.pid}\nProcess started: ${session.process.creationTimeUtc}\n\nThis runs application code and may change its state. A timeout cannot stop a running method.` }, "Invoke");
      if (answer !== "Invoke" || !current()) return;
      const ticket = await this.inspector.prepareSpy(object, method.key, args);
      if (!ticket || !current()) return;
      const result = await this.inspector.invokeSpy(ticket);
      if (!result) return;
      this.inspector.auditInvocation(result.audit.outcome);
      if (!current()) return;
      const value = result.result;
      const raw = value.status === "ok" ? (value.scalar === undefined ? value.kind : String(value.scalar)) : value.status;
      this.invocation = { key: method.key, text: `Result: ${raw.replace(/[\x00-\x1f\x7f]/g, " ").slice(0, 1024)}` };
    } catch {
      this.inspector.auditInvocation("failed");
      if (current()) this.invocation = { key: method.key, text: "Invocation failed or timed out. The method may still have had an effect." };
    } finally { this.invoking = false; if (!this.disposed) this.publish(); }
  }
}
