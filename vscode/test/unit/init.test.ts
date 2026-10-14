import { beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { Projects } from "../../src/projects";
const mocks = vi.hoisted(() => ({
  handler: undefined as (() => Promise<void>) | undefined,
  installed: vi.fn(),
  execute: vi.fn(),
  install: vi.fn(),
  picker: vi.fn(),
  show: vi.fn(),
  info: vi.fn(),
  error: vi.fn(),
  refresh: vi.fn(),
  trusted: true,
  folder: { name: "demo", uri: { fsPath: "C:/project with spaces" } },
}));
vi.mock("node:util", () => ({ promisify: () => mocks.execute }));
vi.mock("../../src/python", () => ({
  getInterpreter: async () => "python.exe",
  checkWintestkit: mocks.installed,
  installPackage: mocks.install,
}));
vi.mock("vscode", () => ({
  workspace: {
    get isTrusted() {
      return mocks.trusted;
    },
    workspaceFolders: [mocks.folder],
  },
  commands: {
    registerCommand: (_name: string, handler: () => Promise<void>) => {
      mocks.handler = handler;
      return { dispose() {} };
    },
  },
  Uri: {
    joinPath: (root: { fsPath: string }, ...parts: string[]) => ({
      fsPath: [root.fsPath, ...parts].join("/"),
    }),
  },
  window: {
    showOpenDialog: mocks.picker,
    showTextDocument: mocks.show,
    showInformationMessage: mocks.info,
    showErrorMessage: mocks.error,
  },
}));
import { registerInitialize } from "../../src/init";
beforeEach(() => {
  vi.clearAllMocks();
  mocks.trusted = true;
  mocks.installed.mockResolvedValue({ installed: true });
  mocks.execute.mockResolvedValue({ stdout: "Created", stderr: "" });
  mocks.picker.mockResolvedValue(undefined);
  registerInitialize(
    { refresh: mocks.refresh } as unknown as Projects,
    {
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      show: vi.fn(),
    } as unknown as vscode.LogOutputChannel,
  );
});
describe("Initialize Project", () => {
  it("supports skipping app selection and refreshes before opening the screen", async () => {
    await mocks.handler?.();
    expect(mocks.execute).toHaveBeenCalledWith(
      "python.exe",
      ["-m", "wintestkit", "init", mocks.folder.uri.fsPath],
      expect.objectContaining({
        cwd: mocks.folder.uri.fsPath,
        windowsHide: true,
      }),
    );
    expect(mocks.refresh).toHaveBeenCalledOnce();
    expect(mocks.show).toHaveBeenCalledWith({
      fsPath: "C:/project with spaces/screens/main.py",
    });
  });
  it("passes selected executable paths without shell concatenation", async () => {
    mocks.picker.mockResolvedValue([{ fsPath: "C:/App Folder/App.exe" }]);
    await mocks.handler?.();
    expect(mocks.execute.mock.calls[0][1]).toEqual([
      "-m",
      "wintestkit",
      "init",
      mocks.folder.uri.fsPath,
      "--app",
      "C:/App Folder/App.exe",
    ]);
  });
  it("offers installation instead of running a missing package", async () => {
    mocks.installed.mockResolvedValue({ installed: false });
    mocks.info.mockResolvedValue("Install");
    await mocks.handler?.();
    expect(mocks.install).toHaveBeenCalledWith(mocks.folder.uri);
    expect(mocks.execute).not.toHaveBeenCalled();
  });
  it("does not execute code in an untrusted workspace", async () => {
    mocks.trusted = false;
    await mocks.handler?.();
    expect(mocks.execute).not.toHaveBeenCalled();
    expect(mocks.error).toHaveBeenCalledWith(
      expect.stringContaining("Trust the workspace"),
      "Show Output",
    );
  });
});
