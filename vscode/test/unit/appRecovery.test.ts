import { beforeEach, describe, expect, it, vi } from "vitest";
import { recoverStoppedApp } from "../../src/editor/appRecovery";
import { readConfiguration } from "../../src/settings/files";
import type { Project, ServerManager } from "../../src/server/serverManager";

const mocks = vi.hoisted(() => ({
  info: vi.fn(),
  execute: vi.fn(),
  request: vi.fn(),
}));
vi.mock("vscode", () => ({
  window: { showInformationMessage: mocks.info },
  commands: { executeCommand: mocks.execute },
}));
vi.mock("../../src/settings/files", () => ({
  readConfiguration: vi.fn(),
}));

const project = { root: { fsPath: "/project" }, name: "demo" } as Project;
const servers = {
  get: async () => ({ client: { request: mocks.request } }),
} as unknown as ServerManager;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("stopped app recovery", () => {
  it("uses the staged launch command in Launch for tests mode", async () => {
    vi.mocked(readConfiguration).mockResolvedValue({ launch: "per-session" });
    mocks.info.mockResolvedValue("Launch App");
    await expect(recoverStoppedApp(project, servers)).resolves.toBe(true);
    expect(mocks.execute).toHaveBeenCalledWith("wintestkit.launchAppStrict", {
      resourceUri: project.root,
    });
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("only retries Attach mode after external start and a successful refresh", async () => {
    vi.mocked(readConfiguration).mockResolvedValue({
      launch: "attach",
      "app.process": "Demo.exe",
    });
    mocks.info.mockResolvedValue("Refresh");
    mocks.request.mockResolvedValue({ running: true });
    await expect(recoverStoppedApp(project, servers)).resolves.toBe(true);
    expect(mocks.info).toHaveBeenCalledWith(
      expect.stringContaining("Start it yourself"),
      "Refresh",
    );
    expect(mocks.request).toHaveBeenCalledWith("app.status");
    expect(mocks.execute).not.toHaveBeenCalled();
  });

  it("does not retry Attach mode while the app remains stopped", async () => {
    vi.mocked(readConfiguration).mockResolvedValue({ launch: "attach" });
    mocks.info.mockResolvedValue("Refresh");
    mocks.request.mockResolvedValue({ running: false });
    await expect(recoverStoppedApp(project, servers)).resolves.toBe(false);
    expect(mocks.execute).not.toHaveBeenCalled();
    expect(mocks.request).toHaveBeenCalledWith("app.status");
  });

  it("does not report recovery after launch command rejects", async () => {
    vi.mocked(readConfiguration).mockResolvedValue({ launch: "per-session" });
    mocks.info.mockResolvedValue("Launch App");
    mocks.execute.mockRejectedValue(new Error("launch failed"));
    await expect(recoverStoppedApp(project, servers)).rejects.toThrow(
      "launch failed",
    );
  });
});
