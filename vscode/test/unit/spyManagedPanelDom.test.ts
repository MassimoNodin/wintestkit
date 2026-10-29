import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { describe, expect, it } from "vitest";

class Node {
  children: Node[] = []; parent?: Node; textContent = ""; className = ""; value = ""; type = ""; title = ""; hidden = false; disabled = false; checked = false; open = false; tabIndex = 0; dataset: Record<string, string> = {}; events: Record<string, () => void> = {}; focused = false; scrolled = false;
  constructor(public tagName = "div") {}
  append(...nodes: Node[]) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
  replaceChildren(...nodes: Node[]) { this.children = []; this.append(...nodes); }
  addEventListener(name: string, listener: () => void) { this.events[name] = listener; }
  click() { this.events.click?.(); }
  focus() { this.focused = true; }
  scrollIntoView() { this.scrolled = true; }
  closest(tag: string): Node | undefined { return this.tagName === tag ? this : this.parent?.closest(tag); }
  all(): Node[] { return [this, ...this.children.flatMap((child) => child.all())]; }
  text(): string { return [this.textContent, ...this.children.map((child) => child.text())].join(" "); }
}
function setup() {
  const nodes = new Map<string, Node>(); const messages: unknown[] = []; let receive: (event: { data: unknown }) => void = () => {};
  const element = (id: string) => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id)!; };
  const document = { getElementById: element, createElement: (tag: string) => new Node(tag), querySelectorAll: () => element("managed-groups").all().filter((node) => node.className === "managed-check" && node.checked && !node.disabled) };
  const script = readFileSync("media/spy/spy.js", "utf8");
  const start = script.indexOf("  // Managed inspection"); const end = script.indexOf("  let tutorialView;", start);
  runInNewContext(`const element = document.getElementById; const post = (type, values = {}) => messages.push({ type, ...values });\n` + script.slice(start, end), { document, messages, window: { addEventListener: (_name: string, listener: typeof receive) => { receive = listener; } } });
  const send = (data: object) => receive({ data: { type: "managedPanel", sequence: 1, visible: true, state: "ready", ...data } });
  return { element, messages, send };
}
const member = (name: string, extra = {}) => ({ memberKey: name, name, declaringType: "Base", declaredType: "String", category: "clrProperty", visibility: "public", readable: true, pathSegment: { kind: "property", name }, ...extra });
const object = { objectId: "root", type: { fullName: "Example", assemblyName: "App", baseTypes: [] } };
describe("managed panel DOM", () => {
  it("renders explanations for every state and hides absent capability", () => {
    const fixture = setup(); for (const state of ["not enabled", "not installed", "unsupported target", "blocked by policy", "restart required", "attach failed", "mapping unavailable", "detached (idle)", "ready", "not attached to this process"]) { fixture.send({ state, install: "install", sequence: 1 }); expect(fixture.element("managed-explanation").textContent, state).not.toBe(""); } fixture.send({ visible: false }); expect(fixture.element("managed-panel").hidden).toBe(true);
  });
  it("renders unread rows as text and sends one read message", () => {
    const fixture = setup(); fixture.send({ object, rows: [{ id: "1", member: member("<img>") }] }); const root = fixture.element("managed-groups"); expect(root.text()).toContain("not read"); expect(root.text()).toContain("<img>"); root.all().find((node) => node.textContent === "Read")!.click(); expect(fixture.messages).toEqual([{ type: "managedRead", memberKey: "<img>" }]);
  });
  it("renders scoped children, partial pages, and cycle navigation", () => {
    const fixture = setup(); fixture.send({ object, rows: [{ id: "1", member: member("Parent"), value: { status: "ok", kind: "object", object: { objectId: "child" } }, page: { complete: false, nextToken: true }, children: [{ id: "2", member: member("Child"), value: { status: "cycle", cycleTo: { objectId: "child" } } }] }] }); const root = fixture.element("managed-groups"); const row = root.all().find((node) => node.className === "managed-row")!; root.all().find((node) => node.textContent === "Go to ancestor")!.click(); expect(row.focused && row.scrolled).toBe(true); const child = root.all().filter((node) => node.textContent === "Read")[1]; child.click(); expect(fixture.messages).toContainEqual({ type: "managedRead", memberKey: "Child", scope: "1" }); root.all().find((node) => node.textContent === "Load more")!.click(); expect(fixture.messages).toContainEqual({ type: "managedLoadMore", group: "1" }); expect(root.text()).toContain("Partial list");
  });
  it("shows redaction, truncation, declaring type and dependency source", () => {
    const fixture = setup(); fixture.send({ object, rows: [{ id: "1", member: member("Secret"), value: { status: "redacted", redactionRule: "password" } }, { id: "2", member: member("Text"), value: { status: "truncated", scalar: "prefix", truncatedAt: 100, dependencySource: { baseValueSource: "Local" } } }] }); const text = fixture.element("managed-groups").text(); for (const term of ["password", "prefix", "truncated at 100", "declaring: Base", "source: Local"]) expect(text).toContain(term); expect(fixture.element("managed-groups").all().filter((node) => node.textContent === "Copy value")).toHaveLength(0);
  });
  it("filters loaded rows and ignores old snapshots", () => {
    const fixture = setup(); fixture.send({ sequence: 5, object, rows: [{ id: "1", member: member("Alpha") }, { id: "2", member: member("Beta") }] }); fixture.element("managed-search").value = "alpha"; fixture.element("managed-search").events.input(); fixture.send({ sequence: 4, state: "attach failed" }); expect(fixture.element("managed-groups").text()).toContain("Alpha"); expect(fixture.element("managed-groups").text()).not.toContain("Beta"); expect(fixture.element("managed-state").textContent).toBe("ready");
  });
  it("caps visible reads at 32 and includes child scopes", () => {
    const fixture = setup(); fixture.send({ object, rows: Array.from({ length: 40 }, (_, index) => ({ id: String(index), member: member(String(index), { category: "typeMetadata" }) })) }); const root = fixture.element("managed-groups"); for (const check of root.all().filter((node) => node.className === "managed-check")) check.checked = true; fixture.element("managed-read-visible").click(); expect((fixture.messages[0] as { memberKeys: string[] }).memberKeys).toHaveLength(32);
  });
  it("offers only safe copy and disables locator and nonpublic reads", () => {
    const fixture = setup(); fixture.send({ object, rows: [{ id: "1", member: member("Public"), value: { status: "ok", kind: "string", scalar: "<b>text</b>" } }, { id: "2", member: member("Private", { visibility: "private", readable: false }) }] }); const root = fixture.element("managed-groups"); expect(root.text()).toContain("<b>text</b>"); expect(root.all().filter((node) => node.textContent === "Read")).toHaveLength(1); const locator = root.all().find((node) => node.textContent === "Copy locator")!; expect(locator.disabled).toBe(true); expect(locator.title).toBe("Needs uniqueness check — not available yet"); root.all().find((node) => node.textContent === "Copy value")!.click(); expect(fixture.messages).toContainEqual({ type: "managedCopy", kind: "value", memberKey: "Public" });
  });
  it("appends loaded metadata while retaining a partial label", () => {
    const fixture = setup(); fixture.send({ object, page: { complete: false, nextToken: true }, rows: [{ id: "1", member: member("First") }] }); fixture.send({ sequence: 2, object, page: { complete: false, nextToken: true }, rows: [{ id: "1", member: member("First") }, { id: "2", member: member("Second") }] }); const text = fixture.element("managed-groups").text(); expect(text).toContain("First"); expect(text).toContain("Second"); expect(text).toContain("Partial list"); expect(text).not.toContain("Complete list");
  });
});
