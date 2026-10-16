import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { DiscoveryStore, LocatedElement } from "../../src/discovery/store";
import type { DiscoveryResult } from "../../src/protocol/generated";
import type { Project } from "../../src/server/serverManager";
import type { Projects } from "../../src/projects";

const mocks = vi.hoisted(() => ({
  edit: undefined as
    ((event: vscode.TextDocumentChangeEvent) => void) | undefined,
  discover: undefined as ((project: Project) => void) | undefined,
}));
vi.mock("vscode", () => ({
  EventEmitter: class {
    private listeners = new Set<() => void>();
    event = (listener: () => void) => {
      this.listeners.add(listener);
      return { dispose: () => this.listeners.delete(listener) };
    };
    fire() {
      this.listeners.forEach((listener) => listener());
    }
    dispose() {
      this.listeners.clear();
    }
  },
  workspace: {
    onDidChangeTextDocument: (listener: typeof mocks.edit) => {
      mocks.edit = listener;
      return { dispose() {} };
    },
    onDidChangeConfiguration: () => ({ dispose() {} }),
    getConfiguration: () => ({ get: () => true }),
  },
  languages: { registerCodeLensProvider: () => ({ dispose() {} }) },
  Range: class {},
  CodeLens: class {
    constructor(
      public range: unknown,
      public command: unknown,
    ) {}
  },
}));

import { CheckResultsStore } from "../../src/editor/decorations";
import { CodeLenses } from "../../src/editor/codeLens";

const discovery = JSON.parse(
  readFileSync("../python/tests/contract/fixtures/discovery.json", "utf8"),
) as DiscoveryResult;
const project = { root: { toString: () => discovery.root } } as Project;
const located: LocatedElement = {
  project,
  page: discovery.pages[0],
  element: discovery.pages[0].elements[0],
};
let store: CheckResultsStore;
let discoveryStore: DiscoveryStore;
beforeEach(() => {
  discoveryStore = {
    get: () => discovery,
    onDidChange: (listener: typeof mocks.discover) => {
      mocks.discover = listener;
      return { dispose() {} };
    },
  } as unknown as DiscoveryStore;
  store = new CheckResultsStore(discoveryStore);
});
afterEach(() => store.dispose());

describe("inline action feedback", () => {
  it("retains independent results and ignores superseded completions", () => {
    const first = { status: "running" } as const;
    const second = { status: "running" } as const;
    store.setFeedback(located, "highlight", first);
    store.setFeedback(located, "check", { status: "found", durationMs: 1 });
    store.setFeedback(located, "highlight", second);
    expect(
      store.setFeedback(
        located,
        "highlight",
        { status: "not_found", durationMs: 1 },
        first,
      ),
    ).toBe(false);
    expect(
      store.setFeedback(
        located,
        "highlight",
        { status: "found", durationMs: 1 },
        second,
      ),
    ).toBe(true);
    expect(store.feedback.get(located.element.id)).toMatchObject({
      highlight: { status: "found" },
      check: { status: "found" },
    });
  });
  it("clears edited declarations and rejects their in-flight completions", () => {
    const pending = { status: "running" } as const;
    store.setFeedback(located, "highlight", pending);
    mocks.edit?.({
      document: { uri: { fsPath: located.page.file.replaceAll("\\", "/") } },
      contentChanges: [{ range: located.element.range }],
    } as unknown as vscode.TextDocumentChangeEvent);
    expect(store.feedback.size).toBe(0);
    expect(
      store.setFeedback(
        located,
        "highlight",
        { status: "found", durationMs: 1 },
        pending,
      ),
    ).toBe(false);
  });
  it("retains feedback when edits do not overlap the declaration", () => {
    store.setFeedback(located, "check", { status: "found", durationMs: 1 });
    const line = located.element.range.end.line + 10;
    mocks.edit?.({
      document: { uri: { fsPath: located.page.file } },
      contentChanges: [{ range: { start: { line }, end: { line } } }],
    } as unknown as vscode.TextDocumentChangeEvent);
    expect(store.feedback.size).toBe(1);
  });
  it("clears feedback and decorations on project rediscovery", () => {
    const result = {
      qualname: located.element.qualname,
      status: "found",
      durationMs: 1,
    } as const;
    store.set({ ...located, result });
    store.setFeedback(located, "check", result);
    mocks.discover?.(project);
    expect(store.feedback.size).toBe(0);
    expect(store.entries.size).toBe(0);
    expect(store.results.size).toBe(0);
  });
  it("refreshes CodeLens when action feedback changes", () => {
    const lenses = new CodeLenses(
      { projectFor: () => project } as unknown as Projects,
      discoveryStore,
      store,
    );
    try {
      const changed = vi.fn();
      lenses.onDidChangeCodeLenses(changed);
      store.setFeedback(located, "highlight", { status: "running" });
      expect(changed).toHaveBeenCalledOnce();
      const document = {
        uri: { fsPath: located.page.file },
      } as vscode.TextDocument;
      expect(
        lenses
          .provideCodeLenses(document)
          .some((lens) => lens.command?.title.includes("Highlighting")),
      ).toBe(true);
    } finally {
      lenses.dispose();
    }
  });
});
