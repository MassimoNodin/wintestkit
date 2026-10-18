import vm from "node:vm";
import { afterEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { Projects } from "../../src/projects";
import type { Project } from "../../src/server/serverManager";
import type { DiscoveryStore } from "../../src/discovery/store";
import type { CheckResultsStore } from "../../src/editor/decorations";
import type { ElementNode } from "../../src/views/elementsTreeModel";
import type { DiscoveryResult } from "../../src/protocol/generated";
import { flowKey, type FlowRuns } from "../../src/editor/flowRuns";
import type { FlowStatus } from "../../src/editor/lensModel";
import { actionsFor } from "../../src/views/navigationModel";

const mocks = vi.hoisted(() => ({
  providers: new Map<string, vscode.WebviewViewProvider>(),
  commands: new Map<string, (node: ElementNode) => Promise<void>>(),
  execute: vi.fn(),
  error: vi.fn(),
  show: vi.fn(async () => ({ revealRange: vi.fn() })),
  posted: [] as unknown[],
  listener: undefined as ((value: unknown) => void) | undefined,
  html: "",
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
    constructor(
      public id: string,
      public color?: { id: string },
    ) {}
  },
  ThemeColor: class {
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
  Uri: {
    file: (file: string) => ({ fsPath: file }),
    joinPath: (base: { fsPath: string }, ...parts: string[]) => ({
      fsPath: [base.fsPath, ...parts].join("/"),
    }),
  },
  TextEditorRevealType: { InCenterIfOutsideViewport: 1 },
  window: {
    registerWebviewViewProvider: (
      id: string,
      provider: vscode.WebviewViewProvider,
    ) => {
      mocks.providers.set(id, provider);
      return { dispose: vi.fn() };
    },
    showTextDocument: mocks.show,
    showErrorMessage: mocks.error,
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
import { navigationDocument } from "../../src/views/navigationDocument";

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
      runnable: true,
    },
    {
      id: "flows/navigation.py::open_dialog",
      name: "open_dialog",
      file: "/project/flows/navigation.py",
      range,
      nameRange: range,
      runnable: false,
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
function createTree(host?: {
  globalState: vscode.Memento;
  workspaceState: vscode.Memento;
  extensionUri: vscode.Uri;
}) {
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
  const flows = {
    states: new Map<string, FlowStatus>(),
    onDidChange: subscribe,
  } as unknown as FlowRuns;
  const tree = new ElementsTree(
    projects as unknown as Projects,
    discovery,
    checks,
    flows,
    host,
  );
  trees.push(tree);
  return { tree, projects, checks, flows };
}
afterEach(() => {
  trees.splice(0).forEach((tree) => tree.dispose());
  mocks.commands.clear();
  mocks.providers.clear();
  mocks.posted.length = 0;
  mocks.listener = undefined;
  vi.clearAllMocks();
});
function memoryState(initial?: Record<string, unknown>) {
  const values = new Map<string, unknown>(Object.entries(initial ?? {}));
  return {
    keys: () => [...values.keys()],
    get: <T>(key: string, fallback?: T) =>
      (values.has(key) ? values.get(key) : fallback) as T | undefined,
    update: (key: string, value: unknown) => {
      values.set(key, value);
      return Promise.resolve();
    },
  };
}
function hostFor(global: ReturnType<typeof memoryState> = memoryState()) {
  return {
    globalState: global as unknown as vscode.Memento,
    workspaceState: memoryState() as unknown as vscode.Memento,
    extensionUri: { fsPath: "C:/ext" } as vscode.Uri,
  };
}
function contextArguments(html: string): Array<Record<string, unknown>> {
  return [...html.matchAll(/data-vscode-context="([^"]*)"/g)].map((match) =>
    JSON.parse(
      match[1]
        .replaceAll("&quot;", '"')
        .replaceAll("&#39;", "'")
        .replaceAll("&lt;", "<")
        .replaceAll("&gt;", ">")
        .replaceAll("&amp;", "&"),
    ),
  );
}
function resolve(tree: ElementsTree) {
  const webview = {
    cspSource: "vscode-resource:",
    options: {},
    html: "",
    asWebviewUri: (uri: { fsPath: string }) => ({
      toString: () => "https://icons/" + uri.fsPath,
    }),
    postMessage: (message: unknown) => {
      mocks.posted.push(message);
      return Promise.resolve(true);
    },
    onDidReceiveMessage: (listener: (value: unknown) => void) => {
      mocks.listener = listener;
      return { dispose: vi.fn() };
    },
  };
  tree.resolveWebviewView({
    description: "",
    webview,
    onDidDispose: () => ({ dispose: vi.fn() }),
    onDidChangeVisibility: () => ({ dispose: vi.fn() }),
    visible: true,
    show: () => undefined,
  } as unknown as vscode.WebviewView);
  mocks.html = webview.html;
}
class ClientNode {
  parent: ClientNode | null = null;
  children: ClientNode[] = [];
  attrs: Record<string, string> = {};
  tabIndex = -1;
  scrollTop = 0;
  listeners: Record<
    string,
    Array<(event: { key: string; preventDefault: () => void }) => void>
  > = {};
  constructor(readonly id = "") {}
  getAttribute(name: string): string | null {
    return this.attrs[name] ?? null;
  }
  setAttribute(name: string, value: string): void {
    this.attrs[name] = value;
  }
  append(child: ClientNode): void {
    child.parent = this;
    this.children.push(child);
  }
  contains(node: ClientNode | null): boolean {
    let current = node;
    while (current) {
      if (current === this) return true;
      current = current.parent;
    }
    return false;
  }
  querySelectorAll(selector: string): ClientNode[] {
    const matches: ClientNode[] = [];
    const visit = (node: ClientNode) => {
      if (node.matches(selector)) matches.push(node);
      node.children.forEach(visit);
    };
    this.children.forEach(visit);
    return matches;
  }
  querySelector(selector: string): ClientNode | null {
    return this.querySelectorAll(selector)[0] ?? null;
  }
  matches(selector: string): boolean {
    if (selector === "[data-section]")
      return this.getAttribute("data-section") !== null;
    if (selector === "[aria-selected='true']")
      return this.getAttribute("aria-selected") === "true";
    return false;
  }
  focus(): void {
    clientFocus.current = this;
  }
  addEventListener(
    type: string,
    listener: (event: { key: string; preventDefault: () => void }) => void,
  ): void {
    (this.listeners[type] ??= []).push(listener);
  }
  set innerHTML(_html: string) {
    this.children = [];
  }
}
const clientFocus: { current: ClientNode | null } = { current: null };
function bootClient() {
  const html = navigationDocument({
    cspSource: "vscode-resource:",
    nonce: "n",
    iconsHref: "https://icons/codicon.css",
    section: "pages",
    treeHtml: "",
  });
  const script = /<script nonce="n">([\s\S]*)<\/script>/.exec(html)?.[1];
  if (!script) throw new Error("missing navigation script");
  clientFocus.current = null;
  const posts: unknown[] = [];
  const messages: Array<(event: { data: unknown }) => void> = [];
  class Element extends ClientNode {}
  class HTMLElement extends Element {}
  const segments = new HTMLElement("segments");
  const tree = new HTMLElement("tree");
  const outside = new HTMLElement("outside");
  const tabs: Record<string, HTMLElement> = {};
  for (const section of ["pages", "flows"]) {
    const tab = new HTMLElement();
    tab.setAttribute("data-section", section);
    tab.setAttribute("aria-selected", section === "pages" ? "true" : "false");
    tab.tabIndex = section === "pages" ? 0 : -1;
    segments.append(tab);
    tabs[section] = tab;
  }
  vm.runInNewContext(
    script,
    {
      document: {
        getElementById: (id: string) =>
          id === "segments" ? segments : id === "tree" ? tree : null,
        get activeElement() {
          return clientFocus.current;
        },
        hasFocus: () => true,
      },
      window: {
        addEventListener: (
          type: string,
          listener: (event: { data: unknown }) => void,
        ) => {
          if (type === "message") messages.push(listener);
        },
      },
      acquireVsCodeApi: () => ({
        postMessage: (message: unknown) => posts.push(message),
      }),
      Element,
      HTMLElement,
    },
    { filename: "navigation.js" },
  );
  return {
    posts,
    tabs,
    tree,
    outside,
    active: () => clientFocus.current,
    paint(section: string) {
      for (const listener of messages)
        listener({ data: { type: "render", section, html: "" } });
    },
    key(key: string) {
      const event = { key, preventDefault() {} };
      for (const listener of segments.listeners.keydown ?? []) listener(event);
    },
  };
}
describe("navigation view", () => {
  it("registers one shared panel and keeps every section available", () => {
    const { tree } = createTree();
    expect([...mocks.providers.keys()]).toEqual(["wintestkit.navigation"]);
    expect(mocks.providers.get("wintestkit.navigation")).toBe(tree);
    expect(tree.getChildren().map((node) => node.label)).toEqual(["Main"]);
    expect(tree.getChildren(undefined, "flows")[0].kind).toBe("flow");
  });
  it("opens a flow at its definition", async () => {
    const { tree } = createTree();
    const flow = tree.getChildren(undefined, "flows")[0];
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
  });
  it("colors check status icons with the testing theme tokens", () => {
    const { tree, checks } = createTree();
    checks.results.set("Main.username", {
      status: "ambiguous",
      durationMs: 1,
      qualname: "Main.username",
    });
    expect(
      tree.getTreeItem({
        id: "element",
        label: "username",
        description: "Edit",
        kind: "element",
        icon: "symbol-field",
        children: [],
        elementId: "Main.username",
      }).iconPath,
    ).toMatchObject({
      id: "warning",
      color: { id: "list.warningForeground" },
    });
  });
  it("shows tile-themed Page Tree and Flows tabs and restores the last tab", () => {
    const global = memoryState({ "wintestkit.navigation.section": "flows" });
    const { tree } = createTree(hostFor(global));
    resolve(tree);
    expect(mocks.html).toContain('role="tablist"');
    expect(mocks.html).toContain(">Page Tree</span></button>");
    expect(mocks.html).toContain(">Flows</span></button>");
    expect(mocks.html).toContain(
      'codicon-list-tree tab-icon" aria-hidden="true"',
    );
    expect(mocks.html).toContain(
      'codicon-run-all tab-icon" aria-hidden="true"',
    );
    expect(mocks.html).toContain("min-height: 56px");
    expect(mocks.html).toContain(
      "background: var(--vscode-editor-background, #fff)",
    );
    expect(mocks.html).toContain("border-radius: 5px");
    expect(mocks.html).not.toContain(">Tests</button>");
    expect(mocks.html).toContain('data-section="flows" aria-selected="true"');
    expect(mocks.html).not.toContain("executeCommand");
    mocks.listener?.({ type: "select", section: "flows" });
    expect(global.get("wintestkit.navigation.section")).toBe("flows");
    expect(mocks.posted.at(-1)).toMatchObject({
      type: "render",
      section: "flows",
    });
    expect(mocks.posted.at(-1)).not.toHaveProperty("reveal");
    const restored = createTree(hostFor(global));
    resolve(restored.tree);
    expect(mocks.html).toContain('data-section="flows" aria-selected="true"');
  });
  it("falls back to Page Tree when the removed Tests tab was last selected", () => {
    const global = memoryState({ "wintestkit.navigation.section": "tests" });
    resolve(createTree(hostFor(global)).tree);
    expect(mocks.html).toContain('data-section="pages" aria-selected="true"');
  });
  it("routes rendered context-menu arguments into check and open", async () => {
    const element = {
      id: "Main.username",
      name: "username",
      qualname: "Main.username",
      kind: "element" as const,
      range,
      nameRange: range,
      locator: { name: "username" },
      dynamic: false,
    };
    result.pages[0].elements.push(element);
    try {
      const { tree } = createTree(hostFor());
      resolve(tree);
      const page = tree.getChildren()[0];
      mocks.listener?.({ type: "toggle", id: page.id });
      expect(mocks.posted.at(-1)).not.toHaveProperty("reveal");
      const openHtml = (mocks.posted.at(-1) as { html: string }).html;
      const pageContext = contextArguments(openHtml).find(
        (entry) => entry.webviewSection === "page",
      );
      const elementContext = contextArguments(openHtml).find(
        (entry) => entry.webviewSection === "element",
      );
      expect(pageContext).toEqual({
        webviewSection: "page",
        preventDefaultContextMenuItems: true,
        file: "/project/pages/main.py",
        page: "Main",
      });
      expect(elementContext).toEqual({
        webviewSection: "element",
        preventDefaultContextMenuItems: true,
        file: "/project/pages/main.py",
        qualname: "Main.username",
      });
      mocks.listener?.({
        type: "action",
        action: "check",
        id: page.children[0].id,
      });
      expect(mocks.execute).toHaveBeenCalledWith("wintestkit.checkElement", {
        file: elementContext?.file,
        qualname: elementContext?.qualname,
      });
      mocks.listener?.({ type: "action", action: "checkPage", id: page.id });
      expect(mocks.execute).toHaveBeenCalledWith("wintestkit.checkPage", {
        file: pageContext?.file,
        page: pageContext?.page,
      });
      mocks.execute.mockClear();
      mocks.listener?.({ type: "action", action: "highlight", id: page.id });
      expect(mocks.execute).not.toHaveBeenCalled();
      mocks.listener?.({ type: "open", id: page.id });
      expect(mocks.show).toHaveBeenCalledWith(
        { fsPath: pageContext?.file },
        expect.objectContaining({
          selection: expect.objectContaining({
            startLine: 2,
            startCharacter: 4,
          }),
        }),
      );
    } finally {
      result.pages[0].elements.pop();
    }
  });
  it("moves the keyboard focus and opens the focused definition", () => {
    const { tree } = createTree(hostFor());
    resolve(tree);
    mocks.listener?.({ type: "key", key: "ArrowDown" });
    expect(mocks.posted.at(-1)).toMatchObject({ type: "render", reveal: true });
    mocks.listener?.({ type: "key", key: "Enter" });
    expect(mocks.posted.at(-1)).toMatchObject({ type: "render", reveal: true });
    expect(mocks.show).toHaveBeenCalledWith(
      { fsPath: "/project/pages/main.py" },
      expect.objectContaining({
        selection: expect.objectContaining({ startLine: 2, startCharacter: 4 }),
      }),
    );
  });
  it("moves segment focus onto the newly selected tab and leaves focus outside it", () => {
    const client = bootClient();
    expect(client.posts[0]).toEqual({ type: "ready" });
    client.tabs.pages.focus();
    client.key("ArrowRight");
    expect(client.posts.at(-1)).toEqual({
      type: "segmentKey",
      key: "ArrowRight",
    });
    expect(client.active()).toBe(client.tabs.pages);
    client.paint("flows");
    expect(client.active()).toBe(client.tabs.flows);
    expect(client.tabs.flows.tabIndex).toBe(0);
    expect(client.tabs.pages.tabIndex).toBe(-1);
    expect(client.tabs.flows.getAttribute("aria-selected")).toBe("true");
    client.outside.focus();
    client.paint("pages");
    expect(client.active()).toBe(client.outside);
    expect(client.tabs.pages.getAttribute("aria-selected")).toBe("true");
    client.tree.focus();
    client.paint("pages");
    expect(client.active()).toBe(client.tree);
    expect(client.tabs.pages.getAttribute("aria-selected")).toBe("true");
  });
  it("offers Run only on runnable flows and sends the flow to the runner", async () => {
    const { tree } = createTree(hostFor());
    resolve(tree);
    mocks.listener?.({ type: "select", section: "flows" });
    const [runnable, other] = tree.getChildren(undefined, "flows");
    expect(actionsFor(runnable)).toEqual(["run"]);
    expect(actionsFor(other)).toEqual([]);
    mocks.listener?.({ type: "action", action: "run", id: runnable.id });
    await vi.waitFor(() =>
      expect(mocks.execute).toHaveBeenCalledWith("wintestkit.runFlow", {
        file: "/project/flows/navigation.py",
        name: "open_page",
      }),
    );
    mocks.execute.mockClear();
    mocks.listener?.({ type: "action", action: "run", id: other.id });
    expect(mocks.execute).not.toHaveBeenCalled();
  });
  it("shows a running spinner and the last result on a flow", () => {
    const { tree, flows } = createTree(hostFor());
    resolve(tree);
    mocks.listener?.({ type: "select", section: "flows" });
    const key = flowKey({
      file: "/project/flows/navigation.py",
      name: "open_page",
    });
    const html = () => (mocks.posted.at(-1) as { html: string }).html;
    const repaint = () =>
      mocks.listener?.({ type: "select", section: "flows" });
    flows.states.set(key, { status: "running" });
    repaint();
    expect(html()).toContain("codicon-loading codicon-modifier-spin");
    flows.states.set(key, { status: "failed", durationMs: 1, message: "boom" });
    repaint();
    expect(html()).toContain("codicon-error");
    expect(html()).toContain("testing-iconFailed");
  });
  it("reports open and action failures", async () => {
    const { tree } = createTree(hostFor());
    resolve(tree);
    const page = tree.getChildren()[0];
    mocks.listener?.({ type: "open", id: page.id });
    await vi.waitFor(() => expect(mocks.show).toHaveBeenCalled());
    expect(mocks.error).not.toHaveBeenCalled();
    mocks.show.mockRejectedValueOnce(new Error("Unable to read file"));
    mocks.listener?.({ type: "open", id: page.id });
    await vi.waitFor(() =>
      expect(mocks.error).toHaveBeenCalledWith("Unable to read file"),
    );
    mocks.error.mockClear();
    mocks.execute.mockRejectedValueOnce(new Error("Check failed"));
    mocks.listener?.({ type: "action", action: "checkPage", id: page.id });
    await vi.waitFor(() =>
      expect(mocks.error).toHaveBeenCalledWith("Check failed"),
    );
  });
});
