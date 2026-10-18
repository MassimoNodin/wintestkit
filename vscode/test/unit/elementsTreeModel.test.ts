import { describe, expect, it } from "vitest";
import { buildTree } from "../../src/views/elementsTreeModel";
import type {
  DiscoveryResult,
  ElementEntry,
} from "../../src/protocol/generated";

const range = (line: number) => ({
  start: { line, character: 4 },
  end: { line, character: 10 },
});
const element = (
  name: string,
  line: number,
  withinName?: string,
): ElementEntry => ({
  id: "Main." + name,
  name,
  qualname: "Main." + name,
  kind: "element",
  range: range(line),
  nameRange: range(line),
  locator: { controlType: "Button", name },
  dynamic: false,
  withinName,
});
const discovery = (
  elements: ElementEntry[],
  root = "C:/demo",
): DiscoveryResult => ({
  version: 1,
  root,
  errors: [],
  tests: [],
  pages: [
    {
      id: "Main",
      name: "Main",
      qualname: "Main",
      file: root + "/pages/main.py",
      bases: ["Page"],
      range: range(1),
      nameRange: range(1),
      elements,
    },
  ],
});
describe("Elements tree model", () => {
  it("puts windows first, nests within references and preserves source order", () => {
    const window = {
      ...element("window", 20),
      kind: "window" as const,
      locator: { window: { title: "Demo" } },
    };
    const tree = buildTree([
      discovery([
        element("child", 4, "group"),
        window,
        element("group", 3),
        element("last", 5),
      ]),
    ]);
    expect(tree.map((node) => node.label)).toEqual(["Main"]);
    expect(tree[0].children.map((node) => node.label)).toEqual([
      "window",
      "group",
      "last",
    ]);
    expect(tree[0].children[1].children[0].label).toBe("child");
    expect(tree[0].children[1].children[0].qualname).toBe("Main.child");
  });
  it("shows the type of typed elements but not of plain ones", () => {
    const tree = buildTree([
      discovery([
        { ...element("country", 3), elementType: "ComboBox" },
        { ...element("plain", 4), elementType: "Element" },
        element("unknown", 5),
      ]),
    ]);
    const [country, plain, unknown] = tree[0].children;
    expect(country.description.startsWith("ComboBox · ")).toBe(true);
    expect(country.tooltip?.startsWith("ComboBox: ")).toBe(true);
    expect(plain.description).toBe('Button[name="plain"]');
    expect(unknown.description).toBe('Button[name="unknown"]');
  });
  it("adds project roots only for multi-project workspaces", () => {
    const tree = buildTree([discovery([]), discovery([], "C:/second")]);
    expect(tree.map((node) => node.kind)).toEqual(["project", "project"]);
    expect(tree[1].children[0].file).toBe("C:/second/pages/main.py");
    expect(tree[0].children[0].id).not.toBe(tree[1].children[0].id);
  });
  it("keeps missing parents and cycles visible", () => {
    const tree = buildTree([
      discovery([
        element("first", 2, "second"),
        element("second", 3, "first"),
        element("orphan", 4, "absent"),
      ]),
    ]);
    expect(tree[0].children).toHaveLength(3);
  });
  it("uses short descriptions and full source tooltips", () => {
    const child = element("child", 4, "group");
    child.locator.within = { controlType: "Group", name: "group" };
    const node = buildTree([discovery([child])])[0].children[0];
    expect(node.description).toBe('Button[name="child"]');
    expect(node.tooltip).toContain(
      'Group[name="group"] > Button[name="child"]',
    );
    expect(node.tooltip).toContain("main.py:5");
  });
  it("sorts pages by name without changing discovery", () => {
    const result = discovery([]);
    result.pages.unshift({ ...result.pages[0], id: "Zulu", name: "Zulu" });
    expect(buildTree([result]).map((node) => node.label)).toEqual([
      "Main",
      "Zulu",
    ]);
    expect(result.pages[0].name).toBe("Zulu");
    expect(buildTree([])).toEqual([]);
  });
  it("nests child pages under each parent and roots only unreferenced pages", () => {
    const page = (id: string, children: string[] = []) => ({
      ...discovery([]).pages[0],
      id,
      name: id,
      qualname: id,
      children: children.map((child) => ({
        name: child.toLowerCase(),
        pageId: child,
        range: range(2),
        nameRange: range(2),
      })),
    });
    const result = discovery([]);
    result.pages = [
      page("Shared"),
      page("Standard", ["Shared"]),
      page("Calculator", ["Standard", "Shared"]),
      page("Standalone"),
    ];
    const tree = buildTree([result]);
    expect(tree.map((node) => node.label)).toEqual(["Calculator", "Standalone"]);
    const [standard, shared] = tree[0].children;
    expect(standard.label).toBe("standard: Standard");
    expect(standard.children[0].label).toBe("shared: Shared");
    expect(shared.label).toBe("shared: Shared");
    expect(standard.children[0].id).not.toBe(shared.id);
  });
});
describe("Window actions", () => {
  it("offers only highlight for windows", async () => {
    const { actionsFor } = await import("../../src/views/navigationModel");
    const window = {
      ...element("window", 2),
      kind: "window" as const,
      locator: { window: { title: "Demo" } },
    };
    const node = buildTree([discovery([window])])[0].children[0];
    expect(actionsFor(node)).toEqual(["highlight"]);
  });
});
