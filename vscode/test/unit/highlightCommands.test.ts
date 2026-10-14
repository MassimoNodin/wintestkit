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
  request: vi.fn(),
  set: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn(),
  status: vi.fn(),
  progress: vi.fn(),
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
    executeCommand: vi.fn(),
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
      return action();
    },
  },
  ProgressLocation: { Notification: 15 },
}));
import { HighlightCommands } from "../../src/editor/highlightCommands";
import { RpcError } from "../../src/server/jsonrpc";
const discovery = JSON.parse(
  readFileSync("../python/tests/contract/fixtures/discovery.json", "utf8"),
) as DiscoveryResult;
const diagnostic = JSON.parse(
  readFileSync("../python/tests/contract/fixtures/diagnostic.json", "utf8"),
) as Diagnostic;
const screen = discovery.screens[0];
const target = { file: screen.file, qualname: screen.elements[0].qualname };
let commands: HighlightCommands;
beforeEach(() => {
  vi.clearAllMocks();
  mocks.request.mockReset();
  const project = { root: { toString: () => discovery.root }, name: "demo" };
  commands = new HighlightCommands(
    { projectFor: () => project } as unknown as Projects,
    { get: () => discovery } as unknown as DiscoveryStore,
    {
      get: async () => ({ client: { request: mocks.request } }),
    } as unknown as ServerManager,
    { set: mocks.set } as unknown as CheckResultsStore,
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
    expect(mocks.set).toHaveBeenCalledWith(
      expect.objectContaining({ element: screen.elements[0] }),
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
      "app.launch",
      "element.highlight",
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
    expect(mocks.request).toHaveBeenCalledWith("screen.check", {
      file: screen.file,
      screen: screen.qualname,
    });
    expect(mocks.set).toHaveBeenCalledOnce();
    expect(mocks.status).not.toHaveBeenCalled();
  });
});
