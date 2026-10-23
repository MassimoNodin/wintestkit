import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  execute: vi.fn(async (...args: unknown[]): Promise<unknown> => void args),
  interpreter: vi.fn(async (): Promise<string | undefined> => "C:/py/python.exe"),
  installed: vi.fn(async (): Promise<{ installed: boolean; version?: string }> => ({ installed: true, version: "0.1.1" })),
  config: vi.fn(async (): Promise<Record<string, unknown>> => ({ "app.path": "C:/Apps/Demo.exe" })),
  warning: vi.fn(async (): Promise<string | undefined> => undefined),
  running: false,
  hasProject: true,
  projectsLoaded: true,
  interpreterListeners: [] as (() => void)[],
}));

vi.mock("node:child_process", () => ({
  execFile: (_file: string, _args: string[], _options: unknown, callback: (error: null, stdout: string) => void) =>
    callback(null, JSON.stringify([{ id: "platform", title: "Windows", status: "ok", detail: "ok" }])),
}));
vi.mock("node:fs", () => ({ existsSync: () => true }));
vi.mock("../../src/python", () => ({
  getInterpreter: mocks.interpreter,
  checkWintestkit: mocks.installed,
  describeInterpreter: async () => ({ name: ".venv", path: "C:/py/python.exe", overridden: false }),
  onDidChangeInterpreter: async (listener: () => void) => {
    mocks.interpreterListeners.push(listener);
    return { dispose() {} };
  },
}));
vi.mock("../../src/settings/files", () => ({ readConfiguration: mocks.config }));
vi.mock("vscode", () => {
  class EventEmitter {
    private listeners = new Set<(value: unknown) => void>();
    event = (listener: (value: unknown) => void) => {
      this.listeners.add(listener);
      return { dispose: () => this.listeners.delete(listener) };
    };
    fire(value?: unknown) {
      this.listeners.forEach((listener) => listener(value));
    }
    dispose() {}
  }
  const noop = () => ({ dispose() {} });
  return {
    EventEmitter,
    commands: { executeCommand: mocks.execute },
    window: { activeTextEditor: undefined, showWarningMessage: mocks.warning },
    workspace: {
      workspaceFolders: [{ uri: { fsPath: "C:/work", toString: () => "file:///C:/work" } }],
      onDidChangeConfiguration: noop,
    },
  };
});
import { SetupMonitor } from "../../src/setup/monitor";
import { EXTRA_STEPS, SETUP_STEPS } from "../../src/setup/tour";

const root = { fsPath: "C:/work", toString: () => "file:///C:/work" };
const project = { root, name: "work" };

const make = (options: { enabled?: boolean; memento?: Record<string, unknown> } = {}) => {
  const values = new Map<string, unknown>(Object.entries(options.memento ?? {}));
  const memento = {
    get: <T>(key: string, fallback?: T) => (values.has(key) ? (values.get(key) as T) : fallback),
    update: vi.fn(async (key: string, value: unknown) => void values.set(key, value)),
  };
  const projects = {
    get loaded() {
      return mocks.projectsLoaded;
    },
    get all() {
      return mocks.hasProject ? [project] : [];
    },
    projectFor: () => (mocks.hasProject ? project : undefined),
    onDidChange: () => ({ dispose() {} }),
  };
  const status = {
    onDidChangeApplication: () => ({ dispose() {} }),
    applicationState: () => ({ running: mocks.running }),
  };
  const enablement = { enabled: options.enabled ?? true, onDidChange: () => ({ dispose() {} }) };
  const installer = { busy: false, error: undefined, onDidChange: () => ({ dispose() {} }) };
  const log = { warn: vi.fn(), debug: vi.fn() };
  const monitor = new SetupMonitor(
    projects as never,
    status as never,
    memento as never,
    log as never,
    enablement as never,
    installer as never,
    "0.1.1",
  );
  return { monitor, values, installer, memento, log };
};
const contexts = (key: string) =>
  mocks.execute.mock.calls.filter(([name, id]) => name === "setContext" && id === key).map(([, , value]) => value);
const settle = () => vi.advanceTimersByTimeAsync(50);

describe("setup monitor", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mocks.interpreter.mockResolvedValue("C:/py/python.exe");
    mocks.installed.mockResolvedValue({ installed: true, version: "0.1.1" });
    mocks.config.mockResolvedValue({ "app.path": "C:/Apps/Demo.exe" });
    mocks.execute.mockResolvedValue(undefined);
    mocks.warning.mockResolvedValue(undefined);
    mocks.running = false;
    mocks.hasProject = true;
    mocks.projectsLoaded = true;
    mocks.interpreterListeners.length = 0;
  });
  afterEach(() => vi.useRealTimers());

  it("waits for the projects to be found, so a set-up project does not flash as missing", async () => {
    // On a reload the project list is still empty for a moment; the project step passed before.
    mocks.projectsLoaded = false;
    mocks.hasProject = false;
    const { monitor } = make({
      memento: { "wintestkit.setup.passed": ["interpreter", "package", "project"] },
    });
    await settle();
    expect(monitor.health).toBeUndefined();
    expect(monitor.tour).toBeUndefined();
    expect(monitor.blocker).toBeUndefined();
    expect(mocks.warning).not.toHaveBeenCalled();
    expect(contexts("wintestkit.setupBlocked")).not.toContain(true);
    mocks.hasProject = true;
    mocks.projectsLoaded = true;
    await monitor.check();
    expect(monitor.health?.project.state).toBe("ok");
    expect(monitor.tour?.step).not.toBe("project");
    monitor.dispose();
  });

  it("starts the first introduction even in an already configured workspace", async () => {
    const { monitor, values } = make();
    await settle();
    expect(monitor.tour).toMatchObject({ step: "interpreter", phase: "setup", kind: "done", canNext: true });
    expect(monitor.resumable).toBe(false);
    expect(values.get("wintestkit.tour.completed")).toBeUndefined();
    monitor.dispose();
  });

  it("visits all seven steps without auto-advancing past healthy steps", async () => {
    mocks.running = true;
    const { monitor, values } = make();
    await settle();
    for (const [index, step] of SETUP_STEPS.entries()) {
      expect(monitor.tour).toMatchObject({ step, progress: { index: index + 1, total: 7 } });
      await monitor.check();
      expect(monitor.tour?.step).toBe(step);
      if (step === "mode") {
        expect(monitor.tour?.canNext).toBe(false);
        await monitor.confirmMode();
        expect(monitor.tour?.step).toBe("mode");
      }
      expect(monitor.tour?.canNext).toBe(true);
      monitor.next();
    }
    expect(monitor.tour?.step).toBe("complete");
    expect(values.get("wintestkit.tour.cursor")).toBe("complete");
    await monitor.finish();
    expect(monitor.tour).toBeUndefined();
    expect(values.get("wintestkit.tour.completed")).toBe(true);
    expect(values.get("wintestkit.tour.cursor")).toBeUndefined();
    monitor.dispose();
  });

  it("waits for the user to advance after fixing the current first-run step", async () => {
    mocks.hasProject = false;
    mocks.interpreter.mockResolvedValue(undefined);
    const { monitor } = make();
    await settle();
    expect(monitor.tour).toMatchObject({ step: "interpreter", phase: "setup", progress: { index: 1, total: 7 } });
    expect(monitor.focus).toEqual({ dim: true, spyLit: false });
    monitor.next();
    monitor.continueExtras();
    await monitor.finish();
    expect(monitor.tour?.step).toBe("interpreter");
    mocks.interpreter.mockResolvedValue("C:/py/python.exe");
    mocks.installed.mockResolvedValue({ installed: false });
    mocks.interpreterListeners.forEach((listener) => listener());
    await vi.advanceTimersByTimeAsync(2000);
    expect(monitor.tour).toMatchObject({ step: "interpreter", kind: "done", canNext: true });
    monitor.next();
    expect(monitor.tour).toMatchObject({ step: "package", lit: ["package"] });
    monitor.dispose();
  });

  it("goes back and forward without undoing anything", async () => {
    mocks.hasProject = false;
    mocks.installed.mockResolvedValue({ installed: false });
    const { monitor } = make();
    await settle();
    monitor.next();
    expect(monitor.tour?.step).toBe("package");
    monitor.back();
    expect(monitor.tour).toMatchObject({ step: "interpreter", kind: "done", canNext: true, canBack: false });
    monitor.next();
    expect(monitor.tour).toMatchObject({ step: "package", canNext: false });
    monitor.dispose();
  });

  it("asks about the launch mode once, and remembers the answer", async () => {
    mocks.config.mockResolvedValue({ "app.path": "C:/Apps/Demo.exe", launch: "per-test" });
    const { monitor, values } = make({ memento: { "wintestkit.tour.cursor": "mode" } });
    await settle();
    expect(monitor.tour).toMatchObject({ step: "mode", lit: ["mode"] });
    await monitor.confirmMode();
    expect(values.get("wintestkit.tour.modeConfirmed")).toBe(true);
    expect(monitor.tour).toMatchObject({ step: "mode", kind: "done", canNext: true });
    monitor.next();
    expect(monitor.tour).toMatchObject({ step: "launch" });
    monitor.dispose();
  });

  it("finishes with the extras or by closing the introduction", async () => {
    mocks.running = true;
    const { monitor, values } = make({ memento: { "wintestkit.tour.cursor": "complete", "wintestkit.tour.modeConfirmed": true } });
    await settle();
    expect(monitor.tour?.step).toBe("complete");
    monitor.continueExtras();
    expect(monitor.tour).toMatchObject({ step: "spy", phase: "extras" });
    expect(values.get("wintestkit.tour.cursor")).toBe("spy");
    expect(monitor.focus).toEqual({ dim: false, spyLit: true });
    for (const step of EXTRA_STEPS.slice(1)) {
      monitor.next();
      expect(monitor.tour?.step).toBe(step);
      expect(values.get("wintestkit.tour.cursor")).toBe(step);
    }
    for (const step of [...EXTRA_STEPS.slice(0, -1)].reverse()) {
      monitor.back();
      expect(monitor.tour?.step).toBe(step);
      expect(values.get("wintestkit.tour.cursor")).toBe(step);
    }
    monitor.back();
    expect(monitor.tour?.step).toBe("complete");
    expect(values.get("wintestkit.tour.cursor")).toBe("complete");
    await monitor.finish();
    expect(values.get("wintestkit.tour.completed")).toBe(true);
    expect(monitor.tour).toBeUndefined();
    monitor.dispose();
  });

  it("skips the tutorial without disabling WinTestKit or leaving a resume prompt", async () => {
    const { monitor, values } = make({ memento: { "wintestkit.tour.seen": true } });
    await settle();
    expect(monitor.tour).toBeDefined();
    await monitor.skip();
    expect(values.get("wintestkit.tour.completed")).toBe(true);
    expect(values.get("wintestkit.tour.modeConfirmed")).toBe(true);
    expect(monitor.tour).toBeUndefined();
    expect(monitor.resumable).toBe(false);
    expect(mocks.execute).not.toHaveBeenCalledWith("wintestkit.disable");
    await monitor.check();
    expect(monitor.tour).toBeUndefined();
    monitor.dispose();
  });

  it.each(EXTRA_STEPS)("pauses persisted extras at %s on reload until explicitly resumed", async (step) => {
    mocks.running = true;
    const { monitor, values } = make({ memento: {
      "wintestkit.tour.cursor": "complete",
      "wintestkit.tour.modeConfirmed": true,
    } });
    await settle();
    monitor.continueExtras();
    for (const previous of EXTRA_STEPS) {
      if (previous === step) break;
      monitor.next();
    }
    expect(values.get("wintestkit.tour.cursor")).toBe(step);
    monitor.dispose();

    const reloaded = make({ memento: Object.fromEntries(values) }).monitor;
    await settle();
    expect(reloaded.tour).toBeUndefined();
    expect(reloaded.resumable).toBe(true);
    expect(reloaded.focus).toEqual({ dim: false, spyLit: false });
    mocks.running = false;
    await reloaded.check();
    expect(reloaded.tour).toBeUndefined();
    expect(reloaded.resumable).toBe(true);
    expect(reloaded.focus).toEqual({ dim: false, spyLit: false });
    reloaded.resume();
    expect(reloaded.tour).toMatchObject({ step: "spy", phase: "extras" });
    reloaded.back();
    expect(reloaded.tour?.step).toBe("launch");
    mocks.running = true;
    await reloaded.check();
    expect(reloaded.tour?.step).toBe("complete");
    reloaded.dispose();
  });

  it("opening the sidebar explicitly restarts paused extras at the first card", async () => {
    const { monitor, values } = make({ memento: {
      "wintestkit.tour.cursor": "spyLocators",
      "wintestkit.tour.modeConfirmed": true,
    } });
    await settle();
    expect(monitor.tour).toBeUndefined();
    await monitor.show();
    expect(monitor.tour).toMatchObject({ step: "spy", phase: "extras" });
    expect(values.get("wintestkit.tour.cursor")).toBe("spy");
    expect(mocks.execute).toHaveBeenCalledWith("workbench.view.extension.wintestkit");
    monitor.dispose();
  });

  it("pauses extras when their progress cannot be saved and allows an explicit restart", async () => {
    mocks.running = true;
    const { monitor, values, memento, log } = make({ memento: {
      "wintestkit.tour.cursor": "complete",
      "wintestkit.tour.modeConfirmed": true,
    } });
    await settle();
    memento.update.mockRejectedValueOnce(new Error("storage unavailable"));
    monitor.continueExtras();
    await settle();
    expect(monitor.tour).toBeUndefined();
    expect(monitor.resumable).toBe(true);
    expect(monitor.focus).toEqual({ dim: false, spyLit: false });
    expect(log.warn).toHaveBeenCalledWith(expect.stringContaining("Cannot save tutorial progress"));
    monitor.resume();
    expect(monitor.tour?.step).toBe("spy");
    expect(values.get("wintestkit.tour.cursor")).toBe("spy");
    monitor.next();
    memento.update.mockRejectedValueOnce(new Error("storage unavailable"));
    monitor.next();
    await settle();
    expect(monitor.tour).toBeUndefined();
    expect(monitor.resumable).toBe(true);
    monitor.resume();
    expect(monitor.tour?.step).toBe("spy");
    monitor.back();
    expect(monitor.tour?.step).toBe("complete");
    monitor.dispose();
  });

  it.each([
    { action: "finish", extras: false },
    { action: "skip", extras: false },
    { action: "finish", extras: true },
    { action: "skip", extras: true },
  ] as const)("$action publishes completion before rejected persistence (extras: $extras)", async ({ action, extras }) => {
    mocks.running = true;
    const { monitor, memento } = make({ memento: {
      "wintestkit.tour.cursor": "complete",
      "wintestkit.tour.modeConfirmed": true,
    } });
    await settle();
    if (extras) {
      monitor.continueExtras();
      monitor.next();
    }
    const changed = vi.fn();
    monitor.onDidChange(changed);
    memento.update.mockClear();
    memento.update.mockImplementation(async () => {
      expect(changed).toHaveBeenCalled();
      expect(monitor.tour).toBeUndefined();
      expect(monitor.resumable).toBe(false);
      expect(monitor.focus).toEqual({ dim: false, spyLit: false });
      throw new Error("storage unavailable");
    });
    const completion = monitor[action]();
    expect(changed).toHaveBeenCalledTimes(1);
    expect(monitor.tour).toBeUndefined();
    expect(monitor.focus).toEqual({ dim: false, spyLit: false });
    await expect(completion).rejects.toThrow("storage unavailable");
    expect(memento.update).toHaveBeenCalledWith("wintestkit.tour.completed", true);
    expect(memento.update).toHaveBeenCalledWith("wintestkit.tour.modeConfirmed", true);
    expect(memento.update).toHaveBeenCalledWith("wintestkit.tour.cursor", undefined);
    await monitor.check();
    expect(monitor.tour).toBeUndefined();
    expect(monitor.resumable).toBe(false);
    monitor.dispose();
  });

  it("closing extras persists completion so reopening and reloading do not replay them", async () => {
    mocks.running = true;
    const { monitor, values } = make({ memento: {
      "wintestkit.tour.cursor": "spySelection",
      "wintestkit.tour.modeConfirmed": true,
    } });
    await settle();
    monitor.resume();
    monitor.next();
    monitor.close();
    expect(monitor.tour).toBeUndefined();
    expect(monitor.resumable).toBe(false);
    await settle();
    await monitor.show();
    expect(monitor.tour).toBeUndefined();
    monitor.dispose();
    expect(values.get("wintestkit.tour.completed")).toBe(true);
    expect(values.get("wintestkit.tour.cursor")).toBeUndefined();
    const reloaded = make({ memento: Object.fromEntries(values) }).monitor;
    await settle();
    expect(reloaded.tour).toBeUndefined();
    expect(reloaded.resumable).toBe(false);
    expect(reloaded.focus).toEqual({ dim: false, spyLit: false });
    reloaded.dispose();
  });

  it.each(["complete", "spyPick"])("closing %s catches failed completion writes without replay", async (cursor) => {
    mocks.running = true;
    const { monitor, memento, log } = make({ memento: {
      "wintestkit.tour.cursor": cursor,
      "wintestkit.tour.modeConfirmed": true,
    } });
    await settle();
    if (monitor.resumable) monitor.resume();
    memento.update.mockRejectedValue(new Error("storage unavailable"));
    monitor.close();
    expect(monitor.tour).toBeUndefined();
    expect(monitor.resumable).toBe(false);
    expect(monitor.focus).toEqual({ dim: false, spyLit: false });
    await settle();
    expect(log.warn).toHaveBeenCalledWith(expect.stringContaining("Cannot save tutorial completion"));
    await monitor.show();
    expect(monitor.tour).toBeUndefined();
    await monitor.check();
    expect(monitor.tour).toBeUndefined();
    monitor.dispose();
  });

  it("counts closing the introduction on the last card as finishing setup", async () => {
    mocks.running = true;
    const { monitor, values } = make({ memento: { "wintestkit.tour.cursor": "complete", "wintestkit.tour.modeConfirmed": true } });
    await settle();
    monitor.close();
    expect(values.get("wintestkit.tour.completed")).toBe(true);
    expect(monitor.tour).toBeUndefined();
    expect(monitor.resumable).toBe(false);
    monitor.dispose();
  });

  it("can be closed part way and resumed, and the sidebar shrinks to a button meanwhile", async () => {
    mocks.hasProject = false;
    mocks.interpreter.mockResolvedValue(undefined);
    const { monitor } = make();
    await settle();
    expect(contexts("wintestkit.setupBlocked").at(-1)).toBe(false);
    monitor.close();
    expect(monitor.tour).toBeUndefined();
    expect(monitor.resumable).toBe(true);
    expect(monitor.blocker).toMatchObject({ step: "interpreter" });
    expect(contexts("wintestkit.setupBlocked").at(-1)).toBe(true);
    monitor.resume();
    expect(monitor.tour?.step).toBe("interpreter");
    expect(contexts("wintestkit.setupBlocked").at(-1)).toBe(false);
    monitor.dispose();
  });

  it("remembers explicit progress when the guide is closed or the extension reloads", async () => {
    mocks.hasProject = false;
    mocks.installed.mockResolvedValue({ installed: false });
    const { monitor, values } = make();
    await settle();
    monitor.next();
    expect(monitor.tour?.step).toBe("package");
    monitor.close();
    monitor.resume();
    expect(monitor.tour?.step).toBe("package");
    expect(values.get("wintestkit.tour.cursor")).toBe("package");
    monitor.dispose();
    const reloaded = make({ memento: Object.fromEntries(values) }).monitor;
    await settle();
    expect(reloaded.tour?.step).toBe("package");
    reloaded.next();
    expect(reloaded.tour?.step).toBe("package");
    reloaded.dispose();
  });

  it.each(["invalid", 123])("ignores an invalid stored tutorial cursor: %s", async (cursor) => {
    const { monitor } = make({ memento: { "wintestkit.tour.cursor": cursor } });
    await settle();
    expect(monitor.tour?.step).toBe("interpreter");
    monitor.dispose();
  });

  const finished = {
    "wintestkit.tour.seen": true,
    "wintestkit.tour.completed": true,
    "wintestkit.setup.passed": ["interpreter", "package", "machine", "project", "app", "launch"],
  };
  const breakPackage = async () => {
    mocks.installed.mockResolvedValue({ installed: false });
    mocks.interpreterListeners.forEach((listener) => listener());
    await vi.advanceTimersByTimeAsync(2000);
  };

  it("brings the tour back for a step that stopped working after setup was finished", async () => {
    const { monitor } = make({ memento: finished });
    await settle();
    expect(monitor.tour).toBeUndefined();
    await breakPackage();
    expect(monitor.tour).toMatchObject({ step: "package", phase: "repair", kind: "attention", lit: ["package"] });
    monitor.back();
    monitor.next();
    expect(monitor.tour?.step).toBe("package");
    // The sidebar is already showing it, so there is no pop-up as well.
    expect(mocks.warning).not.toHaveBeenCalled();
    mocks.installed.mockResolvedValue({ installed: true, version: "0.1.1" });
    await monitor.check();
    expect(monitor.tour).toBeUndefined();
    monitor.dispose();
  });

  it("skips healthy steps between repairs and hides the guide after the last fix", async () => {
    const { monitor } = make({ memento: finished });
    await settle();
    mocks.installed.mockResolvedValue({ installed: false });
    mocks.config.mockResolvedValue({});
    await monitor.check();
    expect(monitor.tour).toMatchObject({ step: "package", phase: "repair", canBack: false, canNext: false });
    mocks.installed.mockResolvedValue({ installed: true, version: "0.1.1" });
    await monitor.check();
    expect(monitor.tour).toMatchObject({ step: "app", phase: "repair", canBack: false, canNext: false });
    expect(monitor.tour?.progress).toBeUndefined();
    mocks.config.mockResolvedValue({ "app.path": "C:/Apps/Demo.exe" });
    await monitor.check();
    expect(monitor.tour).toBeUndefined();
    monitor.dispose();
  });

  it("tells the user with a pop-up when the tour is closed, and the pop-up brings it back", async () => {
    const { monitor } = make({ memento: finished });
    await settle();
    monitor.close();
    mocks.warning.mockResolvedValue("Open WinTestKit");
    await breakPackage();
    expect(mocks.warning).toHaveBeenCalledWith(expect.stringContaining("The wintestkit package needs attention"), "Open WinTestKit");
    await vi.advanceTimersByTimeAsync(10);
    expect(monitor.tour?.step).toBe("package");
    expect(mocks.execute).toHaveBeenCalledWith("workbench.view.extension.wintestkit");
    monitor.dispose();
  });

  it("opens the sidebar with the guide showing", async () => {
    mocks.hasProject = false;
    mocks.interpreter.mockResolvedValue(undefined);
    const { monitor } = make();
    await settle();
    monitor.close();
    await monitor.show();
    expect(monitor.tour?.step).toBe("interpreter");
    expect(mocks.execute).toHaveBeenCalledWith("workbench.view.extension.wintestkit");
    monitor.dispose();
  });

  it("checks nothing until WinTestKit is enabled for the workspace", async () => {
    const { monitor } = make({ enabled: false });
    await settle();
    expect(mocks.interpreter).not.toHaveBeenCalled();
    expect(monitor.health).toBeUndefined();
    expect(monitor.tour).toBeUndefined();
    monitor.dispose();
  });
});
