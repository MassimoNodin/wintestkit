import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { Project } from "../../src/server/serverManager";
const mocks = vi.hoisted(() => ({
  spawn: vi.fn(),
  execFile: vi.fn(),
  trusted: true,
}));
vi.mock("node:child_process", () => ({
  spawn: mocks.spawn,
  execFile: mocks.execFile,
}));
vi.mock("vscode", () => ({
  workspace: {
    get isTrusted() {
      return mocks.trusted;
    },
  },
}));
import { runArguments, runProcess, replaysByDefault } from "../../src/testing/runner";
class Child extends EventEmitter {
  pid = 1234;
  stdout = new PassThrough();
  stderr = new PassThrough();
  kill = vi.fn(() => {
    this.emit("close", null);
    return true;
  });
}
const project = {
  root: { fsPath: "C:/project with spaces" },
  name: "demo",
} as Project;
beforeEach(() => {
  vi.clearAllMocks();
  mocks.trusted = true;
});
describe("test subprocess runner", () => {
  it("preserves argument boundaries and places nodeids after the separator", () => {
    expect(
      runArguments(
        "tcp://127.0.0.1:123",
        ["tests/test.py::test_case[with space]"],
        true,
        ["-k", "selected"],
      ),
    ).toEqual([
      "-m",
      "wintestkit",
      "run",
      "--events",
      "tcp://127.0.0.1:123",
      "--no-html",
      "--highlight",
      "-k",
      "selected",
      "--",
      "tests/test.py::test_case[with space]",
    ]);
  });
  it("enables backend replay retention for the recording profile", () => {
    const args = runArguments("tcp://localhost:1", ["test_x"], false, ["--replay", "off"], true);
    expect(args.lastIndexOf("retain-on-failure")).toBeGreaterThan(args.indexOf("off"));
    expect(args.slice(args.lastIndexOf("--replay"), args.indexOf("--"))).toEqual(["--replay", "retain-on-failure"]);
  });
  it("records a replay by default that extra args and the recording profile can override", () => {
    const args = runArguments("tcp://localhost:1", ["test_x"], false, ["--replay", "off"], true, true);
    expect(args.slice(args.indexOf("--replay"), args.indexOf("--replay") + 2)).toEqual(["--replay", "on"]);
    expect(args.slice(args.lastIndexOf("--replay"), args.indexOf("--"))).toEqual(["--replay", "retain-on-failure"]);
    expect(runArguments("tcp://localhost:1", ["test_x"], false, [])).not.toContain("--replay");
  });
  it("only defaults to tracing when nothing chose a replay mode", () => {
    expect(replaysByDefault({}, [], {})).toBe(true);
    expect(replaysByDefault({ replay: "off" }, [], {})).toBe(false);
    expect(replaysByDefault({}, ["--replay=off"], {})).toBe(false);
    expect(replaysByDefault({}, ["--wtk-replay", "off"], {})).toBe(false);
    expect(replaysByDefault({}, ["--replay-fps", "2"], {})).toBe(true);
    expect(replaysByDefault({}, [], { WTK_REPLAY: "off" })).toBe(false);
  });
  it("gives a run its own report folder when asked", () => {
    const args = runArguments("tcp://localhost:1", ["test_x"], false, [], false, false, "C:/p/wtk-report/runs/r1");
    expect(args.slice(args.indexOf("--report"), args.indexOf("--report") + 2)).toEqual(["--report", "C:/p/wtk-report/runs/r1"]);
    expect(args.indexOf("--report")).toBeLessThan(args.indexOf("--"));
    expect(runArguments("tcp://localhost:1", ["test_x"], false, [])).not.toContain("--report");
  });
  it("decodes chunked Unicode output and exits without leaking cancellation subscriptions", async () => {
    const child = new Child();
    mocks.spawn.mockReturnValue(child);
    const dispose = vi.fn();
    const token = {
      isCancellationRequested: false,
      onCancellationRequested: () => ({ dispose }),
    } as unknown as vscode.CancellationToken;
    const output = vi.fn();
    const completed = runProcess(project, "python.exe", ["run"], token, output);
    child.stdout.write(Buffer.from([0xc3]));
    child.stdout.write(Buffer.from([0xa9, 0x0a]));
    child.emit("close", 0);
    expect(await completed).toBe(0);
    expect(output.mock.calls.map((call) => call[0]).join("")).toBe(
      "\u00e9\r\n",
    );
    expect(dispose).toHaveBeenCalledOnce();
    expect(mocks.spawn).toHaveBeenCalledWith(
      "python.exe",
      ["run"],
      expect.objectContaining({ cwd: project.root.fsPath, windowsHide: true }),
    );
  });
  it("does not spawn cancelled or untrusted runs", async () => {
    const token = { isCancellationRequested: true } as vscode.CancellationToken;
    expect(
      await runProcess(project, "python.exe", [], token, vi.fn()),
    ).toBeNull();
    mocks.trusted = false;
    await expect(
      runProcess(
        project,
        "python.exe",
        [],
        { isCancellationRequested: false } as vscode.CancellationToken,
        vi.fn(),
      ),
    ).rejects.toThrow("Trust the workspace");
    expect(mocks.spawn).not.toHaveBeenCalled();
  });
});
