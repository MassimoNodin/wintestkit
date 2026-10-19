import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  register: vi.fn(), warning: vi.fn(), information: vi.fn(), error: vi.fn(), execute: vi.fn(),
  choose: vi.fn(), plan: vi.fn(), clean: vi.fn(), trusted: true,
  documents: [] as { isDirty: boolean; uri: { scheme: string; fsPath: string } }[],
  folders: [{}] as unknown[],
}));
vi.mock("vscode", () => ({
  commands: { registerCommand: mocks.register, executeCommand: mocks.execute },
  window: { showWarningMessage: mocks.warning, showInformationMessage: mocks.information, showErrorMessage: mocks.error },
  workspace: {
    get isTrusted() { return mocks.trusted; },
    get textDocuments() { return mocks.documents; },
    get workspaceFolders() { return mocks.folders; },
  },
}));
vi.mock("../../src/init", () => ({ chooseWorkspaceFolder: mocks.choose }));
vi.mock("../../src/setup/resetFiles", () => ({ planReset: mocks.plan, cleanReset: mocks.clean }));
import { registerDevReset } from "../../src/setup/devReset";

beforeEach(() => {
  vi.resetAllMocks();
  mocks.trusted = true;
  mocks.documents = [];
  mocks.folders = [{}];
  mocks.choose.mockResolvedValue({ scheme: "file", fsPath: "C:/demo" });
  mocks.plan.mockResolvedValue({ root: "C:/demo", remove: ["pages", "tests"] });
  mocks.clean.mockResolvedValue("C:/Temp/wintestkit-reset-backup");
  mocks.register.mockReturnValue({ dispose() {} });
});

function command(busy = () => false) {
  const prepare = vi.fn(async () => {});
  const update = vi.fn(async (key: string, value: unknown) => { void key; void value; });
  registerDevReset({
    subscriptions: [], workspaceState: {
      keys: () => ["wintestkit.enabled", "wintestkit.tour.completed", "wintestkit.setup.passed", "development.packageSource.file:///demo", "other.state"], update,
    },
  } as never, prepare, busy);
  expect(mocks.register.mock.calls[0][0]).toBe("wintestkit.dev.resetRepository");
  return { run: mocks.register.mock.calls[0][1] as () => Promise<void>, prepare, update };
}

describe("development reset command", () => {
  it("previews cleanup and does nothing if confirmation is canceled", async () => {
    const reset = command();
    await reset.run();
    expect(mocks.warning.mock.calls[0][1]).toMatchObject({ modal: true });
    expect(mocks.warning.mock.calls[0][1].detail).toContain("pages\ntests");
    expect(reset.prepare).not.toHaveBeenCalled();
    expect(mocks.clean).not.toHaveBeenCalled();
    expect(reset.update).not.toHaveBeenCalled();
  });

  it("backs up and cleans before clearing only WinTestKit state and reloading", async () => {
    mocks.warning.mockResolvedValue("Back Up and Reset");
    const reset = command();
    await reset.run();
    expect(reset.prepare).toHaveBeenCalledOnce();
    expect(mocks.clean).toHaveBeenCalledOnce();
    expect(reset.prepare.mock.invocationCallOrder[0]).toBeLessThan(mocks.clean.mock.invocationCallOrder[0]);
    expect(mocks.clean.mock.invocationCallOrder[0]).toBeLessThan(reset.update.mock.invocationCallOrder[0]);
    expect(reset.update.mock.calls.map(([key]) => key)).toEqual([
      "wintestkit.enabled", "wintestkit.tour.completed", "wintestkit.setup.passed",
    ]);
    expect(mocks.information.mock.calls[0][0]).toContain("wintestkit-reset-backup");
    expect(mocks.execute).toHaveBeenCalledWith("workbench.action.reloadWindow");
  });

  it("keeps introduction state and does not reload when cleanup fails", async () => {
    mocks.warning.mockResolvedValue("Back Up and Reset");
    mocks.clean.mockRejectedValue(new Error("backup failed"));
    const reset = command();
    await reset.run();
    expect(reset.update).not.toHaveBeenCalled();
    expect(mocks.execute).not.toHaveBeenCalled();
    expect(mocks.error).toHaveBeenCalledWith("Error: backup failed");
  });

  it.each(["untrusted", "busy", "multi-root", "dirty"])("refuses an unsafe workspace: %s", async (reason) => {
    mocks.trusted = reason !== "untrusted";
    if (reason === "multi-root") mocks.folders = [{}, {}];
    if (reason === "dirty") mocks.documents = [{ isDirty: true, uri: { scheme: "file", fsPath: "C:/demo/tests/test.py" } }];
    const reset = command(() => reason === "busy");
    await reset.run();
    expect(mocks.error).toHaveBeenCalledOnce();
    expect(mocks.clean).not.toHaveBeenCalled();
    expect(reset.prepare).not.toHaveBeenCalled();
  });

  it("rechecks unsaved files after confirmation", async () => {
    mocks.warning.mockImplementation(async () => {
      mocks.documents = [{ isDirty: true, uri: { scheme: "file", fsPath: "C:/demo/pages/main.py" } }];
      return "Back Up and Reset";
    });
    const reset = command();
    await reset.run();
    expect(mocks.error).toHaveBeenCalledOnce();
    expect(mocks.clean).not.toHaveBeenCalled();
  });
});
