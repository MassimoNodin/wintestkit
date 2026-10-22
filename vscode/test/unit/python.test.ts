import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ execFile: vi.fn() }));
vi.mock("node:child_process", () => ({ execFile: mocks.execFile }));
vi.mock("vscode", () => ({}));
vi.mock("@vscode/python-extension", () => ({ PythonExtension: {} }));

import { installArguments, requirePip } from "../../src/python";
import { ALLOW_PRERELEASE, PYTHON_REQUIREMENT } from "../../src/compatibility";

beforeEach(() => vi.clearAllMocks());

it("constrains production package installation to the supported range", async () => {
  expect(await installArguments()).toEqual([
    "-m", "pip", "install", "--upgrade", "--force-reinstall", ...(ALLOW_PRERELEASE ? ["--pre"] : []), PYTHON_REQUIREMENT,
  ]);
});

describe("pip availability", () => {
  it("probes only the selected interpreter, without a shell or mutation", async () => {
    mocks.execFile.mockImplementation((_file, _args, _options, callback) => callback(null));
    await requirePip("C:/Python env/python.exe", await installArguments());
    expect(mocks.execFile).toHaveBeenCalledExactlyOnceWith(
      "C:/Python env/python.exe", ["-I", "-m", "pip", "--version"],
      { timeout: 10000, windowsHide: true }, expect.any(Function),
    );
  });
  it.each(["No module named pip", "spawn ENOENT", "timed out"])("offers actionable guidance for %s without bootstrapping", async (reason) => {
    mocks.execFile.mockImplementation((_file, _args, _options, callback) => callback(new Error(reason)));
    await expect(requirePip("C:/O'Brien $env/python.exe", await installArguments())).rejects.toThrow(
      "uv pip install --python 'C:/O''Brien $env/python.exe' --upgrade " + (ALLOW_PRERELEASE ? "--prerelease allow " : "") + "'" + PYTHON_REQUIREMENT + "'",
    );
    expect(mocks.execFile).toHaveBeenCalledOnce();
  });
  it("preserves prerelease opt-in in uv guidance", async () => {
    mocks.execFile.mockImplementation((_file, _args, _options, callback) => callback(new Error("No module named pip")));
    await expect(requirePip("python.exe", ["--pre", PYTHON_REQUIREMENT])).rejects.toThrow("--prerelease allow");
  });
  it("names the selected local wheel in guidance", async () => {
    mocks.execFile.mockImplementation((_file, _args, _options, callback) => callback(new Error("No module named pip")));
    await expect(requirePip("python.exe", ["-m", "pip", "install", "C:/Local wheels/wintestkit.whl"])).rejects.toThrow("'C:/Local wheels/wintestkit.whl'");
  });
});
