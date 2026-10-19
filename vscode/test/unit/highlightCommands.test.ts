import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { Projects } from "../../src/projects";
import type { DiscoveryStore } from "../../src/discovery/store";
import type { ServerManager } from "../../src/server/serverManager";
import type { CheckResultsStore } from "../../src/editor/decorations";
import type { DiscoveryResult, Diagnostic } from "../../src/protocol/generated";

const mocks = vi.hoisted(() => ({
  commands: new Map<string, (target?: unknown) => Promise<void>>(),
  executeCommand: vi.fn(),
  request: vi.fn(),
  set: vi.fn(),
  feedback: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn(),
  status: vi.fn(),
  progress: vi.fn(),
  progressDone: vi.fn(),
  show: vi.fn(),
  log: vi.fn(),
}));
vi.mock("vscode", () => ({
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
  workspace: { getConfiguration: () => ({ get: () => 1500 }) },
  window: {
    showInformationMessage: mocks.info,
    showWarningMessage: mocks.warning,
    showErrorMessage: mocks.error,
    setStatusBarMessage: mocks.status,
    withProgress: (_options: unknown, action: () => Promise<unknown>) => {
      mocks.progress();
      return action().finally(mocks.progressDone);
    },
  },
  ProgressLocation: { Notification: 15 },
}));
vi.mock("../../src/settings/files", () => ({
  readConfiguration: vi.fn(async () => ({ launch: "per-test" })),
}));
import { HighlightCommands } from "../../src/editor/highlightCommands";
import { RpcError } from "../../src/server/jsonrpc";
const discovery = JSON.parse(
  readFileSync("../python/tests/contract/fixtures/discovery.json", "utf8"),
) as DiscoveryResult;
const diagnostic = JSON.parse(
  readFileSync("../python/tests/contract/fixtures/diagnostic.json", "utf8"),
) as Diagnostic;
const page = discovery.pages[0];
const target = { file: page.file, qualname: page.elements[0].qualname };
let commands: HighlightCommands;
beforeEach(() => {
  vi.clearAllMocks();
  mocks.request.mockReset();
  mocks.info.mockReset();
  mocks.feedback.mockReturnValue(true);
  const project = { root: { toString: () => discovery.root }, name: "demo" };
  commands = new HighlightCommands(
    { projectFor: () => project } as unknown as Projects,
    { get: () => discovery } as unknown as DiscoveryStore,
    {
      get: async () => ({ client: { request: mocks.request } }),
    } as unknown as ServerManager,
    {
      set: mocks.set,
      setFeedback: mocks.feedback,
    } as unknown as CheckResultsStore,
    {
      info: mocks.log,
      error: vi.fn(),
      show: mocks.show,
    } as unknown as vscode.LogOutputChannel,
  );
});
afterEach(() => {
  commands.dispose();
  vi.useRealTimers();
});
describe("editor highlight commands", () => {
  it("highlights quickly without a progress notification", async () => {
    mocks.request.mockResolvedValue({
      status: "found",
      element: { controlType: "Button", name: "Sign in" },
      durationMs: 1,
    });
    await mocks.commands.get("wintestkit.highlightElement")?.(target);
    expect(mocks.request).toHaveBeenCalledWith("element.highlight", {
      ...target,
      durationMs: 1500,
    });
    expect(mocks.progress).not.toHaveBeenCalled();
    expect(mocks.feedback.mock.calls.map((call) => call[2].status)).toEqual([
      "running",
      "found",
    ]);
    expect(mocks.feedback.mock.calls[1][1]).toBe("highlight");
    expect(mocks.set).toHaveBeenCalledWith(
      expect.objectContaining({ element: page.elements[0] }),
    );
    expect(mocks.status).toHaveBeenCalledWith(
      '$(eye) Found Button "Sign in"',
      5000,
    );
  });
  it("offers launch and retries once when the app is absent", async () => {
    mocks.request
      .mockRejectedValueOnce(new RpcError(-32002, "Not running"))
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({
        status: "found",
        element: { controlType: "Button", name: "Sign in" },
        durationMs: 1,
      });
    mocks.info.mockResolvedValue("Launch App");
    await mocks.commands.get("wintestkit.highlightElement")?.(target);
    expect(mocks.request.mock.calls.map((call) => call[0])).toEqual([
      "element.highlight",
      "element.highlight",
    ]);
    expect(mocks.executeCommand).toHaveBeenCalledWith(
      "wintestkit.launchAppStrict",
      { resourceUri: expect.anything() },
    );
  });
  it("does not retry when the staged launch command fails", async () => {
    mocks.request.mockRejectedValueOnce(new RpcError(-32002, "Not running"));
    mocks.info.mockResolvedValue("Launch App");
    mocks.executeCommand.mockRejectedValueOnce(new Error("Launch failed"));
    await mocks.commands.get("wintestkit.highlightElement")?.(target);
    expect(mocks.request).toHaveBeenCalledOnce();
    expect(mocks.error).toHaveBeenCalledWith("Launch failed", "Show Output");
  });
  it.each([0, 600])(
    "cleans up highlight before an undismissed launch prompt after %s ms",
    async (delay) => {
      vi.useFakeTimers();
      let rejectRequest!: (error: Error) => void;
      let dismissPrompt!: (value: undefined) => void;
      mocks.request.mockImplementationOnce(
        () =>
          new Promise((_resolve, reject) => {
            rejectRequest = reject;
          }),
      );
      mocks.info.mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            dismissPrompt = resolve;
          }),
      );
      const operation = mocks.commands.get("wintestkit.highlightElement")?.(
        target,
      );
      await vi.advanceTimersByTimeAsync(delay);
      rejectRequest(new RpcError(-32002, "Not running"));
      await vi.advanceTimersByTimeAsync(0);
      expect(mocks.info).toHaveBeenCalledWith(
        "The app isn't running.",
        "Launch App",
      );
      expect(mocks.feedback.mock.calls.map((call) => call[2].status)).toEqual([
        "running",
        "error",
      ]);
      expect(mocks.progressDone).toHaveBeenCalledTimes(delay ? 1 : 0);
      await vi.advanceTimersByTimeAsync(1000);
      expect(mocks.progress).toHaveBeenCalledTimes(delay ? 1 : 0);
      dismissPrompt(undefined);
      await operation;
      expect(mocks.error).not.toHaveBeenCalled();
    },
  );
  it("does not repeat the launch prompt if the retry fails", async () => {
    mocks.request
      .mockRejectedValueOnce(new RpcError(-32002, "Not running"))
      .mockRejectedValueOnce(new RpcError(-32002, "Not running"));
    mocks.info.mockResolvedValue("Launch App");
    await mocks.commands.get("wintestkit.highlightElement")?.(target);
    expect(mocks.info).toHaveBeenCalledOnce();
    expect(mocks.error).toHaveBeenCalledWith(
      "The app isn't running.",
      "Show Output",
    );
    expect(mocks.feedback.mock.calls.map((call) => call[2].status)).toEqual([
      "running",
      "error",
      "running",
      "error",
    ]);
  });
  it("shows formatted details for unresolved locators", async () => {
    mocks.request.mockResolvedValue({
      status: "not_found",
      diagnostic,
      durationMs: 1,
    });
    mocks.warning.mockResolvedValue("Show Details");
    await mocks.commands.get("wintestkit.highlightElement")?.(target);
    expect(mocks.warning).toHaveBeenCalledWith(
      diagnostic.message,
      "Show Details",
      "Open Spy",
    );
    expect(mocks.log).toHaveBeenCalledWith(
      expect.stringContaining("  Locator: "),
    );
    expect(mocks.show).toHaveBeenCalledOnce();
  });
  it("checks a single declaration without flashing", async () => {
    mocks.request.mockResolvedValue({
      results: [
        { qualname: target.qualname, status: "found", durationMs: 1 },
        { qualname: "Other", status: "not_found", durationMs: 1 },
      ],
    });
    await mocks.commands.get("wintestkit.checkElement")?.(target);
    expect(mocks.request).toHaveBeenCalledWith("page.check", {
      file: page.file,
      page: page.qualname,
    });
    expect(mocks.set).toHaveBeenCalledOnce();
    expect(mocks.feedback.mock.calls.map((call) => call[2].status)).toEqual([
      "running",
      "found",
    ]);
    expect(mocks.feedback.mock.calls[1][1]).toBe("check");
    expect(mocks.status).not.toHaveBeenCalled();
  });
  it.each(["highlightElement", "checkElement"])(
    "reports request failures inline for %s",
    async (command) => {
      mocks.request.mockRejectedValue(new Error("Connection lost"));
      await mocks.commands.get("wintestkit." + command)?.(target);
      expect(mocks.feedback.mock.calls.map((call) => call[2].status)).toEqual([
        "running",
        "error",
      ]);
      expect(mocks.feedback.mock.calls[1][2].message).toBe("Connection lost");
      expect(mocks.set).toHaveBeenCalledWith(
        expect.objectContaining({
          result: expect.objectContaining({
            status: "error",
            message: "Connection lost",
          }),
        }),
      );
      expect(mocks.error).toHaveBeenCalledWith(
        "Connection lost",
        "Show Output",
      );
    },
  );
  it("keeps progress inline while highlighting is pending", async () => {
    vi.useFakeTimers();
    let finish!: (value: unknown) => void;
    mocks.request.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const operation = mocks.commands.get("wintestkit.highlightElement")?.(
      target,
    );
    await vi.advanceTimersByTimeAsync(501);
    expect(mocks.feedback).toHaveBeenCalledOnce();
    expect(mocks.feedback.mock.calls[0][2].status).toBe("running");
    expect(mocks.progress).toHaveBeenCalledOnce();
    finish({
      status: "found",
      element: { controlType: "Button" },
      durationMs: 1,
    });
    await operation;
    expect(mocks.feedback.mock.calls[1][2].status).toBe("found");
  });
  it.each(["not_found", "ambiguous", "error"])(
    "reports %s from highlight and check",
    async (status) => {
      const result = {
        qualname: target.qualname,
        status,
        diagnostic,
        durationMs: 1,
      };
      mocks.request
        .mockResolvedValueOnce(result)
        .mockResolvedValueOnce({ results: [result] });
      await mocks.commands.get("wintestkit.highlightElement")?.(target);
      await mocks.commands.get("wintestkit.checkElement")?.(target);
      expect(mocks.feedback.mock.calls.map((call) => call[2].status)).toEqual([
        "running",
        status,
        "running",
        status,
      ]);
    },
  );
  it("updates each element during a whole-page check", async () => {
    const elements = page.elements;
    mocks.request.mockResolvedValue({
      results: elements.map((element) => ({
        qualname: element.qualname,
        status: "found",
        durationMs: 1,
      })),
    });
    await mocks.commands.get("wintestkit.checkPage")?.({
      file: page.file,
      page: page.qualname,
    });
    expect(mocks.feedback).toHaveBeenCalledTimes(elements.length * 2);
    expect(mocks.set).toHaveBeenCalledTimes(elements.length);
  });
  it("reports missing server results instead of leaving checking stuck", async () => {
    mocks.request.mockResolvedValue({ results: [] });
    await mocks.commands.get("wintestkit.checkElement")?.(target);
    expect(mocks.feedback.mock.calls[1][2]).toMatchObject({
      status: "error",
      message: expect.stringContaining("no check result"),
    });
  });
  it.each(["highlightElement", "checkElement"])(
    "does not restore stale decorations for %s",
    async (command) => {
      const result = {
        qualname: target.qualname,
        status: "found",
        durationMs: 1,
      };
      mocks.request.mockResolvedValue(
        command === "highlightElement" ? result : { results: [result] },
      );
      mocks.feedback.mockReturnValueOnce(true).mockReturnValueOnce(false);
      await mocks.commands.get("wintestkit." + command)?.(target);
      expect(mocks.set).not.toHaveBeenCalled();
    },
  );
});
