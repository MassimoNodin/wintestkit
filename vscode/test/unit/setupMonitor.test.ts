import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  execute: vi.fn(async (...args: unknown[]): Promise<unknown> => void args),
  interpreter: vi.fn(async (): Promise<string | undefined> => "C:/py/python.exe"),
  installed: vi.fn(async (): Promise<{ installed: boolean; version?: string }> => ({ installed: true, version: "0.1.1" })),
  config: vi.fn(async (): Promise<Record<string, unknown>> => ({ "app.path": "C:/Apps/Demo.exe" })),
  warning: vi.fn(async (): Promise<string | undefined> => undefined),
  running: false,
  hasProject: true,
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
import { EXTRA_STEPS } from "../../src/setup/tour";

const root = { fsPath: "C:/work", toString: () => "file:///C:/work" };
const project = { root, name: "work" };

const make = (options: { enabled?: boolean; memento?: Record<string, unknown> } = {}) => {
  const values = new Map<string, unknown>(Object.entries(options.memento ?? {}));
  const memento = {
    get: <T>(key: string, fallback?: T) => (values.has(key) ? (values.get(key) as T) : fallback),
    update: async (key: string, value: unknown) => void values.set(key, value),
  };
  const projects = {
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
  const monitor = new SetupMonitor(
    projects as never,
    status as never,
    memento as never,
    { warn: vi.fn(), debug: vi.fn() } as never,
    enablement as never,
    installer as never,
    "0.1.1",
  );
  return { monitor, values, installer };
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
    mocks.interpreterListeners.length = 0;
  });
  afterEach(() => vi.useRealTimers());

  it("does not walk a workspace through setup that was already set up", async () => {
    const { monitor, values } = make();
    await settle();
    expect(monitor.tour).toBeUndefined();
    expect(monitor.resumable).toBe(false);
    expect(values.get("wintestkit.tour.completed")).toBe(true);
    monitor.dispose();
  });

  it("starts the tour at the first step that is not done", async () => {
    mocks.hasProject = false;
    mocks.interpreter.mockResolvedValue(undefined);
    const { monitor } = make();
    await settle();
    expect(monitor.tour).toMatchObject({ step: "interpreter", phase: "setup", progress: { index: 1, total: 7 } });
    expect(monitor.focus).toEqual({ dim: true, spyLit: false });
    // Picking an interpreter moves it on to installing the package.
    mocks.interpreter.mockResolvedValue("C:/py/python.exe");
    mocks.installed.mockResolvedValue({ installed: false });
    mocks.interpreterListeners.forEach((listener) => listener());
    await vi.advanceTimersByTimeAsync(2000);
    expect(monitor.tour).toMatchObject({ step: "package", lit: ["package"] });
    monitor.dispose();
  });

  it("goes back and forward without undoing anything", async () => {
    mocks.hasProject = false;
    mocks.installed.mockResolvedValue({ installed: false });
    const { monitor } = make();
    await settle();
    expect(monitor.tour?.step).toBe("package");
    monitor.back();
    expect(monitor.tour).toMatchObject({ step: "interpreter", kind: "done", canNext: true, canBack: false });
    monitor.next();
    expect(monitor.tour).toMatchObject({ step: "package", canNext: false });
    monitor.dispose();
  });

  it("asks about the launch mode once, and remembers the answer", async () => {
    mocks.config.mockResolvedValue({ "app.path": "C:/Apps/Demo.exe", launch: "per-test" });
    const { monitor, values } = make({ memento: { "wintestkit.tour.seen": true } });
    await settle();
    expect(monitor.tour).toMatchObject({ step: "mode", lit: ["mode"] });
    await monitor.confirmMode();
    expect(values.get("wintestkit.tour.modeConfirmed")).toBe(true);
    expect(monitor.tour).toMatchObject({ step: "launch" });
    monitor.dispose();
  });

  it("finishes with the extras or by closing the introduction", async () => {
    mocks.running = true;
    const { monitor, values } = make({ memento: { "wintestkit.tour.seen": true, "wintestkit.tour.modeConfirmed": true } });
    await settle();
    expect(monitor.tour?.step).toBe("complete");
    monitor.continueExtras();
    expect(monitor.tour).toMatchObject({ step: "spy", phase: "extras" });
    expect(monitor.focus).toEqual({ dim: false, spyLit: true });
    for (const step of EXTRA_STEPS.slice(1)) {
      monitor.next();
      expect(monitor.tour?.step).toBe(step);
    }
    for (const step of [...EXTRA_STEPS.slice(0, -1)].reverse()) {
      monitor.back();
      expect(monitor.tour?.step).toBe(step);
    }
    monitor.back();
    expect(monitor.tour?.step).toBe("complete");
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

  it("counts closing the introduction on the last card as finishing setup", async () => {
    mocks.running = true;
    const { monitor, values } = make({ memento: { "wintestkit.tour.seen": true, "wintestkit.tour.modeConfirmed": true } });
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
    // The sidebar is already showing it, so there is no pop-up as well.
    expect(mocks.warning).not.toHaveBeenCalled();
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
