import vm from "node:vm";
import { afterEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { Projects } from "../../src/projects";
import type { Project } from "../../src/server/serverManager";
import type { DiscoveryStore } from "../../src/discovery/store";
import type { UnusedDefinitions } from "../../src/views/unusedDefinitions";
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
  activeEditor: undefined as { document: { uri: { fsPath: string } } } | undefined,
  activeEditorListener: undefined as ((editor: unknown) => void) | undefined,
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
    get activeTextEditor() { return mocks.activeEditor; },
    onDidChangeActiveTextEditor: (listener: (editor: unknown) => void) => {
      mocks.activeEditorListener = listener;
      return { dispose: vi.fn() };
    },
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
import { renderBody } from "../../src/views/navigationDocument";
import { sidebarDocument } from "../../src/views/sidebarDocument";

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
/** The sidebar page around the Pages & Flows part, as the extension builds it. */
function navigationDocument(options: {
  cspSource: string;
  nonce: string;
  iconsHref: string;
  section: "pages" | "flows";
  treeHtml: string;
}): string {
  return sidebarDocument({
    ...options,
    stylesHref: "https://styles/setup.css",
    scriptHref: "https://scripts/setup.js",
  });
}
const trees: ElementsTree[] = [];
function createTree(
  host?: {
    globalState: vscode.Memento;
    workspaceState: vscode.Memento;
    extensionUri: vscode.Uri;
  },
  options: { result?: DiscoveryResult; unused?: unknown } = {},
) {
  const subscribe = () => ({ dispose: vi.fn() });
  const projects = {
    all: [project],
    onDidChange: subscribe,
    projectFor: (uri: { fsPath: string }) =>
      uri.fsPath.startsWith("/other") ? { ...project, root: { fsPath: "/other" }, name: "other-project" } : project,
  };
  const discovery = {
    get: () => options.result ?? result,
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
    undefined,
    options.unused as UnusedDefinitions | undefined,
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
  mocks.activeEditor = undefined;
  mocks.activeEditorListener = undefined;
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
  const view = {
    description: "",
    webview,
    onDidDispose: () => ({ dispose: vi.fn() }),
    onDidChangeVisibility: () => ({ dispose: vi.fn() }),
    visible: true,
    show: () => undefined,
  };
  tree.attach(view as unknown as vscode.WebviewView);
  mocks.listener = (value) => tree.handleMessage(value);
  mocks.html = navigationDocument({
    cspSource: webview.cspSource,
    nonce: "n",
    iconsHref: webview.asWebviewUri({ fsPath: "C:/ext/media/codicons/codicon.css" }).toString(),
    ...tree.initial(),
  });
  return view;
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
class ToolNode extends ClientNode {
  hidden = false;
  disabled = false;
  title = "";
  className = "";
  textContent = "";
  parts: Record<string, ToolNode> = {};
  override querySelector(selector: string): ClientNode | null {
    return this.parts[selector] ?? null;
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
  const script = /<script nonce="n">([\s\S]*?)<\/script>/.exec(html)?.[1];
  if (!script) throw new Error("missing navigation script");
  clientFocus.current = null;
  const posts: unknown[] = [];
  const messages: Array<(event: { data: unknown }) => void> = [];
  class Element extends ClientNode {}
  class HTMLElement extends Element {}
  const segments = new HTMLElement("segments");
  const tree = new HTMLElement("tree");
  const outside = new HTMLElement("outside");
  const unusedTools = new ToolNode("unused-tools");
  const unusedScan = new ToolNode("unused-scan");
  const unusedToggle = new ToolNode("unused-toggle");
  const unusedCount = new ToolNode("unused-count");
  for (const tool of [unusedScan, unusedToggle])
    tool.parts = { ".codicon": new ToolNode(), ".tool-label": new ToolNode() };
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
          ({
            segments,
            tree,
            "unused-tools": unusedTools,
            "unused-scan": unusedScan,
            "unused-toggle": unusedToggle,
            "unused-count": unusedCount,
          } as Record<string, ClientNode>)[id] ?? null,
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
    unused: { tools: unusedTools, scan: unusedScan, toggle: unusedToggle, count: unusedCount },
    active: () => clientFocus.current,
    paint(section: string, unused?: unknown) {
      for (const listener of messages)
        listener({ data: { type: "render", section, html: "", unused } });
    },
    key(key: string) {
      const event = { key, preventDefault() {} };
      for (const listener of segments.listeners.keydown ?? []) listener(event);
    },
  };
}
describe("navigation view", () => {
  describe("unused definitions tools", () => {
    const element = (name: string, line: number) => ({
      id: "pages/main.py::Main." + name,
      name,
      qualname: "Main." + name,
      kind: "element" as const,
      range,
      nameRange: { ...range, start: { line, character: 4 } },
      locator: { controlType: "Button", name },
      dynamic: false,
    });
    const PAGE_ID = "/project|pages/main.py::Main";
    const withElements: DiscoveryResult = {
      ...result,
      pages: [
        { ...result.pages[0], elements: [element("used", 3), element("spare", 4), element("lonely", 5)] },
      ],
    };
    function unusedStub(initial: { scanned: boolean; ids?: string[]; scanning?: boolean }) {
      const state = { ...initial, ids: new Set(initial.ids ?? []) };
      return {
        state,
        scan: vi.fn(() => Promise.resolve({ cancelled: false, capped: false, unavailable: 0 })),
        has: (_project: unknown, id: string) => state.ids.has(id),
        hasResult: () => state.scanned,
        get hasResults() { return state.scanned; },
        get scanning() { return state.scanning === true; },
        get count() { return state.ids.size; },
        onDidChange: () => ({ dispose: vi.fn() }),
      };
    }
    function render(stub: ReturnType<typeof unusedStub>, section?: string) {
      const { tree } = createTree(hostFor(), { result: withElements, unused: stub });
      resolve(tree);
      mocks.listener?.({ type: "toggle", id: PAGE_ID });
      if (section) mocks.listener?.({ type: "select", section });
      mocks.listener?.({ type: "ready" });
      return mocks.posted.at(-1) as { html: string; unused?: Record<string, unknown> };
    }
    it("marks definitions with no references and reports the scan state", () => {
      const stub = unusedStub({ scanned: true, ids: ["pages/main.py::Main.spare", "pages/main.py::Main.lonely"] });
      const payload = render(stub);
      expect(payload.unused).toEqual({ scanning: false, scanned: true, count: 2, filtering: false });
      expect(payload.html).toContain("spare");
      expect(payload.html.match(/possibly unused/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
      expect(payload.html).toContain("used");
    });
    it("shows only unused definitions after the toggle and keeps the rest hidden", () => {
      const stub = unusedStub({ scanned: true, ids: ["pages/main.py::Main.spare"] });
      const { tree } = createTree(hostFor(), { result: withElements, unused: stub });
      resolve(tree);
      mocks.listener?.({ type: "toggle", id: PAGE_ID });
      mocks.listener?.({ type: "unusedToggle" });
      const payload = mocks.posted.at(-1) as { html: string; unused?: Record<string, unknown> };
      expect(payload.unused?.filtering).toBe(true);
      expect(payload.html).toContain("spare");
      expect(payload.html).not.toContain(">lonely<");
      expect(payload.html).not.toContain(">used<");
      mocks.listener?.({ type: "unusedToggle" });
      const restored = mocks.posted.at(-1) as { html: string };
      expect(restored.html).toContain(">lonely<");
    });
    it("explains an empty filtered tree", () => {
      const stub = unusedStub({ scanned: true, ids: [] });
      const { tree } = createTree(hostFor(), { result: withElements, unused: stub });
      resolve(tree);
      mocks.listener?.({ type: "unusedToggle" });
      const payload = mocks.posted.at(-1) as { html: string };
      expect(payload.html).toContain("No unused definitions found");
    });
    it("ignores the toggle until a scan has produced results and does not start a second scan", () => {
      const stub = unusedStub({ scanned: false });
      const { tree } = createTree(hostFor(), { result: withElements, unused: stub });
      resolve(tree);
      mocks.listener?.({ type: "unusedToggle" });
      mocks.listener?.({ type: "ready" });
      expect((mocks.posted.at(-1) as { unused?: { filtering: boolean } }).unused?.filtering).toBe(false);
      mocks.listener?.({ type: "unusedScan" });
      expect(stub.scan).toHaveBeenCalledOnce();
      stub.state.scanning = true;
      mocks.listener?.({ type: "unusedScan" });
      expect(stub.scan).toHaveBeenCalledOnce();
    });
    it("only offers the tools on the Page Tree", () => {
      const payload = render(unusedStub({ scanned: true }), "flows");
      expect(payload.unused).toBeUndefined();
    });
    it("paints the toolbar from the scan state and posts scan and toggle requests", () => {
      const client = bootClient();
      const { tools, scan, toggle, count } = client.unused;
      expect(navigationDocument({ cspSource: "x", nonce: "n", iconsHref: "i", section: "pages", treeHtml: "" }))
        .toContain('id="unused-tools" role="toolbar"');
      client.paint("pages", { scanning: false, scanned: false, count: 0, filtering: false });
      expect(tools.hidden).toBe(false);
      expect(scan.parts[".tool-label"].textContent).toBe("Find unused definitions");
      expect(toggle.disabled).toBe(true);
      expect(count.hidden).toBe(true);
      client.paint("pages", { scanning: true, scanned: false, count: 0, filtering: false });
      expect(scan.disabled).toBe(true);
      expect(scan.parts[".codicon"].className).toContain("codicon-modifier-spin");
      client.paint("pages", { scanning: false, scanned: true, count: 3, filtering: true });
      expect(scan.parts[".tool-label"].textContent).toBe("Rescan");
      expect(toggle.disabled).toBe(false);
      expect(toggle.getAttribute("aria-pressed")).toBe("true");
      expect(count.hidden).toBe(false);
      expect(count.textContent).toBe("3");
      scan.listeners.click?.forEach((listener) => listener({ key: "", preventDefault() {} }));
      toggle.listeners.click?.forEach((listener) => listener({ key: "", preventDefault() {} }));
      expect(client.posts).toEqual(
        expect.arrayContaining([{ type: "unusedScan" }, { type: "unusedToggle" }]),
      );
      client.paint("flows", { scanning: false, scanned: true, count: 3, filtering: false });
      expect(tools.hidden).toBe(true);
    });
  });
  it("has no initialization or Getting Started button: the guided setup in Test Target does that", () => {
    const body = renderBody({ nodes: [], expanded: new Set(), welcome: "Set up WinTestKit" });
    expect(body).toContain("Set up WinTestKit");
    expect(body).not.toContain("data-initialize");
    expect(body).not.toContain("data-getting-started");
    expect(body).not.toContain("<button");
  });
  it("dulls itself when the guided setup is showing", () => {
    const { tree } = createTree(hostFor());
    resolve(tree);
    const document = (mocks.html ?? "") as string;
    expect(document).toContain('message.type === "tour"');
    expect(document).toContain("tour-dim");
  });
  it("leaves the view description empty", () => {
    const { tree } = createTree(hostFor());
    const view = resolve(tree);
    expect(view.description).toBe("");
    mocks.activeEditor = { document: { uri: { fsPath: "/other/tests/test.py" } } };
    mocks.activeEditorListener?.(mocks.activeEditor);
    expect(view.description).toBe("");
  });
  it("leaves the view to the sidebar and keeps every section available", () => {
    const { tree } = createTree();
    expect(mocks.providers.size).toBe(0);
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
  it("shows a saved element preview while retaining source navigation", async () => {
    const { tree } = createTree();
    const element: ElementNode = {
      id: "pages/main.py::Main.username",
      elementId: "pages/main.py::Main.username",
      label: "username",
      qualname: "Main.username",
      file: "/project/pages/main.py",
      range,
      description: "Edit",
      kind: "element",
      icon: "symbol-field",
      children: [],
    };
    await mocks.commands.get("wintestkit.elements.goTo")!(element);
    expect(mocks.show).toHaveBeenCalledWith(
      { fsPath: element.file },
      { selection: expect.objectContaining({ startLine: 2, startCharacter: 4 }) },
    );
    expect(mocks.execute).toHaveBeenCalledWith("wintestkit.spy.showDefinition", {
      id: element.elementId,
      qualname: element.qualname,
      projectRoot: "/project",
    });
    tree.dispose();
  });
  it("does not request element previews for saved window definitions", async () => {
    createTree();
    const window: ElementNode = {
      id: "pages/main.py::Main.window",
      elementId: "pages/main.py::Main.window",
      label: "window",
      qualname: "Main.window",
      file: "/project/pages/main.py",
      range,
      description: "Window",
      kind: "window",
      icon: "window",
      children: [],
    };
    await mocks.commands.get("wintestkit.elements.goTo")!(window);
    expect(mocks.execute).not.toHaveBeenCalledWith(
      "wintestkit.spy.showDefinition",
      expect.anything(),
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
  it("shows compact segmented Page Tree and Flows tabs and restores the last tab", () => {
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
    expect(mocks.html).toContain("min-height: 30px");
    expect(mocks.html).not.toContain("min-height: 56px");
    expect(mocks.html).toContain(
      "background: var(--vscode-list-inactiveSelectionBackground)",
    );
    expect(mocks.html).toContain("border-radius: 4px");
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
