import * as path from "node:path";
import * as vscode from "vscode";
import type { Projects } from "../projects";
import { readConfiguration } from "./files";
import { executableIcon } from "./appIcon";

export class CurrentSetup
  implements vscode.TreeDataProvider<vscode.TreeItem>, vscode.Disposable
{
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;
  private readonly subscriptions: vscode.Disposable[];
  private readonly icons = new Map<string, vscode.Uri | undefined>();
  private readonly pendingIcons = new Set<string>();
  private disposed = false;
  constructor(private readonly projects: Projects) {
    this.subscriptions = [
      projects.onDidChange(() => this.refresh()),
      vscode.window.onDidChangeActiveTextEditor(() => this.refresh()),
      vscode.window.registerTreeDataProvider("wintestkit.setup", this),
    ];
  }
  refresh(): void {
    this.changed.fire();
  }
  getTreeItem(item: vscode.TreeItem): vscode.TreeItem {
    return item;
  }
  async getChildren(): Promise<vscode.TreeItem[]> {
    const active = vscode.window.activeTextEditor?.document.uri;
    const project =
      (active && this.projects.projectFor(active)) || this.projects.all[0];
    if (!project) return [];
    const item = new vscode.TreeItem("Configure application");
    item.id = project.root.toString();
    item.contextValue = "current-setup";
    item.resourceUri = project.root;
    item.command = {
      command: "wintestkit.openSettings",
      title: "Configure WinTestKit",
      arguments: [project.root],
    };
    item.iconPath = new vscode.ThemeIcon("desktop-download");
    if (!vscode.workspace.isTrusted) {
      item.description = "Workspace not trusted";
      return [item];
    }
    try {
      const config = await readConfiguration(project.root);
      const file =
        typeof config["app.path"] === "string" ? config["app.path"] : undefined;
      const process =
        typeof config["app.process"] === "string"
          ? config["app.process"]
          : undefined;
      item.label = path.win32
        .basename(file || process || "Configure application")
        .replace(/\.exe$/i, "");
      item.description = project.name + " · " + String(config.launch);
      item.tooltip =
        (file || process || "Select an application in local settings") +
        "\nClick to configure this project.";
      const iconSource = file
        ? path.isAbsolute(file)
          ? file
          : path.resolve(project.root.fsPath, file)
        : process;
      if (iconSource) {
        if (!this.icons.has(iconSource) && !this.pendingIcons.has(iconSource)) {
          this.pendingIcons.add(iconSource);
          void executableIcon(iconSource).then((icon) => {
            this.pendingIcons.delete(iconSource);
            this.icons.set(iconSource, icon);
            if (!this.disposed) this.refresh();
          });
        }
        item.iconPath = this.icons.get(iconSource) ?? item.iconPath;
      }
    } catch (error) {
      item.description = "Configuration error";
      item.tooltip = String(error);
    }
    return [item];
  }
  dispose(): void {
    this.disposed = true;
    this.subscriptions.forEach((subscription) => subscription.dispose());
    this.changed.dispose();
  }
}
