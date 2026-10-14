import * as vscode from "vscode";
import type { AppStatusResult } from "./protocol/generated";
import { ServerManager, type Project } from "./server/serverManager";

export class StatusBar implements vscode.Disposable {
  private readonly item = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100,
  );
  private readonly subscriptions: vscode.Disposable[];
  private readonly timer: ReturnType<typeof setInterval>;
  private updating = false;
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
    if (this.updating || this.disposed) return;
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
      this.item.text = `$(beaker) WTK: ${running ? "$(circle-filled) app running" : "$(circle-outline) app stopped"}`;
    } catch {
      this.item.text =
        this.servers.state(project) === "not-installed"
          ? "$(beaker) WTK: $(warning) not installed"
          : "$(beaker) WTK: $(error) server error";
    } finally {
      this.updating = false;
      if (!this.disposed) {
        this.item.show();
        await vscode.commands.executeCommand(
          "setContext",
          "wintestkit.appRunning",
          running,
        );
      }
    }
  }
  dispose(): void {
    this.disposed = true;
    clearInterval(this.timer);
    this.item.dispose();
    this.subscriptions.forEach((subscription) => subscription.dispose());
  }
}
