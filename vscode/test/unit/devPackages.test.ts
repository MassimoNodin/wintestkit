import { beforeEach, describe, expect, it, vi } from "vitest";
import * as vscode from "vscode";

const mocks = vi.hoisted(() => ({
  trusted: true,
  dialog: vi.fn(),
  stat: vi.fn(),
}));
vi.mock("node:fs/promises", () => ({ stat: mocks.stat }));
vi.mock("vscode", () => ({
  workspace: { get isTrusted() { return mocks.trusted; } },
  window: { showOpenDialog: mocks.dialog },
}));
import { DevPackages } from "../../src/setup/devPackages";

const folder = { toString: () => "file:///work" } as vscode.Uri;
function source() {
  const values = new Map<string, unknown>();
  const state = {
    get: (key: string) => values.get(key),
    update: async (key: string, value: unknown) => { values.set(key, value); },
  } as unknown as vscode.Memento;
  return new DevPackages(state);
}
const wheel = (name = "wintestkit-0.1.2-py3-none-any.whl") => ({ scheme: "file", fsPath: "C:/Local packages/" + name });

beforeEach(() => {
  vi.clearAllMocks();
  mocks.trusted = true;
  mocks.stat.mockResolvedValue({ isFile: () => true });
});

describe("development package selection", () => {
  it("defaults to remote and stores a local selection outside workspace configuration", async () => {
    const packages = source();
    expect(packages.view(folder)).toEqual({ source: "remote" });
    mocks.dialog.mockResolvedValue([wheel()]);
    await packages.select(folder, "local");
    expect(packages.view(folder)).toEqual({ source: "local", wheel: wheel().fsPath });
    expect(await packages.arguments(folder)).toEqual(["-m", "pip", "install", "--upgrade", wheel().fsPath]);
    expect(mocks.dialog).toHaveBeenCalledOnce();
    await packages.select(folder, "remote");
    expect(packages.view(folder)).toEqual({ source: "remote" });
    expect(await packages.arguments(folder)).toEqual(["-m", "pip", "install", "--upgrade", "--force-reinstall", "wintestkit"]);
  });
  it("preserves the selected source when the picker is cancelled", async () => {
    const packages = source();
    mocks.dialog.mockResolvedValue(undefined);
    await packages.select(folder, "local");
    expect(packages.view(folder)).toEqual({ source: "remote" });
    mocks.dialog.mockResolvedValue([wheel()]);
    await packages.select(folder, "local");
    mocks.dialog.mockResolvedValue(undefined);
    await packages.select(folder, "local");
    expect(packages.view(folder).wheel).toBe(wheel().fsPath);
  });
  it("rejects untrusted workspaces, other distributions and non-files", async () => {
    const packages = source();
    mocks.trusted = false;
    await expect(packages.select(folder, "local")).rejects.toThrow("Trust");
    expect(mocks.dialog).not.toHaveBeenCalled();
    mocks.trusted = true;
    for (const selected of [wheel("other-1-py3-none-any.whl"), wheel("wintestkit.tar.gz"), { ...wheel(), scheme: "https" }]) {
      mocks.dialog.mockResolvedValue([selected]);
      await expect(packages.select(folder, "local")).rejects.toThrow("local wintestkit wheel");
    }
    mocks.dialog.mockResolvedValue([wheel()]);
    mocks.stat.mockResolvedValue({ isFile: () => false });
    await expect(packages.select(folder, "local")).rejects.toThrow("not a file");
  });
  it("isolates workspace selections and reports removed wheels rather than using remote", async () => {
    const packages = source();
    mocks.dialog.mockResolvedValue([wheel()]);
    await packages.select(folder, "local");
    expect(packages.view({ toString: () => "file:///other" } as vscode.Uri).source).toBe("remote");
    mocks.stat.mockRejectedValue(new Error("ENOENT"));
    await expect(packages.arguments(folder)).rejects.toThrow("ENOENT");
  });
});
