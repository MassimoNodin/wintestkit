import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import * as path from "node:path";
import type * as vscode from "vscode";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Projects } from "../../src/projects";
import type { ServerManager } from "../../src/server/serverManager";
import type { SetupMonitor } from "../../src/setup/monitor";
import type { TourView } from "../../src/setup/tour";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  notifications: new Map<string, (value: unknown) => void>(),
  clipboard: vi.fn(),
  command: vi.fn(),
  commands: new Map<string, (...args: unknown[]) => unknown>(),
  information: vi.fn(() => Promise.resolve(undefined)),
  icons: vi.fn(() => Promise.resolve({} as Record<string, string>)),
  previews: vi.fn(() => Promise.resolve(undefined as unknown)),
  activeEditor: undefined as
    { document: { uri: { fsPath: string; toString(): string } } } | undefined,
  editorListeners: [] as Array<() => void>,
  markers: true,
  bringToFront: false,
  updateConfig: vi.fn(() => Promise.resolve()),
  configListeners: [] as Array<
    (event: { affectsConfiguration(key: string): boolean }) => void
  >,
  showPreview: vi.fn<(view: string, dataUrl: string) => Promise<void>>(() => Promise.resolve()),
  disposeViewer: vi.fn(),
  warning: vi.fn<(message: string) => Promise<undefined>>(() => Promise.resolve(undefined)),
  shownProperties: [] as unknown,
  providerRegistrations: [] as unknown[][],
  projectListeners: [] as Array<() => void>,
  openDocument: vi.fn((uri: unknown) => Promise.resolve({ uri })),
  showDocument: vi.fn(() => Promise.resolve(undefined)),
}));
vi.mock("../../src/spy/appIcons", () => ({
  readApplicationIcons: mocks.icons,
}));
vi.mock("../../src/spy/previewViewer", () => ({
  PreviewViewer: class {
    show = mocks.showPreview;
    dispose = mocks.disposeViewer;
  },
}));
vi.mock("../../src/spy/objectPreviews", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/spy/objectPreviews")>()),
  readObjectPreview: mocks.previews,
}));
vi.mock("vscode", () => ({
  ConfigurationTarget: { Global: 1 },
  Position: class {
    constructor(
      readonly line: number,
      readonly character: number,
    ) {}
  },
  Range: class {
    constructor(
      readonly start: unknown,
      readonly end: unknown,
    ) {}
  },
  workspace: {
    getConfiguration: () => ({
      get: (key: string, fallback: boolean) =>
        key === "bringWindowToFront"
          ? mocks.bringToFront
          : key === "shownProperties"
            ? mocks.shownProperties
            : mocks.markers && fallback,
      update: mocks.updateConfig,
    }),
    onDidChangeConfiguration: (
      listener: (event: { affectsConfiguration(key: string): boolean }) => void,
    ) => {
      mocks.configListeners.push(listener);
      return { dispose() {} };
    },
    onDidSaveTextDocument: () => ({ dispose() {} }),
    openTextDocument: mocks.openDocument,
  },
  Uri: {
    file: (fsPath: string) => ({ fsPath }),
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
    registerWebviewViewProvider: (...args: unknown[]) => {
      mocks.providerRegistrations.push(args);
      return { dispose() {} };
    },
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
    showWarningMessage: mocks.warning,
    showTextDocument: mocks.showDocument,
  },
  commands: {
    registerCommand: (
      name: string,
      handler: (...args: unknown[]) => unknown,
    ) => {
      mocks.commands.set(name, handler);
      return {
        dispose() {
          mocks.commands.delete(name);
        },
      };
    },
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
    mocks.commands.clear();
    mocks.activeEditor = undefined;
    mocks.markers = true;
    mocks.bringToFront = false;
    mocks.configListeners.splice(0, mocks.configListeners.length);
    mocks.editorListeners.splice(0, mocks.editorListeners.length);
    mocks.providerRegistrations.splice(0);
    mocks.shownProperties = [];
    mocks.updateConfig.mockClear();
    mocks.warning.mockClear();
    mocks.projectListeners.splice(0);
    mocks.previews.mockReset().mockResolvedValue(undefined);
  });
  const latestSession = (): string | undefined => {
    const call = [...mocks.request.mock.calls].reverse().find((entry) => entry[0] === "spy.start");
    return (call?.[1] as { sessionId?: string } | undefined)?.sessionId;
  };
  const create = async (
    connect?: () => Promise<unknown>,
    setup?: SetupMonitor,
    memory?: unknown,
  ) => {
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
        onDidChange: (listener: () => void) => {
          mocks.projectListeners.push(listener);
          return { dispose() {} };
        },
      } as unknown as Projects,
      {
        get: connect || (() => Promise.resolve({ client, initialized: { config: { app: { process: "Demo.exe" } } } })),
        state: () => serverState,
        onDidChange: (callback: (value: typeof project) => void) => {
          serverChanged = () => callback(project);
          return { dispose() {} };
        },
      } as unknown as ServerManager,
      { fsPath: path.resolve(".") } as vscode.Uri,
      { error: vi.fn() } as unknown as vscode.LogOutputChannel,
      setup,
      memory as never,
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
      client,
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
  const tutorialView = (): TourView => ({
    step: "spy",
    phase: "extras",
    kind: "todo",
    title: "Meet Spy",
    text: "Explore the panel.",
    lit: ["spy"],
    panel: false,
    buttons: [{ id: "next", label: "Next" }],
    canBack: true,
    canNext: false,
  });
  const tutorialResponses = (name = "any workspace - Visual Studio Code") => {
    const root = {
      nodeId: "code-window",
      info: { controlType: "Window", name, processId: 42 },
      hasChildren: true,
    };
    const children = [
      { nodeId: "first-child", info: { controlType: "Pane", name: "" } },
      { nodeId: "content", info: { controlType: "Pane", name } },
    ];
    const suggestion = {
      attributeName: "content",
      code: "Element(depth=1, index=1)",
      helpers: [],
    };
    const definition = { id: "main-content", qualname: "MainPage.content" };
    mocks.request.mockImplementation(async (method: string) => {
      if (method === "inspect.roots") return [root];
      if (method === "inspect.children") return children;
      if (method === "inspect.properties")
        return { info: children[1].info, properties: {}, ancestors: [] };
      if (method === "suggest.locator") return suggestion;
      if (method === "inspect.definitions")
        return {
          definitions: [definition],
          errors: [],
          pageCount: 1,
          appRunning: true,
        };
      if (method === "app.status") return { running: true };
      return null;
    });
    return { root, children, definition };
  };
  it("opens the bottom Spy panel once on tutorial entry and forwards its navigation", async () => {
    tutorialResponses();
    let tutorial: TourView | undefined;
    let changed = () => {};
    const back = vi.fn(() => {
      tutorial = undefined;
      changed();
    });
    const next = vi.fn();
    const skip = vi.fn(async () => {});
    const finish = vi.fn(async () => {});
    const close = vi.fn();
    const setup = {
      get tour() {
        return tutorial;
      },
      get focus() {
        return { dim: false, spyLit: !!tutorial };
      },
      onDidChange: (listener: () => void) => {
        changed = listener;
        return { dispose() {} };
      },
      back,
      next,
      skip,
      finish,
      close,
    } as unknown as SetupMonitor;
    const fixture = await create(undefined, setup);
    expect(mocks.command).not.toHaveBeenCalledWith("wintestkit.spy.focus");
    tutorial = {
      step: "spy",
      phase: "extras",
      kind: "todo",
      title: "Meet Spy",
      text: "Explore the panel.",
      lit: ["spy"],
      panel: false,
      buttons: [{ id: "next", label: "Next" }],
      canBack: true,
      canNext: false,
    };
    changed();
    await vi.waitFor(() =>
      expect(mocks.command).toHaveBeenCalledWith("wintestkit.spy.focus"),
    );
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "selected")).toBe(
        true,
      ),
    );
    expect(mocks.command).toHaveBeenCalledWith(
      "workbench.action.positionPanelBottom",
    );
    expect(fixture.sent.at(-1)).toMatchObject({
      type: "tour",
      tutorial: { step: "spy" },
    });
    tutorial = { ...tutorial, step: "spyPick", spyTarget: "pick" };
    changed();
    expect(
      mocks.command.mock.calls.filter(
        ([command]) => command === "wintestkit.spy.focus",
      ),
    ).toHaveLength(1);
    for (const [action, handler] of [
      ["next", next],
      ["skip", skip],
      ["finish", finish],
      ["close", close],
    ] as const) {
      fixture.receive({ type: "tour", action });
      expect(handler).toHaveBeenCalledOnce();
    }
    fixture.receive({ type: "tour", action: "back" });
    expect(back).toHaveBeenCalledOnce();
    expect(mocks.command).toHaveBeenCalledWith("wintestkit.sidebar.focus");
    expect(
      fixture.sent.filter((message) => message.type === "tour").at(-1),
    ).toMatchObject({ type: "tour", tutorial: undefined });
    fixture.receive({ type: "tour", action: "next" });
    expect(next).toHaveBeenCalledOnce();
    fixture.provider.dispose();
  });

  it.each([
    "test - Visual Studio Code",
    "another workspace - Visual Studio Code",
    "Visual Studio Code",
  ])(
    "selects the hosting window's second child for %s and freezes its snapshot",
    async (name) => {
      const expected = tutorialResponses(name);
      const setup = {
        tour: tutorialView(),
        focus: {},
        onDidChange: () => ({ dispose() {} }),
      } as unknown as SetupMonitor;
      const fixture = await create(undefined, setup);
      fixture.receive({ type: "ready" });
      await vi.waitFor(() =>
        expect(
          fixture.sent.some((message) => message.type === "definitions"),
        ).toBe(true),
      );
      expect(mocks.request).toHaveBeenCalledWith("inspect.roots", {
        foregroundForProcessId: process.pid,
      });
      expect(fixture.sent).toContainEqual({
        type: "children",
        nodeId: expected.root.nodeId,
        nodes: expected.children,
        expanded: true,
      });
      expect(
        fixture.sent.find((message) => message.type === "selected"),
      ).toMatchObject({ nodeId: "content" });
      expect(
        fixture.sent.find((message) => message.type === "definitions"),
      ).toMatchObject({ definitions: [expected.definition] });
      const count = fixture.sent.length;
      mocks.request.mockClear();
      for (const type of [
        "refresh",
        "pick",
        "chooseApp",
        "addToPage",
        "copy",
        "select",
        "expand",
        "highlight",
        "loadProperties",
        "openDefinition",
        "showOtherApps",
        "bringToFront",
      ])
        fixture.receive({
          type,
          nodeId: "first-child",
          id: "main-content",
          text: "copy",
          enabled: false,
        });
      mocks.notifications.get("spy.picked")?.({ node: expected.children[0] });
      mocks.notifications.get("spy.hover")?.({ node: expected.children[0] });
      await fixture.provider.refresh();
      await mocks.commands.get("wintestkit.spy.startPick")?.();
      await mocks.commands.get("wintestkit.spy.revealRelocation")?.(
        "elsewhere",
      );
      expect(mocks.request).not.toHaveBeenCalled();
      expect(mocks.clipboard).not.toHaveBeenCalled();
      expect(fixture.sent).toHaveLength(count);
      fixture.provider.dispose();
    },
  );

  it.each(["visibility", "ready", "resolve"])(
    "restores the current tutorial and frozen example after %s",
    async (reason) => {
      tutorialResponses();
      const tutorial: TourView = {
        ...tutorialView(),
        step: "spyProperties",
        spyTarget: "properties-pane",
      };
      const fixture = await create(undefined, {
        tour: tutorial,
        focus: {},
        onDidChange: () => ({ dispose() {} }),
      } as unknown as SetupMonitor);
      fixture.receive({ type: "ready" });
      await vi.waitFor(() =>
        expect(fixture.sent.at(-1)).toMatchObject({
          type: "tour",
          tutorial: { step: "spyProperties" },
        }),
      );
      await vi.waitFor(() =>
        expect(fixture.sent.some((message) => message.type === "coverage")).toBe(true),
      );
      const snapshot = fixture.sent.filter((message) => message.type !== "tour");
      fixture.sent.length = 0;
      mocks.request.mockClear();
      fixture.view.visible = false;
      fixture.visibility();
      fixture.view.visible = true;
      if (reason === "visibility") fixture.visibility();
      else {
        if (reason === "resolve")
          await fixture.provider.resolveWebviewView(
            fixture.view as unknown as vscode.WebviewView,
          );
        fixture.receive({ type: "ready" });
      }
      await vi.waitFor(() =>
        expect(fixture.sent.filter((message) => message.type !== "tour")).toEqual(snapshot),
      );
      expect(fixture.sent.at(-1)).toMatchObject({
        type: "tour",
        tutorial: { step: "spyProperties", spyTarget: "properties-pane" },
      });
      expect(mocks.request.mock.calls).toEqual([["spy.stop"]]);
      fixture.provider.dispose();
    },
  );

  it.each([true, false])(
    "shows all desktop apps while retaining the host (enumerated: %s)",
    async (includeHost) => {
      const expected = tutorialResponses();
      const respond = mocks.request.getMockImplementation()!;
      const otherApp = {
        nodeId: "other-app",
        info: { controlType: "Window", name: "Notepad", processId: 73 },
      };
      mocks.request.mockImplementation(
        async (method: string, params?: { includeOtherApps?: boolean }) => {
          if (method === "inspect.roots" && params?.includeOtherApps)
            return includeHost ? [expected.root, otherApp] : [otherApp];
          return respond(method);
        },
      );
      const setup = {
        tour: tutorialView(),
        focus: {},
        onDidChange: () => ({ dispose() {} }),
      } as unknown as SetupMonitor;
      const fixture = await create(undefined, setup);
      fixture.receive({ type: "ready" });
      await vi.waitFor(() =>
        expect(
          fixture.sent.some((message) => message.type === "definitions"),
        ).toBe(true),
      );
      expect(mocks.request).toHaveBeenCalledWith("inspect.roots", {
        includeOtherApps: true,
      });
      expect(fixture.sent).toContainEqual({
        type: "roots",
        nodes: [expected.root, otherApp],
      });
      expect(
        fixture.sent.find((message) => message.type === "state"),
      ).toMatchObject({ showOtherApps: true });
      expect(
        fixture.sent.find((message) => message.type === "selected"),
      ).toMatchObject({ nodeId: "content" });
      expect(
        fixture.sent.find((message) => message.type === "definitions"),
      ).toMatchObject({ definitions: [expected.definition] });
      fixture.provider.dispose();
    },
  );

  it("does not select a substitute when the expected content pane is missing", async () => {
    tutorialResponses();
    const respond = mocks.request.getMockImplementation()!;
    mocks.request.mockImplementation((method: string) =>
      method === "inspect.children" ? Promise.resolve([]) : respond(method),
    );
    const next = vi.fn();
    const fixture = await create(undefined, {
      tour: { ...tutorialView(), step: "spyPick" },
      focus: {},
      next,
      onDidChange: () => ({ dispose() {} }),
    } as unknown as SetupMonitor);
    fixture.receive({ type: "ready" });
    await vi.waitFor(() =>
      expect(fixture.sent.at(-1)).toMatchObject({
        type: "tour",
        tutorial: {
          text: expect.stringContaining("second child"),
          buttons: [],
        },
      }),
    );
    fixture.receive({ type: "tour", action: "next" });
    expect(next).not.toHaveBeenCalled();
    expect(fixture.sent.some((message) => message.type === "selected")).toBe(
      false,
    );
    fixture.provider.dispose();
  });

  it("only waits for the snapshot between tutorial steps two and three", async () => {
    tutorialResponses();
    const respond = mocks.request.getMockImplementation()!;
    let finishProperties: (value: unknown) => void = () => {};
    mocks.request.mockImplementation((method: string) =>
      method === "inspect.properties"
        ? new Promise((resolve) => {
            finishProperties = resolve;
          })
        : respond(method),
    );
    let tutorial = tutorialView();
    let changed = () => {};
    const next = vi.fn(() => {
      tutorial = { ...tutorial, step: "spyPick" };
      changed();
    });
    const fixture = await create(undefined, {
      get tour() {
        return tutorial;
      },
      focus: {},
      next,
      onDidChange: (listener: () => void) => {
        changed = listener;
        return { dispose() {} };
      },
    } as unknown as SetupMonitor);
    fixture.receive({ type: "ready" });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.properties", {
        nodeId: "content",
      }),
    );
    expect(
      fixture.sent.filter((message) => message.type === "tour").at(-1),
    ).toMatchObject({
      tutorial: {
        step: "spy",
        text: "Explore the panel.",
        buttons: [{ id: "next" }],
      },
    });
    fixture.receive({ type: "tour", action: "next" });
    expect(next).toHaveBeenCalledOnce();
    expect(fixture.sent.at(-1)).toMatchObject({
      tutorial: {
        step: "spyPick",
        buttons: [],
        text: expect.stringContaining("Preparing the objects preview"),
      },
    });
    fixture.receive({ type: "tour", action: "next" });
    expect(next).toHaveBeenCalledOnce();
    finishProperties({ info: { name: "content" } });
    await vi.waitFor(() =>
      expect(fixture.sent.at(-1)).toMatchObject({
        tutorial: { step: "spyPick", buttons: [{ id: "next" }] },
      }),
    );
    fixture.receive({ type: "tour", action: "next" });
    expect(next).toHaveBeenCalledTimes(2);
    fixture.provider.dispose();
  });

  it("restores ordinary Spy actions after closing the tutorial", async () => {
    tutorialResponses();
    let tutorial: TourView | undefined = tutorialView();
    let changed = () => {};
    const fixture = await create(undefined, {
      get tour() {
        return tutorial;
      },
      focus: {},
      onDidChange: (listener: () => void) => {
        changed = listener;
        return { dispose() {} };
      },
    } as unknown as SetupMonitor);
    fixture.receive({ type: "ready" });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "selected")).toBe(
        true,
      ),
    );
    tutorial = undefined;
    changed();
    fixture.receive({ type: "copy", text: "available again" });
    expect(mocks.clipboard).toHaveBeenCalledWith("available again");
    fixture.provider.dispose();
  });

  it("does not publish a late tutorial snapshot after the tutorial closes", async () => {
    tutorialResponses();
    const respond = mocks.request.getMockImplementation()!;
    let finishProperties: (value: unknown) => void = () => {};
    mocks.request.mockImplementation((method: string) =>
      method === "inspect.properties"
        ? new Promise((resolve) => {
            finishProperties = resolve;
          })
        : respond(method),
    );
    let tutorial: TourView | undefined = tutorialView();
    let changed = () => {};
    const fixture = await create(undefined, {
      get tour() {
        return tutorial;
      },
      focus: {},
      onDidChange: (listener: () => void) => {
        changed = listener;
        return { dispose() {} };
      },
    } as unknown as SetupMonitor);
    fixture.receive({ type: "ready" });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.properties", {
        nodeId: "content",
      }),
    );
    tutorial = undefined;
    changed();
    finishProperties({ info: { name: "late object" } });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fixture.sent.some((message) => message.type === "selected")).toBe(
      false,
    );
    expect(
      fixture.sent.filter((message) => message.type === "tour").at(-1),
    ).toMatchObject({ tutorial: undefined });
    fixture.provider.dispose();
  });

  it("keeps the displayed tutorial snapshot fixed through server and workspace changes", async () => {
    tutorialResponses();
    const fixture = await create(undefined, {
      tour: tutorialView(),
      focus: {},
      onDidChange: () => ({ dispose() {} }),
    } as unknown as SetupMonitor);
    fixture.receive({ type: "ready" });
    await vi.waitFor(() =>
      expect(
        fixture.sent.some((message) => message.type === "definitions"),
      ).toBe(true),
    );
    const count = fixture.sent.length;
    fixture.serverChanged("ready");
    fixture.activate({
      root: { fsPath: "C:/another", toString: () => "another" },
      name: "another",
    });
    fixture.visibility();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(
      fixture.sent.slice(count).filter((message) => message.type !== "tour"),
    ).toEqual(
      fixture.sent.slice(0, count).filter((message) => message.type !== "tour"),
    );
    fixture.provider.dispose();
  });

  it("refreshes after app actions only for the visible matching project", async () => {
    const fixture = await create();
    const project = {
      root: { fsPath: "C:/demo", toString: () => "demo" },
      name: "demo",
    } as import("../../src/server/serverManager").Project;
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(method === "inspect.refresh" ? { nodes: [], status: { running: true } } : []),
    );
    await fixture.provider.refreshForProject({
      ...project,
      root: { toString: () => "other" } as vscode.Uri,
    });
    expect(mocks.request).not.toHaveBeenCalled();
    fixture.view.visible = false;
    await fixture.provider.refreshForProject(project);
    expect(mocks.request).not.toHaveBeenCalled();
    fixture.view.visible = true;
    await fixture.provider.refreshForProject(project);
    expect(mocks.request).toHaveBeenCalledWith("inspect.refresh", { includeOtherApps: true });
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
    expect(html).toContain(
      '<span id="other-apps-label">Show Other Apps</span>',
    );
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
        method === "inspect.refresh" ? { nodes: [], status: { running: true, pids: [7] } } : [],
      ),
    );
    const fixture = await create();
    const rootCalls = () =>
      mocks.request.mock.calls.filter((call) => call[0] === "inspect.refresh");
    fixture.receive({ type: "ready", showOtherApps: false });
    await vi.waitFor(() => expect(rootCalls()).toEqual([["inspect.refresh"]]));
    expect(fixture.sent).toContainEqual(
      expect.objectContaining({
        type: "state",
        appRunning: true,
        targetName: "demo",
        showOtherApps: false,
      }),
    );
    mocks.request.mockClear();
    fixture.receive({ type: "showOtherApps", enabled: true });
    await vi.waitFor(() =>
      expect(rootCalls()).toEqual([
        ["inspect.refresh", { includeOtherApps: true }],
      ]),
    );
    expect(fixture.sent).toContainEqual(
      expect.objectContaining({
        type: "state",
        appRunning: true,
        targetName: "demo",
        showOtherApps: true,
      }),
    );
    mocks.request.mockClear();
    fixture.receive({ type: "refresh" });
    await vi.waitFor(() =>
      expect(rootCalls()).toEqual([
        ["inspect.refresh", { includeOtherApps: true }],
      ]),
    );
    mocks.request.mockClear();
    fixture.receive({ type: "showOtherApps", enabled: false });
    await vi.waitFor(() => expect(rootCalls()).toEqual([["inspect.refresh"]]));
    mocks.request.mockClear();
    fixture.receive({ type: "showOtherApps", enabled: "yes" });
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(mocks.request).not.toHaveBeenCalled();
    fixture.provider.dispose();
  });
  it("separates properties from the selection summary, definitions and locator", () => {
    const html = readFileSync("media/spy/spy.html", "utf8");
    const css = readFileSync("media/spy/spy.css", "utf8");
    const selection = html.slice(
      html.indexOf('id="selection-main"'),
      html.indexOf('id="properties-pane"'),
    );
    const properties = html.slice(html.indexOf('id="properties-pane"'));
    for (const id of [
      "selection-summary",
      "definitions-group",
      "locator-panel",
    ])
      expect(selection).toContain(`id="${id}"`);
    expect(selection).not.toContain('id="property-groups"');
    for (const id of [
      "property-groups",
      "properties",
      "state-properties",
      "geometry-properties",
      "automation-properties",
      "all-properties",
    ])
      expect(properties).toContain(`id="${id}"`);
    expect(properties).not.toContain('id="definitions-group"');
    expect(css).toContain(
      "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)",
    );
    expect(css).toContain("#details.inspector-narrow .inspector-columns");
    expect(css).not.toContain("container-type:");
  });
  it("keeps the scope control visible without any scope text", () => {
    const script = readFileSync("media/spy/spy.js", "utf8");
    const html = readFileSync("media/spy/spy.html", "utf8");
    expect(script).toContain("otherApps.hidden = false");
    expect(script).toContain("otherApps.disabled = !running");
    expect(script).not.toContain("Showing");
    expect(html).not.toContain("scope-context");
  });
  it("blurs the object tree behind a spinner and status while it loads", () => {
    const script = readFileSync("media/spy/spy.js", "utf8");
    const html = readFileSync("media/spy/spy.html", "utf8");
    const css = readFileSync("media/spy/spy.css", "utf8");
    expect(html).toContain('id="tree-overlay" role="status"');
    expect(html).toContain('id="tree-stage"');
    expect(script).toContain(
      'element("tree-stage").dataset.busy = String(reloading)',
    );
    expect(script).toContain("Reloading objects…");
    expect(css).toContain('#tree-stage[data-busy="true"] #tree-region');
    expect(css).toContain("filter: blur(3px)");
  });
  it("always starts with all desktop windows and keeps the narrowing button", () => {
    const script = readFileSync("media/spy/spy.js", "utf8");
    const html = readFileSync("media/spy/spy.html", "utf8");
    expect(script).toContain("let showOtherApps = true;");
    expect(script).not.toContain("persisted");
    expect(html).toContain('id="other-apps"');
  });
  it("uses roving focus and tree keyboard semantics for Spy nodes", () => {
    const script = readFileSync("media/spy/spy.js", "utf8");
    expect(script).toContain('addEventListener("focusin"');
    expect(script).toContain("entry.children.querySelector");
    expect(script).toContain('event.key === " "');
    expect(script).toContain('children.setAttribute("role", "group")');
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
        if (method === "inspect.refresh") {
          rootCalls += 1;
          return new Promise<unknown[]>((resolve) => {
            if (params?.includeOtherApps) finishSecond = resolve;
            else finishFirst = resolve;
          }).then((nodes) => ({ nodes, status: { running: true } }));
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
      expect(
        fixture.sent.filter((message) => message.type === "roots"),
      ).toEqual([{ type: "roots", nodes: [{ nodeId: "other" }] }]),
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
        method === "inspect.refresh"
          ? { nodes: [], status: { running: true } }
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
    fixture.receive({ type: "showOtherApps", enabled: false });
    fixture.receive({ type: "showOtherApps", enabled: true });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.refresh", {
        includeOtherApps: true,
      }),
    );
    mocks.request.mockClear();
    fixture.receive({ type: "pick" });
    await vi.waitFor(() =>
      expect(latestSession()).toBeTypeOf("string"),
    );
    mocks.notifications.get("spy.picked")?.({
      sessionId: latestSession(),
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
      (method: string) => {
        if (method === "app.status")
          return Promise.resolve({ running: true, pids: [7] });
        if (method === "inspect.properties")
          return Promise.resolve({
            info: { controlType: "Button", name: "Save" },
            properties: {},
            ancestors: [],
          });
        if (method === "inspect.refresh")
          return new Promise<unknown[]>((resolve) => { finishRefresh = resolve; })
            .then((nodes) => ({ nodes, status: { running: true } }));
        if (method === "inspect.roots")
          return new Promise((resolve) => { finishReveal = resolve; });
        return Promise.resolve(undefined);
      },
    );
    const fixture = await create();
    fixture.receive({ type: "showOtherApps", enabled: false });
    fixture.receive({ type: "pick" });
    await vi.waitFor(() =>
      expect(latestSession()).toBeTypeOf("string"),
    );
    mocks.notifications.get("spy.picked")?.({
      sessionId: latestSession(),
      node: { nodeId: "picked", info: { controlType: "Button", name: "Save" } },
      suggestion: { helpers: [], code: "Element()" },
    });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.roots"),
    );
    fixture.receive({ type: "showOtherApps", enabled: true });
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("inspect.refresh", {
        includeOtherApps: true,
      }),
    );
    finishRefresh([{ nodeId: "other" }]);
    finishReveal([{ nodeId: "scoped" }]);
    await vi.waitFor(() =>
      expect(
        fixture.sent.filter((message) => message.type === "roots"),
      ).toEqual([{ type: "roots", nodes: [{ nodeId: "other" }] }]),
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
      Promise.resolve(method === "inspect.refresh" ? { nodes: [], status: { running: true } } : []),
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
      initialized: { config: {} },
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
    expect(fixture.view.webview.html).toContain('id="tree-overlay"');
    expect(fixture.view.webview.html).not.toContain('id="tree-loading"');
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
      Promise.resolve(method === "inspect.refresh" ? { nodes: roots, status: { running: true } } : roots),
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
      progress.some((message) => message.phase === "Refreshing root windows"),
    ).toBe(true);
    expect(progress.at(-1)).toMatchObject({
      done: true,
      completed: 2,
      total: 2,
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
        method === "inspect.refresh"
          ? { nodes: [{ nodeId: "root", info: { processId: 123 } }], status: { running: true } }
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
  it("still delivers icons when a row is selected while they load", async () => {
    let finishIcons: (icons: Record<string, string>) => void = () => undefined;
    const roots = [{ nodeId: "root", info: { processId: 123 } }];
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(method === "inspect.refresh" ? { nodes: roots, status: { running: true } } : roots),
    );
    mocks.icons.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishIcons = resolve;
        }),
    );
    const fixture = await create();
    await fixture.provider.refresh();
    await vi.waitFor(() => expect(mocks.icons).toHaveBeenCalledTimes(1));
    fixture.receive({ type: "select", nodeId: "root" });
    finishIcons({ "123": "data:image/png;base64,abcd" });
    await vi.waitFor(() =>
      expect(fixture.sent).toContainEqual({
        type: "rootIcons",
        icons: { "123": "data:image/png;base64,abcd" },
      }),
    );
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
  describe("suggested locator", () => {
    const answer = (locator: () => Promise<unknown>) =>
      mocks.request.mockImplementation((method: string) => {
        if (method === "inspect.properties")
          return Promise.resolve({ info: { name: "Save", controlType: "Button" }, properties: {}, ancestors: [] });
        if (method === "suggest.locator") return locator();
        return Promise.resolve(undefined);
      });
    const select = async (nodeId = "control") => {
      const fixture = await create();
      fixture.receive({ type: "select", nodeId });
      await vi.waitFor(() => expect(fixture.sent.some((message) => message.type === "selected")).toBe(true));
      return fixture;
    };
    const locatorRequests = () => mocks.request.mock.calls.filter(([method]) => method === "suggest.locator");

    it("does not generate a locator just because an object was selected", async () => {
      answer(() => Promise.resolve({ helpers: [], code: "Element()" }));
      const fixture = await select();
      await vi.waitFor(() => expect(mocks.request).toHaveBeenCalledWith("inspect.definitions", { nodeId: "control" }));
      expect(locatorRequests()).toHaveLength(0);
      expect(fixture.sent.find((message) => message.type === "selected")).not.toHaveProperty("suggestion");
      expect(fixture.sent.some((message) => message.type === "suggestion" || message.type === "suggestionLoading")).toBe(false);
      fixture.provider.dispose();
    });

    it("loads definitions and the preview without waiting for a locator", async () => {
      answer(() => new Promise(() => {}));
      const fixture = await select();
      await vi.waitFor(() => expect(fixture.sent.some((message) => message.type === "objectPreview")).toBe(true));
      expect(fixture.sent.some((message) => message.type === "definitions" && message.state !== "loading")).toBe(true);
      fixture.provider.dispose();
    });

    it("reports that it is generating, then delivers the locator, when asked", async () => {
      let finish: (value: unknown) => void = () => {};
      answer(() => new Promise((resolve) => { finish = resolve; }));
      const fixture = await select();
      fixture.receive({ type: "generateLocator", nodeId: "control" });
      await vi.waitFor(() => expect(fixture.sent).toContainEqual({ type: "suggestionLoading", nodeId: "control" }));
      expect(fixture.sent.some((message) => message.type === "suggestion")).toBe(false);
      finish({ helpers: [], code: "Element()" });
      await vi.waitFor(() => expect(fixture.sent.some((message) => message.type === "suggestion" && message.nodeId === "control")).toBe(true));
      expect(locatorRequests()).toHaveLength(1);
      fixture.provider.dispose();
    });

    it("reports a window as having no locator instead of leaving it loading", async () => {
      answer(() => Promise.reject(new RpcError(-32006, "Select a window descendant")));
      const fixture = await select("window");
      fixture.receive({ type: "generateLocator", nodeId: "window" });
      await vi.waitFor(() => expect(fixture.sent.some((message) => message.type === "suggestionUnavailable")).toBe(true));
      expect(fixture.sent.find((message) => message.type === "suggestionUnavailable")).toEqual({
        type: "suggestionUnavailable", nodeId: "window", reason: "Select a window descendant",
      });
      expect(fixture.sent.some((message) => message.type === "error")).toBe(false);
      fixture.provider.dispose();
    });

    it("reports other failures so the button can be tried again", async () => {
      answer(() => Promise.reject(new Error("pipe closed")));
      const fixture = await select();
      fixture.receive({ type: "generateLocator", nodeId: "control" });
      await vi.waitFor(() => expect(fixture.sent).toContainEqual({ type: "suggestionUnavailable", nodeId: "control", reason: "pipe closed" }));
      fixture.provider.dispose();
    });

    it("ignores a request for an object that is not the selected one", async () => {
      answer(() => Promise.resolve({ helpers: [], code: "Element()" }));
      const fixture = await select("control");
      fixture.receive({ type: "generateLocator", nodeId: "other" });
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(locatorRequests()).toHaveLength(0);
      fixture.provider.dispose();
    });

    it("drops a locator that finishes after another object was selected", async () => {
      let finish: (value: unknown) => void = () => {};
      answer(() => new Promise((resolve) => { finish = resolve; }));
      const fixture = await select("control");
      fixture.receive({ type: "generateLocator", nodeId: "control" });
      await vi.waitFor(() => expect(locatorRequests()).toHaveLength(1));
      fixture.receive({ type: "select", nodeId: "newer" });
      await vi.waitFor(() => expect(fixture.sent.some((message) => message.type === "selected" && message.nodeId === "newer")).toBe(true));
      finish({ helpers: [], code: "Element()" });
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(fixture.sent.some((message) => message.type === "suggestion")).toBe(false);
      fixture.provider.dispose();
    });

    it("does not generate a locator for a picked object until asked", async () => {
      answer(() => Promise.resolve({ helpers: [], code: "Element()" }));
      mocks.request.mockImplementation((method: string) => {
        if (method === "inspect.properties") return Promise.resolve({ info: { controlType: "Button", name: "Save" }, properties: {}, ancestors: [] });
        if (method === "inspect.roots") return Promise.resolve([]);
        if (method === "suggest.locator") return Promise.resolve({ helpers: [], code: "Element()" });
        return Promise.resolve(undefined);
      });
      const fixture = await create();
      fixture.receive({ type: "pick" });
      await vi.waitFor(() => expect(latestSession()).toBeTypeOf("string"));
      mocks.notifications.get("spy.picked")?.({ sessionId: latestSession(), node: { nodeId: "picked", info: { controlType: "Button", name: "Save" } } });
      await vi.waitFor(() => expect(fixture.sent.some((message) => message.type === "selected" && message.nodeId === "picked")).toBe(true));
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(locatorRequests()).toHaveLength(0);
      fixture.receive({ type: "generateLocator", nodeId: "picked" });
      await vi.waitFor(() => expect(fixture.sent.some((message) => message.type === "suggestion" && message.nodeId === "picked")).toBe(true));
      fixture.provider.dispose();
    });
  });
  const definition = {
    id: "pages/main.py::MainPage.save",
    qualname: "MainPage.save",
    kind: "element",
    locator: 'Button[name="Save"]',
    file: "C:/demo/pages/main.py",
    line: 12,
    range: {
      start: { line: 11, character: 4 },
      end: { line: 11, character: 40 },
    },
    pages: ["MainPage.save"],
    pageCount: 1,
  };
  const selectWith = (handlers: Record<string, unknown>) =>
    mocks.request.mockImplementation((method: string) => {
      if (method in handlers) {
        const value = handlers[method];
        return typeof value === "function"
          ? (value as () => unknown)()
          : Promise.resolve(value);
      }
      if (method === "inspect.properties")
        return Promise.resolve({ info: { name: "Save" }, properties: {} });
      if (method === "suggest.locator")
        return Promise.resolve({ helpers: [], code: "Element()" });
      return Promise.resolve(undefined);
    });
  const sawDefinitions = (
    fixture: { sent: { type: string; [key: string]: unknown }[] },
    state: string,
  ) =>
    fixture.sent.some(
      (message) => message.type === "definitions" && message.state === state,
    );
  describe("bring window to front option", () => {
    const highlightCalls = () =>
      mocks.request.mock.calls.filter(
        ([method]) => method === "inspect.highlight",
      );
    const selectNode = async (
      fixture: Awaited<ReturnType<typeof create>>,
      nodeId = "control",
    ) => {
      mocks.request.mockImplementation((method: string) =>
        Promise.resolve(
          method === "inspect.properties"
            ? { info: { name: "Save" }, properties: {} }
            : method === "suggest.locator"
              ? { helpers: [], code: "Element()" }
              : undefined,
        ),
      );
      fixture.receive({ type: "select", nodeId });
      await vi.waitFor(() =>
        expect(
          fixture.sent.some((message) => message.type === "selected"),
        ).toBe(true),
      );
    };
    it.each([false, true])(
      "never highlights on selection when bringToFront is %s",
      async (bringToFront) => {
        mocks.bringToFront = bringToFront;
        const fixture = await create();
        await selectNode(fixture);
        expect(highlightCalls()).toHaveLength(0);
        fixture.provider.dispose();
      },
    );
    it.each([false, true])(
      "only highlights through the button with bringToFront %s",
      async (bringToFront) => {
        mocks.bringToFront = bringToFront;
        const fixture = await create();
        await selectNode(fixture);
        fixture.receive({ type: "highlight", nodeId: "control" });
        await vi.waitFor(() => expect(highlightCalls()).toHaveLength(1));
        expect(highlightCalls().map(([, params]) => params)).toEqual([
          { nodeId: "control", bringToFront },
        ]);
        fixture.provider.dispose();
      },
    );
    it("saves the toggle to the user settings and tells the panel", async () => {
      const fixture = await create();
      fixture.receive({ type: "bringToFront", enabled: true });
      await vi.waitFor(() =>
        expect(mocks.updateConfig).toHaveBeenCalledWith(
          "bringWindowToFront",
          true,
          1,
        ),
      );
      mocks.bringToFront = true;
      for (const listener of mocks.configListeners)
        listener({
          affectsConfiguration: (key) =>
            key === "wintestkit.spy.bringWindowToFront",
        });
      const states = fixture.sent.filter((message) => message.type === "state");
      expect(states.at(-1)).toMatchObject({ bringToFront: true });
      fixture.provider.dispose();
    });
    it("tells the panel the option is off at first", async () => {
      const fixture = await create();
      fixture.receive({ type: "ready" });
      await vi.waitFor(() =>
        expect(fixture.sent.some((message) => message.type === "state")).toBe(
          true,
        ),
      );
      expect(
        fixture.sent.find((message) => message.type === "state"),
      ).toMatchObject({ bringToFront: false });
      fixture.provider.dispose();
    });
  });
  it("lists the definitions that resolve to the selected object after its locator", async () => {
    selectWith({
      "inspect.definitions": {
        definitions: [definition],
        errors: [],
        pageCount: 4,
      },
    });
    const fixture = await create();
    fixture.receive({ type: "select", nodeId: "save" });
    await vi.waitFor(() => expect(sawDefinitions(fixture, "ready")).toBe(true));
    const order = fixture.sent.map((message) => message.type);
    expect(order.indexOf("suggestion")).toBeLessThan(
      order.lastIndexOf("definitions"),
    );
    expect(
      fixture.sent.find(
        (message) =>
          message.type === "definitions" && message.state === "loading",
      ),
    ).toEqual({ type: "definitions", nodeId: "save", state: "loading" });
    expect(mocks.request).toHaveBeenCalledWith("inspect.definitions", {
      nodeId: "save",
    });
    fixture.provider.dispose();
  });
  it("preserves stopped-app context and the real page count", async () => {
    selectWith({
      "inspect.definitions": {
        definitions: [],
        errors: [],
        pageCount: 4,
        appRunning: false,
      },
    });
    const fixture = await create();
    fixture.receive({ type: "select", nodeId: "save" });
    await vi.waitFor(() => expect(sawDefinitions(fixture, "ready")).toBe(true));
    expect(fixture.sent).toContainEqual({
      type: "definitions",
      nodeId: "save",
      state: "ready",
      definitions: [],
      errors: [],
      pageCount: 4,
      appRunning: false,
    });
    fixture.provider.dispose();
  });
  it("reports definitions as unavailable when the server cannot answer", async () => {
    selectWith({
      "inspect.definitions": () => Promise.reject(new Error("no catalogue")),
    });
    const fixture = await create();
    fixture.receive({ type: "select", nodeId: "save" });
    await vi.waitFor(() =>
      expect(sawDefinitions(fixture, "unavailable")).toBe(true),
    );
    expect(
      fixture.sent.find(
        (message) =>
          message.type === "definitions" && message.state === "unavailable",
      ),
    ).toMatchObject({ reason: "no catalogue" });
    fixture.provider.dispose();
  });
  it("opens a listed definition at its range and ignores unknown ids", async () => {
    selectWith({
      "inspect.definitions": {
        definitions: [definition],
        errors: [],
        pageCount: 1,
      },
    });
    const fixture = await create();
    fixture.receive({ type: "select", nodeId: "save" });
    await vi.waitFor(() => expect(sawDefinitions(fixture, "ready")).toBe(true));
    fixture.receive({ type: "openDefinition", id: "pages/other.py::X.y" });
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(mocks.openDocument).not.toHaveBeenCalled();
    fixture.receive({ type: "openDefinition", id: definition.id });
    await vi.waitFor(() => expect(mocks.showDocument).toHaveBeenCalled());
    expect(mocks.openDocument).toHaveBeenCalledWith({
      fsPath: "C:/demo/pages/main.py",
    });
    expect(mocks.showDocument).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        selection: expect.objectContaining({
          start: expect.objectContaining({ line: 11, character: 4 }),
        }),
      }),
    );
    fixture.provider.dispose();
  });
  const rootsWithCoverage = (coverage: () => unknown): void => {
    mocks.request.mockImplementation((method: string) => {
      if (method === "app.status")
        return Promise.resolve({ running: true, pids: [7] });
      if (method === "inspect.refresh")
        return Promise.resolve({ nodes: [
          {
            nodeId: "a",
            info: { processId: 7, name: "A", controlType: "Window" },
          },
          {
            nodeId: "b",
            info: { processId: 7, name: "B", controlType: "Window" },
          },
        ], status: { running: true, pids: [7] } });
      if (method === "inspect.coverage") return Promise.resolve(coverage());
      return Promise.resolve(undefined);
    });
  };
  it("marks the loaded tree nodes that some definition points at", async () => {
    rootsWithCoverage(() => ({
      covered: { a: { count: 1, first: "MainPage.window" } },
      pending: [],
    }));
    const fixture = await create();
    fixture.receive({ type: "ready", showOtherApps: false });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "coverage")).toBe(
        true,
      ),
    );
    expect(mocks.request).toHaveBeenCalledWith("inspect.coverage", {
      nodeIds: ["a", "b"],
    });
    expect(fixture.sent.find((message) => message.type === "coverage")).toEqual(
      {
        type: "coverage",
        nodeIds: ["a", "b"],
        covered: { a: { count: 1, first: "MainPage.window" } },
      },
    );
    fixture.provider.dispose();
  });
  it("asks again for the nodes the server did not finish", async () => {
    let calls = 0;
    rootsWithCoverage(() => {
      calls++;
      return calls === 1
        ? { covered: { a: { count: 1, first: "P.a" } }, pending: ["b"] }
        : { covered: { b: { count: 2, first: "P.b" } }, pending: [] };
    });
    const fixture = await create();
    fixture.receive({ type: "ready", showOtherApps: false });
    await vi.waitFor(() =>
      expect(
        fixture.sent.filter((message) => message.type === "coverage"),
      ).toHaveLength(2),
    );
    const [first, second] = fixture.sent.filter(
      (message) => message.type === "coverage",
    );
    expect(first?.nodeIds).toEqual(["a"]); // "b" is still pending, so not settled yet
    expect(second?.nodeIds).toEqual(["b"]);
    expect(mocks.request).toHaveBeenLastCalledWith("inspect.coverage", {
      nodeIds: ["b"],
    });
    fixture.provider.dispose();
  });
  it("does not look for defined objects when the setting is off", async () => {
    mocks.markers = false;
    rootsWithCoverage(() => ({ covered: {}, pending: [] }));
    const fixture = await create();
    fixture.receive({ type: "ready", showOtherApps: false });
    await vi.waitFor(() =>
      expect(fixture.sent.some((message) => message.type === "roots")).toBe(
        true,
      ),
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(mocks.request).not.toHaveBeenCalledWith(
      "inspect.coverage",
      expect.anything(),
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
      expect(latestSession()).toBeTypeOf("string"),
    );
    mocks.notifications.get("spy.picked")?.({
      sessionId: latestSession(),
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
      expect(latestSession()).toBeTypeOf("string"),
    );
    mocks.notifications.get("spy.picked")?.({
      sessionId: latestSession(),
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
      completed: 2,
      total: 2,
      done: true,
      failed: false,
    });
    fixture.provider.dispose();
  });
  it("refreshes roots, stops picking when hidden, and releases notifications", async () => {
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(method === "inspect.refresh" ? { nodes: [], status: { running: true } } : []),
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
    mocks.notifications.get("spy.cancelled")?.({ sessionId: latestSession() });
    expect(fixture.sent.at(-1)?.picking).toBe(false);
    fixture.view.visible = false;
    fixture.visibility();
    await vi.waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith("spy.stop"),
    );
    fixture.provider.dispose();
    expect(fixture.notificationDisposals).toHaveLength(3);
  });
  it("reports stale node handles without reloading the tree on its own", async () => {
    mocks.request.mockImplementation((method: string) =>
      method === "inspect.children"
        ? Promise.reject(new RpcError(-32005, "gone"))
        : Promise.resolve(method === "inspect.refresh" ? { nodes: [], status: { running: false } } : []),
    );
    const fixture = await create();
    fixture.receive({ type: "expand", nodeId: "stale" });
    await vi.waitFor(() =>
      expect(fixture.sent).toContainEqual({
        type: "error",
        message: "The element is gone. Reload the objects view to refresh it.",
      }),
    );
    expect(mocks.request).not.toHaveBeenCalledWith("inspect.refresh", expect.anything());
    expect(mocks.request).not.toHaveBeenCalledWith("inspect.refresh");
    fixture.provider.dispose();
  });
  describe("automatic reloads", () => {
    const refreshes = () =>
      mocks.request.mock.calls.filter((call) => call[0] === "inspect.refresh").length;
    const loaded = async () => {
      mocks.markers = false;
      mocks.request.mockImplementation((method: string) =>
        Promise.resolve(method === "inspect.refresh" ? { nodes: [], status: { running: true, pids: [7] } } : []),
      );
      const fixture = await create();
      fixture.receive({ type: "ready" });
      await vi.waitFor(() => expect(refreshes()).toBe(1));
      await new Promise((resolve) => setTimeout(resolve, 20));
      return fixture;
    };
    const settle = () => new Promise((resolve) => setTimeout(resolve, 30));

    it("keeps the webview alive while the panel tab is hidden", async () => {
      const fixture = await create();
      expect(mocks.providerRegistrations).toHaveLength(1);
      expect(mocks.providerRegistrations[0][2]).toEqual({
        webviewOptions: { retainContextWhenHidden: true },
      });
      fixture.provider.dispose();
    });

    it("does not reload a loaded tree when the panel is shown again", async () => {
      const fixture = await loaded();
      fixture.visibility();
      await settle();
      expect(refreshes()).toBe(1);
      fixture.provider.dispose();
    });

    it("does not reload a loaded tree when project files change", async () => {
      const fixture = await loaded();
      for (const listener of mocks.projectListeners) listener();
      await settle();
      expect(refreshes()).toBe(1);
      fixture.provider.dispose();
    });

    it("loads when the panel is shown before anything has loaded", async () => {
      mocks.markers = false;
      mocks.request.mockImplementation((method: string) =>
        Promise.resolve(method === "inspect.refresh" ? { nodes: [], status: { running: true, pids: [7] } } : []),
      );
      const fixture = await create();
      fixture.visibility();
      await vi.waitFor(() => expect(refreshes()).toBe(1));
      fixture.provider.dispose();
    });

    it("still reloads when the reload button is pressed", async () => {
      const fixture = await loaded();
      fixture.receive({ type: "refresh" });
      await vi.waitFor(() => expect(refreshes()).toBe(2));
      fixture.provider.dispose();
    });
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
          return Promise.resolve([{ nodeId: "root", info: { processId: 1 } }]);
        return Promise.resolve(undefined);
      },
    );
    const fixture = await create();
    fixture.receive({ type: "pick" });
    await vi.waitFor(() =>
      expect(latestSession()).toBeTypeOf("string"),
    );
    mocks.notifications.get("spy.picked")?.({
      sessionId: latestSession(),
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
      expect(latestSession()).toBeTypeOf("string"),
    );
    mocks.notifications.get("spy.picked")?.({
      sessionId: latestSession(),
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
      expect(latestSession()).toBeTypeOf("string"),
    );
    mocks.notifications.get("spy.picked")?.({
      sessionId: latestSession(),
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
  it.each(["hide", "stop", "dispose"])("does not start a picker after %s while connecting", async (action) => {
    let finishConnection: (value: unknown) => void = () => {};
    const connect = vi.fn(() => new Promise((resolve) => { finishConnection = resolve; }));
    const fixture = await create(connect);
    mocks.request.mockResolvedValue(undefined);
    fixture.receive({ type: "pick" });
    await vi.waitFor(() => expect(connect).toHaveBeenCalledOnce());
    if (action === "hide") {
      fixture.view.visible = false;
      fixture.visibility();
    } else if (action === "stop") fixture.receive({ type: "stopPick" });
    else fixture.provider.dispose();
    finishConnection({ client: fixture.client, initialized: { config: {} } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mocks.request.mock.calls.some((call) => call[0] === "spy.start")).toBe(false);
    fixture.provider.dispose();
  });

  it("ignores notifications from stopped and superseded picker sessions", async () => {
    mocks.request.mockResolvedValue(undefined);
    const fixture = await create();
    fixture.receive({ type: "pick" });
    await vi.waitFor(() => expect(latestSession()).toBeTypeOf("string"));
    const first = latestSession();
    fixture.receive({ type: "stopPick" });
    fixture.receive({ type: "pick" });
    await vi.waitFor(() => expect(latestSession()).not.toBe(first));
    const before = fixture.sent.length;
    mocks.notifications.get("spy.hover")?.({ sessionId: first, node: { nodeId: "old" } });
    mocks.notifications.get("spy.picked")?.({ sessionId: first, node: { nodeId: "old" } });
    mocks.notifications.get("spy.cancelled")?.({ sessionId: first });
    expect(fixture.sent.slice(before)).toEqual([]);
    mocks.notifications.get("spy.hover")?.({ sessionId: latestSession(), node: { nodeId: "current" } });
    expect(fixture.sent.at(-1)).toMatchObject({ type: "hover", node: { nodeId: "current" } });
    fixture.provider.dispose();
  });

  it("shows picked properties before icons complete", async () => {
    const picked = { nodeId: "picked", info: { controlType: "Button", name: "Save" } };
    mocks.icons.mockImplementationOnce(() => new Promise(() => {}));
    mocks.request.mockImplementation((method: string) => {
      if (method === "inspect.properties") return Promise.resolve({ info: picked.info, properties: {}, ancestors: [] });
      if (method === "inspect.roots") return Promise.resolve([]);
      return Promise.resolve(undefined);
    });
    const fixture = await create();
    fixture.receive({ type: "pick" });
    await vi.waitFor(() => expect(latestSession()).toBeTypeOf("string"));
    mocks.notifications.get("spy.picked")?.({ sessionId: latestSession(), node: picked });
    await vi.waitFor(() => expect(fixture.sent.some((message) => message.type === "selected")).toBe(true));
    fixture.provider.dispose();
  });

  it("coalesces concurrent refreshes and consumes the combined status snapshot", async () => {
    let finish: (value: unknown) => void = () => {};
    mocks.markers = false;
    mocks.request.mockImplementation((method: string) => method === "inspect.refresh"
      ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve(undefined));
    const fixture = await create();
    const first = fixture.provider.refresh();
    const second = fixture.provider.refresh();
    await vi.waitFor(() => expect(mocks.request).toHaveBeenCalledWith("inspect.refresh", { includeOtherApps: true }));
    expect(mocks.request.mock.calls.filter((call) => call[0] === "inspect.refresh")).toHaveLength(1);
    finish({ nodes: [], status: { running: true, mainWindowTitle: "Combined snapshot" } });
    await Promise.all([first, second]);
    expect(mocks.request).not.toHaveBeenCalledWith("app.status");
    expect(fixture.sent).toContainEqual(expect.objectContaining({ type: "state", targetName: "Combined snapshot", appRunning: true }));
    fixture.provider.dispose();
  });

  it("tells the webview which application is selected so its root windows can be marked", async () => {
    mocks.markers = false;
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(method === "inspect.refresh" ? { nodes: [], status: { running: true, pids: [7, 9] } } : undefined),
    );
    const fixture = await create();
    await fixture.provider.refresh();
    expect(fixture.sent).toContainEqual(expect.objectContaining({ type: "state", appName: "Demo", appPids: [7, 9] }));
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(method === "inspect.refresh" ? { nodes: [], status: { running: false, pids: [] } } : undefined),
    );
    await fixture.provider.refresh();
    expect(fixture.sent.filter((message) => message.type === "state").at(-1)).toMatchObject({ appPids: [] });
    fixture.provider.dispose();
  });

  it("retains partial nodes and reports incomplete enumeration instead of retrying a full tree", async () => {
    const node = { nodeId: "partial", info: { controlType: "Window" } };
    mocks.markers = false;
    mocks.request.mockImplementation((method: string) => {
      if (method === "inspect.refresh") return Promise.reject(new RpcError(-32005, "partial", {
        nodes: [node], complete: false, errors: [{ index: 1, message: "Window closed" }],
      }));
      return Promise.resolve({ running: false });
    });
    const fixture = await create();
    await fixture.provider.refresh();
    expect(fixture.sent).toContainEqual({ type: "roots", nodes: [node] });
    expect(fixture.sent).toContainEqual(expect.objectContaining({ type: "enumerationIncomplete", message: expect.stringContaining("Window closed") }));
    expect(fixture.sent.some((message) => message.type === "error")).toBe(false);
    fixture.provider.dispose();
  });

  it("queues newly expanded coverage IDs without invalidating in-flight coverage", async () => {
    let finishCoverage: (value: unknown) => void = () => {};
    const root = { nodeId: "a", info: { controlType: "Window" } };
    const child = { nodeId: "b", info: { controlType: "Button" } };
    mocks.request.mockImplementation((method: string, params?: { nodeIds?: string[] }) => {
      if (method === "inspect.refresh") return Promise.resolve({ nodes: [root], status: { running: true } });
      if (method === "inspect.children") return Promise.resolve([child]);
      if (method === "inspect.coverage" && params?.nodeIds?.includes("a"))
        return new Promise((resolve) => { finishCoverage = resolve; });
      if (method === "inspect.coverage") return Promise.resolve({ covered: {}, pending: [] });
      return Promise.resolve(undefined);
    });
    const fixture = await create();
    await fixture.provider.refresh();
    fixture.receive({ type: "expand", nodeId: "a" });
    await vi.waitFor(() => expect(fixture.sent.some((message) => message.type === "children")).toBe(true));
    finishCoverage({ covered: { a: { count: 1, first: "Page.window" } }, pending: [] });
    await vi.waitFor(() => expect(fixture.sent.filter((message) => message.type === "coverage")).toHaveLength(2));
    expect(fixture.sent.filter((message) => message.type === "coverage").map((message) => message.nodeIds)).toEqual([["a"], ["b"]]);
    fixture.provider.dispose();
  });

  it("does not register a saved-definition preview command", async () => {
    const fixture = await create();
    expect(mocks.commands.has("wintestkit.spy.showDefinition")).toBe(false);
    expect(mocks.previews).not.toHaveBeenCalled();
    fixture.provider.dispose();
  });

  describe("keeping the selection through a reload", () => {
    const info = (controlType: string, name = "", extra: Record<string, string> = {}) =>
      ({ controlType, name, automationId: "", className: controlType === "Window" ? "W" : "P", ...extra });
    const root = { nodeId: "r1", hasChildren: true, info: info("Window", "App") };
    const route = [
      { controlType: "Window", automationId: "", name: "App", className: "W" },
      { controlType: "Pane", automationId: "ed", name: "Editor", className: "P", index: 1 },
      { controlType: "Button", automationId: "", name: "Save", className: "P", index: 0 },
    ];
    /** A server whose tree is rebuilt with new node ids on every call, as after a restart. */
    const serve = (options: { editor?: boolean; generation?: () => number } = {}) => {
      const { editor = true, generation = () => 1 } = options;
      const id = (name: string) => name + generation();
      mocks.request.mockImplementation((method: string, params?: { nodeId?: string }) => {
        if (method === "inspect.refresh")
          return Promise.resolve({ nodes: [{ ...root, nodeId: id("r") }], status: { running: true, pids: [1] } });
        if (method === "inspect.children") {
          if (params?.nodeId === id("r"))
            return Promise.resolve([
              { nodeId: id("a"), hasChildren: false, info: info("Pane") },
              ...(editor ? [{ nodeId: id("ed"), hasChildren: true, info: info("Pane", "Editor", { automationId: "ed" }) }] : []),
            ]);
          if (params?.nodeId === id("ed"))
            return Promise.resolve([{ nodeId: id("save"), hasChildren: false, info: info("Button", "Save") }]);
          return Promise.resolve([]);
        }
        if (method === "inspect.properties")
          return Promise.resolve({ info: info("Button", "Save"), properties: {}, ancestors: [] });
        return Promise.resolve(undefined);
      });
    };
    const selected = (fixture: Awaited<ReturnType<typeof create>>) =>
      fixture.sent.filter((message) => message.type === "selected").map((message) => message.nodeId);
    const memento = (initial: Record<string, unknown> = {}) => {
      const store = new Map<string, unknown>(Object.entries(initial));
      return {
        store,
        get: (key: string) => store.get(key),
        update: vi.fn((key: string, value: unknown) => { store.set(key, value); return Promise.resolve(); }),
      };
    };
    const selectSave = (fixture: Awaited<ReturnType<typeof create>>) => {
      fixture.receive({ type: "select", nodeId: "save1", path: route });
      return vi.waitFor(() => expect(selected(fixture)).toEqual(["save1"]));
    };

    it("selects the same object again after a reload, opening the tree down to it", async () => {
      serve();
      const fixture = await create();
      await selectSave(fixture);
      await fixture.provider.refresh();
      await vi.waitFor(() => expect(selected(fixture)).toEqual(["save1", "save1"]));
      const opened = fixture.sent.filter((message) => message.type === "children" && message.expanded).map((message) => message.nodeId);
      expect(opened).toEqual(["r1", "ed1"]);
      expect(fixture.sent).toContainEqual({ type: "selectionRestored", nodeId: "save1" });
      expect(mocks.warning).not.toHaveBeenCalled();
      fixture.provider.dispose();
    });

    it("finds it under the new node ids after a server restart", async () => {
      let generation = 1;
      serve({ generation: () => generation });
      const fixture = await create();
      await selectSave(fixture);
      generation = 2; // the restarted server numbers everything afresh
      serve({ generation: () => generation });
      await fixture.provider.refresh();
      await vi.waitFor(() => expect(selected(fixture)).toEqual(["save1", "save2"]));
      expect(mocks.warning).not.toHaveBeenCalled();
      fixture.provider.dispose();
    });

    it("says so in a VS Code notification when it is gone, once, and selects nothing", async () => {
      serve();
      const fixture = await create();
      await selectSave(fixture);
      serve({ editor: false });
      await fixture.provider.refresh();
      await vi.waitFor(() => expect(mocks.warning).toHaveBeenCalledOnce());
      expect(mocks.warning.mock.calls[0][0]).toContain('Button "Save"');
      expect(mocks.warning.mock.calls[0][0]).toContain("could not find");
      expect(selected(fixture)).toEqual(["save1"]); // nothing new was selected
      await fixture.provider.refresh();
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(mocks.warning).toHaveBeenCalledOnce(); // it has been forgotten, so it is not repeated
      fixture.provider.dispose();
    });

    it("reports a window that has closed", async () => {
      serve();
      const fixture = await create();
      await selectSave(fixture);
      mocks.request.mockImplementation((method: string) =>
        Promise.resolve(method === "inspect.refresh" ? { nodes: [], status: { running: false, pids: [] } } : []));
      await fixture.provider.refresh();
      await vi.waitFor(() => expect(mocks.warning).toHaveBeenCalledOnce());
      fixture.provider.dispose();
    });

    it("remembers the selection in the workspace, so a VS Code reload keeps it too", async () => {
      serve();
      const first = memento();
      const before = await create(undefined, undefined, first);
      await selectSave(before);
      expect(first.update).toHaveBeenCalled();
      expect(first.store.get("wintestkit.spy.selection")).toEqual({ demo: route });
      before.provider.dispose();
      // a new window: nothing selected yet, but the workspace remembers
      mocks.request.mockClear();
      serve();
      const after = await create(undefined, undefined, first);
      await after.provider.refresh();
      await vi.waitFor(() => expect(selected(after)).toEqual(["save1"]));
      after.provider.dispose();
    });

    it("ignores a damaged or foreign saved selection", async () => {
      serve();
      const store = memento({ "wintestkit.spy.selection": { demo: [{ controlType: 5 }], other: route } });
      const fixture = await create(undefined, undefined, store);
      await fixture.provider.refresh();
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(selected(fixture)).toEqual([]);
      expect(mocks.warning).not.toHaveBeenCalled();
      fixture.provider.dispose();
    });

    it("keeps a different object the user selects after the restore", async () => {
      serve();
      const fixture = await create();
      await selectSave(fixture);
      fixture.receive({ type: "select", nodeId: "a1", path: [route[0], { controlType: "Pane", automationId: "", name: "", className: "P", index: 0 }] });
      await vi.waitFor(() => expect(selected(fixture)).toEqual(["save1", "a1"]));
      await fixture.provider.refresh();
      await vi.waitFor(() => expect(selected(fixture)).toEqual(["save1", "a1", "a1"]));
      fixture.provider.dispose();
    });

    it("does not restore after a change of scope, which is not a reload of the same view", async () => {
      serve();
      const fixture = await create();
      await selectSave(fixture);
      fixture.receive({ type: "showOtherApps", enabled: false });
      await vi.waitFor(() => expect(mocks.request.mock.calls.filter(([method]) => method === "inspect.refresh")).toHaveLength(1));
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(selected(fixture)).toEqual(["save1"]);
      expect(mocks.warning).not.toHaveBeenCalled();
      await fixture.provider.refresh(); // but the next ordinary reload still can
      await vi.waitFor(() => expect(selected(fixture)).toEqual(["save1", "save1"]));
      fixture.provider.dispose();
    });

    it("does nothing when nothing was selected", async () => {
      serve();
      const fixture = await create();
      await fixture.provider.refresh();
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(selected(fixture)).toEqual([]);
      expect(mocks.warning).not.toHaveBeenCalled();
      expect(mocks.request.mock.calls.some(([method]) => method === "inspect.children")).toBe(false);
      fixture.provider.dispose();
    });

    it("rejects a malformed route from the webview", async () => {
      serve();
      const fixture = await create();
      fixture.receive({ type: "select", nodeId: "save1", path: [{ controlType: 5 }] });
      await vi.waitFor(() => expect(selected(fixture)).toEqual(["save1"])); // still selects
      await fixture.provider.refresh();
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(selected(fixture)).toEqual(["save1"]); // but nothing was remembered
      fixture.provider.dispose();
    });
  });

  describe("pinned properties", () => {
    const properties = () =>
      Promise.resolve({ info: { name: "Save", controlType: "Button" }, properties: {}, ancestors: [] });
    const propertyRequests = () =>
      mocks.request.mock.calls.filter(([method]) => method === "inspect.properties").map(([, params]) => params);
    const lastState = (fixture: Awaited<ReturnType<typeof create>>) =>
      fixture.sent.filter((message) => message.type === "state").at(-1);

    it("keeps the list in the user's settings and tells the panel, ignoring invalid names", async () => {
      mocks.shownProperties = ["HelpText", "bad name", "Name", "HelpText", 5, "<x>"];
      const fixture = await create();
      fixture.receive({ type: "ready" });
      await vi.waitFor(() => expect(lastState(fixture)).toMatchObject({ shownProperties: ["HelpText", "Name"] }));
      fixture.provider.dispose();
    });

    it("treats a setting that is not a list as empty", async () => {
      mocks.shownProperties = "HelpText";
      const fixture = await create();
      fixture.receive({ type: "ready" });
      await vi.waitFor(() => expect(lastState(fixture)).toMatchObject({ shownProperties: [] }));
      fixture.provider.dispose();
    });

    it("asks the server to read the pinned properties with every selection", async () => {
      mocks.shownProperties = ["HelpText", "Orientation"];
      mocks.request.mockImplementation((method: string) => method === "inspect.properties" ? properties() : Promise.resolve(undefined));
      const fixture = await create();
      fixture.receive({ type: "select", nodeId: "control" });
      await vi.waitFor(() => expect(propertyRequests()).toEqual([{ nodeId: "control", include: ["HelpText", "Orientation"] }]));
      fixture.provider.dispose();
    });

    it("sends no extra names when nothing is pinned", async () => {
      mocks.request.mockImplementation((method: string) => method === "inspect.properties" ? properties() : Promise.resolve(undefined));
      const fixture = await create();
      fixture.receive({ type: "select", nodeId: "control" });
      await vi.waitFor(() => expect(propertyRequests()).toEqual([{ nodeId: "control" }]));
      fixture.provider.dispose();
    });

    it("reads them for a picked object too", async () => {
      mocks.shownProperties = ["HelpText"];
      mocks.request.mockImplementation((method: string) => {
        if (method === "inspect.properties") return Promise.resolve({ info: { controlType: "Button", name: "Save" }, properties: {}, ancestors: [] });
        if (method === "inspect.roots") return Promise.resolve([]);
        return Promise.resolve(undefined);
      });
      const fixture = await create();
      fixture.receive({ type: "pick" });
      await vi.waitFor(() => expect(latestSession()).toBeTypeOf("string"));
      mocks.notifications.get("spy.picked")?.({ sessionId: latestSession(), node: { nodeId: "picked", info: { controlType: "Button", name: "Save" } } });
      await vi.waitFor(() => expect(propertyRequests()).toEqual([{ nodeId: "picked", includeAncestors: true, include: ["HelpText"] }]));
      fixture.provider.dispose();
    });

    it("pins and unpins in the user settings, never a project's", async () => {
      mocks.shownProperties = ["HelpText"];
      const fixture = await create();
      fixture.receive({ type: "pinProperty", name: "Orientation", pinned: true });
      await vi.waitFor(() => expect(mocks.updateConfig).toHaveBeenCalledWith("shownProperties", ["HelpText", "Orientation"], 1));
      fixture.receive({ type: "pinProperty", name: "HelpText", pinned: false });
      await vi.waitFor(() => expect(mocks.updateConfig).toHaveBeenCalledWith("shownProperties", [], 1));
      fixture.provider.dispose();
    });

    it("changes nothing when the property is already pinned or already absent", async () => {
      mocks.shownProperties = ["HelpText"];
      const fixture = await create();
      fixture.receive({ type: "pinProperty", name: "HelpText", pinned: true });
      fixture.receive({ type: "pinProperty", name: "Other", pinned: false });
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(mocks.updateConfig).not.toHaveBeenCalled();
      fixture.provider.dispose();
    });

    it("never holds more than 64 pinned properties, and tells the panel when it refuses", async () => {
      mocks.shownProperties = Array.from({ length: 64 }, (_, index) => "P" + index);
      const fixture = await create();
      fixture.receive({ type: "ready" });
      await vi.waitFor(() => expect(lastState(fixture)).toBeDefined());
      const states = fixture.sent.filter((message) => message.type === "state").length;
      fixture.receive({ type: "pinProperty", name: "OneMore", pinned: true });
      await vi.waitFor(() => expect(fixture.sent.some((message) => message.type === "error")).toBe(true));
      expect(mocks.updateConfig).not.toHaveBeenCalled();
      expect(fixture.sent.find((message) => message.type === "error")).toMatchObject({ message: expect.stringContaining("At most 64") });
      expect(fixture.sent.filter((message) => message.type === "state").length).toBeGreaterThan(states);
      expect(lastState(fixture)?.shownProperties).not.toContain("OneMore");
      fixture.provider.dispose();
    });

    it("ignores a request for a name that is not a property name", async () => {
      const fixture = await create();
      fixture.receive({ type: "pinProperty", name: "not a name", pinned: true });
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(mocks.updateConfig).not.toHaveBeenCalled();
      fixture.provider.dispose();
    });

    it("tells the panel when the setting changes elsewhere", async () => {
      const fixture = await create();
      fixture.receive({ type: "ready" });
      await vi.waitFor(() => expect(lastState(fixture)).toMatchObject({ shownProperties: [] }));
      mocks.shownProperties = ["Orientation"];
      for (const listener of mocks.configListeners)
        listener({ affectsConfiguration: (key) => key === "wintestkit.spy.shownProperties" });
      expect(lastState(fixture)).toMatchObject({ shownProperties: ["Orientation"] });
      fixture.provider.dispose();
    });
  });

  describe("opening a preview in the image viewer", () => {
    const url = "data:image/webp;base64,UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==";
    it("hands the chosen live image to the viewer", async () => {
      mocks.showPreview.mockClear();
      const fixture = await create();
      fixture.receive({ type: "openPreview", view: "window", dataUrl: url });
      await vi.waitFor(() => expect(mocks.showPreview).toHaveBeenCalledWith("window", url));
      fixture.provider.dispose();
      expect(mocks.disposeViewer).toHaveBeenCalled();
    });
    it("reports a viewer failure in the panel", async () => {
      mocks.showPreview.mockRejectedValueOnce(new Error("disk full"));
      const fixture = await create();
      fixture.receive({ type: "openPreview", view: "element", dataUrl: url });
      await vi.waitFor(() => expect(fixture.sent).toContainEqual({ type: "error", message: "disk full" }));
      fixture.provider.dispose();
    });
    it.each([
      { view: "other", dataUrl: url },
      { view: "element", dataUrl: "https://example.test/a.webp" },
      { view: "element", dataUrl: 5 },
      { view: "element", dataUrl: url + "x".repeat(30_000_000) },
    ])("ignores a malformed request %#", async (request) => {
      mocks.showPreview.mockClear();
      const fixture = await create();
      fixture.receive({ type: "openPreview", ...request });
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect(mocks.showPreview).not.toHaveBeenCalled();
      fixture.provider.dispose();
    });
  });

  describe("live object preview", () => {
    const webp = "UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==";
    it.each(["element", "context"])("renders the %s preview as a live capture", (mode) => {
      const script = readFileSync("media/spy/spy.js", "utf8");
      const start = script.indexOf("  const webpUrl = (value) =>");
      const stop = script.indexOf("  const loadingPreview = () =>");
      expect(start).toBeGreaterThan(0);
      expect(stop).toBeGreaterThan(start);
      const image = { src: "", hidden: true, alt: "" };
      const status = { textContent: "" };
      const context = {
        previewMode: mode,
        previewImages: undefined as unknown,
        preview: {
          elementDataUrl: "data:image/webp;base64," + webp,
          windowDataUrl: "data:image/webp;base64,AAAA",
          capturedAt: "2026-01-01T00:00:00Z",
        },
        element: (id: string) => id === "object-preview-image" ? image
          : id === "object-preview-status" ? status : { setAttribute: vi.fn() },
      };
      runInNewContext(script.slice(start, stop) + "\nrenderObjectPreview(preview);", context);
      expect(image.src).toBe(mode === "context" ? context.preview.windowDataUrl : context.preview.elementDataUrl);
      expect(image.hidden).toBe(false);
      expect(status.textContent).toBe("Live capture." + (mode === "context" ? " The object is outlined in red." : ""));
      expect(context.previewImages).not.toHaveProperty("capturedAt");
    });
    const select = async (preview: () => Promise<unknown>) => {
      mocks.request.mockImplementation((method: string) =>
        method === "inspect.preview" ? preview() : Promise.resolve(method === "inspect.properties"
          ? { info: {}, properties: {}, ancestors: [] } : method === "suggest.locator"
            ? { helpers: [], code: "Element()" } : method === "inspect.definitions"
              ? { definitions: [], errors: [], pageCount: 1, appRunning: true } : undefined));
      const fixture = await create();
      fixture.receive({ type: "select", nodeId: "control" });
      await vi.waitFor(() => expect(fixture.sent.some((message) => message.type === "objectPreview")).toBe(true));
      return fixture;
    };
    it("asks the server for the selected object's crop and window and forwards validated images", async () => {
      const entry = { data: webp, width: 1, height: 1 };
      const fixture = await select(() => Promise.resolve({ element: entry, window: entry }));
      expect(mocks.request).toHaveBeenCalledWith("inspect.preview", { nodeId: "control" });
      const url = "data:image/webp;base64," + webp;
      expect(fixture.sent).toContainEqual({ type: "objectPreview", nodeId: "control",
        preview: { elementDataUrl: url, windowDataUrl: url } });
      expect(mocks.previews).not.toHaveBeenCalled();
      fixture.provider.dispose();
    });
    it("forwards the reason when the server cannot capture", async () => {
      const fixture = await select(() => Promise.resolve({ reason: "The window cannot be captured." }));
      expect(fixture.sent).toContainEqual({ type: "objectPreview", nodeId: "control", reason: "The window cannot be captured." });
      fixture.provider.dispose();
    });
    it("rejects a malformed capture instead of forwarding it", async () => {
      const fixture = await select(() => Promise.resolve({ element: { data: "AAAA", width: 1, height: 1 }, window: {} }));
      const message = fixture.sent.find((entry) => entry.type === "objectPreview");
      expect(message).toMatchObject({ reason: "The automation server returned an invalid preview." });
      expect(message).not.toHaveProperty("preview");
      fixture.provider.dispose();
    });
    it("explains that an older wintestkit package cannot capture previews", async () => {
      const fixture = await select(() => Promise.reject(new RpcError(-32601, "method not found")));
      expect(fixture.sent).toContainEqual(expect.objectContaining({ type: "objectPreview", reason: expect.stringContaining("newer wintestkit") }));
      fixture.provider.dispose();
    });
    it("reports a failed capture without disturbing the selection", async () => {
      const fixture = await select(() => Promise.reject(new Error("pipe closed")));
      expect(fixture.sent).toContainEqual(expect.objectContaining({ type: "objectPreview", reason: expect.stringContaining("pipe closed") }));
      expect(fixture.sent.some((message) => message.type === "selected")).toBe(true);
      fixture.provider.dispose();
    });
  });

  it("does not let a superseded connection clear newer roots", async () => {
    const client = {
      request: mocks.request,
      onNotification: (name: string, callback: (value: unknown) => void) => {
        mocks.notifications.set(name, callback);
        return { dispose: () => mocks.notifications.delete(name) };
      },
    };
    const pending: Array<(value: { client: typeof client; initialized: unknown }) => void> = [];
    const connect = vi.fn(
      () =>
        new Promise<{ client: typeof client; initialized: unknown }>((resolve) => {
          pending.push(resolve);
        }),
    );
    const fixture = await create(connect);
    mocks.request.mockImplementation((method: string) =>
      Promise.resolve(
        method === "inspect.refresh"
          ? { nodes: [{ nodeId: "fresh", info: { processId: 1 } }], status: { running: true } }
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
    pending[1]({ client, initialized: { config: {} } });
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
    pending[0]({ client, initialized: { config: {} } });
    await first;
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fixture.sent.filter((message) => message.type === "roots")).toEqual([
      {
        type: "roots",
        nodes: [{ nodeId: "fresh", info: { processId: 1 } }],
      },
    ]);
    fixture.provider.dispose();
  });
});
