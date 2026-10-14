import { beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { Project } from "../../src/server/serverManager";
const mocks = vi.hoisted(() => ({
  installed: true,
  trusted: true,
  start: vi.fn(),
  stop: vi.fn(),
  show: vi.fn(),
  started: undefined as ((session: unknown) => void) | undefined,
  terminated: undefined as ((session: unknown) => void) | undefined,
  dispose: vi.fn(),
}));
vi.mock("vscode", () => ({
  workspace: {
    get isTrusted() {
      return mocks.trusted;
    },
    getWorkspaceFolder: () => undefined,
  },
  extensions: { getExtension: () => (mocks.installed ? {} : undefined) },
  window: { showErrorMessage: mocks.show },
  commands: { executeCommand: vi.fn() },
  debug: {
    startDebugging: mocks.start,
    stopDebugging: mocks.stop,
    onDidStartDebugSession: (callback: (session: unknown) => void) => {
      mocks.started = callback;
      return { dispose: mocks.dispose };
    },
    onDidTerminateDebugSession: (callback: (session: unknown) => void) => {
      mocks.terminated = callback;
      return { dispose: mocks.dispose };
    },
  },
}));
import { debugConfiguration, runDebugSession } from "../../src/testing/debug";
const project = { root: { fsPath: "C:/demo" }, name: "demo" } as Project;
const token = {
  isCancellationRequested: false,
  onCancellationRequested: () => ({ dispose: mocks.dispose }),
} as unknown as vscode.CancellationToken;
beforeEach(() => {
  vi.clearAllMocks();
  mocks.installed = true;
  mocks.trusted = true;
  mocks.show.mockResolvedValue(undefined);
});
describe("debug profile", () => {
  it("launches the module with extended waits and no report or environment gate", () => {
    expect(
      debugConfiguration("C:/demo", "python.exe", "tcp://127.0.0.1:10", [
        "test.py::test",
      ]),
    ).toMatchObject({
      type: "debugpy",
      module: "wintestkit",
      cwd: "C:/demo",
      python: "python.exe",
      justMyCode: true,
      args: [
        "run",
        "--events",
        "tcp://127.0.0.1:10",
        "--no-report",
        "--no-env-check",
        "--timeout",
        "3600",
        "--",
        "test.py::test",
      ],
    });
  });
  it("ends on protocol completion and disposes debug listeners", async () => {
    mocks.start.mockResolvedValue(true);
    await expect(
      runDebugSession(
        project,
        "python.exe",
        "tcp://127.0.0.1:10",
        [],
        {} as vscode.TestRun,
        token,
        Promise.resolve(),
      ),
    ).resolves.toBe(0);
    expect(mocks.start).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining({ wintestkitRunId: expect.any(String) }),
      { testRun: {} },
    );
    expect(mocks.dispose).toHaveBeenCalledTimes(3);
  });
  it("does not confuse unrelated debug sessions with its own", async () => {
    mocks.start.mockImplementation(async (_folder, configuration) => {
      mocks.terminated?.({ configuration: { wintestkitRunId: "unrelated" } });
      mocks.started?.({ configuration });
      mocks.terminated?.({ configuration });
      return true;
    });
    expect(
      await runDebugSession(
        project,
        "python.exe",
        "tcp://127.0.0.1:10",
        [],
        {} as vscode.TestRun,
        token,
        new Promise<void>(() => {}),
      ),
    ).toBe(0);
  });
  it("offers installation if Python Debugger is missing", async () => {
    mocks.installed = false;
    await expect(
      runDebugSession(
        project,
        "python.exe",
        "tcp://127.0.0.1:10",
        [],
        {} as vscode.TestRun,
        token,
        Promise.resolve(),
      ),
    ).rejects.toThrow("Install Python Debugger");
    expect(mocks.show).toHaveBeenCalledWith(
      expect.stringContaining("required"),
      "Install Python Debugger",
    );
    expect(mocks.start).not.toHaveBeenCalled();
  });
});
