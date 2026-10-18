import { existsSync } from "node:fs";
import { readFile, stat } from "node:fs/promises";
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

/** Points the report's relative screenshot and trace paths at the folder it was written to. */
export function previewHtml(html: string, baseHref: string): string {
  const base = `<base href="${baseHref.replace(/"/g, "&quot;")}">`;
  return /<head[^>]*>/i.test(html)
    ? html.replace(/<head[^>]*>/i, (head) => head + base)
    : base + html;
}

/**
 * The test run announces its report before the file is written, so wait until it exists and has
 * stopped growing. Resolves false if it never appears.
 */
export async function waitForFile(
  file: string,
  timeoutMs = 15000,
  size: (file: string) => Promise<number | undefined> = async (target) =>
    stat(target).then((info) => info.size, () => undefined),
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
): Promise<boolean> {
  const step = 150;
  let previous: number | undefined;
  for (let waited = 0; waited <= timeoutMs; waited += step) {
    const current = await size(file);
    if (current !== undefined && current > 0 && current === previous) return true;
    previous = current;
    await sleep(step);
  }
  return false;
}

export function failureMessage(failed: number): string {
  return `${failed} ${failed === 1 ? "test" : "tests"} failed.`;
}

export interface LastRunSummary {
  passed: number;
  failed: number;
  report?: string;
  at: number;
}

const LAST_RUNS_KEY = "wintestkit.lastRuns";

export class Reports {
  private readonly last = new Map<string, string>();
  private latest: string | undefined;
  private readonly summaries = new Map<string, LastRunSummary>();
  private readonly listeners = new Set<(project: Project) => void>();
  private panel?: vscode.WebviewPanel;
  private panelDir?: string;
  constructor(
    private readonly servers: ServerManager,
    private readonly log: vscode.LogOutputChannel,
    private readonly state?: vscode.Memento,
  ) {
    const saved = state?.get<Record<string, LastRunSummary>>(LAST_RUNS_KEY) ?? {};
    for (const [root, summary] of Object.entries(saved)) this.summaries.set(root, summary);
  }

  onDidChange(listener: (project: Project) => void): vscode.Disposable {
    this.listeners.add(listener);
    return { dispose: () => this.listeners.delete(listener) };
  }
  lastRun(project: Project | undefined): LastRunSummary | undefined {
    return project && this.summaries.get(project.root.toString());
  }
  record(project: Project, file: string | undefined, failed: number, passed = 0): void {
    const key = project.root.toString();
    const summary = { passed, failed, report: file, at: Date.now() };
    this.summaries.set(key, summary);
    void this.state?.update(LAST_RUNS_KEY, Object.fromEntries(this.summaries));
    this.listeners.forEach((listener) => listener(project));
    if (file) {
      this.last.set(key, file);
      this.latest = file;
    } else this.last.delete(key);
    if (failed > 0) void this.onFailure(failed, file);
  }
  /** Opens the report straight away; the toast is only the fallback when that is off or fails. */
  private async onFailure(failed: number, file: string | undefined): Promise<void> {
    if (file) {
      try {
        if (vscode.workspace.getConfiguration("wintestkit").get<boolean>("openReportOnFailure", true)) {
          await this.preview(file);
          return;
        }
      } catch (error) {
        this.log?.warn?.(`Cannot preview the report: ${String(error)}`);
      }
    }
    await this.notify(failed, file);
  }
  /** Shows the HTML report in the main editor area, leaving the side bar as it is, reusing one panel. */
  async preview(file: string): Promise<void> {
    const dir = path.dirname(file);
    if (!(await waitForFile(file))) throw new Error(`the report was not written: ${file}`);
    const html = await readFile(file, "utf8");
    if (this.panel && this.panelDir !== dir) this.panel.dispose();
    if (!this.panel) {
      const panel = vscode.window.createWebviewPanel(
        "wintestkit.report",
        "WinTestKit Report",
        { viewColumn: vscode.ViewColumn.Active, preserveFocus: false },
        {
          enableScripts: true,
          retainContextWhenHidden: true,
          localResourceRoots: [vscode.Uri.file(dir)],
        },
      );
      panel.onDidDispose(() => {
        if (this.panel === panel) this.panel = undefined;
      });
      this.panel = panel;
      this.panelDir = dir;
    } else this.panel.reveal(vscode.ViewColumn.Active, false);
    const base = this.panel.webview.asWebviewUri(vscode.Uri.file(dir)).toString();
    this.panel.webview.html = previewHtml(html, base.endsWith("/") ? base : base + "/");
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
    const summary = project && this.lastRun(project);
    const file = project
      ? reportPath(summary?.report ?? (key && this.last.get(key)), reportDir, project.root.fsPath)
      : this.latest;
    if (!file) {
      await vscode.window.showInformationMessage(
        "No WinTestKit report found. Run the tests first.",
      );
      return;
    }
    await this.preview(file);
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
    if (choice === openReport && file) await this.preview(file);
    else if (choice === showResults)
      await vscode.commands.executeCommand("testing.showMostRecentOutput");
  }
}
