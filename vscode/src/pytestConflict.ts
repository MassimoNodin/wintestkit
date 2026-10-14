import * as vscode from "vscode";
import type { Projects } from "./projects";

export class PytestConflict implements vscode.Disposable {
  private readonly subscriptions: vscode.Disposable[];
  private readonly asked: Set<string>;
  private disposed = false;
  constructor(
    private readonly projects: Projects,
    private readonly state: vscode.Memento,
    private readonly log: vscode.LogOutputChannel,
  ) {
    this.asked = new Set(state.get<string[]>("wintestkit.pytestConflict", []));
    const check = () => {
      void this.check().catch((error) => log.error(String(error)));
    };
    this.subscriptions = [
      projects.onDidChange(check),
      vscode.workspace.onDidChangeConfiguration(check),
    ];
    check();
  }
  private async check(): Promise<void> {
    for (const project of this.projects.all) {
      if (this.disposed) return;
      const folder = vscode.workspace.getWorkspaceFolder(project.root);
      if (!folder) continue;
      const key = folder.uri.toString();
      if (
        this.asked.has(key) ||
        !vscode.workspace
          .getConfiguration("python.testing", folder.uri)
          .get<boolean>("pytestEnabled", false) ||
        !vscode.workspace
          .getConfiguration("wintestkit", folder.uri)
          .get<boolean>("promptDisablePytestExplorer", true)
      )
        continue;
      this.asked.add(key);
      await this.state.update("wintestkit.pytestConflict", [...this.asked]);
      const choice = await vscode.window.showInformationMessage(
        "WinTestKit shows your tests in Test Explorer. Turn off the Python extension's pytest discovery for this workspace to avoid duplicate tests?",
        "Turn Off",
        "Keep Both",
        "Don't Ask Again",
      );
      if (this.disposed) return;
      if (choice === "Turn Off")
        await vscode.workspace
          .getConfiguration("python.testing", folder.uri)
          .update(
            "pytestEnabled",
            false,
            vscode.ConfigurationTarget.WorkspaceFolder,
          );
      if (choice === "Don't Ask Again")
        await vscode.workspace
          .getConfiguration("wintestkit")
          .update(
            "promptDisablePytestExplorer",
            false,
            vscode.ConfigurationTarget.Global,
          );
    }
  }
  dispose(): void {
    this.disposed = true;
    this.subscriptions.forEach((subscription) => subscription.dispose());
  }
}
