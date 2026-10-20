import { readFile } from "node:fs/promises";
import * as path from "node:path";
import * as vscode from "vscode";
import type { Projects } from "../projects";
import type { Enablement } from "../enablement";
import type { Reports } from "../report";
import { describeInterpreter, onDidChangeInterpreter } from "../python";
import { chooseWorkspaceFolder, initializeProject } from "../init";
import { packageCompatibility } from "../compatibility";
import type { SetupMonitor } from "../setup/monitor";
import { TOUR_ACTIONS, type TourAction } from "../setup/tour";
import type { AppProcessesResult } from "../protocol/generated";
import type { Project, ServerManager } from "../server/serverManager";
import type { StatusBar } from "../statusBar";
import { executableIcon } from "./appIcon";
import { readConfiguration, writeLocalSettings } from "./files";
import {
  buildTestAppModel,
  type InterpreterView,
  launchModeId,
  modeChoices,
  type TestAppModel,
  type TileId,
  type TileStrip,
} from "./testAppModel";

declare const __WTK_DEV__: boolean;

type WebviewMessage =
  | { type: "ready" }
  | { type: "tile"; id: TileId }
  | { type: "tour"; action: TourAction }
  | { type: "packageSource"; source: "remote" | "local" };

const TILES = new Set<string>([
  "app",
  "mode",
  "interpreter",
  "launch",
  "restart",
  "close",
  "refresh",
  "output",
  "doctor",
  "dismiss",
  "openReport",
  "dismissRun",
  "enable",
  "resumeSetup",
  "installPackage",
  "updateExtension",
  "initProject",
  "recheck",
]);
const TOUR = new Set<string>(TOUR_ACTIONS);

/** Non-breaking spaces, which a quick pick keeps, so its icons are not jammed against the label. */
const ICON_GAP = "  ";

export function parseTestAppMessage(
  value: unknown,
): WebviewMessage | undefined {
  if (!value || typeof value !== "object") return;
  const message = value as Record<string, unknown>;
  if (message.type === "ready") return { type: "ready" };
  if (typeof __WTK_DEV__ !== "undefined" && __WTK_DEV__ && message.type === "packageSource" &&
    (message.source === "local" || message.source === "remote"))
    return { type: "packageSource", source: message.source };
  if (message.type === "tile" && TILES.has(String(message.id)))
    return { type: "tile", id: message.id as TileId };
  if (message.type === "tour" && TOUR.has(String(message.action)))
    return { type: "tour", action: message.action as TourAction };
}

/** The Test Target part of the sidebar view (see `SidebarView`): the application under test, how it starts, and its project. */
export class TestAppView implements vscode.Disposable {
  private view?: vscode.WebviewView;
  private disposed = false;
  private readonly subscriptions: vscode.Disposable[];
  private viewSubscriptions: vscode.Disposable[] = [];
  private readonly icons = new Map<string, string | undefined>();
  private readonly pendingIcons = new Set<string>();
  private rendering = false;
  private renderAgain = false;
  private initializing = false;
  get initializingProject(): boolean {
    return this.initializing;
  }
  private interpreterWatch?: vscode.Disposable;
  constructor(
    private readonly projects: Projects,
    private readonly status: StatusBar,
    private readonly servers: ServerManager,
    private readonly extensionUri: vscode.Uri,
    private readonly reports?: Reports,
    private readonly setup?: SetupMonitor,
    private readonly enablement?: Enablement,
    private readonly log?: vscode.LogOutputChannel,
  ) {
    this.subscriptions = [
      ...(enablement ? [enablement.onDidChange(() => this.refresh())] : []),
      ...(setup ? [setup.onDidChange(() => this.refresh())] : []),
      { dispose: () => this.interpreterWatch?.dispose() },
      ...(reports ? [reports.onDidChange(() => this.refresh())] : []),
      projects.onDidChange(() => this.refresh()),
      status.onDidChangeApplication(() => this.refresh()),
      vscode.window.onDidChangeActiveTextEditor(() => this.refresh()),
    ];
    // The tile shows the interpreter, so it follows a change made from anywhere (the status bar too).
    void onDidChangeInterpreter(() => this.refresh())
      .then((watch) => {
        if (this.disposed) watch.dispose();
        else this.interpreterWatch = watch;
      })
      .catch(() => undefined);
  }
  /** Starts publishing to the sidebar's webview, whose page the sidebar view builds. */
  attach(view: vscode.WebviewView): void {
    if (this.disposed) return;
    this.view = view;
    // A badge from before a restart or reload describes a run this session knows nothing about.
    view.badge = undefined;
    this.viewSubscriptions.forEach((subscription) => subscription.dispose());
    this.viewSubscriptions = [
      view.onDidChangeVisibility(() => {
        if (view.visible) this.refresh();
      }),
      view.onDidDispose(() => {
        if (this.view === view) this.view = undefined;
      }),
    ];
  }
  /** Takes a message from the sidebar page; the ones that are not this part's are ignored. */
  handleMessage(value: unknown): void {
    const message = parseTestAppMessage(value);
    if (message?.type === "ready") this.refresh();
    else if (message?.type === "tile") void this.run(message.id);
    else if (message?.type === "tour") void this.runTour(message.action);
    else if (message?.type === "packageSource") void this.selectPackageSource(message.source);
  }
  refresh(): void {
    if (this.disposed || !this.view) return;
    if (this.rendering) {
      this.renderAgain = true;
      return;
    }
    this.rendering = true;
    void this.render().finally(() => {
      this.rendering = false;
      if (this.renderAgain) {
        this.renderAgain = false;
        this.refresh();
      }
    });
  }
  async chooseApp(): Promise<void> {
    await this.run("app");
  }
  private currentProject() {
    const active = vscode.window.activeTextEditor?.document.uri;
    return (active && this.projects.projectFor(active)) || this.projects.all[0];
  }
  async model(): Promise<TestAppModel> {
    if (this.enablement && !this.enablement.enabled) return buildTestAppModel({ enabled: false, trusted: true });
    const project = this.currentProject();
    const interpreter = await this.interpreter();
    const pythonIcon = await this.pythonIcon();
    const currentTour = this.setup?.tour;
    const tour = currentTour;
    const guide = {
      initializing: this.initializing,
      interpreter,
      pythonIcon,
      tour,
      resumable: this.setup?.resumable,
      blocker: this.setup?.blocker,
    };
    // While the guide is closed and setup is incomplete only the interpreter and a way back remain.
    if (guide.blocker && !tour) return buildTestAppModel({ ...guide, trusted: true });
    const trusted = vscode.workspace.isTrusted;
    if (!project || !trusted) return buildTestAppModel({ ...guide, project, trusted });
    try {
      const config = await readConfiguration(project.root);
      const file =
        typeof config["app.path"] === "string" ? config["app.path"] : undefined;
      const processName =
        typeof config["app.process"] === "string"
          ? config["app.process"]
          : undefined;
      const source = file?.trim()
        ? path.isAbsolute(file)
          ? file
          : path.resolve(project.root.fsPath, file)
        : processName;
      return buildTestAppModel({
        ...guide,
        project,
        trusted,
        config,
        state: this.status.applicationState(project),
        icon: source ? this.icon(source) : undefined,
        lastRun: this.shownLastRun(project),
      });
    } catch (error) {
      return buildTestAppModel({ ...guide, project, trusted, configError: String(error) });
    }
  }
  /** The Python logo from the extension's media, as a data URI the webview may show. */
  private pythonIconUri?: Promise<string | undefined>;
  private pythonIcon(): Promise<string | undefined> {
    this.pythonIconUri ??= readFile(
      vscode.Uri.joinPath(this.extensionUri, "media", "setup", "python.svg").fsPath,
    ).then(
      (svg) => "data:image/svg+xml;base64," + svg.toString("base64"),
      () => undefined,
    );
    return this.pythonIconUri;
  }
  /** The folder whose interpreter is shown: the project's, or the workspace's before there is one. */
  private interpreterFolder(): vscode.Uri | undefined {
    return this.currentProject()?.root ?? vscode.workspace.workspaceFolders?.[0]?.uri;
  }
  private async interpreter(): Promise<InterpreterView | undefined> {
    const folder = this.interpreterFolder();
    if (!folder) return undefined;
    try {
      const info = await describeInterpreter(folder);
      return info && { ...info, strip: this.packageStrip() };
    } catch {
      return undefined;
    }
  }
  /** Whether wintestkit is installed in the interpreter, and the button that fixes it. */
  private packageStrip(): TileStrip | undefined {
    const strip = this.packageStatus();
    const folder = this.interpreterFolder();
    if (typeof __WTK_DEV__ !== "undefined" && __WTK_DEV__ && strip && folder && this.setup?.installer.development) {
      const selection = this.setup.installer.development.view(folder);
      strip.source = { value: selection.source, wheel: selection.wheel };
      if (strip.state === "ok")
        strip.action = { id: "installPackage", label: selection.source === "local" ? "Install selected wheel" : "Install remote package" };
    }
    return strip;
  }
  private async selectPackageSource(source: "remote" | "local"): Promise<void> {
    if (!(typeof __WTK_DEV__ !== "undefined" && __WTK_DEV__)) return;
    const folder = this.interpreterFolder();
    const installer = this.setup?.installer;
    if (!folder || !installer?.development || installer.busy || !vscode.workspace.isTrusted) return;
    try {
      await installer.selectSource(folder, source);
    } catch (error) {
      void vscode.window.showErrorMessage(String(error));
    } finally {
      this.refresh();
    }
  }
  private packageStatus(): TileStrip | undefined {
    const health = this.setup?.health;
    const installer = this.setup?.installer;
    if (!health || health.interpreter.state !== "ok") return undefined;
    if (installer?.busy) return { state: "busy", text: "Installing wintestkit…" };
    if (installer?.error)
      return {
        state: "error",
        text: "Install failed",
        tooltip: installer.error,
        action: { id: "installPackage", label: "Try again" },
      };
    if (health.package.state === "pending")
      return {
        state: "missing",
        text: "wintestkit not installed",
        action: { id: "installPackage", label: "Install" },
      };
    const version = health.package.version;
    const issue = packageCompatibility(version);
    return issue
      ? {
          state: "error",
          text: "wintestkit " + (version ?? "version unknown"),
          tooltip: issue.message,
          action: issue.updateExtension
            ? { id: "updateExtension", label: "Update extension" }
            : { id: "installPackage", label: "Install compatible package" },
        }
      : { state: "ok", text: "wintestkit " + (version ?? "installed") };
  }
  private shownLastRun(project: Project) {
    const summary = this.reports?.lastRun(project);
    return summary && !summary.dismissed ? summary : undefined;
  }
  private icon(source: string): string | undefined {
    if (!this.icons.has(source) && !this.pendingIcons.has(source)) {
      this.pendingIcons.add(source);
      void executableIcon(source).then((icon) => {
        this.pendingIcons.delete(source);
        this.icons.set(source, icon?.toString(true));
        this.refresh();
      });
    }
    return this.icons.get(source);
  }
  private async render(): Promise<void> {
    const model = await this.model();
    if (this.disposed || !this.view) return;
    // The badge on the activity bar icon is how a failed attach run is noticed from elsewhere.
    this.view.badge = model.badge ? { value: 1, tooltip: model.badge } : undefined;
    void this.view.webview.postMessage({ type: "model", model });
  }
  private async run(id: TileId): Promise<void> {
    const project = this.currentProject();
    const target = project ? { resourceUri: project.root } : undefined;
    try {
      switch (id) {
        case "app":
          return await this.pickApp();
        case "mode":
          return await this.pickMode();
        case "initProject":
          return await this.runTour("initProject");
        case "recheck":
          return await this.setup?.check();
        case "interpreter":
          return await this.pickInterpreter();
        case "launch":
          return void (await vscode.commands.executeCommand(
            "wintestkit.launchApp",
            target,
          ));
        case "restart":
          return void (await vscode.commands.executeCommand(
            "wintestkit.restartApp",
            target,
          ));
        case "close":
          return void (await vscode.commands.executeCommand(
            "wintestkit.closeApp",
            target,
          ));
        case "dismiss":
          return project ? this.status.clearAttachFailure(project) : undefined;
        case "openReport":
          return await this.reports?.open(project);
        case "enable":
          return void (await vscode.commands.executeCommand("wintestkit.enable"));
        case "resumeSetup":
          return this.setup?.resume();
        case "installPackage":
          return await this.installPackage();
        case "updateExtension":
          return void (await vscode.commands.executeCommand("wintestkit.updateExtension"));
        case "dismissRun":
          return this.reports?.dismissLastRun(project);
        case "refresh":
          return void (await this.status.refresh());
        case "output":
          return void (await vscode.commands.executeCommand(
            "wintestkit.showOutput",
          ));
        case "doctor":
          return void (await vscode.commands.executeCommand(
            "wintestkit.runDoctor",
            target,
          ));
      }
    } catch (error) {
      await vscode.window.showErrorMessage(String(error));
    }
  }
  /** Installs or updates wintestkit in the selected interpreter, then looks again. */
  async installPackage(target?: vscode.Uri): Promise<void> {
    const setup = this.setup;
    const folder = target ?? this.interpreterFolder();
    if (!setup || !folder) return;
    const python = await describeInterpreter(folder);
    if (!python) return;
    const done = await setup.installer.install(folder, python.path);
    if (done) {
      try {
        await this.servers.restartUsingInterpreter(python.path);
      } finally {
        await setup.check();
      }
    }
    else if (setup.installer.error)
      void vscode.window
        .showErrorMessage("Installing wintestkit failed: " + setup.installer.error, "Show Output")
        .then((choice) => choice && vscode.commands.executeCommand("wintestkit.showOutput"));
  }
  /** What the buttons in the tour's callout do. */
  private async runTour(action: TourAction): Promise<void> {
    const setup = this.setup;
    if (!setup) return;
    const project = this.currentProject();
    try {
      switch (action) {
        case "back":
          return setup.back();
        case "next":
          return setup.next();
        case "close":
          return setup.close();
        case "disable":
          return void (await vscode.commands.executeCommand("wintestkit.disable"));
        case "skip":
          return await setup.skip();
        case "pickInterpreter":
          return await this.pickInterpreter();
        case "installPackage":
          return await this.installPackage();
        case "recheck":
          return await setup.check();
        case "showDetails":
          return void (await vscode.commands.executeCommand("wintestkit.runDoctor"));
        case "initProject": {
          if (this.initializing) return;
          this.initializing = true;
          this.refresh();
          try {
            const folder = await chooseWorkspaceFolder();
            if (!folder || !this.log) return;
            await initializeProject(folder, this.projects, this.log);
            return await setup.check();
          } finally {
            this.initializing = false;
            this.refresh();
          }
        }
        case "pickApp":
          return await this.pickApp();
        case "confirmMode":
          return await setup.confirmMode();
        case "changeMode":
          await this.pickMode();
          return await setup.confirmMode();
        case "launch":
          return void (await vscode.commands.executeCommand(
            "wintestkit.launchApp",
            project ? { resourceUri: project.root } : undefined,
          ));
        case "continueExtras":
          return setup.continueExtras();
        case "finish":
          return await setup.finish();
        case "openTesting":
          await setup.finish();
          return void (await vscode.commands.executeCommand("wintestkit.openTesting"));
        case "openSpy":
          return void (await vscode.commands.executeCommand("wintestkit.spy.focus"));
      }
    } catch (error) {
      this.log?.error(String(error));
      await vscode.window.showErrorMessage(String(error));
    }
  }
  private async save(changes: Record<string, unknown>): Promise<void> {
    const project = this.currentProject();
    if (!project) return;
    await writeLocalSettings(project.root, changes);
    this.refresh();
  }
  private async pickMode(): Promise<void> {
    const project = this.currentProject();
    if (!project) return;
    const config = await readConfiguration(project.root);
    const current = launchModeId(config.launch);
    const choice = await vscode.window.showQuickPick(
      modeChoices.map((mode) => ({
        label: "$(" + mode.codicon + ")" + ICON_GAP + mode.title,
        description: mode.id === current ? "current" : undefined,
        detail: mode.description,
        id: mode.id,
      })),
      { placeHolder: "How should WinTestKit get the application?" },
    );
    if (choice && choice.id !== current) await this.save({ launch: choice.id });
    if (choice) await this.setup?.confirmMode();
  }
  /** Lets the user choose another interpreter; the monitor then checks it and the guide follows. */
  async pickInterpreter(target?: vscode.Uri): Promise<void> {
    const folder = target ?? this.interpreterFolder();
    if (!folder) return;
    const configuration = vscode.workspace.getConfiguration("wintestkit", folder);
    const configured = configuration.get<string>("pythonPath")?.trim();
    if (configured) {
      const choice = await vscode.window.showWarningMessage(
        `The wintestkit.pythonPath setting uses ${configured} and overrides the interpreter selected in VS Code.`,
        "Stop overriding",
        "Open setting",
      );
      if (choice === "Open setting")
        return void (await vscode.commands.executeCommand(
          "workbench.action.openSettings",
          "wintestkit.pythonPath",
        ));
      if (choice !== "Stop overriding") return;
      const found = configuration.inspect<string>("pythonPath");
      await configuration.update(
        "pythonPath",
        undefined,
        found?.workspaceFolderValue !== undefined
          ? vscode.ConfigurationTarget.WorkspaceFolder
          : found?.workspaceValue !== undefined
            ? vscode.ConfigurationTarget.Workspace
            : vscode.ConfigurationTarget.Global,
      );
    }
    await vscode.commands.executeCommand("python.setInterpreter", folder);
  }
  private async pickApp(): Promise<void> {
    const project = this.currentProject();
    if (!project) return;
    const choice = await vscode.window.showQuickPick(
      [
        {
          label: "$(folder-opened)" + ICON_GAP + "Browse for an executable…",
          detail: "Launch it for tests (stored only on this machine)",
          action: "browse",
        },
        {
          label: "$(pulse)" + ICON_GAP + "Attach to a running app…",
          detail: "Pick an application that already has a window",
          action: "running",
        },
        {
          label: "$(gear)" + ICON_GAP + "Open settings…",
          detail: "All application settings",
          action: "settings",
        },
      ],
      { placeHolder: "Choose the application to test" },
    );
    if (!choice) return;
    if (choice.action === "settings")
      await vscode.commands.executeCommand(
        "wintestkit.openSettings",
        project.root,
      );
    else await this.applyApp(choice.action as "browse" | "running");
  }
  private async applyApp(action: "browse" | "running"): Promise<void> {
    const project = this.currentProject();
    if (!project) return;
    if (action === "browse") {
      const [picked] =
        (await vscode.window.showOpenDialog({
          canSelectMany: false,
          filters: { Applications: ["exe"] },
          openLabel: "Use this application",
          title: "Application to test",
        })) ?? [];
      if (picked)
        await this.save({
          "app.path": picked.fsPath,
          "app.process": undefined,
          launch: "per-test",
        });
    } else {
      const connection = await this.servers.get(project);
      const { processes } =
        await connection.client.request<AppProcessesResult>("app.processes");
      const running = await vscode.window.showQuickPick(
        processes.map((entry) => ({
          label: entry.name,
          description:
            entry.pids.length > 1
              ? entry.pids.length + " processes"
              : "PID " + entry.pids[0],
          detail: entry.windowTitle,
        })),
        {
          placeHolder: "Attach to which running application?",
          matchOnDetail: true,
        },
      );
      if (running)
        await this.save({
          "app.process": running.label,
          "app.path": undefined,
          launch: "attach",
        });
    }
  }
  dispose(): void {
    this.disposed = true;
    if (this.view) this.view.badge = undefined;
    this.viewSubscriptions.forEach((subscription) => subscription.dispose());
    this.subscriptions.forEach((subscription) => subscription.dispose());
  }
}
