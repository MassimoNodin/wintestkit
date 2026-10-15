import { afterEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { Projects } from "../../src/projects";
import type { Project } from "../../src/server/serverManager";
import type { DiscoveryStore } from "../../src/discovery/store";
import type { CheckResultsStore } from "../../src/editor/decorations";
import type { ElementNode } from "../../src/views/elementsTreeModel";
import type { DiscoveryResult } from "../../src/protocol/generated";

const mocks = vi.hoisted(() => ({
  providers: new Map<string, vscode.TreeDataProvider<ElementNode>>(),
  commands: new Map<string, (node: ElementNode) => Promise<void>>(),
  execute: vi.fn(),
  show: vi.fn(async () => ({ revealRange: vi.fn() })),
}));
vi.mock("vscode", () => ({
  EventEmitter: class {
    event = vi.fn();
    fire = vi.fn();
    dispose = vi.fn();
  },
  TreeItem: class {
    constructor(
      public label: string,
      public collapsibleState: number,
    ) {}
  },
  TreeItemCollapsibleState: { Collapsed: 1, None: 0 },
  ThemeIcon: class {
    constructor(public id: string) {}
  },
  Range: class {
    constructor(
      public startLine: number,
      public startCharacter: number,
      public endLine: number,
      public endCharacter: number,
    ) {}
  },
  Uri: { file: (file: string) => ({ fsPath: file }) },
  TextEditorRevealType: { InCenterIfOutsideViewport: 1 },
  window: {
    registerTreeDataProvider: (
      id: string,
      provider: vscode.TreeDataProvider<ElementNode>,
    ) => {
      mocks.providers.set(id, provider);
      return { dispose: vi.fn() };
    },
    showTextDocument: mocks.show,
  },
  commands: {
    registerCommand: (
      id: string,
      handler: (node: ElementNode) => Promise<void>,
    ) => {
      mocks.commands.set(id, handler);
      return { dispose: vi.fn() };
    },
    executeCommand: mocks.execute,
  },
}));
import { ElementsTree } from "../../src/views/elementsTree";

const range = {
  start: { line: 2, character: 4 },
  end: { line: 2, character: 12 },
};
const project = { root: { fsPath: "/project" }, name: "project" } as Project;
const result: DiscoveryResult = {
  version: 1,
  root: "/project",
  errors: [],
  pages: [
    {
      id: "pages/main.py::Main",
      name: "Main",
      qualname: "Main",
      file: "/project/pages/main.py",
      bases: ["Page"],
      range,
      nameRange: range,
      elements: [],
    },
  ],
  flows: [
    {
      id: "flows/navigation.py::open_page",
      name: "open_page",
      file: "/project/flows/navigation.py",
      range,
      nameRange: range,
    },
  ],
  tests: [
    {
      id: "tests/test_main.py::test_open",
      name: "test_open",
      file: "/project/tests/test_main.py",
      kind: "function",
      parent: null,
      range,
      nameRange: range,
    },
  ],
};
const trees: ElementsTree[] = [];
function createTree() {
  const subscribe = () => ({ dispose: vi.fn() });
  const projects = { all: [project], onDidChange: subscribe };
  const discovery = {
    get: () => result,
    onDidChange: subscribe,
  } as unknown as DiscoveryStore;
  const checks = {
    results: new Map(),
    onDidChange: subscribe,
  } as unknown as CheckResultsStore;
  const tree = new ElementsTree(
    projects as unknown as Projects,
    discovery,
    checks,
  );
  trees.push(tree);
  return { tree, projects };
}
afterEach(() => {
  trees.splice(0).forEach((tree) => tree.dispose());
  mocks.commands.clear();
  mocks.providers.clear();
  vi.clearAllMocks();
});
describe("sidebar providers", () => {
  it("registers three independent sections with shared refresh notifications", () => {
    const { tree } = createTree();
    expect([...mocks.providers.keys()]).toEqual([
      "wintestkit.elements",
      "wintestkit.flows",
      "wintestkit.tests",
    ]);
    expect(tree.getChildren().map((node) => node.label)).toEqual(["Main"]);
    expect(tree.getChildren(undefined, "flows")[0].children[0].kind).toBe(
      "flow",
    );
    expect(tree.getChildren(undefined, "tests")[0].children[0].kind).toBe(
      "test",
    );
    expect(mocks.providers.get("wintestkit.flows")!.onDidChangeTreeData).toBe(
      tree.onDidChangeTreeData,
    );
  });
  it.each(["run", "debug"] as const)(
    "routes %s actions to the existing runner with the originating project",
    async (action) => {
      const { tree } = createTree();
      const file = tree.getChildren(undefined, "tests")[0];
      expect(tree.getTreeItem(file).contextValue).toBe("test-file");
      await mocks.commands.get("wintestkit.tests." + action)!(file.children[0]);
      expect(mocks.execute).toHaveBeenCalledWith(
        action === "run" ? "wintestkit.runTest" : "wintestkit.debugTest",
        { id: result.tests[0].id, project },
      );
      await mocks.commands.get("wintestkit.tests." + action)!(file);
      expect(mocks.execute).toHaveBeenLastCalledWith(expect.any(String), {
        id: "tests/test_main.py",
        project,
      });
    },
  );
  it("ignores non-test entries and stale projects", async () => {
    const { tree, projects } = createTree();
    await mocks.commands.get("wintestkit.tests.run")!(tree.getChildren()[0]);
    const test = tree.getChildren(undefined, "tests")[0].children[0];
    projects.all.splice(0);
    await mocks.commands.get("wintestkit.tests.run")!(test);
    expect(mocks.execute).not.toHaveBeenCalled();
  });
  it("opens flow definitions and source files", async () => {
    const { tree } = createTree();
    const file = tree.getChildren(undefined, "flows")[0];
    const flow = file.children[0];
    expect(tree.getTreeItem(flow).command?.command).toBe(
      "wintestkit.elements.goTo",
    );
    await mocks.commands.get("wintestkit.elements.goTo")!(flow);
    expect(mocks.show).toHaveBeenLastCalledWith(
      { fsPath: flow.file },
      {
        selection: expect.objectContaining({ startLine: 2, startCharacter: 4 }),
      },
    );
    await mocks.commands.get("wintestkit.elements.goTo")!(file);
    expect(mocks.show).toHaveBeenLastCalledWith(
      { fsPath: file.file },
      {
        selection: expect.objectContaining({ startLine: 0, startCharacter: 0 }),
      },
    );
  });
});
