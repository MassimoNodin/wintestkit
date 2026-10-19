import { beforeEach, describe, expect, it, vi } from "vitest";
const files = vi.hoisted(() => new Map<string, string>());
vi.mock("vscode", () => {
  class FileSystemError extends Error {
    code = "FileNotFound";
  }
  return {
    FileSystemError,
    Uri: {
      joinPath: (root: { fsPath: string }, name: string) => ({
        fsPath: root.fsPath + "/" + name,
      }),
    },
    workspace: {
      fs: {
        readFile: async (uri: { fsPath: string }) => {
          if (!files.has(uri.fsPath)) throw new FileSystemError();
          return Buffer.from(files.get(uri.fsPath)!);
        },
        writeFile: async (uri: { fsPath: string }, data: Uint8Array) => {
          files.set(uri.fsPath, Buffer.from(data).toString("utf8"));
        },
      },
    },
  };
});
import * as vscode from "vscode";
import {
  readConfiguration,
  writeLocalSettings,
} from "../../src/settings/files";
const root = { fsPath: "/project" } as vscode.Uri;
describe("configuration file resolution", () => {
  beforeEach(() => files.clear());
  it("merges defaults, legacy TOML, shared YAML and local TOML/YAML in order", async () => {
    files.set(
      "/project/pyproject.toml",
      '[tool.wintestkit]\ntimeout = 11\n[tool.wintestkit.app]\nprocess = "Legacy.exe"',
    );
    files.set(
      "/project/wintestkit.yaml",
      "timeout: 12\napp:\n  process: Shared.exe\n",
    );
    files.set(
      "/project/wintestkit.local.toml",
      "[tool.wintestkit]\ntimeout = 13\n",
    );
    files.set(
      "/project/wintestkit.local.yaml",
      "timeout: 14\napp:\n  path: C:/Apps/Local.exe\n",
    );
    const config = await readConfiguration(root);
    expect(config.timeout).toBe(14);
    expect(config["app.process"]).toBe("Shared.exe");
    expect(config["app.path"]).toBe("C:/Apps/Local.exe");
    expect(config.launch).toBe("per-test");
  });
  it("previews an unsaved document without writing it", async () => {
    files.set("/project/wintestkit.yaml", "timeout: 10\n");
    const config = await readConfiguration(root, {
      "wintestkit.yaml": "timeout: 20\n",
    });
    expect(config.timeout).toBe(20);
    expect(files.get("/project/wintestkit.yaml")).toBe("timeout: 10\n");
  });
  it("reports invalid local configuration instead of ignoring it", async () => {
    files.set("/project/wintestkit.local.yaml", "timeout: nope\n");
    await expect(readConfiguration(root)).rejects.toThrow(/timeout/);
  });
});

describe("writing local settings", () => {
  beforeEach(() => {
    files.clear();
    // Every ignore pattern is already present, so the .gitignore is left alone.
    files.set(
      "/project/.gitignore",
      [
        "wintestkit.local.toml",
        "wintestkit.local.yaml",
        ".venv/",
        "__pycache__/",
        ".pytest_cache/",
        ".ruff_cache/",
        "wtk-report/",
        "wtk-results/",
      ].join("\n"),
    );
  });
  it("creates the local file and sets, replaces and removes settings", async () => {
    await writeLocalSettings(root, {
      "app.path": "C:/Apps/Demo.exe",
      launch: "attach",
    });
    let config = await readConfiguration(root);
    expect(config["app.path"]).toBe("C:/Apps/Demo.exe");
    expect(config.launch).toBe("attach");
    await writeLocalSettings(root, {
      "app.process": "Demo.exe",
      "app.path": undefined,
    });
    config = await readConfiguration(root);
    expect(config["app.process"]).toBe("Demo.exe");
    expect(config["app.path"]).toBeUndefined();
    expect(config.launch).toBe("attach");
    expect(files.get("/project/wintestkit.local.yaml")).toContain(
      "Local machine overrides",
    );
  });
  it("refuses a value that is not valid for the setting", async () => {
    await expect(
      writeLocalSettings(root, { launch: "sometimes" }),
    ).rejects.toThrow();
    expect(files.has("/project/wintestkit.local.yaml")).toBe(false);
  });
});
