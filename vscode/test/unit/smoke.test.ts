import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";

const mocks = vi.hoisted(() => ({
  log: { info: vi.fn(), show: vi.fn(), dispose: vi.fn() },
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
    expect(subscriptions).toHaveLength(
      manifest.contributes.commands.length + 3,
    );
  });

  it("shows output and clearly logs placeholder commands", () => {
    const showOutput = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.showOutput",
    );
    const runDoctor = mocks.registerCommand.mock.calls.find(
      ([command]) => command === "wintestkit.runDoctor",
    );
    expect(showOutput).toBeDefined();
    expect(runDoctor).toBeDefined();
    showOutput?.[1]();
    runDoctor?.[1]();
    expect(mocks.log.show).toHaveBeenCalledOnce();
    expect(mocks.log.info).toHaveBeenCalledWith(
      "wintestkit.runDoctor: not implemented in the extension scaffold",
    );
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
