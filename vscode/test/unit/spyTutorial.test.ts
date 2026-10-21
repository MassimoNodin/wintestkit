import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { describe, expect, it, vi } from "vitest";

const script = readFileSync("media/spy/spy.js", "utf8");

describe("Spy tutorial webview", () => {
  it("spotlights the selected green-tick row only during the definitions step", () => {
    const row = { classList: { add: vi.fn(), remove: vi.fn() } };
    const subject = { classList: { add: vi.fn(), remove: vi.fn() } };
    const context = {
      tutorialView: { spyTarget: "definitions-group" },
      tutorialSubject: () => subject,
      tutorialSpotlights: [],
      tutorialTarget: subject,
      selected: "pane",
      nodes: new Map([["pane", { row }]]),
      coverage: new Map<string, unknown>(),
      element: () => ({ clientWidth: 900, classList: { toggle: vi.fn() } }),
      placeTutorial: vi.fn(),
    };
    const start = script.indexOf("  const refreshTutorial = () => {");
    const stop = script.indexOf("  const renderTutorial =", start);
    const refresh = () => runInNewContext("{\n" + script.slice(start, stop) + "\nrefreshTutorial();\n}", context);
    refresh();
    expect(row.classList.add).not.toHaveBeenCalled();
    context.coverage.set("pane", { count: 1, first: "MainPage.content" });
    refresh();
    expect(row.classList.add).toHaveBeenCalledWith("tutorial-spotlight");
    expect(subject.classList.add).toHaveBeenCalledWith("tutorial-spotlight");
    context.tutorialView = { spyTarget: "locator-panel" };
    refresh();
    expect(row.classList.remove).toHaveBeenCalledWith("tutorial-spotlight");
  });

  it("preserves navigation buttons when an unchanged tutorial is republished", () => {
    const start = script.indexOf("  const renderTutorial = (view) => {");
    const stop = script.indexOf("  // Selecting an object", start);
    const tutorial = { step: "spy", buttons: [{ id: "next" }] };
    const refreshTutorial = vi.fn();
    const element = vi.fn(() => { throw new Error("Unchanged tutorial replaced its buttons"); });
    runInNewContext(script.slice(start, stop) + "\nrenderTutorial(view);", {
      tutorialView: tutorial, view: structuredClone(tutorial), refreshTutorial, element,
    });
    expect(element).not.toHaveBeenCalled();
    expect(refreshTutorial).toHaveBeenCalledOnce();
  });

  it("clears stale progress on tutorial entry and ignores late ordinary progress", () => {
    let receive: (event: { data: unknown }) => void = () => {};
    const tasks = new Map([[1, { target: "tree" }]]);
    const entry = { loading: true };
    const progress = vi.fn();
    const renderStatus = vi.fn();
    const context = {
      tutorialView: undefined as unknown,
      savedDefinition: false,
      tasks, nodes: new Map([["window", entry]]), selecting: true, fullPropertiesLoading: true,
      treeError: "old error", detailsError: "old error", failureTarget: "tree",
      progress, renderStatus,
      document: { body: { classList: { toggle: vi.fn() }, inert: false } },
      element: () => ({ classList: { toggle: vi.fn() } }),
      renderTutorial: (view: unknown) => { context.tutorialView = view; },
      window: { addEventListener: (_type: string, handler: typeof receive) => { receive = handler; } },
    };
    const start = script.indexOf('  window.addEventListener("message",');
    const stop = script.lastIndexOf('  renderStatus();\n  post("ready"');
    expect(start).toBeGreaterThan(0);
    expect(stop).toBeGreaterThan(start);
    runInNewContext(script.slice(start, stop), context);
    receive({ data: { type: "tour", tutorial: { step: "spy" } } });
    expect(tasks.size).toBe(0);
    expect(entry.loading).toBe(false);
    expect(context.selecting).toBe(false);
    expect(context.fullPropertiesLoading).toBe(false);
    expect(context.treeError).toBe("");
    expect(renderStatus).toHaveBeenCalledOnce();
    receive({ data: { type: "progress", taskId: 1, done: false } });
    expect(progress).not.toHaveBeenCalled();
    receive({ data: { type: "tour" } });
    receive({ data: { type: "progress", taskId: 2, done: false } });
    expect(progress).toHaveBeenCalledOnce();
  });
});
