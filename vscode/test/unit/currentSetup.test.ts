import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as vscode from "vscode";
import type { Projects } from "../../src/projects";
import type { Project, ServerManager } from "../../src/server/serverManager";

const mocks = vi.hoisted(() => ({
  trusted: true,
  active: undefined as vscode.TextEditor | undefined,
  readConfig: vi.fn(),
  request: vi.fn(),
  getServer: vi.fn(),
  state: "ready",
  statusItem: { hide: vi.fn(), show: vi.fn(), dispose: vi.fn(), text: "" },
  execute: vi.fn(async () => undefined),
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
    dispose() { this.listeners.clear(); }
  },
  TreeItem: class { constructor(public label: string) {} },
  ThemeIcon: class { constructor(public id: string) {} },
  StatusBarAlignment: { Left: 1 },
  workspace: { get isTrusted() { return mocks.trusted; } },
  window: {
    get activeTextEditor() { return mocks.active; },
    state: { focused: true },
    createStatusBarItem: () => mocks.statusItem,
    onDidChangeActiveTextEditor: () => ({ dispose() {} }),
    onDidChangeWindowState: () => ({ dispose() {} }),
    registerTreeDataProvider: () => ({ dispose() {} }),
  },
  commands: {
    executeCommand: mocks.execute,
    registerCommand: () => ({ dispose() {} }),
  },
}));
vi.mock("../../src/settings/files", () => ({ readConfiguration: mocks.readConfig }));
vi.mock("../../src/settings/appIcon", () => ({ executableIcon: async () => undefined }));

import { CurrentSetup } from "../../src/settings/currentSetup";
import { StatusBar } from "../../src/statusBar";

const project = {
  root: { fsPath: "/project", toString: () => "file:///project" },
  name: "project",
} as Project;
const disposables: vscode.Disposable[] = [];
function create() {
  const projects = {
    all: [project], projectFor: () => undefined,
    onDidChange: () => ({ dispose() {} }),
  } as unknown as Projects;
  const servers = {
    get: mocks.getServer, state: () => mocks.state,
    onDidChange: () => ({ dispose() {} }),
  } as unknown as ServerManager;
  const status = new StatusBar(servers, () => project);
  const setup = new CurrentSetup(projects, status);
  disposables.push(status, setup);
  return { status, setup };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  mocks.trusted = true;
  mocks.active = undefined;
  mocks.state = "ready";
  mocks.readConfig.mockResolvedValue({ "app.path": "C:/Apps/Demo.exe", launch: "attach" });
  mocks.request.mockResolvedValue({ running: false, pids: [] });
  mocks.getServer.mockResolvedValue({ client: { request: mocks.request } });
});
afterEach(() => {
  disposables.splice(0).forEach((disposable) => disposable.dispose());
  vi.useRealTimers();
});

describe("Current Setup application controls", () => {
  it("puts stopped status and launchable context on the application row", async () => {
    const { setup } = create();
    await vi.advanceTimersByTimeAsync(0);
    const [item] = await setup.getChildren();
    expect(item.label).toBe("Demo");
    expect(item.description).toBe("project · attach · Stopped");
    expect(item.contextValue).toBe("current-setup-stopped-launchable");
    expect(item.resourceUri).toBe(project.root);
    expect(item.command?.command).toBe("wintestkit.openSettings");
    expect(mocks.request).toHaveBeenCalledExactlyOnceWith("app.status");
  });
  it("updates the row from the shared status poll without extra status requests", async () => {
    const { setup, status } = create();
    const changed = vi.fn();
    setup.onDidChangeTreeData(changed);
    await vi.advanceTimersByTimeAsync(0);
    mocks.request.mockResolvedValue({ running: true, pids: [123] });
    await status.refresh();
    const [item] = await setup.getChildren();
    expect(item.description).toContain("Running");
    expect(item.contextValue).toBe("current-setup-running-launchable");
    expect(changed).toHaveBeenCalled();
    expect(mocks.request).toHaveBeenCalledTimes(2);
  });
  it("does not offer launch or restart for process-only attach setups", async () => {
    mocks.readConfig.mockResolvedValue({ "app.process": "CalculatorApp.exe", launch: "attach" });
    const { setup } = create();
    await vi.advanceTimersByTimeAsync(0);
    const [item] = await setup.getChildren();
    expect(item.label).toBe("CalculatorApp");
    expect(item.contextValue).toBe("current-setup-stopped-attach");
    expect(item.tooltip).toContain("Start the app manually");
  });
  it("keeps close available for an attached running app", async () => {
    mocks.readConfig.mockResolvedValue({ "app.process": "CalculatorApp.exe", launch: "attach" });
    mocks.request.mockResolvedValue({ running: true });
    const { setup } = create();
    await vi.advanceTimersByTimeAsync(0);
    expect((await setup.getChildren())[0].contextValue).toBe("current-setup-running-attach");
  });
  it("does not mistake a server error for a stopped application", async () => {
    mocks.request.mockRejectedValue(new Error("Server disconnected"));
    const { setup } = create();
    await vi.advanceTimersByTimeAsync(0);
    const [item] = await setup.getChildren();
    expect(item.contextValue).toBe("current-setup");
    expect(item.description).toContain("Status unavailable");
    expect(item.tooltip).toContain("Server disconnected");
  });
  it("does not connect to the server in an untrusted workspace", async () => {
    mocks.trusted = false;
    const { setup } = create();
    const [item] = await setup.getChildren();
    expect(item.description).toBe("Workspace not trusted");
    expect(item.contextValue).toBe("current-setup");
    expect(mocks.getServer).not.toHaveBeenCalled();
    expect(mocks.readConfig).not.toHaveBeenCalled();
  });
  it("keeps the current project visible when an unrelated file is active", async () => {
    mocks.active = { document: { uri: { fsPath: "/unrelated/file.py" } } } as vscode.TextEditor;
    const { setup } = create();
    await vi.advanceTimersByTimeAsync(0);
    expect((await setup.getChildren())[0].resourceUri).toBe(project.root);
  });
  it("queues an action refresh arriving while a status request is pending", async () => {
    let finish!: (value: { running: boolean }) => void;
    mocks.request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { status } = create();
    await vi.advanceTimersByTimeAsync(0);
    await status.refresh();
    finish({ running: false });
    mocks.request.mockResolvedValue({ running: true });
    await vi.advanceTimersByTimeAsync(0);
    expect(status.applicationState(project)?.running).toBe(true);
    expect(mocks.request).toHaveBeenCalledTimes(2);
  });
  it("places lifecycle actions only on the relevant setup row contexts", () => {
    const manifest = JSON.parse(readFileSync("package.json", "utf8"));
    const menus = manifest.contributes.menus["view/item/context"] as { command: string; when: string; group: string }[];
    const launch = menus.find((entry) => entry.command === "wintestkit.launchApp")!;
    const restart = menus.find((entry) => entry.command === "wintestkit.restartApp")!;
    const close = menus.find((entry) => entry.command === "wintestkit.closeApp")!;
    expect(launch.when).toContain("view == wintestkit.setup");
    expect(launch.when).toContain("current-setup-stopped-launchable");
    expect(restart.when).toContain("current-setup-running-launchable");
    expect(close.when).toContain("/^current-setup-running-/");
    expect(launch.group).toContain("inline");
    expect(readFileSync("media/spy/spy.html", "utf8")).not.toMatch(/id="(?:launch|state)"/);
  });
});
