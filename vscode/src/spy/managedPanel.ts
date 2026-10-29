import * as vscode from "vscode";
import type { Member, ObjectRef, Value, InspectManagedMembersResult, ManagedBindingInfo } from "../protocol/generated";
import type { ManagedRequest } from "./messages";
import { ManagedInspector, MANAGED_INSTALL_HINT } from "./managedSession";

let panelSequence = 0;
type Row = { id: string; member: Member; value?: Value; children?: Row[]; page?: InspectManagedMembersResult };
export class ManagedPanel {
  private epoch = 0;
  private node?: string;
  private object?: ObjectRef;
  private rows: Row[] = [];
  private page?: InspectManagedMembersResult;
  private bindings: ManagedBindingInfo[] = [];
  private warned = false;
  private rowSequence = 0;
  private makeRows(items: Member[]): Row[] { return items.map((member) => ({ id: String(++this.rowSequence), member })); }
  constructor(private inspector: ManagedInspector, private send: (message: unknown) => void) { this.publish(); }
  private publish(): void { const rows = (items: Row[]): unknown[] => items.map(({ page, children, ...row }) => ({ ...row, ...(children ? { children: rows(children) } : {}), ...(page ? { page: { complete: page.complete, nextToken: !!page.nextToken } } : {}) })); this.send({ type: "managedPanel", visible: this.inspector.visible, state: this.inspector.state, install: MANAGED_INSTALL_HINT, object: this.object, rows: rows(this.rows), page: this.page && { complete: this.page.complete, nextToken: !!this.page.nextToken, diagnostics: this.page.diagnostics }, bindings: this.bindings, sequence: ++panelSequence }); }
  select(node?: string): void { if (this.node === node) return; this.node = node; const epoch = ++this.epoch; this.object = undefined; this.rows = []; this.page = undefined; this.bindings = []; const selected = this.inspector.select(node); this.publish(); void Promise.resolve(selected).then(async () => { if (epoch !== this.epoch || !node || !this.inspector.sessionInfo) return; const mapping = await this.inspector.resolve(node); if (epoch !== this.epoch) return; this.object = mapping?.object; if (this.object) await this.load(epoch); else this.publish(); }); }
  dispose(): void { this.epoch++; this.object = undefined; this.rows = []; }
  private async load(epoch: number, append = false): Promise<void> {
    const object = this.object; if (!object) return;
    const page = await this.inspector.members({ objectId: object.objectId, generation: object.generation, ...(append && this.page?.nextToken ? { pageToken: this.page.nextToken } : {}) });
    if (epoch !== this.epoch) return;
    if (!page) { this.publish(); return; }
    this.page = page; this.rows = [...(append ? this.rows : []), ...this.makeRows(page.items)];
    const keys = page.items.filter((m) => m.category === "dependencyProperty" || m.category === "attachedProperty").map((m) => m.memberKey).slice(0, 32);
    if (keys.length) { const result = await this.inspector.bindings({ objectId: object.objectId, generation: object.generation, memberKeys: keys as [string, ...string[]] }); if (epoch !== this.epoch) return; if (result) this.bindings = [...(append ? this.bindings : []), ...result.bindings]; }
    this.publish();
  }
  private findId(id: string, rows = this.rows): Row | undefined { for (const row of rows) { if (row.id === id) return row; const child = row.children && this.findId(id, row.children); if (child) return child; } return undefined; }
  private async loadChild(row: Row, epoch: number, append = false): Promise<void> {
    const object = row.value?.object; if (!object) return;
    const page = await this.inspector.members({ objectId: object.objectId, generation: object.generation, ...(append && row.page?.nextToken ? { pageToken: row.page.nextToken } : {}) });
    if (epoch !== this.epoch || !page) return;
    row.page = page; row.children = [...(append ? row.children || [] : []), ...this.makeRows(page.items)];
  }
  private async read(keys: string[], expand: boolean, scope?: string): Promise<void> {
    const parent = scope ? this.findId(scope) : undefined;
    const object = scope ? parent?.value?.object : this.object, epoch = this.epoch; if (!object) return;
    const available = scope ? parent?.children || [] : this.rows;
    const rows = keys.map((key) => available.find((row) => row.member.memberKey === key)).filter((row): row is Row => !!row && row.member.readable && row.member.visibility === "public" && !!row.member.pathSegment);
    if (!rows.length) return;
    const result = await this.inspector.read({ objectId: object.objectId, generation: object.generation, paths: rows.map((r) => [r.member.pathSegment!]) as [[NonNullable<Member["pathSegment"]>], ...[NonNullable<Member["pathSegment"]>][]] });
    if (epoch !== this.epoch || !result) { if (epoch === this.epoch) this.publish(); return; }
    rows.forEach((row, i) => { row.value = result.values[i]?.value; row.children = undefined; row.page = undefined; });
    if (expand && rows[0].value?.object) await this.loadChild(rows[0], epoch);
    this.publish();
  }
  async handle(message: ManagedRequest): Promise<void> {
    if (message.type === "managedDetach") { this.epoch++; this.object = undefined; this.rows = []; this.page = undefined; this.warned = false; await this.inspector.detach(); this.publish(); return; }
    if (message.type === "managedAttach") { const epoch = ++this.epoch; await this.inspector.attach(); if (epoch !== this.epoch) return; if (this.inspector.state === "ready" && this.node) { const mapping = await this.inspector.resolve(this.node); if (epoch !== this.epoch) return; this.object = mapping?.object; if (this.object) await this.load(epoch); } this.publish(); return; }
    if (message.type === "managedRefresh") { const epoch = ++this.epoch; this.rows = []; this.page = undefined; this.bindings = []; this.publish(); if (this.object) await this.load(epoch); return; }
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
        if (message.kind === "value" && row?.member.readable && row.member.visibility === "public" && row.value?.status === "ok" && row.value.scalar !== undefined && !["object", "array", "unavailable"].includes(row.value.kind)) await vscode.env.clipboard.writeText(String(row.value.scalar));
        if (message.kind === "path" && row) { const path = (items: Row[], target: Row, prefix: Member[]): Member[] | undefined => { for (const item of items) { const next = [...prefix, item.member]; if (item === target) return next; const found = item.children && path(item.children, target, next); if (found) return found; } return undefined; }; const members = path(this.rows, row, []); const segments = members?.map((member) => member.pathSegment); if (!segments?.length || segments.some((segment) => !segment)) return; const first = segments[0]!; if (first.kind === "type" && segments.length === 1) await vscode.env.clipboard.writeText("type:" + first.name); else if ((first.kind === "property" || first.kind === "field") && segments.slice(1).every((segment) => segment?.kind === "property")) { const escaped = segments.map((segment) => segment!.name.replace(/[.\\]/g, "\\$&")); await vscode.env.clipboard.writeText((first.kind === "field" ? "field:" : "clr:") + escaped.join(".")); } else if (first.kind === "dependency" && segments.slice(1).every((segment) => segment?.kind === "property") && ![first.ownerAssembly, first.ownerType, first.name].some((part) => /[|:/]/.test(part))) { const suffix = segments.slice(1).map((segment) => segment!.name.replace(/[/\\]/g, "\\$&")); await vscode.env.clipboard.writeText("dp:" + first.ownerAssembly + "|" + first.ownerType + "::" + first.name + (suffix.length ? "/" + suffix.join("/") : "")); } }
      }
    }
  }
}
