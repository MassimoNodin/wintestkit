import { describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { Project } from "../../src/server/serverManager";
import { EventMapper, type RunAction } from "../../src/testing/eventMapper";

vi.mock("vscode", () => ({
  Uri: { file: (file: string) => ({ fsPath: file }) },
  Range: class {},
}));
vi.mock("../../src/python", () => ({ getInterpreter: vi.fn() }));
vi.mock("../../src/testing/saveSources", () => ({ saveExecutionSources: vi.fn(async () => false) }));
vi.mock("../../src/testing/runner", () => ({ runProcess: vi.fn(), runArguments: vi.fn(), replaysByDefault: vi.fn() }));
import { TestController } from "../../src/testing/controller";
import { saveExecutionSources } from "../../src/testing/saveSources";
import { runProcess } from "../../src/testing/runner";

describe("refresh during a runtime parameterized run", () => {
  it("keeps collected items reachable for later passing events", () => {
    const project = { root: { fsPath: "/project" } } as Project;
    const nodeid = "tests/test_a.py::test_ok";
    const items = new Map<string, vscode.TestItem>();
    const parent = { children: { add: vi.fn() } } as unknown as vscode.TestItem;
    items.set("/project|" + nodeid, parent);
    const controller = Object.assign(Object.create(TestController.prototype), {
      items, metadata: new WeakMap(), active: new Set([{}]),
      lastMessages: new Map(),
      controller: {
        createTestItem: (id: string, label: string) => ({ id, label }),
      },
    }) as {
      rebuild(): void;
      apply(project: Project, run: vscode.TestRun, actions: RunAction[]): void;
      rebuildPending: boolean;
    };
    const mapper = new EventMapper([nodeid]);
    const run = { enqueued: vi.fn(), passed: vi.fn() } as unknown as vscode.TestRun;
    const runtimeId = nodeid + "[one]";
    controller.apply(project, run, mapper.consume({
      event: "collected", time: 0, errors: [],
      tests: [{ id: runtimeId, name: "test_ok[one]", file: "/project/tests/test_a.py", line: 0, parent: nodeid }],
    }));
    controller.rebuild();
    const child = items.get("/project|" + runtimeId);
    expect(child).toBeDefined();
    controller.apply(project, run, mapper.consume({
      event: "test_end", time: 1, id: runtimeId, outcome: "passed", duration: 0.2, screenshots: [],
    }));
    expect(run.passed).toHaveBeenCalledWith(child, 200);
    expect(controller.rebuildPending).toBe(true);
  });
  it.each([[false, false], [true, false], [false, true]])("blocks execution without source-save consent (debug %s, recording %s)", async (debug, recording) => {
    const project = { root: { fsPath: "/project" } } as Project;
    const item = { id: "/project|test" } as vscode.TestItem;
    const metadata = new WeakMap([[item, { project, nodeid: "test" }]]);
    const controller = Object.assign(Object.create(TestController.prototype), {
      metadata, items: new Map([[item.id, item]]), projects: {},
      lastMessages: new Map(), log: { error: vi.fn() },
    }) as { runProject(project: Project, items: vscode.TestItem[], run: vscode.TestRun, token: vscode.CancellationToken, debug: boolean, recording: boolean): Promise<void> };
    const run = { skipped: vi.fn(), errored: vi.fn(), appendOutput: vi.fn() } as unknown as vscode.TestRun;
    await controller.runProject(project, [item], run, { isCancellationRequested: false } as vscode.CancellationToken, debug, recording);
    expect(saveExecutionSources).toHaveBeenCalled();
    expect(run.skipped).toHaveBeenCalledWith(item);
    expect(run.errored).not.toHaveBeenCalled();
    expect(runProcess).not.toHaveBeenCalled();
  });
});
