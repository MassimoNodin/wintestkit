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
