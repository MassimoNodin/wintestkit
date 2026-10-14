import { existsSync } from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";
import type { Project, ServerManager } from "./server/serverManager";

export function reportPath(
  last: string | undefined,
  reportDir: string | undefined,
  root: string,
  exists: (file: string) => boolean = existsSync,
): string | undefined {
  if (last && exists(last)) return last;
  if (!reportDir) return undefined;
  const candidate = path.resolve(root, reportDir, "index.html");
  return exists(candidate) ? candidate : undefined;
}

export function failureMessage(failed: number): string {
  return `${failed} ${failed === 1 ? "test" : "tests"} failed.`;
}

export class Reports {
  private readonly last = new Map<string, string>();
  private latest: string | undefined;
  constructor(
    private readonly servers: ServerManager,
    private readonly log: vscode.LogOutputChannel,
  ) {}

  record(project: Project, file: string | undefined, failed: number): void {
    if (file) {
      this.last.set(project.root.toString(), file);
      this.latest = file;
    }
    if (failed > 0) void this.notify(failed, file);
  }

  async open(project: Project | undefined): Promise<void> {
    const key = project?.root.toString();
    let reportDir: string | undefined;
    if (project && !(key && this.last.has(key))) {
      try {
        reportDir = (await this.servers.get(project)).initialized.config
          .reportDir;
      } catch (error) {
        this.log.warn(`Cannot read the report directory: ${String(error)}`);
      }
    }
    const file = project
      ? reportPath(key && this.last.get(key), reportDir, project.root.fsPath)
      : this.latest;
    if (!file) {
      await vscode.window.showInformationMessage(
        "No WinTestKit report found. Run the tests first.",
      );
      return;
    }
    await vscode.env.openExternal(vscode.Uri.file(file));
  }

  private async notify(
    failed: number,
    file: string | undefined,
  ): Promise<void> {
    const openReport = "Open Report";
    const showResults = "Show Test Results";
    const choice = await vscode.window.showErrorMessage(
      failureMessage(failed),
      ...(file ? [openReport] : []),
      showResults,
    );
    if (choice === openReport && file)
      await vscode.env.openExternal(vscode.Uri.file(file));
    else if (choice === showResults)
      await vscode.commands.executeCommand("testing.showMostRecentOutput");
  }
}
