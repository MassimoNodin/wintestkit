import * as path from "node:path";
import * as vscode from "vscode";
import type { Project } from "./server/serverManager";

export function normalizedPath(
  file: string,
  insensitive = process.platform === "win32",
): string {
  const normalized = (
    /^[a-z]:[\\/]|^\\\\/i.test(file)
      ? path.win32.resolve(file)
      : path.resolve(file)
  )
    .replaceAll("\\", "/")
    .replace(/\/$/, "");
  return insensitive ? normalized.toLowerCase() : normalized;
}
export function pickProject(
  roots: string[],
  file: string,
  insensitive = process.platform === "win32",
): string | undefined {
  const target = normalizedPath(file, insensitive);
  return roots
    .filter((root) => {
      const prefix = normalizedPath(root, insensitive);
      return target === prefix || target.startsWith(prefix + "/");
    })
    .sort(
      (first, second) =>
        normalizedPath(second).length - normalizedPath(first).length,
    )[0];
}

export class Projects implements vscode.Disposable {
  private projects: Project[] = [];
  private preferredRoot?: string;
  private revision = 0;
  private disposed = false;
  private readonly changed = new vscode.EventEmitter<readonly Project[]>();
  readonly onDidChange = this.changed.event;
  private readonly subscriptions: vscode.Disposable[];
  constructor(private readonly log: vscode.LogOutputChannel) {
    const watcher = vscode.workspace.createFileSystemWatcher(
      "**/{pyproject.toml,wintestkit.yaml,wintestkit.local.yaml,wintestkit.local.toml}",
    );
    const refresh = () => {
      void this.refresh();
    };
    this.subscriptions = [
      watcher,
      watcher.onDidCreate(refresh),
      watcher.onDidChange(refresh),
      watcher.onDidDelete(refresh),
      vscode.workspace.onDidChangeWorkspaceFolders(refresh),
    ];
  }
  get all(): readonly Project[] {
    return this.projects;
  }
  /**
   * Makes ``project`` the one views fall back to (``all[0]``) when no open file belongs to a
   * project, for example when the user picks a project in the Test Target card.
   */
  select(project: Project): void {
    this.preferredRoot = normalizedPath(project.root.fsPath);
    this.projects = this.prefer(this.projects);
    this.changed.fire(this.projects);
  }
  private prefer(projects: Project[]): Project[] {
    if (!this.preferredRoot) return projects;
    const preferred = projects.find(
      (project) => normalizedPath(project.root.fsPath) === this.preferredRoot,
    );
    return preferred
      ? [preferred, ...projects.filter((project) => project !== preferred)]
      : projects;
  }
  projectFor(uri: vscode.Uri): Project | undefined {
    const root = pickProject(
      this.projects.map((project) => project.root.fsPath),
      uri.fsPath,
    );
    return this.projects.find((project) => project.root.fsPath === root);
  }
  async refresh(): Promise<void> {
    const revision = ++this.revision;
    try {
      const files = await vscode.workspace.findFiles(
        "**/{pyproject.toml,wintestkit.yaml}",
        "**/{node_modules,.venv,venv,.git,site-packages}/**",
      );
      const projects: Project[] = [];
      for (const file of files) {
        try {
          const source = Buffer.from(
            await vscode.workspace.fs.readFile(file),
          ).toString("utf8");
          if (
            path.basename(file.fsPath) === "wintestkit.yaml" ||
            /^\s*\[tool\.wintestkit(?:\.app)?\]\s*(?:#.*)?$/m.test(source)
          ) {
            const root = vscode.Uri.file(path.dirname(file.fsPath));
            if (
              !projects.some(
                (project) =>
                  normalizedPath(project.root.fsPath) ===
                  normalizedPath(root.fsPath),
              )
            )
              projects.push({ root, name: path.basename(root.fsPath) });
          }
        } catch (error) {
          this.log.debug(
            `Cannot read project ${file.fsPath}: ${String(error)}`,
          );
        }
      }
      if (this.disposed || revision !== this.revision) return;
      this.projects = this.prefer(
        projects.sort((first, second) =>
          first.root.fsPath.localeCompare(second.root.fsPath),
        ),
      );
      await vscode.commands.executeCommand(
        "setContext",
        "wintestkit.hasProject",
        projects.length > 0,
      );
      this.changed.fire(this.projects);
    } catch (error) {
      this.log.error(`Project discovery failed: ${String(error)}`);
    }
  }
  dispose(): void {
    this.disposed = true;
    this.revision++;
    this.subscriptions.forEach((subscription) => subscription.dispose());
    this.changed.dispose();
  }
}
