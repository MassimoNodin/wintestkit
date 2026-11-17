import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ execFile: vi.fn() }));
vi.mock("node:child_process", () => ({ execFile: mocks.execFile }));
vi.mock("vscode", () => ({}));
vi.mock("@vscode/python-extension", () => ({ PythonExtension: {} }));

import { installArguments, requirePip } from "../../src/python";
import { ALLOW_PRERELEASE, PYTHON_REQUIREMENT, UPGRADE_REQUIREMENT } from "../../src/compatibility";

beforeEach(() => vi.clearAllMocks());

it("constrains production package installation to the supported range", async () => {
  expect(await installArguments()).toEqual([
    "-m", "pip", "install", "--upgrade", "--force-reinstall", ...(ALLOW_PRERELEASE ? ["--pre"] : []), UPGRADE_REQUIREMENT,
  ]);
});

describe("installer selection", () => {
  it("uses pip when available", async () => {
    mocks.execFile.mockImplementation((_file, _args, _options, callback) => callback(null));
    const args = await installArguments();
    expect(await requirePip("python.exe", args)).toEqual({ executable: "python.exe", args });
    expect(mocks.execFile).toHaveBeenCalledExactlyOnceWith("python.exe", ["-I", "-m", "pip", "--version"], { timeout: 10000, windowsHide: true }, expect.any(Function));
  });
  it.each([false, true])("uses uv with prerelease=%s", async (prerelease) => {
    mocks.execFile.mockImplementation((file, _args, _options, callback) => callback(file === "uv" ? null : new Error("missing")));
    const args = ["-m", "pip", "install", ...(prerelease ? ["--pre"] : []), UPGRADE_REQUIREMENT];
    expect(await requirePip("python.exe", args)).toEqual({ executable: "uv", args: ["pip", "install", "--python", "python.exe", "--upgrade", "--reinstall-package", "wintestkit", "--reinstall-package", "wintestkit-inspector", ...(prerelease ? ["--prerelease", "allow"] : []), UPGRADE_REQUIREMENT] });
  });
  it("checks profile locations after PATH", async () => {
    vi.stubEnv("USERPROFILE", "C:/Users/test");
    mocks.execFile.mockImplementation((file, _args, _options, callback) => callback(String(file).includes(".cargo") ? null : new Error("missing")));
    const result = await requirePip("python.exe", await installArguments());
    expect(result.executable).toContain(".cargo");
    expect(mocks.execFile.mock.calls.map((call) => call[0])).toHaveLength(4);
    vi.unstubAllEnvs();
  });
  it("keeps manual guidance when neither is available", async () => {
    mocks.execFile.mockImplementation((_file, _args, _options, callback) => callback(new Error("missing")));
    await expect(requirePip("C:/O'Brien/python.exe", ["--pre", PYTHON_REQUIREMENT])).rejects.toThrow("uv pip install --python 'C:/O''Brien/python.exe' --upgrade --prerelease allow '" + PYTHON_REQUIREMENT + "'");
  });
});
