import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { DiscoveryStore, LocatedElement } from "../../src/discovery/store";
import type { DiscoveryResult } from "../../src/protocol/generated";
import type { Project } from "../../src/server/serverManager";
import type { FlowRuns } from "../../src/editor/flowRuns";
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
    getConfiguration: () => ({ get: (_key: string, fallback: unknown) => fallback }),
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
  it("keeps results when the declaration is edited", () => {
    store.set({
      ...located,
      result: { qualname: located.element.qualname, status: "found", durationMs: 1 },
    });
    store.setFeedback(located, "check", { status: "found", durationMs: 1 });
    expect(mocks.edit).toBeUndefined();
    expect(store.feedback.size).toBe(1);
    expect(store.results.size).toBe(1);
  });
  it("keeps results across a rediscovery and moves them to the element's new place", () => {
    const result = {
      qualname: located.element.qualname,
      status: "found",
      durationMs: 1,
    } as const;
    store.set({ ...located, result });
    store.setFeedback(located, "check", result);
    const range = {
      start: { line: 40, character: 0 },
      end: { line: 41, character: 0 },
    };
    const moved = {
      ...discovery,
      pages: [
        {
          ...discovery.pages[0],
          elements: discovery.pages[0].elements.map((element) =>
            element.id === located.element.id ? { ...element, range } : element,
          ),
        },
      ],
    };
    discoveryStore.get = () => moved;
    mocks.discover?.(project);
    expect(store.feedback.size).toBe(1);
    expect(store.results.get(located.element.id)).toEqual(result);
    expect(store.entries.get(located.element.id)?.element.range).toEqual(range);
  });
  it("drops a result whose element no longer exists after a rediscovery", () => {
    const result = {
      qualname: located.element.qualname,
      status: "found",
      durationMs: 1,
    } as const;
    store.set({ ...located, result });
    store.setFeedback(located, "check", result);
    discoveryStore.get = () => ({ ...discovery, pages: [] });
    mocks.discover?.(project);
    expect(store.feedback.size).toBe(0);
    expect(store.entries.size).toBe(0);
    expect(store.results.size).toBe(0);
  });
  it("clears every result on request", () => {
    const result = {
      qualname: located.element.qualname,
      status: "found",
      durationMs: 1,
    } as const;
    store.set({ ...located, result });
    store.setFeedback(located, "check", result);
    const changed = vi.fn();
    store.onDidChange(changed);
    store.clear();
    expect(store.feedback.size).toBe(0);
    expect(store.entries.size).toBe(0);
    expect(store.results.size).toBe(0);
    expect(changed).toHaveBeenCalledOnce();
  });
  it("refreshes CodeLens when action feedback changes", () => {
    const lenses = new CodeLenses(
      { projectFor: () => project } as unknown as Projects,
      discoveryStore,
      store,
      {
        states: new Map(),
        onDidChange: () => ({ dispose: vi.fn() }),
      } as unknown as FlowRuns,
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
