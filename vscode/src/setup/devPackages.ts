import * as path from "node:path";
import { stat } from "node:fs/promises";
import * as vscode from "vscode";
import { packageCompatibility, PYTHON_REQUIREMENT } from "../compatibility";

type Selection = { source: "remote" | "local"; wheel?: string };

export class DevPackages {
  constructor(private readonly state: vscode.Memento) {}

  private key(folder: vscode.Uri): string {
    return "development.packageSource." + folder.toString();
  }

  view(folder: vscode.Uri): Selection {
    const saved = this.state.get<Selection>(this.key(folder));
    return saved?.source === "local" && typeof saved.wheel === "string"
      ? { source: "local", wheel: saved.wheel }
      : { source: "remote" };
  }

  async select(folder: vscode.Uri, source: "remote" | "local"): Promise<void> {
    if (!vscode.workspace.isTrusted) throw new Error("Trust the workspace before selecting a package source.");
    if (source === "remote") {
      await this.state.update(this.key(folder), { source });
      return;
    }
    const selected = await vscode.window.showOpenDialog({
      title: "Development: select a trusted WinTestKit wheel",
      openLabel: "Use local wheel",
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: false,
      filters: { "Python wheel": ["whl"] },
    });
    if (!selected?.length) return;
    const wheel = selected[0];
    if (wheel.scheme !== "file" || !/^wintestkit-[^-]+-[^-]+-[^-]+-[^-]+\.whl$/i.test(path.basename(wheel.fsPath)))
      throw new Error("Select a local wintestkit wheel, not a source archive or another package.");
    if (!(await stat(wheel.fsPath)).isFile()) throw new Error("The selected wheel is not a file.");
    this.checkVersion(wheel.fsPath);
    await this.state.update(this.key(folder), { source, wheel: wheel.fsPath });
  }

  async arguments(folder: vscode.Uri): Promise<string[] | undefined> {
    const selection = this.view(folder);
    if (selection.source === "remote")
      return ["-m", "pip", "install", "--upgrade", "--force-reinstall", PYTHON_REQUIREMENT];
    if (selection.source !== "local" || !selection.wheel) return undefined;
    if (!(await stat(selection.wheel)).isFile()) throw new Error("The selected local wheel no longer exists.");
    this.checkVersion(selection.wheel);
    return ["-m", "pip", "install", "--upgrade", "--force-reinstall", selection.wheel];
  }
  private checkVersion(wheel: string): void {
    const version = /^wintestkit-([^-]+)-/i.exec(path.basename(wheel))?.[1];
    const issue = packageCompatibility(version);
    if (issue) throw new Error(issue.message);
  }
}
