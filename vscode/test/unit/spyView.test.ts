import { readFileSync } from "node:fs";
import * as path from "node:path";
import type * as vscode from "vscode";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Projects } from "../../src/projects";
import type { ServerManager } from "../../src/server/serverManager";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  notifications: new Map<string, (value: unknown) => void>(),
  clipboard: vi.fn(),
  command: vi.fn(),
  information: vi.fn(() => Promise.resolve(undefined)),
  icons: vi.fn(() => Promise.resolve({} as Record<string, string>)),
  activeEditor: undefined as
    | { document: { uri: { fsPath: string; toString(): string } } }
    | undefined,
  editorListeners: [] as Array<() => void>,
}));
vi.mock("../../src/spy/appIcons", () => ({
  readApplicationIcons: mocks.icons,
}));
vi.mock("vscode", () => ({
  Uri: {
    joinPath: (uri: { fsPath: string }, ...parts: string[]) => ({
      fsPath: [uri.fsPath, ...parts].join("/"),
      toString() {
        return this.fsPath;
      },
    }),
  },
  window: {
    get activeTextEditor() {
      return mocks.activeEditor;
    },
    registerWebviewViewProvider: () => ({ dispose() {} }),
    onDidChangeActiveTextEditor: (callback: () => void) => {
      mocks.editorListeners.push(callback);
      return {
        dispose() {
          const index = mocks.editorListeners.indexOf(callback);
          if (index >= 0) mocks.editorListeners.splice(index, 1);
        },
      };
    },
    showInformationMessage: mocks.information,
  },
  commands: {
    registerCommand: () => ({ dispose() {} }),
    executeCommand: mocks.command,
  },
  env: { clipboard: { writeText: mocks.clipboard } },
}));
import { SpyView } from "../../src/spy/spyView";
import { RpcError } from "../../src/server/jsonrpc";

describe("Spy view bridge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.notifications.clear();
    mocks.activeEditor = undefined;
    mocks.editorListeners.splice(0, mocks.editorListeners.length);
  });
  const create = async (connect?: () => Promise<unknown>) => {
    const project = {
      root: { fsPath: "C:/demo", toString: () => "demo" },
      name: "demo",
    };
    const known = [project];
    const notificationDisposals: string[] = [];
    const client = {
      request: mocks.request,
      onNotification: (name: string, callback: (value: unknown) => void) => {
        mocks.notifications.set(name, callback);
        return {
          dispose: () => {
            notificationDisposals.push(name);
            mocks.notifications.delete(name);
          },
        };
      },
    };
    let serverChanged = () => {};
    let serverState = "ready";
    const provider = new SpyView(
      {
        all: known,
        projectFor: (uri: { toString(): string }) =>
          known.find((item) => item.root.toString() === uri.toString()),
        onDidChange: () => ({ dispose() {} }),
      } as unknown as Projects,
      {
        get: connect || (() => Promise.resolve({ client })),
        state: () => serverState,
        onDidChange: (callback: (value: typeof project) => void) => {
          serverChanged = () => callback(project);
          return { dispose() {} };
        },
      } as unknown as ServerManager,
      { fsPath: path.resolve(".") } as vscode.Uri,
      { error: vi.fn() } as unknown as vscode.LogOutputChannel,
    );
    let receive: (value: unknown) => void = () => {};
    let visibility: () => void = () => {};
    const sent: { type: string; [key: string]: unknown }[] = [];
    const webview = {
      html: "",
      options: {},
      cspSource: "vscode-resource:",
      asWebviewUri: (uri: vscode.Uri) => uri,
      postMessage: (message: { type: string }) => {
        sent.push(message);
        return Promise.resolve(true);
      },
      onDidReceiveMessage: (callback: (value: unknown) => void) => {
        receive = callback;
        return { dispose() {} };
      },
    };
    const view = {
      webview,
      visible: true,
      onDidChangeVisibility: (callback: () => void) => {
        visibility = callback;
        return { dispose() {} };
      },
      onDidDispose: () => ({ dispose() {} }),
    };
    await provider.resolveWebviewView(view as unknown as vscode.WebviewView);
    return {
      provider,
      sent,
      receive: (value: unknown) => receive(value),
      view,
      visibility: () => visibility(),
      notificationDisposals,
      serverChanged: (state: string) => {
        serverState = state;
        serverChanged();
      },
      activate: (next: typeof project) => {
        known.push(next);
        mocks.activeEditor = { document: { uri: next.root } };
        for (const listener of [...mocks.editorListeners]) listener();
      },
    };
  };
  it("refreshes after app actions only for the visible matching project", async () => {
    const fixture = await create();
    const project = {
      root: { fsPath: "C:/demo", toString: () => "demo" }, name: "demo",
    } as import("../../src/server/serverManager").Project;
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(method === "app.status" ? { running: true } : []),
    );
    await fixture.provider.refreshForProject({
      ...project, root: { toString: () => "other" } as vscode.Uri,
    });
    expect(mocks.request).not.toHaveBeenCalled();
    fixture.view.visible = false;
    await fixture.provider.refreshForProject(project);
    expect(mocks.request).not.toHaveBeenCalled();
    fixture.view.visible = true;
    await fixture.provider.refreshForProject(project);
    expect(mocks.request).toHaveBeenCalledWith("app.status");
    expect(fixture.sent).toContainEqual({ type: "roots", nodes: [] });
    fixture.provider.dispose();
  });
  it("places the other-apps toggle after collapse and keeps the tree guides on the last child", async () => {
    const fixture = await create();
    const html = fixture.view.webview.html;
    expect(html).toMatch(/id="pick"[\s\S]*id="refresh"[\s\S]*id="collapse"/);
    expect(html).toMatch(
      /id="collapse"[\s\S]*?<\/button>\s*<button[\s\S]*?id="other-apps"/,
    );
    expect(html).toMatch(/id="other-apps"[\s\S]*?\bhidden\b/);
    expect(html).toContain('<span id="other-apps-label">Show Other Apps</span>');
    expect(readFileSync("media/spy/spy.css", "utf8")).toMatch(
      /#other-apps\s*\{[^}]*margin-left:\s*auto/,
    );
    const css = readFileSync("media/spy/spy.css", "utf8");
    expect(css).not.toMatch(/#tree ul\s*\{[^}]*border-left/);
    expect(css).toMatch(
      /#tree ul > li:last-child::after,\s*#tree ul > li\.last-branch::after\s*\{[^}]*height:\s*14px/,
    );
    const script = readFileSync("media/spy/spy.js", "utf8");
    expect(script).toContain("last-branch");
    expect(script).toContain('post("showOtherApps"');
    expect(script).toContain("vscode.getState()");
    fixture.provider.dispose();
  });
  it("scopes roots to the current app until other apps are requested", async () => {
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(
        method === "app.status" ? { running: true, pids: [7] } : [],
      ),
    );
    const fixture = await create();
    const rootCalls = () =>
      mocks.request.mock.calls.filter((call) => call[0] === "inspect.roots");
    fixture.receive({ type: "ready", showOtherApps: false });
    await vi.waitFor(() => expect(rootCalls()).toEqual([["inspect.roots"]]));
    expect(fixture.sent).toContainEqual(
      expect.objectContaining({
        type: "state",
        appRunning: true,
        showOtherApps: false,
      }),
    );
    mocks.request.mockClear();
    fixture.receive({ type: "showOtherApps", enabled: true });
    await vi.waitFor(() =>
      expect(rootCalls()).toEqual([
        ["inspect.roots", { includeOtherApps: true }],
      ]),
    );
    expect(fixture.sent).toContainEqual(
      expect.objectContaining({
        type: "state",
        appRunning: true,
        showOtherApps: true,
      }),
    );
    mocks.request.mockClear();
    fixture.receive({ type: "refresh" });
    await vi.waitFor(() =>
      expect(rootCalls()).toEqual([
        ["inspect.roots", { includeOtherApps: true }],
      ]),
    );
    mocks.request.mockClear();
    fixture.receive({ type: "showOtherApps", enabled: false });
    await vi.waitFor(() => expect(rootCalls()).toEqual([["inspect.roots"]]));
    mocks.request.mockClear();
    fixture.receive({ type: "showOtherApps", enabled: "yes" });
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(mocks.request).not.toHaveBeenCalled();
    fixture.provider.dispose();
  });
  it("drops a superseded scope's roots and selection", async () => {
    let finishFirst: (nodes: unknown[]) => void = () => {};
    let finishSecond: (nodes: unknown[]) => void = () => {};
    let finishSelect: (value: unknown) => void = () => {};
    let rootCalls = 0;
    mocks.request.mockImplementation(
      (method: string, params?: { includeOtherApps?: boolean }) => {
        if (method === "app.status")
          return Promise.resolve({ running: true, pids: [7] });
        if (method === "inspect.roots") {
          rootCalls += 1;
          return new Promise((resolve) => {
            if (params?.includeOtherApps) finishSecond = resolve;
            else finishFirst = resolve;
          });
        }
        if (method === "inspect.properties")
          return new Promise((resolve) => {
            finishSelect = resolve;
          });
        if (method === "suggest.locator")
          return Promise.resolve({ helpers: [], code: "Element()" });
        return Promise.resolve(undefined);
      },
    );
    const fixture = await create();
    fixture.receive({ type: "ready", showOtherApps: false });
    await vi.waitFor(() => expect(rootCalls).toBe(1));
    fixture.receive({ type: "select", nodeId: "kept" });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.properties", {
        nodeId: "kept",
      }),
    );
    fixture.receive({ type: "showOtherApps", enabled: true });
    await vi.waitFor(() => expect(rootCalls).toBe(2));
    finishFirst([{ nodeId: "scoped" }]);
    finishSelect({ info: { name: "Kept" }, properties: {}, ancestors: [] });
    finishSecond([{ nodeId: "other" }]);
    await vi.waitFor(() =>
      expect(fixture.sent.filter((message) => message.type === "roots")).toEqual(
        [{ type: "roots", nodes: [{ nodeId: "other" }] }],
      ),
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fixture.sent.filter((message) => message.type === "roots")).toEqual([
      { type: "roots", nodes: [{ nodeId: "other" }] },
    ]);
    expect(fixture.sent.some((message) => message.type === "selected")).toBe(
      false,
    );
    fixture.provider.dispose();
  });
  it("keeps the other-apps scope when revealing a picked control", async () => {
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(
        method === "app.status"
          ? { running: true }
          : method === "inspect.properties"
            ? {
                info: { controlType: "Button", name: "Save" },
                properties: {},
                ancestors: [],
              }
            : method === "inspect.roots"
              ? []
              : undefined,
      ),
    );
    const fixture = await create();
    fixture.receive({ type: "showOtherApps", enabled: true });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.roots", {
        includeOtherApps: true,
      }),
    );
    mocks.request.mockClear();
    fixture.receive({ type: "pick" });
    await vi.waitFor(() =>
      expect(mocks.notifications.has("spy.picked")).toBe(true),
    );
    mocks.notifications.get("spy.picked")?.({
      node: { nodeId: "picked", info: { controlType: "Button", name: "Save" } },
      suggestion: { helpers: [], code: "Element()" },
    });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.roots", {
        includeOtherApps: true,
      }),
    );
    fixture.provider.dispose();
  });
  it("drops a picked reveal superseded by a scope change", async () => {
    let finishReveal: (nodes: unknown[]) => void = () => {};
    let finishRefresh: (nodes: unknown[]) => void = () => {};
    mocks.request.mockImplementation(
      (method: string, params?: { includeOtherApps?: boolean }) => {
        if (method === "app.status")
          return Promise.resolve({ running: true, pids: [7] });
        if (method === "inspect.properties")
          return Promise.resolve({
            info: { controlType: "Button", name: "Save" },
            properties: {},
            ancestors: [],
          });
        if (method === "inspect.roots")
          return new Promise((resolve) => {
            if (params?.includeOtherApps) finishRefresh = resolve;
            else finishReveal = resolve;
          });
        return Promise.resolve(undefined);
      },
    );
    const fixture = await create();
    fixture.receive({ type: "pick" });
    await vi.waitFor(() =>
      expect(mocks.notifications.has("spy.picked")).toBe(true),
    );
    mocks.notifications.get("spy.picked")?.({
      node: { nodeId: "picked", info: { controlType: "Button", name: "Save" } },
      suggestion: { helpers: [], code: "Element()" },
    });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.roots"),
    );
    fixture.receive({ type: "showOtherApps", enabled: true });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.roots", {
        includeOtherApps: true,
      }),
    );
    finishRefresh([{ nodeId: "other" }]);
    finishReveal([{ nodeId: "scoped" }]);
    await vi.waitFor(() =>
      expect(fixture.sent.filter((message) => message.type === "roots")).toEqual(
        [{ type: "roots", nodes: [{ nodeId: "other" }] }],
      ),
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fixture.sent.filter((message) => message.type === "roots")).toEqual([
      { type: "roots", nodes: [{ nodeId: "other" }] },
    ]);
    expect(
      fixture.sent.some(
        (message) => message.type === "picked" || message.type === "selected",
      ),
    ).toBe(false);
    fixture.provider.dispose();
  });
  it("reloads the tree when the server becomes ready after a failed startup", async () => {
    let rejectConnection: (error: Error) => void = () => {};
    const connect = vi.fn().mockImplementationOnce(
      () =>
        new Promise((resolve, reject) => {
          rejectConnection = reject;
        }),
    );
    const fixture = await create(connect);
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(method === "app.status" ? { running: true } : []),
    );
    fixture.receive({ type: "ready" });
    await vi.waitFor(() => expect(connect).toHaveBeenCalledOnce());
    fixture.serverChanged("error");
    fixture.serverChanged("ready");
    connect.mockResolvedValue({
      client: {
        request: mocks.request,
        onNotification: () => ({ dispose() {} }),
      },
    });
    rejectConnection(new Error("server stopped"));
    await vi.waitFor(() =>
      expect(fixture.sent).toContainEqual({ type: "roots", nodes: [] }),
    );
    expect(connect).toHaveBeenCalledTimes(2);
    fixture.provider.dispose();
  });
  it("uses a restrictive CSP, validates messages and copies text", async () => {
    const fixture = await create();
    expect(fixture.view.webview.html).toContain("default-src 'none'");
    expect(fixture.view.webview.html).toContain("img-src data:");
    expect(fixture.view.webview.html).not.toContain('id="loading"');
    expect(fixture.view.webview.html).toContain('id="tree-loading"');
    expect(fixture.view.webview.html).toContain('id="details-loading"');
    expect(fixture.view.webview.html).toContain('id="details-empty"');
    expect(fixture.view.webview.html).toMatch(
      /script-src 'nonce-[a-f0-9]{48}'/,
    );
    expect(fixture.view.webview.html).not.toContain("{{");
    fixture.receive({ type: "execute", command: "unsafe" });
    expect(mocks.request).not.toHaveBeenCalled();
    fixture.receive({ type: "copy", text: "ok = Element()" });
    await vi.waitFor(() =>
      expect(mocks.clipboard).toHaveBeenCalledWith("ok = Element()"),
    );
    fixture.provider.dispose();
  });
  it("loads executable icons after roots and reports each refresh phase", async () => {
    const roots = [{ nodeId: "root", info: { processId: 123 } }];
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(method === "app.status" ? { running: true } : roots),
    );
    mocks.icons.mockResolvedValueOnce({ "123": "data:image/png;base64,abcd" });
    const fixture = await create();
    await fixture.provider.refresh();
    expect(mocks.icons).toHaveBeenCalledWith([123]);
    expect(fixture.sent).toContainEqual({
      type: "rootIcons",
      icons: { "123": "data:image/png;base64,abcd" },
    });
    expect(
      fixture.sent.findIndex((message) => message.type === "roots"),
    ).toBeLessThan(
      fixture.sent.findIndex((message) => message.type === "rootIcons"),
    );
    const progress = fixture.sent.filter(
      (message) => message.type === "progress",
    );
    expect(
      progress.some((message) => message.phase === "Loading application icons"),
    ).toBe(true);
    expect(progress.at(-1)).toMatchObject({
      done: true,
      completed: 4,
      total: 4,
    });
    expect(new Set(progress.map((message) => message.taskId)).size).toBe(1);
    fixture.provider.dispose();
  });
  it("cleans up loading progress when a request fails", async () => {
    mocks.request.mockRejectedValue(new Error("cannot connect"));
    const fixture = await create();
    fixture.receive({ type: "refresh" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "error")).toBe(
        true,
      ),
    );
    expect(
      fixture.sent.filter((message) => message.type === "progress").at(-1),
    ).toMatchObject({ done: true, failed: true, target: "tree" });
    fixture.provider.dispose();
  });
  it("does not resurrect failed progress when a parallel inspection phase finishes", async () => {
    let finishHighlight: (value: unknown) => void = () => {};
    mocks.request.mockImplementation((method: string) => {
      if (method === "inspect.properties")
        return Promise.reject(new Error("element gone"));
      if (method === "inspect.highlight")
        return new Promise((resolve) => {
          finishHighlight = resolve;
        });
      return Promise.resolve({});
    });
    const fixture = await create();
    fixture.receive({ type: "select", nodeId: "control" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "error")).toBe(
        true,
      ),
    );
    const count = fixture.sent.filter(
      (message) => message.type === "progress",
    ).length;
    finishHighlight(undefined);
    await new Promise((resolve) => setTimeout(resolve, 10));
    const progress = fixture.sent.filter(
      (message) => message.type === "progress",
    );
    expect(progress).toHaveLength(count);
    expect(progress.at(-1)).toMatchObject({
      done: true,
      failed: true,
      target: "details",
    });
    fixture.provider.dispose();
  });
  it("discards icon results from an obsolete refresh", async () => {
    let finishIcons: (value: Record<string, string>) => void = () => {};
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(
        method === "app.status"
          ? { running: true }
          : [{ nodeId: "root", info: { processId: 123 } }],
      ),
    );
    mocks.icons.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishIcons = resolve;
        }),
    );
    mocks.icons.mockResolvedValueOnce({ "123": "data:image/png;base64,bmV3" });
    const fixture = await create();
    const first = fixture.provider.refresh();
    await vi.waitFor(() => expect(mocks.icons).toHaveBeenCalledTimes(1));
    await fixture.provider.refresh();
    finishIcons({ "123": "data:image/png;base64,b2xk" });
    await first;
    expect(
      fixture.sent.filter((message) => message.type === "rootIcons"),
    ).toEqual([
      { type: "rootIcons", icons: { "123": "data:image/png;base64,bmV3" } },
    ]);
    fixture.provider.dispose();
  });
  it("reports per-node expansion progress and completes after children arrive", async () => {
    mocks.request.mockResolvedValue([]);
    const fixture = await create();
    fixture.receive({ type: "expand", nodeId: "branch" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "children")).toBe(
        true,
      ),
    );
    const progress = fixture.sent.filter(
      (message) => message.type === "progress",
    );
    expect(progress.at(-1)).toMatchObject({
      nodeId: "branch",
      target: "tree",
      failed: false,
      completed: 2,
      total: 2,
      done: true,
    });
    expect(
      progress.some((message) => message.phase === "Reading child controls"),
    ).toBe(true);
    fixture.provider.dispose();
  });
  it("shows basic properties before a slow locator is ready", async () => {
    let finishLocator: (value: unknown) => void = () => {};
    mocks.request.mockImplementation((method: string) => {
      if (method === "inspect.properties")
        return Promise.resolve({
          info: { name: "Save" },
          properties: {},
          ancestors: [],
        });
      if (method === "suggest.locator")
        return new Promise((resolve) => {
          finishLocator = resolve;
        });
      return Promise.resolve(undefined);
    });
    const fixture = await create();
    fixture.receive({ type: "select", nodeId: "control" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "selected")).toBe(
        true,
      ),
    );
    expect(mocks.request).toHaveBeenCalledWith("inspect.properties", {
      nodeId: "control",
    });
    expect(
      fixture.sent.find((message) => message.type === "selected"),
    ).not.toHaveProperty("suggestion");
    expect(fixture.sent.some((message) => message.type === "suggestion")).toBe(
      false,
    );
    finishLocator({ helpers: [], code: "Element()" });
    await vi.waitFor(() =>
      expect(
        fixture.sent.some((message) => message.type === "suggestion"),
      ).toBe(true),
    );
    fixture.provider.dispose();
  });
  it("requests ancestors only when revealing a picked control", async () => {
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(
        method === "inspect.properties"
          ? { info: {}, properties: {}, ancestors: [] }
          : method === "inspect.roots"
            ? []
            : undefined,
      ),
    );
    const fixture = await create();
    fixture.receive({ type: "pick" });
    await vi.waitFor(() =>
      expect(mocks.notifications.has("spy.picked")).toBe(true),
    );
    mocks.notifications.get("spy.picked")?.({
      node: { nodeId: "picked", info: { controlType: "Button", name: "Save" } },
      suggestion: { helpers: [], code: "Element()" },
    });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "selected")).toBe(
        true,
      ),
    );
    expect(mocks.request).toHaveBeenCalledWith("inspect.properties", {
      nodeId: "picked",
      includeAncestors: true,
    });
    fixture.provider.dispose();
  });
  it("reveals a picked control from fresh roots down through unloaded ancestors", async () => {
    const node = (nodeId: string) => ({
      nodeId,
      hasChildren: true,
      info: { name: nodeId, controlType: "Pane", processId: 123 },
    });
    const desktop = node("desktop");
    const root = node("app");
    const panel = node("panel");
    const picked = node("picked");
    mocks.request.mockImplementation(
      (method: string, params?: { nodeId: string }) => {
        if (method === "inspect.properties")
          return Promise.resolve({
            info: picked.info,
            properties: {},
            ancestors: [desktop, root, panel],
          });
        if (method === "inspect.roots") return Promise.resolve([root]);
        if (method === "inspect.children")
          return Promise.resolve(params?.nodeId === "app" ? [panel] : [picked]);
        return Promise.resolve(undefined);
      },
    );
    const fixture = await create();
    fixture.receive({ type: "pick" });
    await vi.waitFor(() =>
      expect(mocks.notifications.has("spy.picked")).toBe(true),
    );
    mocks.notifications.get("spy.picked")?.({
      node: picked,
      suggestion: { helpers: [], code: "Element()" },
    });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "selected")).toBe(
        true,
      ),
    );
    expect(
      fixture.sent.filter((message) =>
        ["roots", "children", "picked"].includes(message.type),
      ),
    ).toEqual([
      { type: "roots", nodes: [root] },
      { type: "children", nodeId: "app", nodes: [panel] },
      { type: "children", nodeId: "panel", nodes: [picked] },
      {
        type: "picked",
        node: picked,
        suggestion: { helpers: [], code: "Element()" },
        ancestors: [desktop, root, panel],
      },
    ]);
    expect(mocks.request).not.toHaveBeenCalledWith("inspect.children", {
      nodeId: "desktop",
    });
    expect(mocks.icons).toHaveBeenCalledWith([123]);
    fixture.provider.dispose();
  });
  it("loads full properties only for the explicit button request", async () => {
    mocks.request.mockResolvedValue({
      info: {},
      properties: { Name: "Save" },
      ancestors: [],
    });
    const fixture = await create();
    expect(mocks.request).not.toHaveBeenCalled();
    fixture.receive({ type: "loadProperties", nodeId: "control" });
    await vi.waitFor(() =>
      expect(
        fixture.sent.some((message) => message.type === "allProperties"),
      ).toBe(true),
    );
    expect(mocks.request).toHaveBeenCalledWith("inspect.properties", {
      nodeId: "control",
      full: true,
    });
    expect(
      fixture.sent.filter((message) => message.type === "propertiesLoading"),
    ).toEqual([
      { type: "propertiesLoading", nodeId: "control", loading: true },
      { type: "propertiesLoading", nodeId: "control", loading: false },
    ]);
    fixture.provider.dispose();
  });
  it("allows retrying a failed full-property request", async () => {
    mocks.request.mockRejectedValue(new Error("properties unavailable"));
    const fixture = await create();
    fixture.receive({ type: "loadProperties", nodeId: "control" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "error")).toBe(
        true,
      ),
    );
    expect(
      fixture.sent
        .filter((message) => message.type === "propertiesLoading")
        .at(-1),
    ).toMatchObject({ loading: false, nodeId: "control" });
    fixture.provider.dispose();
  });
  it("discards full properties after another object is selected", async () => {
    let finishProperties: (value: unknown) => void = () => {};
    mocks.request.mockImplementation(
      (method: string, params: { full?: boolean }) => {
        if (method === "inspect.properties" && params.full)
          return new Promise((resolve) => {
            finishProperties = resolve;
          });
        return Promise.resolve(
          method === "inspect.properties"
            ? { info: {}, properties: {}, ancestors: [] }
            : { helpers: [], code: "Element()" },
        );
      },
    );
    const fixture = await create();
    fixture.receive({ type: "loadProperties", nodeId: "old" });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.properties", {
        nodeId: "old",
        full: true,
      }),
    );
    fixture.receive({ type: "select", nodeId: "new" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "selected")).toBe(
        true,
      ),
    );
    finishProperties({ info: {}, properties: {}, ancestors: [] });
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(
      fixture.sent.some((message) => message.type === "allProperties"),
    ).toBe(false);
    fixture.provider.dispose();
  });
  it("scopes successful inspection progress to the selected-object pane", async () => {
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(
        method === "inspect.properties"
          ? { info: {}, properties: {} }
          : method === "suggest.locator"
            ? { helpers: [], code: "Element()" }
            : undefined,
      ),
    );
    const fixture = await create();
    fixture.receive({ type: "select", nodeId: "control" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "selected")).toBe(
        true,
      ),
    );
    const progress = fixture.sent.filter(
      (message) => message.type === "progress",
    );
    expect(progress.every((message) => message.target === "details")).toBe(
      true,
    );
    expect(progress.at(-1)).toMatchObject({
      nodeId: "control",
      completed: 4,
      total: 4,
      done: true,
      failed: false,
    });
    fixture.provider.dispose();
  });
  it("refreshes roots, stops picking when hidden, and releases notifications", async () => {
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(method === "app.status" ? { running: true } : []),
    );
    const fixture = await create();
    fixture.receive({ type: "ready" });
    fixture.receive({ type: "pick" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "roots")).toBe(
        true,
      ),
    );
    await vi.waitFor(() =>
      expect(
        fixture.sent.some(
          (message) => message.type === "state" && message.picking === true,
        ),
      ).toBe(true),
    );
    mocks.notifications.get("spy.cancelled")?.({});
    expect(fixture.sent.at(-1)?.picking).toBe(false);
    fixture.view.visible = false;
    fixture.visibility();
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("spy.stop"),
    );
    fixture.provider.dispose();
    expect(fixture.notificationDisposals).toHaveLength(3);
  });
  it("refreshes stale node handles instead of retaining a broken tree", async () => {
    mocks.request.mockImplementation((method: string) =>
      method === "inspect.children"
        ? Promise.reject(new RpcError(-32005, "gone"))
        : Promise.resolve(method === "app.status" ? { running: false } : []),
    );
    const fixture = await create();
    fixture.receive({ type: "expand", nodeId: "stale" });
    await vi.waitFor(() =>
      expect(fixture.sent).toContainEqual({
        type: "error",
        message: "The element is gone; refreshed.",
      }),
    );
    expect(fixture.sent.some((message) => message.type === "roots")).toBe(true);
    fixture.provider.dispose();
  });
  it("does not let an in-flight pick overwrite a newer row selection", async () => {
    let finishPick: (value: unknown) => void = () => {};
    mocks.request.mockImplementation(
      (method: string, params?: { includeAncestors?: boolean }) => {
        if (method === "inspect.properties" && params?.includeAncestors)
          return new Promise((resolve) => {
            finishPick = resolve;
          });
        if (method === "inspect.properties")
          return Promise.resolve({
            info: { name: "Row" },
            properties: {},
            ancestors: [],
          });
        if (method === "suggest.locator")
          return Promise.resolve({ helpers: [], code: "Row()" });
        if (method === "inspect.roots")
          return Promise.resolve([
            { nodeId: "root", info: { processId: 1 } },
          ]);
        return Promise.resolve(undefined);
      },
    );
    const fixture = await create();
    fixture.receive({ type: "pick" });
    await vi.waitFor(() =>
      expect(mocks.notifications.has("spy.picked")).toBe(true),
    );
    mocks.notifications.get("spy.picked")?.({
      node: { nodeId: "picked", info: { controlType: "Button", name: "Save" } },
      suggestion: { helpers: [], code: "Element()" },
    });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.properties", {
        nodeId: "picked",
        includeAncestors: true,
      }),
    );
    fixture.receive({ type: "select", nodeId: "row" });
    await vi.waitFor(() =>
      expect(
        fixture.sent.some(
          (message) => message.type === "selected" && message.nodeId === "row",
        ),
      ).toBe(true),
    );
    finishPick({
      info: { controlType: "Button", name: "Save" },
      properties: {},
      ancestors: [],
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(
      fixture.sent
        .filter((message) => message.type === "selected")
        .map((message) => message.nodeId),
    ).toEqual(["row"]);
    expect(
      fixture.sent.some(
        (message) => message.type === "picked" || message.type === "roots",
      ),
    ).toBe(false);
    fixture.provider.dispose();
  });
  it("does not let an older selection overwrite a picked control", async () => {
    let finishSelect: (value: unknown) => void = () => {};
    mocks.request.mockImplementation(
      (method: string, params?: { includeAncestors?: boolean }) => {
        if (method === "inspect.properties" && params?.includeAncestors)
          return Promise.resolve({
            info: { controlType: "Button", name: "Save" },
            properties: {},
            ancestors: [],
          });
        if (method === "inspect.properties")
          return new Promise((resolve) => {
            finishSelect = resolve;
          });
        if (method === "suggest.locator")
          return Promise.resolve({ helpers: [], code: "Element()" });
        if (method === "inspect.roots") return Promise.resolve([]);
        return Promise.resolve(undefined);
      },
    );
    const fixture = await create();
    fixture.receive({ type: "select", nodeId: "row" });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.properties", {
        nodeId: "row",
      }),
    );
    fixture.receive({ type: "pick" });
    await vi.waitFor(() =>
      expect(mocks.notifications.has("spy.picked")).toBe(true),
    );
    mocks.notifications.get("spy.picked")?.({
      node: { nodeId: "picked", info: { controlType: "Button", name: "Save" } },
      suggestion: { helpers: [], code: "Element()" },
    });
    await vi.waitFor(() =>
      expect(
        fixture.sent.some(
          (message) =>
            message.type === "selected" && message.nodeId === "picked",
        ),
      ).toBe(true),
    );
    finishSelect({ info: { name: "Row" }, properties: {}, ancestors: [] });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(
      fixture.sent
        .filter((message) => message.type === "selected")
        .map((message) => message.nodeId),
    ).toEqual(["picked"]);
    expect(
      fixture.sent.some(
        (message) => message.type === "suggestion" && message.nodeId === "row",
      ),
    ).toBe(false);
    fixture.provider.dispose();
  });
  it("drops expanded children superseded when a pick replaces the tree", async () => {
    let finishExpand: (nodes: unknown[]) => void = () => {};
    const picked = {
      nodeId: "picked",
      info: { controlType: "Button", name: "Save", processId: 4 },
    };
    mocks.request.mockImplementation((method: string) => {
      if (method === "inspect.children")
        return new Promise((resolve) => {
          finishExpand = resolve;
        });
      if (method === "inspect.properties")
        return Promise.resolve({
          info: picked.info,
          properties: {},
          ancestors: [],
        });
      if (method === "inspect.roots")
        return Promise.resolve([
          {
            nodeId: "root",
            hasChildren: true,
            info: { name: "App", controlType: "Window", processId: 4 },
          },
        ]);
      return Promise.resolve(undefined);
    });
    const fixture = await create();
    fixture.receive({ type: "expand", nodeId: "root" });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.children", {
        nodeId: "root",
      }),
    );
    fixture.receive({ type: "pick" });
    await vi.waitFor(() =>
      expect(mocks.notifications.has("spy.picked")).toBe(true),
    );
    mocks.notifications.get("spy.picked")?.({
      node: picked,
      suggestion: { helpers: [], code: "Element()" },
    });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "roots")).toBe(
        true,
      ),
    );
    finishExpand([{ nodeId: "stale" }]);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(
      fixture.sent.filter((message) => message.type === "children"),
    ).toEqual([]);
    fixture.provider.dispose();
  });
  it("does not let a superseded connection clear newer roots", async () => {
    const client = {
      request: mocks.request,
      onNotification: (name: string, callback: (value: unknown) => void) => {
        mocks.notifications.set(name, callback);
        return { dispose: () => mocks.notifications.delete(name) };
      },
    };
    const pending: Array<(value: { client: typeof client }) => void> = [];
    const connect = vi.fn(
      () =>
        new Promise<{ client: typeof client }>((resolve) => {
          pending.push(resolve);
        }),
    );
    const fixture = await create(connect);
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(
        method === "app.status"
          ? { running: true }
          : [{ nodeId: "fresh", info: { processId: 1 } }],
      ),
    );
    const first = fixture.provider.refresh();
    await vi.waitFor(() => expect(pending).toHaveLength(1));
    fixture.activate({
      root: { fsPath: "C:/other", toString: () => "other" },
      name: "other",
    });
    await vi.waitFor(() => expect(pending).toHaveLength(2));
    pending[1]({ client });
    await vi.waitFor(() =>
      expect(
        fixture.sent.filter((message) => message.type === "roots"),
      ).toEqual([
        {
          type: "roots",
          nodes: [{ nodeId: "fresh", info: { processId: 1 } }],
        },
      ]),
    );
    pending[0]({ client });
    await first;
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fixture.sent.filter((message) => message.type === "roots")).toEqual(
      [
        {
          type: "roots",
          nodes: [{ nodeId: "fresh", info: { processId: 1 } }],
        },
      ],
    );
    fixture.provider.dispose();
  });
});
