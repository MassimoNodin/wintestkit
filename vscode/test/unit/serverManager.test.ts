import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";

const mocks = vi.hoisted(() => ({
  spawn: vi.fn(),
  installed: vi.fn(),
  interpreter: vi.fn(),
  trusted: true,
  showError: vi.fn(() => Promise.resolve(undefined)),
  showInfo: vi.fn(() => Promise.resolve(undefined)),
}));
vi.mock("node:child_process", () => ({ spawn: mocks.spawn }));
vi.mock("../../src/python", () => ({
  checkWintestkit: mocks.installed,
  getInterpreter: mocks.interpreter,
  installPackage: vi.fn(),
}));
vi.mock("vscode", () => ({
  EventEmitter: class {
    event = () => ({ dispose() {} });
    fire() {}
    dispose() {}
  },
  workspace: {
    get isTrusted() {
      return mocks.trusted;
    },
    getConfiguration: () => ({ get: () => "info" }),
  },
  window: {
    showErrorMessage: mocks.showError,
    showInformationMessage: mocks.showInfo,
  },
  commands: { executeCommand: vi.fn() },
}));
import { ServerManager, type Project } from "../../src/server/serverManager";

class Child extends EventEmitter {
  stdin = new PassThrough();
  stdout = new PassThrough();
  stderr = new PassThrough();
  kill = vi.fn(() => {
    this.emit("exit", 0);
    this.emit("close", 0);
    return true;
  });
  requests: Record<string, unknown>[] = [];
  constructor(initializationError?: { code: number; message: string }) {
    super();
    this.stdin.on("data", (chunk) => {
      const request = JSON.parse(String(chunk));
      this.requests.push(request);
      const result =
        request.method === "initialize" ? { protocolVersion: 1 } : null;
      this.stdout.write(
        JSON.stringify({
          jsonrpc: "2.0",
          id: request.id,
          ...(request.method === "initialize" && initializationError
            ? { error: initializationError }
            : { result }),
        }) + "\n",
      );
    });
  }
}
const project = {
  root: { fsPath: "C:\demo", toString: () => "demo" },
  name: "demo",
} as Project;
const log = {
  info: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
  show: vi.fn(),
} as unknown as vscode.LogOutputChannel;
let manager: ServerManager;
beforeEach(() => {
  vi.clearAllMocks();
  mocks.trusted = true;
  mocks.interpreter.mockResolvedValue("python.exe");
  mocks.installed.mockResolvedValue({ installed: true, version: "0.1.0" });
  mocks.spawn.mockImplementation(() => new Child());
  manager = new ServerManager(log);
});
afterEach(async () => {
  await manager.shutdown();
  vi.useRealTimers();
});
describe("server manager", () => {
  it("coalesces starts, initializes once and shuts down gracefully", async () => {
    const [first, second] = await Promise.all([
      manager.get(project),
      manager.get(project),
    ]);
    expect(first).toBe(second);
    expect(mocks.spawn).toHaveBeenCalledOnce();
    expect(mocks.spawn.mock.calls[0][1]).toEqual([
      "-m",
      "wintestkit",
      "--log-level",
      "INFO",
      "serve",
      "--stdio",
    ]);
    const child = mocks.spawn.mock.results[0].value as Child;
    expect(child.requests[0].method).toBe("initialize");
    expect(manager.state(project)).toBe("ready");
    await manager.shutdown();
    expect(child.requests[1].method).toBe("shutdown");
    expect(child.kill).toHaveBeenCalledOnce();
  });
  it("never executes code in an untrusted workspace", async () => {
    mocks.trusted = false;
    await expect(manager.get(project)).rejects.toThrow("Trust the workspace");
    expect(mocks.interpreter).not.toHaveBeenCalled();
    expect(mocks.spawn).not.toHaveBeenCalled();
  });
  it("ignores duplicate interpreter events while the initial server is starting", async () => {
    let resolveInterpreter: (value: string) => void = () => {};
    mocks.interpreter.mockImplementationOnce(
      () =>
        new Promise<string>((resolve) => {
          resolveInterpreter = resolve;
        }),
    );
    const starting = manager.get(project);
    const changed = manager.restartIfInterpreterChanged(project);
    resolveInterpreter("python.exe");
    const connection = await starting;
    await changed;
    expect(mocks.spawn).toHaveBeenCalledOnce();
    expect(
      (mocks.spawn.mock.results[0].value as Child).kill,
    ).not.toHaveBeenCalled();
    expect(await manager.get(project)).toBe(connection);
  });
  it("restarts the server when the interpreter actually changes", async () => {
    await manager.get(project);
    mocks.interpreter.mockResolvedValue("other-python.exe");
    await manager.restartIfInterpreterChanged(project);
    expect(mocks.spawn).toHaveBeenCalledTimes(2);
    expect(
      (mocks.spawn.mock.results[0].value as Child).kill,
    ).toHaveBeenCalledOnce();
    expect((await manager.get(project)).python).toBe("other-python.exe");
  });
  it("reports a missing package once without spawning", async () => {
    mocks.installed.mockResolvedValue({ installed: false });
    await expect(manager.get(project)).rejects.toThrow("not installed");
    await expect(manager.get(project)).rejects.toThrow("not installed");
    expect(manager.state(project)).toBe("not-installed");
    expect(mocks.showInfo).toHaveBeenCalledOnce();
    expect(mocks.spawn).not.toHaveBeenCalled();
  });
  it("backs off after crashes and requires restart after three", async () => {
    vi.useFakeTimers();
    await manager.get(project);
    for (let index = 0; index < 3; index++) {
      const child = mocks.spawn.mock.results[index].value as Child;
      child.emit("exit", 1);
      child.emit("close", 1);
      if (index < 2) await vi.advanceTimersByTimeAsync(1000 * 2 ** index);
    }
    await expect(manager.get(project)).rejects.toThrow("repeated crashes");
    expect(mocks.spawn).toHaveBeenCalledTimes(3);
    await manager.restart(project);
    expect(mocks.spawn).toHaveBeenCalledTimes(4);
  });
  it("does not retry rejected initialization or count it as a crash", async () => {
    vi.useFakeTimers();
    const error = {
      code: -32001,
      message: "tool.wintestkit.timeout: expected a number",
    };
    mocks.spawn.mockImplementation(() => new Child(error));
    await expect(manager.get(project)).rejects.toMatchObject(error);
    const child = mocks.spawn.mock.results[0].value as Child;
    expect(child.kill).toHaveBeenCalledOnce();
    expect(manager.state(project)).toBe("error");
    await vi.advanceTimersByTimeAsync(60000);
    for (let attempt = 0; attempt < 4; attempt++)
      await expect(manager.get(project)).rejects.toMatchObject(error);
    expect(mocks.spawn).toHaveBeenCalledOnce();
    expect(mocks.showError).not.toHaveBeenCalled();
    expect(log.error).toHaveBeenCalledWith(
      expect.stringContaining("Server initialization rejected"),
    );
    expect(log.error).not.toHaveBeenCalledWith(
      expect.stringContaining("stopped unexpectedly"),
    );
    mocks.spawn.mockImplementation(() => new Child());
    await manager.restart(project);
    expect(manager.state(project)).toBe("ready");
    expect(mocks.spawn).toHaveBeenCalledTimes(2);
  });
  it("logs the project and exit details for actual process crashes", async () => {
    vi.useFakeTimers();
    await manager.get(project);
    const child = mocks.spawn.mock.results[0].value as Child;
    child.emit("close", 17, null);
    expect(log.error).toHaveBeenCalledWith(
      expect.stringContaining(
        "[demo] Server stopped unexpectedly for " +
          project.root.fsPath +
          " (exit code 17, signal null)",
      ),
    );
    await vi.advanceTimersByTimeAsync(1000);
    expect(mocks.spawn).toHaveBeenCalledTimes(2);
  });
  it("still retries an unresponsive backend after initialization times out", async () => {
    vi.useFakeTimers();
    mocks.spawn.mockImplementationOnce(() => {
      const child = new Child();
      child.stdin.removeAllListeners("data");
      return child;
    });
    const starting = expect(manager.get(project)).rejects.toThrow(
      "request timed out: initialize",
    );
    await vi.advanceTimersByTimeAsync(30000);
    await starting;
    expect(mocks.spawn).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1000);
    expect(mocks.spawn).toHaveBeenCalledTimes(2);
    expect(manager.state(project)).toBe("ready");
  });
});
