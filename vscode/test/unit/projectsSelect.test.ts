import { describe, expect, it, vi } from "vitest";

const found = vi.hoisted(() => ({
  files: [] as { fsPath: string }[],
  workspaceRoot: "C:/work/",
  findFiles: vi.fn(),
}));
vi.mock("vscode", () => {
  class EventEmitter {
    private listeners = new Set<(value: unknown) => void>();
    event = (listener: (value: unknown) => void) => {
      this.listeners.add(listener);
      return { dispose: () => this.listeners.delete(listener) };
    };
    fire(value: unknown) {
      this.listeners.forEach((listener) => listener(value));
    }
    dispose() {}
  }
  const noop = () => ({ dispose() {} });
  return {
    EventEmitter,
    Uri: { file: (fsPath: string) => ({ fsPath, toString: () => fsPath }) },
    commands: { executeCommand: async () => undefined },
    workspace: {
      createFileSystemWatcher: () => ({
        dispose() {},
        onDidCreate: noop,
        onDidChange: noop,
        onDidDelete: noop,
      }),
      onDidChangeWorkspaceFolders: noop,
      findFiles: async (...args: unknown[]) => {
        found.findFiles(...args);
        return found.files;
      },
      asRelativePath: (file: { fsPath: string }) =>
        file.fsPath.replaceAll("\\", "/").slice(found.workspaceRoot.length),
      fs: {
        readFile: async () => Buffer.from("[tool.wintestkit]\n"),
      },
    },
  };
});
import { Projects } from "../../src/projects";

describe("selecting the project views fall back to", () => {
  const make = async () => {
    found.workspaceRoot = "C:/work/";
    found.files = [
      { fsPath: "C:/work/alpha/wintestkit.yaml" },
      { fsPath: "C:/work/beta/wintestkit.yaml" },
    ];
    const projects = new Projects({
      debug: vi.fn(),
      error: vi.fn(),
    } as never);
    await projects.refresh();
    return projects;
  };
  it("puts the chosen project first and tells listeners", async () => {
    const projects = await make();
    expect(projects.all.map((project) => project.name)).toEqual([
      "alpha",
      "beta",
    ]);
    const changed = vi.fn();
    projects.onDidChange(changed);
    projects.select(projects.all[1]);
    expect(projects.all.map((project) => project.name)).toEqual([
      "beta",
      "alpha",
    ]);
    expect(changed).toHaveBeenCalledOnce();
  });
  it("keeps the choice when the projects are discovered again", async () => {
    const projects = await make();
    projects.select(projects.all[1]);
    await projects.refresh();
    expect(projects.all[0].name).toBe("beta");
  });
  it("ignores projects beneath dot-prefixed workspace folders", async () => {
    const projects = await make();
    found.files.push(
      { fsPath: "C:/work/.pytest-trace-focused/test_copy/wintestkit.yaml" },
      { fsPath: "C:/work/pkg/.custom/project/pyproject.toml" },
      { fsPath: "C:\\work\\pkg\\.cache\\copy\\wintestkit.yaml" },
    );
    await projects.refresh();
    expect(projects.all.map((project) => project.name)).toEqual([
      "alpha",
      "beta",
    ]);
    expect(found.findFiles).toHaveBeenLastCalledWith(
      "**/{pyproject.toml,wintestkit.yaml}",
      "**/{.*,node_modules,venv,site-packages}/**",
    );
  });
  it("allows workspaces whose ancestors are dot-prefixed", async () => {
    const projects = await make();
    found.workspaceRoot = "C:/Users/massi/.t3/projects/wintestkit/";
    found.files = [
      {
        fsPath:
          found.workspaceRoot + "examples/calculator-tests/wintestkit.yaml",
      },
      {
        fsPath:
          found.workspaceRoot +
          "python/.pytest-trace-focused/copy/wintestkit.yaml",
      },
    ];
    await projects.refresh();
    expect(projects.all.map((project) => project.name)).toEqual([
      "calculator-tests",
    ]);
  });
});
