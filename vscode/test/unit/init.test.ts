import { beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { Projects } from "../../src/projects";

const mocks = vi.hoisted(() => ({
  installed: vi.fn(),
  interpreter: vi.fn(),
  execute: vi.fn(),
  pick: vi.fn(),
  refresh: vi.fn(),
  trusted: true,
  folders: [] as { name: string; uri: { fsPath: string } }[],
  owner: undefined as { uri: { fsPath: string } } | undefined,
  active: undefined as { document: { uri: { fsPath: string } } } | undefined,
}));
vi.mock("node:util", () => ({ promisify: () => mocks.execute }));
vi.mock("../../src/python", () => ({
  getInterpreter: mocks.interpreter,
  checkWintestkit: mocks.installed,
}));
vi.mock("vscode", () => ({
  workspace: {
    get isTrusted() {
      return mocks.trusted;
    },
    get workspaceFolders() {
      return mocks.folders;
    },
    getWorkspaceFolder: () => mocks.owner,
  },
  window: {
    get activeTextEditor() {
      return mocks.active;
    },
    showQuickPick: mocks.pick,
  },
}));
import { chooseWorkspaceFolder, initializeProject } from "../../src/init";

const folder = { name: "demo", uri: { fsPath: "C:/project with spaces" } };
const log = { info: vi.fn(), warn: vi.fn() } as unknown as vscode.LogOutputChannel;
const projects = { refresh: mocks.refresh } as unknown as Projects;

beforeEach(() => {
  vi.clearAllMocks();
  mocks.trusted = true;
  mocks.folders = [folder];
  mocks.owner = undefined;
  mocks.active = undefined;
  mocks.interpreter.mockResolvedValue("python.exe");
  mocks.installed.mockResolvedValue({ installed: true });
  mocks.execute.mockResolvedValue({ stdout: "Created", stderr: "" });
});

describe("initializing a project", () => {
  it("runs wtk init in the folder without shell concatenation, then finds the new project", async () => {
    await initializeProject(folder.uri as never, projects, log);
    expect(mocks.execute).toHaveBeenCalledWith(
      "python.exe",
      ["-m", "wintestkit", "init", "C:/project with spaces"],
      expect.objectContaining({ cwd: "C:/project with spaces", windowsHide: true }),
    );
    expect(mocks.refresh).toHaveBeenCalledOnce();
    expect(log.info).toHaveBeenCalledWith("Created");
  });
  it("does not ask for an application: choosing it is the guided setup's next step", async () => {
    await initializeProject(folder.uri as never, projects, log);
    expect(mocks.execute.mock.calls[0][1]).not.toContain("--app");
  });
  it("refuses to run in an untrusted workspace", async () => {
    mocks.trusted = false;
    await expect(initializeProject(folder.uri as never, projects, log)).rejects.toThrow("Trust the workspace");
    expect(mocks.execute).not.toHaveBeenCalled();
  });
  it("needs an interpreter that has the package, and says what to do first", async () => {
    mocks.interpreter.mockResolvedValue(undefined);
    await expect(initializeProject(folder.uri as never, projects, log)).rejects.toThrow("Select a Python interpreter");
    mocks.interpreter.mockResolvedValue("python.exe");
    mocks.installed.mockResolvedValue({ installed: false });
    await expect(initializeProject(folder.uri as never, projects, log)).rejects.toThrow("Install the wintestkit package");
    expect(mocks.execute).not.toHaveBeenCalled();
  });
  it("passes on what wtk init wrote to stderr as a warning", async () => {
    mocks.execute.mockResolvedValue({ stdout: "", stderr: "Skipped existing pages/main.py" });
    await initializeProject(folder.uri as never, projects, log);
    expect(log.warn).toHaveBeenCalledWith("Skipped existing pages/main.py");
  });
});

describe("choosing the workspace folder to set up", () => {
  it("uses the only folder without asking", async () => {
    expect(await chooseWorkspaceFolder()).toBe(folder.uri);
    expect(mocks.pick).not.toHaveBeenCalled();
  });
  it("is undefined when no folder is open", async () => {
    mocks.folders = [];
    expect(await chooseWorkspaceFolder()).toBeUndefined();
  });
  it("uses the folder of the file being edited when there are several", async () => {
    mocks.folders = [folder, { name: "other", uri: { fsPath: "C:/other" } }];
    mocks.active = { document: { uri: { fsPath: "C:/other/a.py" } } };
    mocks.owner = { uri: { fsPath: "C:/other" } };
    expect(await chooseWorkspaceFolder()).toEqual({ fsPath: "C:/other" });
    expect(mocks.pick).not.toHaveBeenCalled();
  });
  it("asks when there are several and no file decides", async () => {
    const other = { name: "other", uri: { fsPath: "C:/other" } };
    mocks.folders = [folder, other];
    mocks.pick.mockResolvedValue({ folder: other });
    expect(await chooseWorkspaceFolder()).toBe(other.uri);
    mocks.pick.mockResolvedValue(undefined);
    expect(await chooseWorkspaceFolder()).toBeUndefined();
  });
});
