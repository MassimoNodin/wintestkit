import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import * as path from "node:path";
import * as vscode from "vscode";
import type { Projects } from "../projects";
import type { AppProcessesResult } from "../protocol/generated";
import type { ServerManager } from "../server/serverManager";
import type { StatusBar } from "../statusBar";
import { executableIcon } from "./appIcon";
import { readConfiguration, writeLocalSettings } from "./files";
import {
  buildTestAppModel,
  modeChoices,
  type TestAppModel,
  type TileId,
} from "./testAppModel";

type WebviewMessage = { type: "ready" } | { type: "tile"; id: TileId };

const TILES = new Set<string>([
  "app",
  "mode",
  "project",
  "launch",
  "restart",
  "close",
  "refresh",
  "init",
  "output",
  "doctor",
]);

export function parseTestAppMessage(
  value: unknown,
): WebviewMessage | undefined {
  if (!value || typeof value !== "object") return;
  const message = value as Record<string, unknown>;
  if (message.type === "ready") return { type: "ready" };
  if (message.type === "tile" && TILES.has(String(message.id)))
    return { type: "tile", id: message.id as TileId };
}

/** The "Test Target" section: the application under test, how it starts, and its project. */
export class TestAppView
  implements vscode.WebviewViewProvider, vscode.Disposable
{
  private view?: vscode.WebviewView;
  private disposed = false;
  private readonly subscriptions: vscode.Disposable[];
  private readonly icons = new Map<string, string | undefined>();
  private readonly pendingIcons = new Set<string>();
  private rendering = false;
  private renderAgain = false;
  constructor(
    private readonly projects: Projects,
    private readonly status: StatusBar,
    private readonly servers: ServerManager,
    private readonly extensionUri: vscode.Uri,
  ) {
    this.subscriptions = [
      projects.onDidChange(() => this.refresh()),
      status.onDidChangeApplication(() => this.refresh()),
      vscode.window.onDidChangeActiveTextEditor(() => this.refresh()),
      vscode.window.registerWebviewViewProvider("wintestkit.setup", this),
    ];
  }
  async resolveWebviewView(view: vscode.WebviewView): Promise<void> {
    this.view = view;
    const assets = vscode.Uri.joinPath(this.extensionUri, "media", "setup");
    const icons = vscode.Uri.joinPath(this.extensionUri, "media", "codicons");
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [assets, icons],
    };
    const nonce = randomBytes(24).toString("hex");
    let html = await readFile(
      vscode.Uri.joinPath(assets, "setup.html").fsPath,
      "utf8",
    );
    for (const [name, value] of Object.entries({
      cspSource: view.webview.cspSource,
      nonce,
      css: view.webview
        .asWebviewUri(vscode.Uri.joinPath(assets, "setup.css"))
        .toString(),
      js: view.webview
        .asWebviewUri(vscode.Uri.joinPath(assets, "setup.js"))
        .toString(),
      icons: view.webview
        .asWebviewUri(vscode.Uri.joinPath(icons, "codicon.css"))
        .toString(),
    }))
      html = html.replaceAll("{{" + name + "}}", value);
    if (this.disposed || this.view !== view) return;
    view.webview.html = html;
    this.subscriptions.push(
      view.webview.onDidReceiveMessage((value) => {
        const message = parseTestAppMessage(value);
        if (message?.type === "ready") this.refresh();
        else if (message?.type === "tile") void this.run(message.id);
      }),
      view.onDidChangeVisibility(() => {
        if (view.visible) this.refresh();
      }),
      view.onDidDispose(() => {
        if (this.view === view) this.view = undefined;
      }),
    );
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
  private currentProject() {
    const active = vscode.window.activeTextEditor?.document.uri;
    return (active && this.projects.projectFor(active)) || this.projects.all[0];
  }
  async model(): Promise<TestAppModel> {
    const project = this.currentProject();
    const trusted = vscode.workspace.isTrusted;
    if (!project || !trusted) return buildTestAppModel({ project, trusted });
    const common = {
      project,
      trusted,
      projectCount: this.projects.all.length,
      workspaceName: vscode.workspace.getWorkspaceFolder(project.root)?.name,
    };
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
        ...common,
        config,
        state: this.status.applicationState(project),
        icon: source ? this.icon(source) : undefined,
      });
    } catch (error) {
      return buildTestAppModel({ ...common, configError: String(error) });
    }
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
    const project = this.currentProject();
    this.view.description =
      this.projects.all.length > 1 || !project
        ? model.status.label
        : `${project.name} · ${model.status.label}`;
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
        case "project":
          return await this.pickProject();
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
        case "init":
          return void (await vscode.commands.executeCommand(
            "wintestkit.initProject",
          ));
      }
    } catch (error) {
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
    const current = String(config.launch ?? "per-session");
    const choice = await vscode.window.showQuickPick(
      modeChoices.map((mode) => ({
        label: "$(" + mode.codicon + ") " + mode.title,
        description: mode.id === current ? "current" : undefined,
        detail: mode.description,
        id: mode.id,
      })),
      { placeHolder: "How should WinTestKit get the application?" },
    );
    if (choice && choice.id !== current) await this.save({ launch: choice.id });
  }
  private async pickProject(): Promise<void> {
    if (this.projects.all.length < 2) return;
    const choice = await vscode.window.showQuickPick(
      this.projects.all.map((project, index) => ({
        label: "$(folder-opened) " + project.name,
        description: index === 0 ? "current" : undefined,
        detail: project.root.fsPath,
        project,
      })),
      { placeHolder: "Choose a WinTestKit project" },
    );
    if (choice) this.projects.select(choice.project);
  }
  private async pickApp(): Promise<void> {
    const project = this.currentProject();
    if (!project) return;
    const choice = await vscode.window.showQuickPick(
      [
        {
          label: "$(folder-opened) Browse for an executable…",
          detail: "Launch it for tests (stored only on this machine)",
          action: "browse",
        },
        {
          label: "$(pulse) Attach to a running app…",
          detail: "Pick an application that already has a window",
          action: "running",
        },
        {
          label: "$(gear) Open settings…",
          detail: "All application settings",
          action: "settings",
        },
      ],
      { placeHolder: "Choose the application to test" },
    );
    if (!choice) return;
    if (choice.action === "settings") {
      await vscode.commands.executeCommand(
        "wintestkit.openSettings",
        project.root,
      );
    } else if (choice.action === "browse") {
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
          launch: "per-session",
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
    this.subscriptions.forEach((subscription) => subscription.dispose());
  }
}
