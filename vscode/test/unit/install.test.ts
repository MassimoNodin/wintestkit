import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  trusted: true,
  localArgs: vi.fn(async () => ["-m", "pip", "install", "--upgrade", "C:/dev/wintestkit-0.1.2-py3-none-any.whl"]),
  execFile: vi.fn(),
  check: vi.fn(async (): Promise<{ installed: boolean; version?: string }> => ({ installed: true, version: "0.1.1" })),
  args: vi.fn(async (): Promise<string[] | undefined> => ["-m", "pip", "install", "--upgrade", "--force-reinstall", "wintestkit>=0.1.1,<0.2.0"]),
}));
vi.mock("node:child_process", () => ({ execFile: mocks.execFile }));
vi.mock("../../src/python", () => ({ installArguments: mocks.args, checkWintestkit: mocks.check }));
vi.mock("../../src/setup/devPackages", () => ({
  DevPackages: class {
    view = () => ({ source: "local" });
    arguments = mocks.localArgs;
    select = vi.fn();
  },
}));
vi.mock("vscode", () => {
  class EventEmitter {
    private listeners = new Set<(value: unknown) => void>();
    event = (listener: (value: unknown) => void) => {
      this.listeners.add(listener);
      return { dispose: () => this.listeners.delete(listener) };
    };
    fire(value?: unknown) {
      this.listeners.forEach((listener) => listener(value));
    }
    dispose() {}
  }
  return { EventEmitter, workspace: { get isTrusted() { return mocks.trusted; } } };
});
import { installFailure, PackageInstaller } from "../../src/setup/install";
import { compareReleaseVersions as compareVersions } from "../../src/compatibility";

describe("package versions", () => {
  it("compares numbers, not text", () => {
    expect(compareVersions("0.10.0", "0.9.9")).toBeGreaterThan(0);
    expect(compareVersions("0.1.1", "0.1.1")).toBe(0);
    expect(compareVersions("0.1", "0.1.0")).toBe(0);
    expect(compareVersions("1.0.0", "0.99.99")).toBeGreaterThan(0);
    expect(compareVersions("0.1.1+local", "0.1.1")).toBe(0);
  });
  it("finds the reason in pip's output", () => {
    expect(installFailure("Collecting x\nERROR: No matching distribution found for wintestkit\n")).toBe(
      "ERROR: No matching distribution found for wintestkit",
    );
    expect(installFailure("something\nwent wrong")).toBe("something went wrong");
    expect(installFailure("")).toBe("pip did not say why");
  });
});

describe("installing the package", () => {
  it.each([{ installed: false }, { installed: true }])("rejects an unverifiable post-install package %j", async (installed) => {
    finish(null);
    mocks.check.mockResolvedValue(installed);
    const installer = new PackageInstaller(log);
    expect(await installer.install(folder, "python.exe")).toBe(false);
    expect(installer.error).toBeTruthy();
  });
  it.each(["0.1.0", "0.2.0", "invalid"])("does not report success if pip leaves incompatible %s installed", async (version) => {
    finish(null);
    mocks.check.mockResolvedValue({ installed: true, version });
    const installer = new PackageInstaller(log);
    expect(await installer.install(folder, "python.exe")).toBe(false);
    expect(installer.error).toContain("requires wintestkit");
    expect(installer.error).toContain("python.exe");
  });
  const log = { info: vi.fn() } as never;
  const folder = { fsPath: "C:/work" } as never;
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.trusted = true;
    mocks.check.mockResolvedValue({ installed: true, version: "0.1.1" });
    mocks.args.mockResolvedValue(["-m", "pip", "install", "--upgrade", "--force-reinstall", "wintestkit>=0.1.1,<0.2.0"]);
  });
  afterEach(() => vi.unstubAllGlobals());
  const finish = (error: Error | null, stdout = "", stderr = "") =>
    mocks.execFile.mockImplementation((_file, _args, _options, callback) => callback(error, stdout, stderr));

  it("runs pip in the chosen interpreter without a terminal, and reports being busy meanwhile", async () => {
    let done: (() => void) | undefined;
    mocks.execFile.mockImplementation((_file, _args, _options, callback) => {
      done = () => callback(null, "Successfully installed", "");
    });
    const installer = new PackageInstaller(log);
    const changed = vi.fn();
    installer.onDidChange(changed);
    const result = installer.install(folder, "C:/py/python.exe");
    await vi.waitFor(() => expect(installer.busy).toBe(true));
    expect(await installer.install(folder, "C:/py/python.exe")).toBe(false);
    done?.();
    expect(await result).toBe(true);
    expect(installer.busy).toBe(false);
    expect(installer.error).toBeUndefined();
    expect(mocks.execFile).toHaveBeenCalledOnce();
    expect(mocks.execFile.mock.calls[0][0]).toBe("C:/py/python.exe");
    expect(mocks.execFile.mock.calls[0][1]).toEqual(["-m", "pip", "install", "--upgrade", "--force-reinstall", "wintestkit>=0.1.1,<0.2.0"]);
    expect(changed).toHaveBeenCalledTimes(2);
  });

  it("keeps the reason when pip fails, and clears it on the next attempt", async () => {
    finish(new Error("exit 1"), "", "ERROR: Could not find a version that satisfies the requirement wintestkit");
    const installer = new PackageInstaller(log);
    expect(await installer.install(folder, "python.exe")).toBe(false);
    expect(installer.error).toContain("Could not find a version");
    finish(null);
    expect(await installer.install(folder, "python.exe")).toBe(true);
    expect(installer.error).toBeUndefined();
  });

  it("ignores saved development selections and local handlers in production", async () => {
    vi.stubGlobal("__WTK_DEV__", false);
    finish(null);
    const installer = new PackageInstaller(log, {} as never);
    expect(installer.development).toBeUndefined();
    await installer.selectSource(folder, "local");
    expect(await installer.install(folder, "python.exe")).toBe(true);
    expect(mocks.localArgs).not.toHaveBeenCalled();
    expect(mocks.execFile.mock.calls[0][1]).toEqual(["-m", "pip", "install", "--upgrade", "--force-reinstall", "wintestkit>=0.1.1,<0.2.0"]);
  });
  it("uses the selected wheel only in a development build", async () => {
    vi.stubGlobal("__WTK_DEV__", true);
    finish(null);
    const installer = new PackageInstaller(log, {} as never);
    expect(installer.development).toBeDefined();
    expect(await installer.install(folder, "python.exe")).toBe(true);
    expect(mocks.args).not.toHaveBeenCalled();
    expect(mocks.execFile.mock.calls[0][1]).toEqual(await mocks.localArgs());
  });
  it("will not run pip in an untrusted workspace", async () => {
    mocks.trusted = false;
    const installer = new PackageInstaller(log);
    await expect(installer.install(folder, "python.exe")).rejects.toThrow("Trust");
    expect(mocks.execFile).not.toHaveBeenCalled();
  });
  it("does nothing when installation argument selection is cancelled", async () => {
    mocks.args.mockResolvedValue(undefined);
    const installer = new PackageInstaller(log);
    expect(await installer.install(folder, "python.exe")).toBe(false);
    expect(mocks.execFile).not.toHaveBeenCalled();
    expect(installer.busy).toBe(false);
  });
});
