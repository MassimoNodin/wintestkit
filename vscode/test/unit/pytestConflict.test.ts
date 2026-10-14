import { beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { Projects } from "../../src/projects";
const mocks = vi.hoisted(() => ({
  choice: vi.fn(),
  update: vi.fn(),
  changed: undefined as (() => void) | undefined,
}));
vi.mock("vscode", () => ({
  workspace: {
    getWorkspaceFolder: () => ({ uri: { toString: () => "workspace" } }),
    getConfiguration: () => ({ get: () => true, update: mocks.update }),
    onDidChangeConfiguration: (callback: () => void) => {
      mocks.changed = callback;
      return { dispose() {} };
    },
  },
  window: { showInformationMessage: mocks.choice },
  ConfigurationTarget: { WorkspaceFolder: 3, Global: 1 },
}));
import { PytestConflict } from "../../src/pytestConflict";
beforeEach(() => vi.clearAllMocks());
describe("duplicate pytest explorer prompt", () => {
  it.each(["Turn Off", "Keep Both", "Don't Ask Again"])(
    "honors %s and asks once per workspace",
    async (choice) => {
      mocks.choice.mockResolvedValue(choice);
      const stateUpdate = vi.fn(async () => {});
      const projects = {
        all: [{ root: {}, name: "demo" }],
        onDidChange: () => ({ dispose() {} }),
      } as unknown as Projects;
      const conflict = new PytestConflict(
        projects,
        { get: () => [], update: stateUpdate } as unknown as vscode.Memento,
        { error: vi.fn() } as unknown as vscode.LogOutputChannel,
      );
      await vi.waitFor(() => expect(mocks.choice).toHaveBeenCalledOnce());
      await Promise.resolve();
      mocks.changed?.();
      await Promise.resolve();
      expect(mocks.choice).toHaveBeenCalledOnce();
      expect(stateUpdate).toHaveBeenCalledWith("wintestkit.pytestConflict", [
        "workspace",
      ]);
      if (choice === "Turn Off")
        expect(mocks.update).toHaveBeenCalledWith("pytestEnabled", false, 3);
      else if (choice === "Don't Ask Again")
        expect(mocks.update).toHaveBeenCalledWith(
          "promptDisablePytestExplorer",
          false,
          1,
        );
      else expect(mocks.update).not.toHaveBeenCalled();
      conflict.dispose();
    },
  );
});
