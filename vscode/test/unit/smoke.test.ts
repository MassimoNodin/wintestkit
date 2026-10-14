import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";

const mocks = vi.hoisted(() => ({
  log: { info: vi.fn(), error: vi.fn(), show: vi.fn(), dispose: vi.fn() },
  request: vi.fn(() => Promise.resolve(null)),
  runTerminal: vi.fn(() => Promise.resolve()),
  folder: {
    uri: { fsPath: "C:\demo", toString: () => "file:///C:/demo" },
    name: "demo",
  },
  registerCommand: vi.fn<
    (command: string, callback: () => void) => vscode.Disposable
  >(() => ({ dispose: vi.fn() })),
  executeCommand: vi.fn(() => Promise.resolve()),
  registerTreeDataProvider: vi.fn(() => ({ dispose: vi.fn() })),
  registerWebviewViewProvider: vi.fn(() => ({ dispose: vi.fn() })),
}));

vi.mock("vscode", () => ({
  window: {
    createOutputChannel: () => mocks.log,
    registerTreeDataProvider: mocks.registerTreeDataProvider,
    registerWebviewViewProvider: mocks.registerWebviewViewProvider,
  },
  commands: {
    registerCommand: mocks.registerCommand,
    executeCommand: mocks.executeCommand,
  },
  workspace: {
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
vi.mock("../../src/server/serverManager", () => ({
  ServerManager: class {
    get() {
      return Promise.resolve({ client: { request: mocks.request } });
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
    refresh() {
      return Promise.resolve();
    }
    dispose() {}
  },
}));

import { activate } from "../../src/extension";

const manifest = JSON.parse(readFileSync("package.json", "utf8"));

describe("extension scaffold", () => {
  let subscriptions: vscode.Disposable[];

  beforeEach(() => {
    vi.clearAllMocks();
    subscriptions = [];
    activate({
      subscriptions,
      extension: { packageJSON: manifest },
    } as unknown as vscode.ExtensionContext);
  });

  it("activates, logs, and registers every contributed command and view", () => {
    expect(mocks.log.info).toHaveBeenCalledWith("WinTestKit activated");
    expect(
      mocks.registerCommand.mock.calls.map(([command]) => command),
    ).toEqual(
      manifest.contributes.commands.map(
        (command: { command: string }) => command.command,
      ),
    );
    expect(mocks.registerTreeDataProvider).toHaveBeenCalledWith(
      "wintestkit.elements",
      expect.any(Object),
    );
    expect(mocks.registerWebviewViewProvider).toHaveBeenCalledWith(
      "wintestkit.spy",
      expect.any(Object),
    );
    expect(subscriptions.length).toBeGreaterThan(
      manifest.contributes.commands.length + 3,
    );
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

  it("has a Windows testing manifest and the single permitted runtime dependency", () => {
    expect(manifest.engines.vscode).toBe("^1.95.0");
    expect(manifest.extensionDependencies).toContain("ms-python.python");
    expect(Object.keys(manifest.dependencies)).toEqual([
      "@vscode/python-extension",
    ]);
    const commandIds = manifest.contributes.commands.map(
      (command: { command: string }) => command.command,
    );
    expect(new Set(commandIds).size).toBe(commandIds.length);
  });
});
