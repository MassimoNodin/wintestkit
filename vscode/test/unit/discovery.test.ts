import { afterEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { Projects } from "../../src/projects";
import type { ServerManager, Project } from "../../src/server/serverManager";
import type { DiscoveryResult } from "../../src/protocol/generated";

const mocks = vi.hoisted(() => ({
  documents: [] as unknown[],
  diagnostics: { clear: vi.fn(), set: vi.fn(), dispose: vi.fn() },
  edit: undefined as ((event: unknown) => void) | undefined,
}));
vi.mock("vscode", () => ({
  EventEmitter: class {
    event = () => ({ dispose() {} });
    fire() {}
    dispose() {}
  },
  Uri: {
    file: (file: string) => ({
      fsPath: file,
      scheme: "file",
      toString: () => file,
    }),
  },
  Range: class {
    constructor(
      public startLine: number,
      public startCharacter: number,
      public endLine: number,
      public endCharacter: number,
    ) {}
  },
  Diagnostic: class {
    constructor(
      public range: unknown,
      public message: string,
      public severity: number,
    ) {}
  },
  DiagnosticSeverity: { Warning: 1 },
  languages: { createDiagnosticCollection: () => mocks.diagnostics },
  workspace: {
    get textDocuments() {
      return mocks.documents;
    },
    createFileSystemWatcher: () => ({
      dispose() {},
      onDidCreate: () => ({ dispose() {} }),
      onDidChange: () => ({ dispose() {} }),
      onDidDelete: () => ({ dispose() {} }),
    }),
    onDidSaveTextDocument: () => ({ dispose() {} }),
    onDidCloseTextDocument: () => ({ dispose() {} }),
    onDidRenameFiles: () => ({ dispose() {} }),
    onDidChangeTextDocument: (callback: (event: unknown) => void) => {
      mocks.edit = callback;
      return { dispose() {} };
    },
  },
}));
import { DiscoveryStore } from "../../src/discovery/store";

afterEach(() => {
  mocks.documents = [];
  vi.useRealTimers();
  vi.clearAllMocks();
});
describe("discovery store", () => {
  it("sends dirty document overrides and refreshes unsaved edits", async () => {
    vi.useFakeTimers();
    const root = { fsPath: "C:/demo", toString: () => "demo" };
    const project = { root, name: "demo" } as Project;
    const uri = { fsPath: "C:/demo/screen.py", scheme: "file" } as vscode.Uri;
    let source = "first";
    const document = {
      uri,
      isDirty: true,
      languageId: "python",
      getText: () => source,
    };
    mocks.documents = [document];
    const result: DiscoveryResult = {
      version: 1,
      root: "C:/demo",
      tests: [],
      screens: [],
      errors: [{ file: uri.fsPath, line: 2, message: "Invalid declaration" }],
    };
    const request = vi.fn(async () => result);
    const projects = {
      all: [project],
      projectFor: () => project,
      onDidChange: () => ({ dispose() {} }),
    } as unknown as Projects;
    const servers = {
      get: async () => ({ client: { request } }),
      onDidChange: () => ({ dispose() {} }),
    } as unknown as ServerManager;
    const store = new DiscoveryStore(projects, servers, {
      error: vi.fn(),
    } as unknown as vscode.LogOutputChannel);
    await vi.advanceTimersByTimeAsync(0);
    expect(request).toHaveBeenCalledWith("discover", {
      overrides: { [uri.fsPath]: "first" },
    });
    expect(store.get(project)).toBe(result);
    expect(mocks.diagnostics.set).toHaveBeenCalledWith(
      expect.objectContaining({ fsPath: uri.fsPath }),
      [
        expect.objectContaining({
          message: "Invalid declaration",
          severity: 1,
        }),
      ],
    );
    source = "unsaved edit";
    mocks.edit?.({ document });
    await vi.advanceTimersByTimeAsync(399);
    expect(request).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(request).toHaveBeenLastCalledWith("discover", {
      overrides: { [uri.fsPath]: "unsaved edit" },
    });
    store.dispose();
  });
});
