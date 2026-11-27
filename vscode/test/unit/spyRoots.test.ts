import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import { describe, expect, it } from "vitest";

const script = (readFileSync("media/spy/treeLabels.js", "utf8") + "\n" + readFileSync("media/spy/spy.js", "utf8"));

const WtkTreeLabels = createRequire(import.meta.url)("../../media/spy/treeLabels.js");

class FakeNode {
  get firstElementChild() { return this.children[0]; }
  className = "";
  textContent = "";
  title = "";
  hidden = false;
  dataset: Record<string, string> = {};
  attributes = new Map<string, string>();
  children: FakeNode[] = [];
  parent?: FakeNode;
  classList = { toggle: () => undefined };
  constructor(public id = "") {}
  append(...items: FakeNode[]) {
    for (const item of items) {
      item.parent = this;
      this.children.push(item);
    }
  }
  setAttribute(name: string, value: string) {
    this.attributes.set(name, value);
  }
  addEventListener() {}
  closest() {
    return null;
  }
  replaceChildren(...items: FakeNode[]) {
    this.children = [];
    this.append(...items);
  }
  querySelectorAll() {
    return [];
  }
  find(className: string): FakeNode | undefined {
    for (const child of this.children) {
      if (child.className.split(" ").includes(className)) return child;
      const nested = child.find(className);
      if (nested) return nested;
    }
  }
}

const render = (appState: unknown, info: Record<string, unknown>, root = true, extra: Record<string, unknown> = {}) => {
  const start = script.indexOf("  const renderNodes = (parent, values, append = false) => {");
  const stop = script.indexOf("  const table = (id, values) => {", start);
  const tree = new FakeNode("tree");
  const parent = root ? tree : new FakeNode("children");
  const nodes = new Map<string, { label: FakeNode; text: FakeNode; row: FakeNode }>();
  runInNewContext(script.slice(start, stop) + "\nrenderNodes(parent, values);", {
    parent, WtkTreeLabels, hasDetails: false,
    values: [{ nodeId: "1", hasChildren: false, info, ...extra }],
    nodes,
    appState, templateParts: false,
    selected: undefined,
    element: () => tree,
    document: { createElement: () => new FakeNode() },
    setIcon: () => undefined,
    rootIcon: () => undefined,
    applyMarker: (entry: { text: FakeNode; name: string; row: FakeNode; baseTitle: string }) => { entry.text.textContent = entry.name; entry.row.title = entry.baseTitle; },
    filter: () => undefined,
    expand: () => undefined,
    choose: () => undefined,
    String,
    Number,
  });
  return nodes.get("1")!;
};

const window = { name: "", automationId: "", controlType: "Window", className: "MainWindowFull", processId: 7 };

describe("Spy child response rows", () => {
  class ChildNode {
    children: ChildNode[] = []; parent?: ChildNode; className = ""; textContent = ""; disabled = false;
    dataset: Record<string, string> = {}; events: Record<string, () => void> = {};
    append(...children: ChildNode[]) { for (const child of children) { child.parent = this; this.children.push(child); } }
    setAttribute() {} removeAttribute() {}
    addEventListener(name: string, callback: () => void) { this.events[name] = callback; }
    querySelector() { return this.children.find((child) => child.className === "tree-message"); }
    querySelectorAll() { return []; }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this); }
  }
  const setup = () => {
    const start = script.indexOf('    } else if (message.type === "children") {') + '    } else if (message.type === "children") {'.length;
    const stop = script.indexOf('    } else if (message.type === "suggestion")', start);
    const children = new ChildNode();
    const entry = { children, row: new ChildNode(), toggle: new ChildNode(), node: { hasChildren: true }, open: true, loaded: false, loading: false };
    const sent: unknown[] = []; const rendered: string[] = [];
    const context = { selected: undefined, renderSidebar: () => {}, nodes: new Map([["parent", entry]]), document: { createElement: () => new ChildNode() }, post: (type: string, data: unknown) => sent.push({ type, ...(data as object) }), filter: () => {}, expand: () => {}, revealLabels: () => {}, renderNodes: (_parent: ChildNode, values: string[], append: boolean) => { if (!append) rendered.length = 0; rendered.push(...values); } };
    const receive = (message: object) => runInNewContext('(function(message) {' + script.slice(start, stop) + '})', context)(message);
    return { receive, children, sent, rendered };
  };
  it("appends pages and removes the load-more action on the last page", () => {
    const view = setup();
    view.receive({ nodeId: "parent", nodes: ["first"], nextPageToken: "next" });
    const button = view.children.children[0].children[0];
    expect(button.textContent).toBe("Load more"); button.events.click();
    expect(view.sent).toEqual([{ type: "treeMore", nodeId: "parent", pageToken: "next" }]);
    view.receive({ nodeId: "parent", nodes: ["second"], append: true });
    expect(view.rendered).toEqual(["first", "second"]); expect(view.children.children).toHaveLength(0);
  });
  it("keeps hosted UIA nodes after the WPF page", () => {
    const view = setup();
    const visual = { nodeId: "visual", source: "wpf" };
    const native = { nodeId: "native", source: "uia" };
    view.receive({ nodeId: "parent", nodes: [visual], nextPageToken: "uia:0" });
    view.receive({ nodeId: "parent", nodes: [native], append: true });
    expect(view.rendered).toEqual([visual, native]);
  });
  it("does not render attach or blocked rows", () => {
    const view = setup();
    view.receive({ nodeId: "parent", nodes: [], attachRequired: true });
    expect(view.children.children).toHaveLength(0);
  });
});

describe("Spy root rows for the selected application", () => {
  it("names a window without a title after the application and marks it", () => {
    const entry = render({ appName: "TeamViewer", appPids: [7] }, window);
    expect(entry.text.textContent).toBe('Window("MainWindowFull")');
    expect(entry.label.find("app-marker")?.title).toBe("Selected application: TeamViewer");
  });

  it("labels WPF identities and exposes their full type and source", () => {
    const named = render(undefined, { ...window, controlType: "Button" }, false, { source: "wpf", identity: { type: "System.Windows.Controls.Button", xName: "SaveButton", automationId: "other" } });
    expect(named.text.textContent).toBe('WPFObject("SaveButton")');
    expect(named.row.title).toContain("System.Windows.Controls.Button");
    expect(named.row.attributes.get("aria-label")).toBe('WPFObject("SaveButton")');
    expect(named.row.find("source-badge")).toBeUndefined();
    const automation = render(undefined, { ...window, controlType: "Button" }, false, { source: "wpf", identity: { type: "Demo.Button", automationId: "save" }, wpfText: "", wpfOrdinal: 1 });
    expect(automation.text.textContent).toBe('WPFObject("Button", "")');
    // An unreadable text can only be told apart by its ordinal.
    const unreadable = render(undefined, { ...window, controlType: "Button" }, false, { source: "wpf", identity: { type: "Demo.Button" }, wpfOrdinal: 3 });
    expect(unreadable.text.textContent).toBe('WPFObject("Button", 3)');
    const uia = render(undefined, { ...window, name: "Main" }, true, { source: "uia" });
    expect(uia.text.textContent).toBe('Window("MainWindowFull")');
    expect(uia.row.find("source-badge")).toBeUndefined();
  });
  it("keeps a window's own title and still marks it", () => {
    const entry = render({ appName: "TeamViewer", appPids: [7] }, { ...window, name: "Main" });
    expect(entry.text.textContent).toBe('Window("MainWindowFull")');
    expect(entry.label.find("app-marker")).toBeDefined();
  });

  it("leaves other applications, and the selected one's descendants, unmarked", () => {
    const other = render({ appName: "TeamViewer", appPids: [8] }, window);
    expect(other.text.textContent).toBe('Window("MainWindowFull")');
    expect(other.label.find("app-marker")).toBeUndefined();
    const child = render({ appName: "TeamViewer", appPids: [7] }, window, false);
    expect(child.text.textContent).toBe('Window("MainWindowFull")');
    expect(child.label.find("app-marker")).toBeUndefined();
    expect(render(undefined, window).label.find("app-marker")).toBeUndefined();
  });
});

describe("the route to a selected row", () => {
  const rows = () => {
    const start = script.indexOf("  const renderNodes = (parent, values, append = false) => {");
    const stop = script.indexOf("  const table = (id, values) => {", start);
    const routeStart = script.indexOf("  // The route from a root window down to a row");
    const routeStop = script.indexOf("  const choose = (nodeId) => {", routeStart);
    expect(routeStart).toBeGreaterThan(0);
    const tree = new FakeNode("tree");
    const nodes = new Map<string, { root: boolean; parentId?: string; index: number }>();
    const info = (controlType: string, name: string, extra: Record<string, unknown> = {}) =>
      ({ controlType, name, automationId: "", className: "C", processId: 1, ...extra });
    const context = {
      nodes, WtkTreeLabels, hasDetails: false, templateParts: false, appState: undefined, selected: undefined, element: () => tree,
      document: { createElement: () => new FakeNode() },
      setIcon: () => undefined, rootIcon: () => undefined, applyMarker: (entry: { text: FakeNode; name: string; row: FakeNode; baseTitle: string }) => { entry.text.textContent = entry.name; entry.row.title = entry.baseTitle; },
      filter: () => undefined, expand: () => undefined, choose: () => undefined, String, Number,
    };
    const render = (parent: FakeNode, values: unknown[]) =>
      runInNewContext(script.slice(start, stop) + "\nrenderNodes(parent, values);", { ...context, parent, values });
    render(tree, [
      { nodeId: "w1", hasChildren: true, info: info("Window", "First") },
      { nodeId: "w2", hasChildren: true, info: info("Window", "App") },
    ]);
    const list = new FakeNode("children");
    (list as unknown as { closest: () => unknown }).closest = () => ({
      querySelector: () => ({ dataset: { nodeId: "w2" }, getAttribute: () => "1" }),
    });
    render(list, [
      { nodeId: "p0", hasChildren: false, info: info("Pane", "") },
      { nodeId: "p1", hasChildren: true, info: info("Pane", "Editor", { automationId: "ed" }) },
    ]);
    const deeper = new FakeNode("grandchildren");
    (deeper as unknown as { closest: () => unknown }).closest = () => ({
      querySelector: () => ({ dataset: { nodeId: "p1" }, getAttribute: () => "2" }),
    });
    render(deeper, [{ nodeId: "b0", hasChildren: false, info: info("Button", "Save") }]);
    const route = (nodeId: string) =>
      runInNewContext(script.slice(routeStart, routeStop) + "\nselectionPathFor(id);", { ...context, id: nodeId });
    return { nodes, route };
  };

  it("records where each row sits: its parent and its position among its siblings", () => {
    const { nodes } = rows();
    expect(nodes.get("w2")).toMatchObject({ root: true, parentId: undefined, index: 1 });
    expect(nodes.get("p1")).toMatchObject({ root: false, parentId: "w2", index: 1 });
    expect(nodes.get("b0")).toMatchObject({ root: false, parentId: "p1", index: 0 });
  });

  it("describes the route from the root window by what each object is, not by node id", () => {
    const { route } = rows();
    expect(JSON.parse(JSON.stringify(route("b0")))).toEqual([
      { controlType: "Window", automationId: "", name: "App", className: "C" },
      { controlType: "Pane", automationId: "ed", name: "Editor", className: "C", index: 1 },
      { controlType: "Button", automationId: "", name: "Save", className: "C", index: 0 },
    ]);
    expect(JSON.parse(JSON.stringify(route("w1")))).toEqual([
      { controlType: "Window", automationId: "", name: "First", className: "C" },
    ]); // a root window's position is not part of its identity: windows reorder
  });

  it("has no route for a row that is not in the tree", () => {
    expect(rows().route("missing")).toBeUndefined();
  });
});
