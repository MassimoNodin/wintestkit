import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import { RpcError } from "../../src/server/jsonrpc";

const mocks = vi.hoisted(() => ({
  log: { info: vi.fn(), error: vi.fn(), show: vi.fn(), dispose: vi.fn() },
  request: vi.fn<(method: string) => Promise<unknown>>(() =>
    Promise.resolve(null),
  ),
  refreshSpy: vi.fn(() => Promise.resolve()),
  refreshStatus: vi.fn(() => Promise.resolve()),
  beginTransition: vi.fn(),
  setStage: vi.fn(),
  endTransition: vi.fn(),
  readConfig: vi.fn(),
  showError: vi.fn(),
  showWarning: vi.fn(),
  serverGet: vi.fn(),
  runTerminal: vi.fn(() => Promise.resolve()),
  folder: {
    uri: { fsPath: "C:\demo", toString: () => "file:///C:/demo" },
    name: "demo",
  },
  registerCommand: vi.fn<
    (
      command: string,
      callback: (target?: vscode.TreeItem) => unknown,
    ) => vscode.Disposable
  >(() => ({ dispose: vi.fn() })),
  executeCommand: vi.fn(() => Promise.resolve()),
  registerTreeDataProvider: vi.fn<
    (id: string, provider: unknown) => vscode.Disposable
  >(() => ({ dispose: vi.fn() })),
  registerWebviewViewProvider: vi.fn<
    (id: string, provider: unknown) => vscode.Disposable
  >(() => ({ dispose: vi.fn() })),
}));

vi.mock("vscode", () => ({
  window: {
    showErrorMessage: mocks.showError,
    showWarningMessage: mocks.showWarning,
    registerCustomEditorProvider: vi.fn(() => ({ dispose: vi.fn() })),
    createOutputChannel: () => mocks.log,
    registerTreeDataProvider: mocks.registerTreeDataProvider,
    registerWebviewViewProvider: mocks.registerWebviewViewProvider,
  },
  commands: {
    registerCommand: mocks.registerCommand,
    executeCommand: mocks.executeCommand,
  },
  workspace: {
    createFileSystemWatcher: vi.fn(() => ({
      dispose: vi.fn(),
      onDidCreate: vi.fn(() => ({ dispose: vi.fn() })),
      onDidChange: vi.fn(() => ({ dispose: vi.fn() })),
      onDidDelete: vi.fn(() => ({ dispose: vi.fn() })),
    })),
    workspaceFolders: [mocks.folder],
    getWorkspaceFolder: () => mocks.folder,
    onDidChangeConfiguration: vi.fn(() => ({ dispose: vi.fn() })),
  },
}));
vi.mock("../../src/python", () => ({
  installPackage: vi.fn(),
  runTerminal: mocks.runTerminal,
  onDidChangeInterpreter: vi.fn(() => Promise.resolve({ dispose: vi.fn() })),
}));
vi.mock("../../src/settings/editor", () => ({
  settingsEditorId: "wintestkit.configuration",
  ConfigurationEditor: class {
    open = vi.fn(() => Promise.resolve());
  },
}));
vi.mock("../../src/settings/testApp", () => ({
  TestAppView: class {
    refresh() {}
    dispose() {}
  },
}));
vi.mock("../../src/settings/files", () => ({
  readConfiguration: mocks.readConfig,
}));
vi.mock("../../src/server/serverManager", () => ({
  ServerManager: class {
    get(project?: unknown) {
      mocks.serverGet(project);
      return Promise.resolve({
        client: {
          request: mocks.request,
          onNotification: () => ({ dispose() {} }),
        },
      });
    }
    restart() {
      return this.get();
    }
    dispose() {}
    shutdown() {
      return Promise.resolve();
    }
  },
}));
vi.mock("../../src/statusBar", () => ({
  StatusBar: class {
    refresh = mocks.refreshStatus;
    beginTransition = mocks.beginTransition;
    setStage = mocks.setStage;
    endTransition = mocks.endTransition;
    dispose() {}
  },
}));
vi.mock("../../src/projects", () => ({
  Projects: class {
    all = [{ root: mocks.folder.uri, name: mocks.folder.name }];
    projectFor(uri?: vscode.Uri) {
      if (uri?.fsPath === "C:/other") return { root: uri, name: "other" };
      return this.all[0];
    }
    onDidChange() {
      return { dispose: vi.fn() };
    }
    refresh() {
      return Promise.resolve();
    }
    dispose() {}
  },
}));
vi.mock("../../src/discovery/store", () => ({
  DiscoveryStore: class {
    dispose() {}
  },
}));
vi.mock("../../src/editor/codeLens", () => ({
  CodeLenses: class {
    dispose() {}
  },
}));
vi.mock("../../src/editor/decorations", () => ({
  CheckResultsStore: class {
    dispose() {}
  },
  CheckDecorations: class {
    dispose() {}
  },
}));
vi.mock("../../src/editor/flowRuns", () => ({
  FlowRuns: class {
    constructor() {
      mocks.registerCommand("wintestkit.runFlow", () => {});
    }
    dispose() {}
  },
}));
vi.mock("../../src/editor/checkAfterFlow", () => ({
  CheckAfterFlow: class {
    constructor() {
      mocks.registerCommand("wintestkit.checkAfterFlow", () => {});
    }
    afterFlow = vi.fn(() => Promise.resolve());
    dispose() {}
  },
}));
vi.mock("../../src/editor/projectSweep", () => ({
  ProjectSweep: class {
    constructor() { mocks.registerCommand("wintestkit.sweepProject", () => {}); }
    dispose() {}
  },
}));
vi.mock("../../src/views/unusedDefinitions", () => ({
  UnusedDefinitions: class {
    dispose() {}
  },
}));
vi.mock("../../src/editor/relocationActions", () => ({
  RelocationActions: class {
    dispose() {}
  },
}));
vi.mock("../../src/editor/highlightCommands", () => ({
  HighlightCommands: class {
    constructor() {
      for (const command of [
        "wintestkit.highlightElement",
        "wintestkit.checkElement",
        "wintestkit.checkPage",
      ])
        mocks.registerCommand(command, () => {});
    }
    dispose() {}
  },
}));

import { activate } from "../../src/extension";
vi.mock("../../src/spy/insertElement", () => ({
  registerInsertElement: () => ({ dispose() {} }),
}));
vi.mock("../../src/spy/spyView", () => ({
  SpyView: class {
    refreshForProject = mocks.refreshSpy;
    constructor() {
      mocks.registerWebviewViewProvider("wintestkit.spy", {});
      mocks.registerCommand("wintestkit.spy.startPick", () => {});
      mocks.registerCommand("wintestkit.spy.refresh", () => {});
      mocks.registerCommand("wintestkit.spy.revealRelocation", () => {});
    }
    dispose() {}
  },
}));
vi.mock("../../src/views/elementsTree", () => ({
  ElementsTree: class {
    constructor() {
      mocks.registerWebviewViewProvider("wintestkit.navigation", {});
      mocks.registerCommand("wintestkit.elements.goTo", () => {});
    }
    dispose() {}
  },
}));
vi.mock("../../src/init", () => ({
  registerInitialize: () =>
    mocks.registerCommand("wintestkit.initProject", () => {}),
}));
vi.mock("../../src/pytestConflict", () => ({
  PytestConflict: class {
    dispose() {}
  },
}));
vi.mock("../../src/testing/controller", () => ({
  TestController: class {
    constructor() {}
    dispose() {}
  },
}));

const manifest = JSON.parse(readFileSync("package.json", "utf8"));

describe("extension scaffold", () => {
  let subscriptions: vscode.Disposable[];

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.readConfig.mockResolvedValue({ "app.path": "C:/Apps/Demo.exe" });
    mocks.request.mockImplementation(async (method) =>
      method === "app.status"
        ? { running: true, pids: [12], owned: true }
        : null,
    );
    mocks.showWarning.mockResolvedValue("Close App");
    subscriptions = [];
    activate({
      subscriptions,
      extension: { packageJSON: manifest },
      asAbsolutePath: (relative: string) => "C:/ext/" + relative,
    } as unknown as vscode.ExtensionContext);
  });

  it("activates, logs, and registers every contributed command and view", () => {
    expect(mocks.log.info).toHaveBeenCalledWith("WinTestKit activated");
    expect(
      mocks.registerCommand.mock.calls.map(([command]) => command).sort(),
    ).toEqual(
      manifest.contributes.commands
        .map((command: { command: string }) => command.command)
        .concat("wintestkit.launchAppStrict")
        .sort(),
    );
    expect(mocks.registerWebviewViewProvider).toHaveBeenCalledWith(
      "wintestkit.navigation",
      expect.any(Object),
    );
    expect(mocks.registerWebviewViewProvider).toHaveBeenCalledWith(
      "wintestkit.spy",
      expect.any(Object),
    );
    expect(manifest.contributes.views.wintestkit).toEqual([
      { id: "wintestkit.setup", name: "Test Target", type: "webview" },
      { id: "wintestkit.navigation", name: "Pages & Flows", type: "webview" },
      { id: "wintestkit.spy", name: "Spy", type: "webview" },
    ]);
    expect(
      JSON.stringify(manifest.contributes.menus["view/title"]),
    ).not.toContain("wintestkit.spy");
    expect(subscriptions.length).toBeGreaterThan(
      manifest.contributes.commands.length + 3,
    );
  });

  it("opens native Testing from the Pages & Flows toolbar", async () => {
    const openTesting = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.openTesting",
    );
    await openTesting?.[1]();
    expect(mocks.executeCommand).toHaveBeenCalledWith(
      "workbench.view.testing.focus",
    );
    expect(manifest.contributes.menus["view/title"]).toContainEqual({
      command: "wintestkit.openTesting",
      when: "view == wintestkit.navigation",
      group: "navigation@1",
    });
  });
  it("shows output and runs doctor with the selected project", async () => {
    const showOutput = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.showOutput",
    );
    const runDoctor = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.runDoctor",
    );
    expect(showOutput).toBeDefined();
    expect(runDoctor).toBeDefined();
    showOutput?.[1]();
    await runDoctor?.[1]();
    expect(mocks.log.show).toHaveBeenCalledOnce();
    expect(mocks.runTerminal).toHaveBeenCalledWith(mocks.folder.uri, [
      "-m",
      "wintestkit",
      "--root",
      mocks.folder.uri.fsPath,
      "doctor",
    ]);
  });

  it.each([
    ["launchApp", ["app.launch"]],
    ["closeApp", ["app.close"]],
    ["restartApp", ["app.close", "app.launch"]],
    ["refreshApp", []],
  ])(
    "runs %s for the setup row's project and refreshes its state",
    async (command, methods) => {
      const root = {
        fsPath: "C:/other",
        toString: () => "file:///C:/other",
      } as vscode.Uri;
      const callback = mocks.registerCommand.mock.calls.find(
        ([registered]) => registered === "wintestkit." + command,
      )?.[1];
      expect(callback).toBeDefined();
      await callback?.({ resourceUri: root } as vscode.TreeItem);
      expect(mocks.request.mock.calls.map(([method]) => method)).toEqual(
        methods.includes("app.close") ? ["app.status", ...methods] : methods,
      );
      if (methods.length)
        expect(mocks.serverGet).toHaveBeenCalledWith({ root, name: "other" });
      expect(mocks.refreshSpy).toHaveBeenCalledWith({ root, name: "other" });
      expect(mocks.refreshStatus).toHaveBeenCalledOnce();
    },
  );

  it("records a launch as starting with its timeout, then as done", async () => {
    mocks.readConfig.mockResolvedValue({
      "app.path": "C:/Apps/Demo.exe",
      "app.startup_timeout": 12,
    });
    const callback = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.launchApp",
    )?.[1];
    await callback?.();
    expect(mocks.beginTransition).toHaveBeenCalledWith(
      expect.anything(),
      "starting",
      12_000,
      "launch",
    );
    expect(mocks.endTransition).toHaveBeenCalledExactlyOnceWith(
      expect.anything(),
    );
    expect(mocks.request).toHaveBeenCalledWith("app.launch", {}, 17_000);
  });

  it("sets launch RPC deadline beyond the configured startup timeout", async () => {
    mocks.readConfig.mockResolvedValue({
      "app.path": "C:/Apps/Demo.exe",
      "app.startup_timeout": 60,
    });
    const callback = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.launchApp",
    )?.[1];
    await callback?.();
    expect(mocks.request).toHaveBeenCalledWith("app.launch", {}, 65_000);
  });

  it("sets close RPC deadline from close_timeout rather than startup_timeout", async () => {
    mocks.readConfig.mockResolvedValue({
      "app.path": "C:/Apps/Demo.exe",
      "app.startup_timeout": 60,
      "app.close_timeout": 35,
    });
    const callback = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.closeApp",
    )?.[1];
    await callback?.();
    expect(mocks.request).toHaveBeenCalledWith("app.close", {}, 40_000);
  });

  it("rejects unbounded app RPC timeouts before requesting lifecycle changes", async () => {
    mocks.readConfig.mockResolvedValue({
      "app.path": "C:/Apps/Demo.exe",
      "app.startup_timeout": Number.POSITIVE_INFINITY,
    });
    const callback = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.launchApp",
    )?.[1];
    await callback?.();
    expect(mocks.request).not.toHaveBeenCalledWith("app.launch", {}, expect.any(Number));
    expect(mocks.showError).toHaveBeenCalledWith(
      expect.stringContaining("finite positive number"),
    );
  });

  it("propagates staged launch failure to recovery callers", async () => {
    mocks.readConfig.mockResolvedValue({ "app.path": "C:/Apps/Demo.exe" });
    mocks.request.mockRejectedValueOnce(new Error("Launch failed"));
    const callback = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.launchAppStrict",
    )?.[1];
    await expect(callback?.()).rejects.toThrow("Launch failed");
    expect(mocks.showError).not.toHaveBeenCalled();
    expect(mocks.endTransition).toHaveBeenCalledWith(expect.anything(), {
      action: "launch",
      message: "Launch failed",
    });
  });

  it("records a restart as one action: closing, then starting", async () => {
    mocks.readConfig.mockResolvedValue({ "app.path": "C:/Apps/Demo.exe" });
    const callback = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.restartApp",
    )?.[1];
    await callback?.();
    expect(
      mocks.beginTransition.mock.calls.map(([, kind, , action]) => [
        kind,
        action,
      ]),
    ).toEqual([
      ["stopping", "restart"],
      ["starting", "restart"],
    ]);
  });

  it("runs environment recovery for the originating project", async () => {
    const projectRoot = {
      fsPath: "C:/other",
      toString: () => "file:///C:/other",
    } as vscode.Uri;
    const callback = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.runDoctor",
    )?.[1];
    await callback?.({ resourceUri: projectRoot } as vscode.TreeItem);
    expect(mocks.runTerminal).toHaveBeenCalledWith(projectRoot, [
      "-m",
      "wintestkit",
      "--root",
      "C:/other",
      "doctor",
    ]);
  });
  it("preserves classified environment failures for the Test Target recovery action", async () => {
    mocks.request.mockRejectedValueOnce(
      new RpcError(-32005, "UI Automation is not available"),
    );
    const callback = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.launchApp",
    )?.[1];
    await callback?.();
    expect(mocks.endTransition).toHaveBeenCalledWith(
      expect.anything(),
      {
        action: "launch",
        message: "UI Automation is not available",
        environment: true,
      },
    );
  });
  it("records why a launch failed so the Test Target section can show it", async () => {
    mocks.readConfig.mockResolvedValue({ "app.path": "C:/Apps/Demo.exe" });
    mocks.request.mockRejectedValueOnce(
      new Error("Demo.exe did not show a window within 30s"),
    );
    const callback = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.launchApp",
    )?.[1];
    await callback?.();
    expect(mocks.endTransition).toHaveBeenCalledWith(expect.anything(), {
      action: "launch",
      message: "Demo.exe did not show a window within 30s",
    });
    expect(mocks.showError).toHaveBeenCalled();
  });

  it("does not close an attached app when restart has no executable", async () => {
    mocks.readConfig.mockResolvedValue({ "app.process": "CalculatorApp.exe" });
    const callback = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.restartApp",
    )?.[1];
    await callback?.();
    expect(mocks.request).not.toHaveBeenCalled();
    expect(mocks.showError).toHaveBeenCalledWith(
      expect.stringContaining("executable"),
    );
    expect(mocks.refreshStatus).toHaveBeenCalledOnce();
  });

  it.each(["closeApp", "restartApp"])(
    "requires confirmation before %s closes an attached app",
    async (command) => {
      mocks.readConfig.mockResolvedValue({
        "app.path": "C:/Apps/Demo.exe",
        "app.process": "Demo.exe",
        launch: "attach",
      });
      mocks.showWarning.mockResolvedValueOnce(undefined);
      const callback = mocks.registerCommand.mock.calls.find(
        ([registered]) => registered === `wintestkit.${command}`,
      )?.[1];
      await callback?.();
      expect(mocks.showWarning).toHaveBeenCalledWith(
        expect.stringContaining("WinTestKit did not start this process"),
        { modal: true },
        "Close App",
      );
      expect(mocks.request).not.toHaveBeenCalledWith("app.close");
    },
  );

  it.each([
    ["closeApp", ["app.close"]],
    ["restartApp", ["app.close", "app.launch"]],
  ])("closes an attached app through %s only after confirmation", async (command, methods) => {
    mocks.readConfig.mockResolvedValue({
      "app.path": "C:/Apps/Demo.exe",
      "app.process": "Demo.exe",
      launch: "attach",
    });
    const callback = mocks.registerCommand.mock.calls.find(
      ([registered]) => registered === `wintestkit.${command}`,
    )?.[1];
    await callback?.();
    expect(mocks.showWarning).toHaveBeenCalledOnce();
    expect(mocks.request.mock.calls.map(([method]) => method)).toEqual([
      "app.status",
      ...methods,
    ]);
  });

  it("confirms a process that Launch mode did not start", async () => {
    mocks.readConfig.mockResolvedValue({ "app.path": "C:/Apps/Demo.exe", launch: "per-test" });
    mocks.request.mockResolvedValueOnce({ running: true, pids: [9], owned: false });
    const callback = mocks.registerCommand.mock.calls.find(
      ([registered]) => registered === "wintestkit.closeApp",
    )?.[1];
    await callback?.();
    expect(mocks.showWarning).toHaveBeenCalledOnce();
    expect(mocks.request.mock.calls.map(([method]) => method)).toEqual([
      "app.status",
      "app.close",
    ]);
  });

  it("fails closed when attached app configuration cannot be read", async () => {
    mocks.readConfig.mockRejectedValueOnce(new Error("Unreadable config"));
    const callback = mocks.registerCommand.mock.calls.find(
      ([registered]) => registered === "wintestkit.closeApp",
    )?.[1];
    await callback?.();
    expect(mocks.showWarning).not.toHaveBeenCalled();
    expect(mocks.request).not.toHaveBeenCalled();
    expect(mocks.showError).toHaveBeenCalledWith("Error: Unreadable config");
  });

  it("has a Windows testing manifest and configuration parser dependencies", () => {
    expect(manifest.engines.vscode).toBe("^1.95.0");
    expect(manifest.extensionDependencies).toContain("ms-python.python");
    expect(Object.keys(manifest.dependencies)).toEqual([
      "@vscode/python-extension",
      "smol-toml",
      "yaml",
    ]);
    const commandIds = manifest.contributes.commands.map(
      (command: { command: string }) => command.command,
    );
    expect(new Set(commandIds).size).toBe(commandIds.length);
  });
});
