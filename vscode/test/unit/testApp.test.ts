import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { ServerManager, Project } from "../../src/server/serverManager";
import {
  buildTestAppModel,
  launchModeId,
  modeChoices,
} from "../../src/settings/testAppModel";
import type { ApplicationState } from "../../src/statusBar";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  getServer: vi.fn(),
  statusItem: { hide: vi.fn(), show: vi.fn(), dispose: vi.fn(), text: "" },
}));
vi.mock("vscode", () => ({
  EventEmitter: class {
    private listeners = new Set<(value: unknown) => void>();
    event = (listener: (value: unknown) => void) => {
      this.listeners.add(listener);
      return { dispose: () => this.listeners.delete(listener) };
    };
    fire(value: unknown) {
      this.listeners.forEach((listener) => listener(value));
    }
    dispose() {
      this.listeners.clear();
    }
  },
  StatusBarAlignment: { Left: 1 },
  workspace: {
    get isTrusted() {
      return true;
    },
  },
  window: {
    get activeTextEditor() {
      return undefined;
    },
    state: { focused: true },
    createStatusBarItem: () => mocks.statusItem,
    onDidChangeActiveTextEditor: () => ({ dispose() {} }),
    onDidChangeWindowState: () => ({ dispose() {} }),
    registerWebviewViewProvider: () => ({ dispose() {} }),
  },
  commands: {
    executeCommand: vi.fn(async () => undefined),
    registerCommand: () => ({ dispose() {} }),
  },
}));
import { StatusBar } from "../../src/statusBar";
import { parseTestAppMessage, TestAppView } from "../../src/settings/testApp";

const project = { name: "demo" };
const launchable = {
  "app.path": "C:/Apps/Demo.exe",
  launch: "per-test",
};
const attach = { "app.process": "CalculatorApp.exe", launch: "attach" };
const build = (
  config: Record<string, unknown>,
  state?: ApplicationState,
  extra: Partial<Parameters<typeof buildTestAppModel>[0]> = {},
) => buildTestAppModel({ project, trusted: true, projectCount: 2, config, state, ...extra });
const ids = (model: ReturnType<typeof build>) =>
  model.tiles.map((tile) => tile.id);

describe("Test Target tiles", () => {
  it("offers to initialize a project when there is none", () => {
    const model = buildTestAppModel({ trusted: true });
    expect(model.kind).toBe("empty");
    expect(ids(model)).toEqual(["init"]);
  });
  it("shows no tiles in an untrusted workspace", () => {
    const model = buildTestAppModel({ project, trusted: false });
    expect(model.status.label).toBe("Workspace not trusted");
    expect(model.tiles).toEqual([]);
    expect(model.message?.tone).toBe("warn");
  });
  it("lays out project, app, mode and launch tiles when stopped", () => {
    const model = build(launchable, { running: false });
    expect(model.status).toEqual({ label: "Stopped", tone: "idle" });
    expect(ids(model)).toEqual(["project", "app", "mode", "launch"]);
    const [projectTile, app, mode, launch] = model.tiles;
    expect(app).toMatchObject({ title: "Demo", chevron: true });
    expect(app.tooltip).toContain("C:/Apps/Demo.exe");
    expect(mode).toMatchObject({
      title: "Launch for tests",
      codicon: "rocket",
      chevron: true,
    });
    expect(projectTile).toMatchObject({
      title: "demo",
      codicon: "folder-opened",
    });
    expect(launch).toMatchObject({ title: "Launch", tone: "launch" });
    expect(launch.disabled).toBeFalsy();
  });
  it("offers launch for tests first by default, and treats the removed per-session value the same", () => {
    expect(modeChoices.map((mode) => [mode.id, mode.title])).toEqual([
      ["per-test", "Launch for tests"],
      ["attach", "Attach"],
    ]);
    expect(
      build({ "app.path": "C:/Apps/Demo.exe" }, { running: false }).tiles[2],
    ).toMatchObject({ title: "Launch for tests", codicon: "rocket" });
    expect(build(attach, { running: false }).tiles[2]).toMatchObject({
      title: "Attach",
      codicon: "link",
    });
    expect(
      build({ ...launchable, launch: "per-session" }, { running: false }).tiles[2]
        .title,
    ).toBe("Launch for tests");
    expect(launchModeId(undefined)).toBe("per-test");
    expect(launchModeId("per-session")).toBe("per-test");
    expect(launchModeId("attach")).toBe("attach");
  });
  it("always shows the project tile, with the workspace as its title and the project as a subtitle", () => {
    const tile = (extra: Parameters<typeof build>[2]) =>
      build(launchable, { running: false }, extra).tiles[0];
    expect(tile({ workspaceName: "Calculator", projectCount: 1 })).toMatchObject({
      id: "project",
      title: "Calculator",
      subtitle: "demo",
    });
    expect(tile({ workspaceName: "Calculator", projectCount: 3 }).title).toBe("Calculator");
    const same = tile({ workspaceName: "demo" });
    expect(same.title).toBe("demo");
    expect(same.subtitle).toBeUndefined();
    expect(tile({ projectCount: 1 }).title).toBe("demo");
  });
  it("shows pids on the app tile and restart and close when running", () => {
    const model = build(launchable, {
      running: true,
      pids: [12, 34],
      mainWindowTitle: "Demo window",
    });
    expect(model.status).toEqual({ label: "Running", tone: "ok" });
    expect(model.tiles[1].subtitle).toBe("PIDs 12, 34");
    expect(ids(model)).toEqual(["project", "app", "mode", "restart", "close"]);
    expect(model.tiles.at(-1)).toMatchObject({ tone: "stop" });
  });
  it("locks the application tile, without its list icon, while the app is running", () => {
    const running = build(launchable, { running: true, pids: [12] }).tiles[1];
    expect(running.locked).toBe(true);
    expect(running.chevron).toBeUndefined();
    expect(running.trailing).toBeUndefined();
    expect(running.tooltip).toContain("Close it to choose a different one");
    const stopped = build(launchable, { running: false }).tiles[1];
    expect(stopped.locked).toBeUndefined();
    expect(stopped).toMatchObject({ chevron: true, trailing: "list-selection" });
  });
  it("marks the Attach tile and explains it after a test run failed in attach mode", () => {
    const failed = { running: false, attachFailure: { at: 1 } };
    const model = build(attach, failed);
    const mode = model.tiles[2];
    expect(mode).toMatchObject({
      title: "Attach",
      subtitle: "App wasn't running",
      codicon: "warning",
      tone: "stop",
      alert: true,
    });
    expect(mode.tooltip).toContain("did not start CalculatorApp.exe");
    expect(model.status).toEqual({ label: "Tests need the app running", tone: "error" });
    expect(model.message).toMatchObject({
      tone: "error",
      action: { id: "mode", label: "Change launch mode" },
    });
    expect(model.message?.text).toContain("CalculatorApp.exe wasn't running");
    expect(model.message).toMatchObject({ icon: "warning", dismiss: "dismiss" });
    expect(model.badge).toContain("CalculatorApp.exe wasn't running");
    expect(build(attach, { running: false }).badge).toBeUndefined();
    expect(parseTestAppMessage({ type: "tile", id: "dismiss" })).toEqual({ type: "tile", id: "dismiss" });
    // It stops describing the app once it runs, or when the mode is no longer attach.
    expect(build(attach, { running: true, pids: [5], attachFailure: { at: 1 } }).tiles[2].alert).toBeUndefined();
    expect(build(launchable, failed).tiles[2].alert).toBeUndefined();
    expect(build(attach, { running: false }).tiles[2].alert).toBeUndefined();
  });
  it("shows the last run as a closable notice with a report button, alongside other messages", () => {
    const model = build(launchable, { running: false }, { lastRun: { passed: 6, failed: 0, at: 1000, report: "/r/index.html" } });
    expect(model.lastRun).toEqual({ passed: 6, failed: 0, at: 1000, report: true, open: "openReport", dismiss: "dismissRun" });
    expect(build(launchable, { running: false }, { lastRun: { passed: 1, failed: 2, at: 1 } }).lastRun?.report).toBe(false);
    expect(build(launchable, { running: false }).lastRun).toBeUndefined();
    const failed = build(attach, { running: false, attachFailure: { at: 1 } }, { lastRun: { passed: 0, failed: 1, at: 1 } });
    expect(failed.message?.dismiss).toBe("dismiss");
    expect(failed.lastRun).toMatchObject({ failed: 1, dismiss: "dismissRun" });
    expect(buildTestAppModel({ trusted: true, lastRun: { passed: 1, failed: 0, at: 1 } }).lastRun).toBeUndefined();
    expect(parseTestAppMessage({ type: "tile", id: "openReport" })).toEqual({ type: "tile", id: "openReport" });
    expect(parseTestAppMessage({ type: "tile", id: "dismissRun" })).toEqual({ type: "tile", id: "dismissRun" });
  });
  it("never offers to launch or restart an attach-only setup", () => {
    const stopped = build(attach, { running: false });
    expect(stopped.status.label).toBe("Waiting for the app");
    expect(stopped.message?.text).toContain("CalculatorApp.exe");
    expect(ids(stopped).slice(3)).toEqual(["refresh"]);
    const running = build(attach, { running: true, pids: [5] });
    expect(ids(running).slice(3)).toEqual(["close"]);
    expect(running.tiles[1].subtitle).toBe("PID 5");
  });
  it("explains that Launch for tests needs an executable instead of saying it attaches", () => {
    const model = build(
      { "app.process": "CalculatorApp.exe", launch: "per-test" },
      { running: false },
    );
    expect(model.status.label).toBe("Needs an executable");
    expect(model.message?.text).toContain("Launch for tests");
    expect(model.message?.text).not.toContain("attaches");
  });
  describe("loading state shown in the clicked button", () => {
    const during = (
      action: "launch" | "restart" | "close",
      kind: "starting" | "stopping",
      stage?: "process" | "window",
      config: Record<string, unknown> = launchable,
    ) =>
      build(config, {
        running: kind === "stopping",
        transition: { action, kind, since: 1_000, stage },
      });
    const tail = (model: ReturnType<typeof during>) => model.tiles.slice(3);

    it("turns Launch into a spinning Starting tile with a simple status", () => {
      const first = during("launch", "starting");
      expect(first.status).toEqual({ label: "Starting…", tone: "busy" });
      expect(tail(first)).toEqual([
        expect.objectContaining({
          id: "launch",
          title: "Starting…",
          subtitle: "Starting process",
          codicon: "loading",
          busy: true,
          disabled: true,
        }),
      ]);
      expect(tail(during("launch", "starting", "process"))[0].subtitle).toBe(
        "Waiting for app",
      );
      expect(tail(during("launch", "starting", "window"))[0].subtitle).toBe(
        "Waiting for window",
      );
    });
    it("shows Restarting on the restart tile, closing first and then starting", () => {
      const closing = during("restart", "stopping");
      expect(closing.status.label).toBe("Restarting…");
      expect(tail(closing)).toEqual([
        expect.objectContaining({
          id: "restart",
          title: "Restarting…",
          subtitle: "Closing windows",
          busy: true,
        }),
        expect.objectContaining({
          id: "close",
          title: "Close",
          disabled: true,
        }),
      ]);
      expect(tail(during("restart", "starting", "window"))[0]).toMatchObject({
        title: "Restarting…",
        subtitle: "Waiting for window",
      });
    });
    it("shows Closing on the close tile and keeps Restart disabled beside it", () => {
      const model = during("close", "stopping");
      expect(model.status.label).toBe("Closing…");
      expect(tail(model)).toEqual([
        expect.objectContaining({
          id: "restart",
          title: "Restart",
          disabled: true,
        }),
        expect.objectContaining({
          id: "close",
          title: "Closing…",
          subtitle: "Closing windows",
          busy: true,
        }),
      ]);
      expect(
        ids(during("close", "stopping", undefined, attach)).slice(3),
      ).toEqual(["close"]);
    });
    it("has no separate progress section below the tiles", () => {
      const model = during("launch", "starting", "window");
      expect(model).not.toHaveProperty("progress");
      expect(model.message).toBeUndefined();
    });
  });
  it("shows a failed launch with the reason, a way to retry and the output", () => {
    const model = build(launchable, {
      running: false,
      failure: {
        action: "launch",
        message: "Demo.exe did not show a window within 30s",
        at: 1,
      },
    });
    expect(model.status).toEqual({ label: "Failed", tone: "error" });
    expect(model.message?.text).toContain("did not show a window within 30s");
    expect(model.message?.action).toEqual({
      id: "output",
      label: "Show output",
    });
    expect(model.tiles.at(-1)).toMatchObject({
      id: "launch",
      title: "Try again",
    });
  });
  it("does not mistake a server error for a stopped application", () => {
    const model = build(launchable, {
      running: false,
      error: "Server disconnected",
    });
    expect(model.status.label).toBe("Status unavailable");
    expect(model.message).toMatchObject({
      tone: "error",
      text: "Server disconnected",
    });
    expect(model.tiles.at(-1)).toMatchObject({ id: "refresh", title: "Retry" });
  });
  it("asks which application to test when none is configured", () => {
    const model = build({ launch: "attach" }, { running: false });
    expect(model.tiles[1]).toMatchObject({
      id: "app",
      title: "Choose app",
      chevron: true,
    });
    expect(model.tiles.at(-1)?.disabled).toBe(true);
  });
  it("reports a configuration error instead of a stale status", () => {
    const model = buildTestAppModel({
      project,
      trusted: true,
      configError: "Error: bad yaml",
    });
    expect(model.status.label).toBe("Configuration error");
    expect(model.message?.text).toContain("bad yaml");
  });
});

describe("Test Target messages and manifest", () => {
  it("offers an environment check only for a classified environment failure", () => {
    const failed = buildTestAppModel({
      project,
      trusted: true,
      config: launchable,
      state: {
        running: false,
        failure: {
          action: "launch",
          message: "UI Automation is unavailable",
          environment: true,
          at: 0,
        },
      },
    });
    expect(failed.message?.action).toEqual({
      id: "doctor",
      label: "Check Environment",
    });
    expect(failed.message?.text).toContain("UI Automation is unavailable");
    expect(parseTestAppMessage({ type: "tile", id: "doctor" })).toEqual({
      type: "tile",
      id: "doctor",
    });
  });
  it("shows what each tile opens with its trailing icon", () => {
    const [projectTile, app, mode] = build(launchable, { running: false }).tiles;
    expect(projectTile).toMatchObject({ chevron: true, trailing: "go-to-file" });
    expect(app).toMatchObject({ chevron: true, trailing: "list-selection" });
    expect(mode).toMatchObject({ chevron: true, trailing: "list-selection" });
    expect(build({}, { running: false }).tiles[1].trailing).toBe("list-selection");
  });
  it("clears the activity bar badge when the extension shuts down", () => {
    const projects = { onDidChange: () => ({ dispose() {} }), all: [] };
    const status = { onDidChangeApplication: () => ({ dispose() {} }) };
    const view = new TestAppView(projects as never, status as never, {} as never, {} as never);
    const fake = { badge: { value: 1, tooltip: "The last test run failed" } };
    (view as unknown as { view: typeof fake }).view = fake;
    view.dispose();
    expect(fake.badge).toBeUndefined();
  });
  it("accepts only known tiles", () => {
    expect(parseTestAppMessage({ type: "ready" })).toEqual({ type: "ready" });
    expect(parseTestAppMessage({ type: "tile", id: "launch" })).toEqual({
      type: "tile",
      id: "launch",
    });
    for (const invalid of [
      null,
      {},
      { type: "tile", id: "rm -rf" },
      { type: "tile" },
      { type: "action", id: "launch" },
    ])
      expect(parseTestAppMessage(invalid)).toBeUndefined();
  });
  it("is a shared sidebar webview named WinTestKit with no leftover tree menus", () => {
    const manifest = JSON.parse(readFileSync("package.json", "utf8"));
    expect(manifest.contributes.views.wintestkit[0]).toEqual({
      id: "wintestkit.sidebar",
      name: "WinTestKit",
      type: "webview",
    });
    expect(manifest.contributes.menus["view/item/context"]).toBeUndefined();
    expect(
      manifest.contributes.viewsWelcome?.some(
        (entry: { view: string }) => entry.view === "wintestkit.setup",
      ),
    ).toBeFalsy();
  });
});

describe("Application status transitions", () => {
  const key = {
    root: { fsPath: "/p", toString: () => "file:///p" },
    name: "p",
  } as Project;
  const created: vscode.Disposable[] = [];
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mocks.request.mockResolvedValue({ running: false, pids: [] });
    mocks.getServer.mockResolvedValue({ client: { request: mocks.request } });
  });
  afterEach(() => {
    created.splice(0).forEach((item) => item.dispose());
    vi.useRealTimers();
  });
  const make = () => {
    const servers = {
      get: mocks.getServer,
      state: () => "ready",
      onDidChange: () => ({ dispose() {} }),
    } as unknown as ServerManager;
    const status = new StatusBar(servers, () => key);
    created.push(status);
    return status;
  };
  it("tracks a launch from starting through its stages to done", async () => {
    const status = make();
    await vi.advanceTimersByTimeAsync(0);
    const changed = vi.fn();
    status.onDidChangeApplication(changed);
    status.beginTransition(key, "starting", 30_000);
    expect(status.applicationState(key)?.transition).toMatchObject({
      action: "launch",
      kind: "starting",
      timeoutMs: 30_000,
    });
    status.setStage(key, "window");
    expect(status.applicationState(key)?.transition?.stage).toBe("window");
    status.endTransition(key);
    expect(status.applicationState(key)?.transition).toBeUndefined();
    expect(changed).toHaveBeenCalledTimes(3);
  });
  it("remembers why an action failed until the app runs or another action starts", async () => {
    const status = make();
    await vi.advanceTimersByTimeAsync(0);
    status.beginTransition(key, "starting");
    status.endTransition(key, { action: "launch", message: "boom" });
    expect(status.applicationState(key)?.failure?.message).toBe("boom");
    await status.refresh(); // still stopped: the failure stays visible
    expect(status.applicationState(key)?.failure?.message).toBe("boom");
    mocks.request.mockResolvedValue({ running: true, pids: [1] });
    await status.refresh();
    expect(status.applicationState(key)?.failure).toBeUndefined();
    status.endTransition(key, { action: "close", message: "stuck" });
    status.beginTransition(key, "starting");
    expect(status.applicationState(key)?.failure).toBeUndefined();
  });
  it("keeps one start time while a restart goes from closing to starting", async () => {
    const status = make();
    await vi.advanceTimersByTimeAsync(0);
    status.beginTransition(key, "stopping", undefined, "restart");
    const first = status.applicationState(key)?.transition?.since;
    await vi.advanceTimersByTimeAsync(4_000);
    status.beginTransition(key, "starting", 30_000, "restart");
    expect(status.applicationState(key)?.transition).toMatchObject({
      action: "restart",
      kind: "starting",
      since: first,
    });
    status.beginTransition(key, "stopping", undefined, "close");
    expect(status.applicationState(key)?.transition?.since).toBeGreaterThan(
      first!,
    );
  });
  it("keeps the pids and window title from the status poll", async () => {
    mocks.request.mockResolvedValue({
      running: true,
      pids: [7],
      mainWindowTitle: "Demo",
    });
    const status = make();
    await vi.advanceTimersByTimeAsync(0);
    expect(status.applicationState(key)).toMatchObject({
      running: true,
      pids: [7],
      mainWindowTitle: "Demo",
    });
  });
});
