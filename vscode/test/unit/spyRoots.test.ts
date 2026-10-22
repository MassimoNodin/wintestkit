import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { describe, expect, it } from "vitest";

const script = readFileSync("media/spy/spy.js", "utf8");

class FakeNode {
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

const render = (appState: unknown, info: Record<string, unknown>, root = true) => {
  const start = script.indexOf("  const renderNodes = (parent, values) => {");
  const stop = script.indexOf("  const table = (id, values) => {", start);
  const tree = new FakeNode("tree");
  const parent = root ? tree : new FakeNode("children");
  const nodes = new Map<string, { label: FakeNode; text: FakeNode }>();
  runInNewContext(script.slice(start, stop) + "\nrenderNodes(parent, values);", {
    parent,
    values: [{ nodeId: "1", hasChildren: false, info }],
    nodes,
    appState,
    selected: undefined,
    element: () => tree,
    document: { createElement: () => new FakeNode() },
    setIcon: () => undefined,
    rootIcon: () => undefined,
    applyMarker: () => undefined,
    filter: () => undefined,
    expand: () => undefined,
    choose: () => undefined,
    String,
    Number,
  });
  return nodes.get("1")!;
};

const window = { name: "", automationId: "", controlType: "Window", className: "MainWindowFull", processId: 7 };

describe("Spy root rows for the selected application", () => {
  it("names a window without a title after the application and marks it", () => {
    const entry = render({ appName: "TeamViewer", appPids: [7] }, window);
    expect(entry.text.textContent).toBe("TeamViewer");
    expect(entry.label.find("app-marker")?.title).toBe("Selected application: TeamViewer");
  });

  it("keeps a window's own title and still marks it", () => {
    const entry = render({ appName: "TeamViewer", appPids: [7] }, { ...window, name: "Main" });
    expect(entry.text.textContent).toBe("Main");
    expect(entry.label.find("app-marker")).toBeDefined();
  });

  it("leaves other applications, and the selected one's descendants, unmarked", () => {
    const other = render({ appName: "TeamViewer", appPids: [8] }, window);
    expect(other.text.textContent).toBe("Window");
    expect(other.label.find("app-marker")).toBeUndefined();
    const child = render({ appName: "TeamViewer", appPids: [7] }, window, false);
    expect(child.text.textContent).toBe("Window");
    expect(child.label.find("app-marker")).toBeUndefined();
    expect(render(undefined, window).label.find("app-marker")).toBeUndefined();
  });
});

describe("the route to a selected row", () => {
  const rows = () => {
    const start = script.indexOf("  const renderNodes = (parent, values) => {");
    const stop = script.indexOf("  const table = (id, values) => {", start);
    const routeStart = script.indexOf("  // The route from a root window down to a row");
    const routeStop = script.indexOf("  const choose = (nodeId) => {", routeStart);
    expect(routeStart).toBeGreaterThan(0);
    const tree = new FakeNode("tree");
    const nodes = new Map<string, { root: boolean; parentId?: string; index: number }>();
    const info = (controlType: string, name: string, extra: Record<string, unknown> = {}) =>
      ({ controlType, name, automationId: "", className: "C", processId: 1, ...extra });
    const context = {
      nodes, appState: undefined, selected: undefined, element: () => tree,
      document: { createElement: () => new FakeNode() },
      setIcon: () => undefined, rootIcon: () => undefined, applyMarker: () => undefined,
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
