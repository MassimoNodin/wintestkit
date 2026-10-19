import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { Projects } from "../../src/projects";
import type { DiscoveryStore } from "../../src/discovery/store";
import type { ServerManager, Project } from "../../src/server/serverManager";
import { RpcError } from "../../src/server/jsonrpc";

const mocks = vi.hoisted(() => ({
  commands: new Map<string, (target?: unknown) => Promise<void>>(),
  executeCommand: vi.fn(),
  rediscover: undefined as ((project: unknown) => void) | undefined,
  request: vi.fn(),
  info: vi.fn(),
  error: vi.fn(),
  status: vi.fn(),
  show: vi.fn(),
}));
vi.mock("vscode", () => ({
  EventEmitter: class {
    private listeners: Array<() => void> = [];
    event = (listener: () => void) => {
      this.listeners.push(listener);
      return { dispose() {} };
    };
    fire = () => this.listeners.forEach((listener) => listener());
    dispose = vi.fn();
  },
  commands: {
    registerCommand: (
      name: string,
      handler: (target?: unknown) => Promise<void>,
    ) => {
      mocks.commands.set(name, handler);
      return { dispose() {} };
    },
    executeCommand: mocks.executeCommand,
  },
  Uri: { file: (file: string) => ({ fsPath: file }) },
  window: {
    showInformationMessage: mocks.info,
    showErrorMessage: mocks.error,
    setStatusBarMessage: mocks.status,
  },
}));
vi.mock("../../src/settings/files", () => ({
  readConfiguration: vi.fn(async () => ({ launch: "per-test" })),
}));
import { FlowRuns, flowKey } from "../../src/editor/flowRuns";

const project = { root: { fsPath: "/project" }, name: "project" } as Project;
const target = { file: "/project/flows/tour.py", name: "tour" };
let flows: FlowRuns;
const run = () => mocks.commands.get("wintestkit.runFlow")!(target);
beforeEach(() => {
  vi.clearAllMocks();
  mocks.commands.clear();
  mocks.error.mockResolvedValue(undefined);
  flows = new FlowRuns(
    { projectFor: () => project } as unknown as Projects,
    {
      get: () => ({ flows: [] }),
      onDidChange: (listener: (project: unknown) => void) => {
        mocks.rediscover = listener;
        return { dispose() {} };
      },
    } as unknown as DiscoveryStore,
    {
      get: async () => ({ client: { request: mocks.request } }),
    } as unknown as ServerManager,
    { info: vi.fn(), show: mocks.show } as unknown as vscode.LogOutputChannel,
  );
});
afterEach(() => flows.dispose());

describe("flow runs", () => {
  it("runs the flow with a long timeout and records a pass", async () => {
    mocks.request.mockResolvedValue({ status: "passed", durationMs: 12.4 });
    await run();
    expect(mocks.request).toHaveBeenCalledWith("flow.run", target, 600000);
    expect(flows.states.get(flowKey(target))).toEqual({
      status: "passed",
      durationMs: 12.4,
    });
    expect(mocks.status).toHaveBeenCalledWith(
      expect.stringContaining("tour passed in 12 ms"),
      5000,
    );
    expect(mocks.error).not.toHaveBeenCalled();
  });
  it("shows the spinner state while running and notifies listeners", async () => {
    let finish: (value: unknown) => void = () => undefined;
    mocks.request.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const changed = vi.fn();
    flows.onDidChange(changed);
    const running = run();
    await vi.waitFor(() =>
      expect(flows.states.get(flowKey(target))).toEqual({ status: "running" }),
    );
    expect(changed).toHaveBeenCalled();
    await run();
    expect(mocks.info).toHaveBeenCalledWith("tour is already running.");
    expect(mocks.request).toHaveBeenCalledOnce();
    finish({ status: "passed", durationMs: 1 });
    await running;
    expect(flows.states.get(flowKey(target))?.status).toBe("passed");
  });
  it("reports a failed flow and can open the output", async () => {
    mocks.request.mockResolvedValue({
      status: "failed",
      durationMs: 3,
      message: "AssertionError: boom",
    });
    mocks.error.mockResolvedValue("Show Output");
    await run();
    expect(mocks.error).toHaveBeenCalledWith(
      "Flow tour failed: AssertionError: boom",
      "Show Output",
    );
    expect(mocks.show).toHaveBeenCalled();
    expect(flows.states.get(flowKey(target))?.status).toBe("failed");
  });
  it("offers to launch a stopped app and retries the flow", async () => {
    mocks.request
      .mockRejectedValueOnce(new RpcError(-32002, "App is not running"))
      .mockResolvedValueOnce({ status: "passed", durationMs: 1 });
    mocks.info.mockResolvedValue("Launch App");
    await run();
    expect(mocks.info).toHaveBeenCalledWith("The app isn't running.", "Launch App");
    expect(mocks.executeCommand).toHaveBeenCalledWith("wintestkit.launchAppStrict", {
      resourceUri: project.root,
    });
    expect(mocks.request).toHaveBeenCalledTimes(2);
    expect(flows.states.get(flowKey(target))?.status).toBe("passed");
  });
  it("does not retry after a failed staged launch", async () => {
    mocks.request.mockRejectedValueOnce(new RpcError(-32002, "App is not running"));
    mocks.info.mockResolvedValue("Launch App");
    mocks.executeCommand.mockRejectedValueOnce(new Error("Launch failed"));
    await run();
    expect(mocks.request).toHaveBeenCalledOnce();
    expect(mocks.error).toHaveBeenCalledWith("Launch failed");
    expect(flows.states.has(flowKey(target))).toBe(false);
  });
  it("shows other errors and clears the running state", async () => {
    mocks.request.mockRejectedValue(
      new RpcError(-32003, "flow 'tour' cannot be run from the editor"),
    );
    await run();
    expect(mocks.error).toHaveBeenCalledWith(
      "flow 'tour' cannot be run from the editor",
    );
    expect(flows.states.has(flowKey(target))).toBe(false);
  });
  it("drops finished results when the project is rediscovered", async () => {
    mocks.request.mockResolvedValue({ status: "passed", durationMs: 1 });
    await run();
    flows.states.set(flowKey({ ...target, name: "slow" }), {
      status: "running",
    });
    mocks.rediscover?.(project);
    expect([...flows.states.keys()]).toEqual([
      flowKey({ ...target, name: "slow" }),
    ]);
  });
});
