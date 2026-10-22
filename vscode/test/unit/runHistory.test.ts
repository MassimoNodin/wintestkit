import * as path from "node:path";
import { describe, expect, it, vi } from "vitest";
import {
  RunHistory,
  runDirectory,
  runNameFrom,
  testItemFrom,
  type HistoryIo,
} from "../../src/runHistory";

const root = path.resolve("/work/app");

function setup(files = new Set<string>(), saved: Record<string, unknown> = {}) {
  const removed: string[] = [];
  const io: HistoryIo = {
    exists: (file) => files.has(path.normalize(file)),
    remove: async (dir) => {
      removed.push(dir);
    },
  };
  const state = {
    get: (key: string) => saved[key] as never,
    update: vi.fn(async (key: string, value: unknown) => {
      saved[key] = value;
    }),
  };
  let tick = 0;
  const clock = () => new Date(2026, 9, 19, 10, 0, 0, tick++ * 1000);
  const history = new RunHistory(state, io, clock);
  const stored = (name: string) => {
    const dir = runDirectory(root, "wtk-report", name);
    files.add(path.join(dir, "results.json"));
    return dir;
  };
  return { history, removed, state, saved, stored, io, clock };
}

describe("what a Test Results button passes", () => {
  it("never prunes active reports, temporarily exceeding retention until completion", async () => {
    const { history, stored, removed } = setup();
    const first = history.newName();
    const firstDir = stored(first);
    history.start(first, "project", "project", firstDir);
    const second = history.newName();
    history.start(second, "project", "project", stored(second));
    const active = new Set([first, second]);
    await history.prune(1, active);
    expect(removed).toEqual([]);
    expect(history.get(first)).toBeDefined();
    active.delete(first);
    await history.prune(1, active);
    expect(removed).toEqual([firstDir]);
    expect(history.get(second)).toBeDefined();
  });
  const info = {
    testRunName: "WinTestKit run A",
    controllerId: "wintestkit",
    resultId: "r1",
    taskId: "t1",
  };
  it("finds the run identity passed alone by the actual run-header button", () => {
    expect(runNameFrom([info])).toBe("WinTestKit run A");
    expect(testItemFrom([info])).toBeUndefined();
  });
  it("does not guess the run from a test item passed without its run identity", () => {
    expect(
      runNameFrom([{ id: "project|test_a.py::test_bad", label: "test_bad" }]),
    ).toBeUndefined();
  });
  it("finds the run name as a separate argument", () => {
    expect(runNameFrom([{ id: "x", label: "x" }, info])).toBe(
      "WinTestKit run A",
    );
  });
  it("finds the run name when both arguments arrive wrapped in one object", () => {
    expect(
      runNameFrom([
        { value: [{ $mid: 16, tests: [{ item: { extId: "e" } }] }, info] },
      ]),
    ).toBe("WinTestKit run A");
  });
  it("finds nothing when no run is named, and survives odd input", () => {
    expect(runNameFrom([])).toBeUndefined();
    expect(
      runNameFrom([undefined, null, "text", 3, { testRunName: 5 }]),
    ).toBeUndefined();
    const loop: Record<string, unknown> = {};
    loop.self = loop;
    expect(runNameFrom([loop])).toBeUndefined();
  });
  it("picks the test item out of the arguments, never the run info", () => {
    const item = { id: "t", label: "t" };
    expect(testItemFrom([info, item])).toBe(item);
    expect(testItemFrom([info])).toBeUndefined();
  });
});

describe("run history", () => {
  it("names each run uniquely, even within the same second", () => {
    const frozen = new RunHistory(
      undefined,
      setup().io,
      () => new Date(2026, 9, 19, 10, 0, 0),
    );
    const names = new Set([
      frozen.newName(),
      frozen.newName(),
      frozen.newName(),
    ]);
    expect(names.size).toBe(3);
    for (const name of names)
      expect(name.startsWith("WinTestKit run ")).toBe(true);
  });

  it("puts each run's report in its own folder under runs/", () => {
    const first = runDirectory(
      root,
      "wtk-report",
      "WinTestKit run 10/19/2026, 10:55:40 AM",
    );
    const second = runDirectory(
      root,
      "wtk-report",
      "WinTestKit run 10/19/2026, 10:33:51 AM",
    );
    expect(first).toBe(
      path.join(root, "wtk-report", "runs", "10-19-2026-10-55-40-AM"),
    );
    expect(second).not.toBe(first);
    expect(runDirectory(root, "out/reports", "WinTestKit run x")).toBe(
      path.join(root, "out", "reports", "runs", "x"),
    );
  });

  it("finds the report folder for a run and for the project that was clicked", () => {
    const { history } = setup();
    const name = history.newName();
    history.start(name, "file:///a", "A", "/a/runs/r");
    history.start(name, "file:///b", "B", "/b/runs/r");
    expect(history.dirFor(name, "file:///b")).toBe("/b/runs/r");
    expect(history.dirFor(name, "file:///zzz")).toBe("/a/runs/r");
    expect(history.dirFor(name)).toBe("/a/runs/r");
    expect(history.dirFor("never", "file:///a")).toBeUndefined();
    expect(history.dirFor(undefined)).toBeUndefined();
  });

  it("records each project's totals and lists runs newest first, only while their results exist", () => {
    const { history, stored } = setup();
    const older = history.newName();
    history.start(older, "file:///a", "A", stored(older));
    history.finish(older, "file:///a", { failed: 1, passed: 5 });
    const newer = history.newName();
    history.start(newer, "file:///a", "A", stored(newer));
    history.finish(newer, "file:///a", { failed: 0, passed: 6 });
    const missing = history.newName();
    history.start(
      missing,
      "file:///a",
      "A",
      runDirectory(root, "wtk-report", missing),
    );
    expect(history.list().map((run) => run.name)).toEqual([newer, older]);
    expect(history.get(older)?.projects["file:///a"]).toMatchObject({
      failed: 1,
      passed: 5,
    });
    history.finish("unknown", "file:///a", { failed: 9, passed: 9 });
    history.finish(undefined, "file:///a", { failed: 9, passed: 9 });
  });

  it("deletes a run's folders when VS Code discards the run, and only folders under runs/", async () => {
    const { history, removed, saved } = setup();
    const name = history.newName();
    const dir = runDirectory(root, "wtk-report", name);
    history.start(name, "file:///a", "A", dir);
    history.start(name, "file:///b", "B", path.join(root, "wtk-report")); // not ours to delete
    await history.discard(name);
    expect(removed).toEqual([dir]);
    expect(history.get(name)).toBeUndefined();
    expect(Object.keys(saved["wintestkit.runHistory"] as object)).toEqual([]);
    await history.discard("unknown");
    expect(removed).toHaveLength(1);
  });

  it("clears only the requested workspace and emits the removed projects", async () => {
    const { history, removed } = setup();
    const listener = vi.fn();
    history.onDidChange(listener);
    history.start("run", "a", "A", path.join(root, "runs", "a"));
    history.start("run", "b", "B", path.join(root, "runs", "b"));
    await history.discard("run", ["a"]);
    expect(removed).toEqual([path.join(root, "runs", "a")]);
    expect(Object.keys(history.get("run")!.projects)).toEqual(["b"]);
    expect(Object.keys(listener.mock.calls[0][0].projects)).toEqual(["a"]);
  });

  it("retains a failed deletion so it can be retried", async () => {
    const { history, io } = setup();
    const remove = vi.spyOn(io, "remove").mockRejectedValueOnce(new Error("locked"));
    history.start("run", "a", "A", path.join(root, "runs", "a"));
    await expect(history.discard("run")).rejects.toThrow("locked");
    expect(history.get("run")).toBeDefined();
    await history.discard("run");
    expect(remove).toHaveBeenCalledTimes(2);
    expect(history.get("run")).toBeUndefined();
  });

  it("serializes simultaneous native disposal and explicit clearing", async () => {
    const { history, removed } = setup();
    history.start("run", "a", "A", path.join(root, "runs", "a"));
    await Promise.all([history.discard("run"), history.discard("run")]);
    expect(removed).toHaveLength(1);
  });

  it("keeps only the newest runs when pruning, and never fewer than one", async () => {
    const { history, removed, stored } = setup();
    const names = [history.newName(), history.newName(), history.newName()];
    for (const name of names)
      history.start(name, "file:///a", "A", stored(name));
    await history.prune(2);
    expect(removed).toEqual([runDirectory(root, "wtk-report", names[0])]);
    await history.prune(0);
    expect(history.get(names[2])).toBeDefined();
    expect(history.get(names[1])).toBeUndefined();
  });

  it("restores saved runs after a restart and drops those whose results were deleted", () => {
    const { history, stored, saved } = setup();
    const kept = history.newName();
    history.start(kept, "file:///a", "A", stored(kept));
    const gone = history.newName();
    history.start(
      gone,
      "file:///a",
      "A",
      runDirectory(root, "wtk-report", gone),
    );
    const files = new Set([
      path.join(runDirectory(root, "wtk-report", kept), "results.json"),
    ]);
    const restarted = setup(files, saved).history;
    expect(restarted.get(kept)).toBeDefined();
    expect(restarted.get(gone)).toBeUndefined();
  });
});
