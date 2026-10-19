import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as vscode from "vscode";
import type { ServerManager, Project } from "../../src/server/serverManager";
import {
  buildTestAppModel,
  interpreterTile,
  launchModeId,
  modeChoices,
} from "../../src/settings/testAppModel";
import type { ApplicationState } from "../../src/statusBar";
import * as configurationFiles from "../../src/settings/files";

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
    showQuickPick: vi.fn(),
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
vi.mock("../../src/python", () => ({
  describeInterpreter: vi.fn(async () => undefined),
  onDidChangeInterpreter: vi.fn(async () => ({ dispose() {} })),
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
) => buildTestAppModel({ project, trusted: true, config, state, ...extra });
const ids = (model: ReturnType<typeof build>) =>
  model.tiles.map((tile) => tile.id);

describe("Test Target tiles", () => {
  it.each(["interpreter", "package", "machine", "project", "app", "mode", "launch"] as const)(
    "shows only interpreter and initialization before a project exists on the %s step", (step) => {
      const strip = {
        state: "ok" as const, text: "wintestkit 0.1.1",
        source: { value: "local" as const, wheel: "C:/build/wintestkit.whl" },
        action: { id: "installPackage" as const, label: "Install selected wheel" },
      };
      const model = buildTestAppModel({
        trusted: true, interpreter: { name: "Python", path: "C:/python.exe", strip },
        tour: {
          step, phase: "setup", kind: "todo", title: "Setup", text: "Instructions",
          lit: [], panel: false, buttons: [], canBack: true, canNext: false,
        },
      });
      expect(model.kind).toBe("app");
      expect(ids(model)).toEqual(["interpreter", "initProject"]);
      expect(model.tiles[0].strip).toMatchObject({ state: "ok", text: "wintestkit 0.1.1" });
      expect(model.tiles[0].strip?.source).toEqual(step === "package" ? strip.source : undefined);
      expect(model.tiles[0].strip?.action).toEqual(step === "package" ? strip.action : undefined);
      expect(model.tiles[0].disabled).toBeUndefined();
      expect(model.tiles[1].disabled).toBeUndefined();
    },
  );
  it.each(["interpreter", "package", "machine", "project", "app", "mode", "launch", "complete", "spy", "test"] as const)(
    "keeps normal tiles and status while showing only the %s step's setup extras", (step) => {
      const strip = {
        state: "ok" as const, text: "wintestkit 0.1.1", tooltip: "Installed package",
        source: { value: "local" as const, wheel: "C:/build/wintestkit.whl" },
        action: { id: "installPackage" as const, label: "Install selected wheel" },
      };
      const input = {
        interpreter: { name: "Python", version: "3.14.7", path: "C:/python.exe", strip },
        tour: {
          step, phase: "setup" as const, kind: "todo" as const, title: "Setup", text: "Instructions",
          lit: [], panel: false, buttons: [], canBack: true, canNext: false,
        },
      };
      const model = build(launchable, { running: false }, input);
      expect(ids(model)).toEqual(["interpreter", "app", "mode", "launch"]);
      expect(model.tiles[0]).toMatchObject({ title: "Python", subtitle: "Python 3.14.7" });
      expect(model.tiles[0].strip).toMatchObject({ state: "ok", text: "wintestkit 0.1.1", tooltip: "Installed package" });
      expect(model.tiles[0].strip?.source).toEqual(step === "package" ? strip.source : undefined);
      expect(model.tiles[0].strip?.action).toEqual(step === "package" ? strip.action : undefined);
      expect(build(launchable, { running: false }, { ...input, tour: undefined }).tiles[0].strip).toEqual(strip);
    },
  );
  it("keeps initialization available before the project exists and removes it afterward", () => {
    const tour = {
      step: "project" as const, phase: "setup" as const, kind: "todo" as const,
      title: "Create project", text: "Use Test Target", lit: ["project" as const],
      panel: false, buttons: [], canBack: true, canNext: false,
    };
    const ready = buildTestAppModel({ trusted: true, tour });
    expect(ready.tiles.map((tile) => tile.id)).toEqual(["interpreter", "initProject"]);
    expect(ready.tour?.buttons).toEqual([]);
    const busy = buildTestAppModel({ trusted: true, tour, initializing: true });
    expect(busy.tiles.at(-1)).toMatchObject({ id: "initProject", disabled: true, busy: true, codicon: "loading" });
    const machine = buildTestAppModel({ trusted: true, tour: { ...tour, step: "machine", lit: ["machine"] } });
    expect(machine.tiles.map((tile) => tile.id)).toEqual(["interpreter", "initProject"]);
    const initialized = buildTestAppModel({ trusted: true, project, tour });
    expect(ids(initialized)).toEqual(["interpreter", "app", "mode", "launch"]);
    expect(parseTestAppMessage({ type: "tile", id: "initProject" })).toEqual({ type: "tile", id: "initProject" });
  });
  it("asks to choose an application instead of showing the starter placeholder", () => {
    const model = build({ "app.path": "C:/path/to/YourApp.exe" });
    expect(model.tiles.find((tile) => tile.id === "app")?.title).not.toBe("YourApp");
    expect(model.tiles.find((tile) => tile.id === "launch")?.disabled).toBe(true);
  });
  it("rejects local source messages in normal builds, including forged messages", () => {
    vi.stubGlobal("__WTK_DEV__", false);
    expect(parseTestAppMessage({ type: "packageSource", source: "local" })).toBeUndefined();
    expect(parseTestAppMessage({ type: "packageSource", source: "remote" })).toBeUndefined();
    vi.unstubAllGlobals();
  });
  it("accepts only valid source values in development builds", () => {
    vi.stubGlobal("__WTK_DEV__", true);
    expect(parseTestAppMessage({ type: "packageSource", source: "local" })).toEqual({ type: "packageSource", source: "local" });
    expect(parseTestAppMessage({ type: "packageSource", source: "remote" })).toEqual({ type: "packageSource", source: "remote" });
    expect(parseTestAppMessage({ type: "packageSource", source: "file:///evil" })).toBeUndefined();
    vi.unstubAllGlobals();
  });
  it("does not show project initialization before the guide reaches that step", () => {
    const model = buildTestAppModel({ trusted: true });
    expect(model.kind).toBe("empty");
    expect(model.tiles).toEqual([]);
    expect(model.message?.text).toContain("No WinTestKit project");
    expect(parseTestAppMessage({ type: "tile", id: "init" })).toBeUndefined();
  });
  it("shows no tiles in an untrusted workspace", () => {
    const model = buildTestAppModel({ project, trusted: false });
    expect(model.status.label).toBe("Workspace not trusted");
    expect(model.tiles).toEqual([]);
    expect(model.message?.tone).toBe("warn");
  });
  it("lays out interpreter, app, mode and launch tiles when stopped", () => {
    const model = build(launchable, { running: false });
    expect(model.status).toEqual({ label: "Stopped", tone: "idle" });
    expect(ids(model)).toEqual(["interpreter", "app", "mode", "launch"]);
    const [interpreter, app, mode, launch] = model.tiles;
    expect(app).toMatchObject({ title: "Demo", chevron: true });
    expect(app.tooltip).toContain("C:/Apps/Demo.exe");
    expect(mode).toMatchObject({
      title: "Launch for tests",
      codicon: "rocket",
      chevron: true,
    });
    expect(interpreter).toMatchObject({ title: "Select interpreter", codicon: "server-environment", tone: "warn" });
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
  it("shows the Python interpreter as the first tile, and what is wrong with it", () => {
    const tile = (interpreter?: Parameters<typeof interpreterTile>[0]) =>
      build(launchable, { running: false }, { interpreter }).tiles[0];
    expect(tile({ name: ".venv", version: "3.13.5", path: "C:/work/.venv/Scripts/python.exe" })).toMatchObject({
      id: "interpreter",
      title: ".venv",
      subtitle: "Python 3.13.5",
      codicon: "server-environment",
      tone: "project",
      chevron: true,
      trailing: "list-selection",
    });
    expect(tile({ name: ".venv", path: "C:/p.exe" }).subtitle).toBeUndefined();
    expect(tile({ name: ".venv", path: "C:/p.exe", overridden: true }).tooltip).toContain("wintestkit.pythonPath");
    // Whether the package is installed is the strip under the tile; the tile itself only changes interpreter.
    const strip = { state: "missing" as const, text: "wintestkit not installed", action: { id: "installPackage" as const, label: "Install" } };
    const bare = tile({ name: "base", version: "3.12.1", path: "C:/py/python.exe", strip });
    expect(bare).toMatchObject({ id: "interpreter", subtitle: "Python 3.12.1", strip });
    expect(bare.tooltip).toContain("C:/py/python.exe");
    expect(bare.alert).toBeUndefined();
    expect(parseTestAppMessage({ type: "tile", id: "installPackage" })).toEqual({ type: "tile", id: "installPackage" });
    expect(tile(undefined)).toMatchObject({ title: "Select interpreter", tone: "warn" });
    // The Python logo is the tile's picture, in every state.
    const logo = "data:image/svg+xml;base64,AAAA";
    expect(interpreterTile({ name: ".venv", path: "C:/p.exe" }, logo).icon).toBe(logo);
    expect(interpreterTile(undefined, logo).icon).toBe(logo);
    expect(build(launchable, { running: false }, { pythonIcon: logo }).tiles[0].icon).toBe(logo);
    expect(buildTestAppModel({ blocker: { title: "x", detail: "y" }, pythonIcon: logo, trusted: true }).tiles[0].icon).toBe(logo);
    expect(parseTestAppMessage({ type: "tile", id: "interpreter" })).toEqual({ type: "tile", id: "interpreter" });
    expect(parseTestAppMessage({ type: "tile", id: "project" })).toBeUndefined();
  });
  it("shows pids on the app tile and restart and close when running", () => {
    const model = build(launchable, {
      running: true,
      pids: [12, 34],
      mainWindowTitle: "Demo window",
    });
    expect(model.status).toEqual({ label: "Running", tone: "ok" });
    expect(model.tiles[1].subtitle).toBe("PIDs 12, 34");
    expect(ids(model)).toEqual(["interpreter", "app", "mode", "restart", "close"]);
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
  it("shows the guided tour's callout with the tiles it points at", () => {
    const tour = {
      step: "app" as const,
      phase: "setup" as const,
      kind: "todo" as const,
      progress: { index: 5, total: 7 },
      title: "Choose the application",
      text: "Pick it.",
      lit: ["app" as const],
      panel: false,
      buttons: [{ id: "pickApp" as const, label: "Choose application", primary: true }],
      canBack: true,
      canNext: false,
    };
    const model = build(launchable, { running: false }, { tour });
    expect(model.tour).toBe(tour);
    expect(ids(model)).toEqual(["interpreter", "app", "mode", "launch"]);
    expect(model.resume).toBeUndefined();
    const early = buildTestAppModel({ trusted: true, tour });
    expect(early.tour).toBe(tour);
    expect(early.tiles.map((tile) => tile.id)).toEqual(["interpreter", "initProject"]);
    expect(parseTestAppMessage({ type: "tour", action: "pickApp" })).toEqual({ type: "tour", action: "pickApp" });
    expect(parseTestAppMessage({ type: "tour", action: "rm -rf" })).toBeUndefined();
  });
  it("offers to resume the guided setup when it was closed with something left to do", () => {
    const model = build(launchable, { running: false }, { resumable: true });
    expect(model.resume).toMatchObject({ action: { id: "resumeSetup", label: "Resume setup" } });
    expect(build(launchable, { running: false }).resume).toBeUndefined();
    expect(parseTestAppMessage({ type: "tile", id: "resumeSetup" })).toEqual({ type: "tile", id: "resumeSetup" });
  });
  it("is a single Enable button, and nothing else, until the workspace is enabled", () => {
    const model = buildTestAppModel({
      enabled: false,
      trusted: true,
      project,
      lastRun: { passed: 1, failed: 0, at: 1 },
    });
    expect(model.kind).toBe("disabled");
    expect(model.tiles.map((tile) => tile.id)).toEqual(["enable"]);
    expect(model.tiles[0].title).toBe("Enable for this workspace");
    expect(model.message).toBeUndefined();
    expect(model.lastRun).toBeUndefined();
    expect(parseTestAppMessage({ type: "tile", id: "enable" })).toEqual({ type: "tile", id: "enable" });
    expect(build(launchable, { running: false }, { enabled: true }).kind).toBe("app");
  });
  it("is the interpreter and a Resume button while setup is not done and the guide is closed", () => {
    const blocker = { title: "The wintestkit package", detail: "It is not installed in C:/py/python.exe" };
    const model = buildTestAppModel({ blocker, trusted: true, project, config: launchable, lastRun: { passed: 1, failed: 0, at: 1 } });
    expect(model.kind).toBe("blocked");
    expect(model.tiles.map((tile) => tile.id)).toEqual(["interpreter", "resumeSetup"]);
    expect(model.tiles[1]).toMatchObject({
      title: "Resume setup",
      subtitle: "The wintestkit package needs attention",
      tooltip: blocker.detail,
    });
    expect(model.message).toBeUndefined();
    expect(model.lastRun).toBeUndefined();
    // With the tour showing there is no need for the button: the tour is the way forward.
    const touring = buildTestAppModel({
      blocker,
      trusted: true,
      project,
      config: launchable,
      tour: { step: "package", phase: "setup", kind: "todo", title: "x", text: "y", lit: [], panel: false, buttons: [], canBack: false, canNext: false },
    });
    expect(touring.kind).toBe("app");
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
    const [interpreter, app, mode] = build(launchable, { running: false }).tiles;
    expect(interpreter).toMatchObject({ chevron: true, trailing: "list-selection" });
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
  it("is part of the one sidebar webview, with no leftover tree menus", () => {
    const manifest = JSON.parse(readFileSync("package.json", "utf8"));
    expect(manifest.contributes.views.wintestkit).toEqual([
      { id: "wintestkit.sidebar", name: "WinTestKit", type: "webview" },
    ]);
    expect(manifest.contributes.menus["view/item/context"]).toBeUndefined();
    expect(
      manifest.contributes.viewsWelcome?.some(
        (entry: { view: string }) => entry.view === "wintestkit.sidebar",
      ),
    ).toBeFalsy();
  });
  it("hands the messages the sidebar page sends to the part they are for", () => {
    const projects = { onDidChange: () => ({ dispose() {} }), all: [] };
    const status = { onDidChangeApplication: () => ({ dispose() {} }) };
    const view = new TestAppView(projects as never, status as never, {} as never, {} as never);
    const refresh = vi.spyOn(view, "refresh").mockImplementation(() => {});
    view.handleMessage({ type: "ready" });
    expect(refresh).toHaveBeenCalledOnce();
    // What Pages & Flows sends is not Test Target's.
    view.handleMessage({ type: "select", section: "flows" });
    view.handleMessage({ type: "unusedScan" });
    view.handleMessage(null);
    expect(refresh).toHaveBeenCalledOnce();
    view.dispose();
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
it.each([true, false])("confirms launch mode only after a real picker choice (selected: %s)", async (selected) => {
  const read = vi.spyOn(configurationFiles, "readConfiguration").mockResolvedValue({ launch: "per-test" });
  vi.mocked(vscode.window.showQuickPick).mockResolvedValueOnce(selected ? { id: "per-test" } as never : undefined);
  const confirmMode = vi.fn(async () => {});
  const view = new TestAppView(
    { all: [{ root: {}, name: "demo" }], onDidChange: () => ({ dispose() {} }) } as never,
    { onDidChangeApplication: () => ({ dispose() {} }) } as never,
    {} as never, {} as never, undefined,
    { confirmMode, onDidChange: () => ({ dispose() {} }) } as never,
  );
  view.handleMessage({ type: "tile", id: "mode" });
  await vi.waitFor(() => expect(read).toHaveBeenCalled());
  await Promise.resolve();
  expect(confirmMode).toHaveBeenCalledTimes(selected ? 1 : 0);
  view.dispose();
  read.mockRestore();
});

it("finishes the introduction before Testing replaces the sidebar", async () => {
  const order: string[] = [];
  const finish = vi.fn(async () => {
    order.push("finish");
  });
  vi.mocked(vscode.commands.executeCommand).mockImplementationOnce(async (command) => {
    order.push(command);
    return undefined;
  });
  const view = new TestAppView(
    { all: [], onDidChange: () => ({ dispose() {} }) } as never,
    { onDidChangeApplication: () => ({ dispose() {} }) } as never,
    {} as never,
    {} as never,
    undefined,
    { finish, onDidChange: () => ({ dispose() {} }) } as never,
  );
  view.handleMessage({ type: "tour", action: "openTesting" });
  await vi.waitFor(() => expect(order).toEqual(["finish", "wintestkit.openTesting"]));
  view.dispose();
});
