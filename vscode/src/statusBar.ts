import * as vscode from "vscode";
import type { AppStatusResult } from "./protocol/generated";
import { ServerManager, type Project } from "./server/serverManager";

export interface ApplicationState {
  running: boolean;
  error?: string;
}

export class StatusBar implements vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<Project>();
  readonly onDidChangeApplication = this.changed.event;
  private readonly applications = new Map<string, ApplicationState>();
  private readonly item = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100,
  );
  private readonly subscriptions: vscode.Disposable[];
  private readonly timer: ReturnType<typeof setInterval>;
  private updating = false;
  private pendingRefresh = false;
  private disposed = false;
  constructor(
    private readonly servers: ServerManager,
    private readonly project: () => Project | undefined,
  ) {
    this.item.command = "wintestkit.statusMenu";
    this.item.tooltip = "WinTestKit application and server status";
    this.subscriptions = [
      servers.onDidChange(() => {
        void this.refresh();
      }),
      vscode.window.onDidChangeWindowState((state) => {
        if (state.focused) void this.refresh();
      }),
      vscode.window.onDidChangeActiveTextEditor(() => {
        void this.refresh();
      }),
      vscode.commands.registerCommand("wintestkit.statusMenu", async () => {
        const actions = [
          ["Launch App", "wintestkit.launchApp"],
          ["Close App", "wintestkit.closeApp"],
          ["Restart Server", "wintestkit.restartServer"],
          ["Open Last Report", "wintestkit.openReport"],
          ["Check Environment", "wintestkit.runDoctor"],
          ["Show Output", "wintestkit.showOutput"],
        ];
        const choice = await vscode.window.showQuickPick(
          actions.map(([label, command]) => ({ label, command })),
        );
        if (choice) await vscode.commands.executeCommand(choice.command);
      }),
    ];
    this.timer = setInterval(() => {
      if (vscode.window.state.focused) void this.refresh();
    }, 5000);
    void this.refresh();
  }
  async refresh(): Promise<void> {
    if (this.disposed) return;
    if (this.updating) {
      this.pendingRefresh = true;
      return;
    }
    const project = this.project();
    if (!project || !vscode.workspace.isTrusted) {
      this.item.hide();
      await vscode.commands.executeCommand(
        "setContext",
        "wintestkit.appRunning",
        false,
      );
      return;
    }
    this.updating = true;
    let running = false;
    try {
      const connection = await this.servers.get(project);
      const status =
        await connection.client.request<AppStatusResult>("app.status");
      running = status.running;
      this.applications.set(project.root.toString(), { running });
      this.item.text = `$(beaker) WTK: ${running ? "$(circle-filled) app running" : "$(circle-outline) app stopped"}`;
    } catch (error) {
      this.applications.set(project.root.toString(), {
        running: false,
        error: this.servers.state(project) === "not-installed"
          ? "Python package not installed" : String(error),
      });
      this.item.text =
        this.servers.state(project) === "not-installed"
          ? "$(beaker) WTK: $(warning) not installed"
          : "$(beaker) WTK: $(error) server error";
    } finally {
      this.updating = false;
      if (!this.disposed) {
        this.changed.fire(project);
        if (this.project()?.root.toString() === project.root.toString()) {
          this.item.show();
          await vscode.commands.executeCommand(
            "setContext", "wintestkit.appRunning", running,
          );
        } else {
          this.pendingRefresh = true;
        }
        if (this.pendingRefresh) {
          this.pendingRefresh = false;
          void this.refresh();
        }
      }
    }
  }
  applicationState(project: Project): ApplicationState | undefined {
    return this.applications.get(project.root.toString());
  }
  dispose(): void {
    this.disposed = true;
    clearInterval(this.timer);
    this.item.dispose();
    this.changed.dispose();
    this.subscriptions.forEach((subscription) => subscription.dispose());
  }
}
