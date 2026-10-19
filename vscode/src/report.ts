import { existsSync } from "node:fs";
import { readFile, stat, writeFile } from "node:fs/promises";
import * as path from "node:path";
import * as vscode from "vscode";
import { buildReportHtml } from "./reportPage";
import type { Project, ServerManager } from "./server/serverManager";

/** `results.json` next to a report path (which names `index.html`, written or not). */
export function resultsFile(report: string): string {
  return path.join(path.dirname(report), "results.json");
}

/** The last report that still has saved results, else the project's default report location. */
export function reportPath(
  last: string | undefined,
  reportDir: string | undefined,
  root: string,
  exists: (file: string) => boolean = existsSync,
): string | undefined {
  if (last && exists(resultsFile(last))) return last;
  if (!reportDir) return undefined;
  const candidate = path.resolve(root, reportDir, "index.html");
  return exists(resultsFile(candidate)) ? candidate : undefined;
}

export type ReportTheme = "light" | "dark";

export function isReportTheme(value: unknown): value is ReportTheme {
  return value === "light" || value === "dark";
}

/**
 * Points the report's relative screenshot and replay-frame paths at the folder it was written to, and
 * passes on the theme the user last picked in the report.
 */
export function previewHtml(html: string, baseHref: string, theme?: ReportTheme): string {
  const base =
    `<base href="${baseHref.replace(/"/g, "&quot;")}">` +
    (theme ? `<meta name="wtk-theme" content="${theme}">` : "");
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
const REPORT_THEME_KEY = "wintestkit.reportTheme";

export class Reports {
  private readonly last = new Map<string, string>();
  private latest: string | undefined;
  private readonly summaries = new Map<string, LastRunSummary>();
  private readonly listeners = new Set<(project: Project) => void>();
  private panel?: vscode.WebviewPanel;
  private panelDir?: string;
  private templateText?: string;
  constructor(
    private readonly servers: ServerManager,
    private readonly log: vscode.LogOutputChannel,
    private readonly state?: vscode.Memento,
    private readonly templateFile?: string,
    private readonly waitMs = 15000,
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
  /** The report page drawn from the saved results; an older run's `index.html` is the fallback. */
  private async pageFor(file: string): Promise<string> {
    const dir = path.dirname(file);
    try {
      this.templateText ??= await readFile(this.templateFile ?? "", "utf8");
      return await buildReportHtml(dir, this.templateText);
    } catch (error) {
      if (existsSync(file)) return readFile(file, "utf8");
      throw error;
    }
  }
  /**
   * Shows the report in the main editor area, leaving the side bar as it is, reusing one panel.
   * It is drawn straight from `results.json`, so no HTML file has to exist.
   */
  async preview(file: string): Promise<void> {
    const dir = path.dirname(file);
    const legacyOnly = !existsSync(resultsFile(file)) && existsSync(file);
    if (!legacyOnly && !(await waitForFile(resultsFile(file), this.waitMs)))
      throw new Error(`the report was not written: ${resultsFile(file)}`);
    const html = await this.pageFor(file);
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
      panel.webview.onDidReceiveMessage((message: { type?: unknown; theme?: unknown }) => {
        if (message?.type === "wtk-theme" && isReportTheme(message.theme))
          void this.state?.update(REPORT_THEME_KEY, message.theme);
        else if (message?.type === "wtk-export")
          void this.exportHtml().catch((error) =>
            vscode.window.showErrorMessage(`Cannot export the report: ${String(error)}`),
          );
      });
      panel.onDidDispose(() => {
        if (this.panel === panel) this.panel = undefined;
      });
      this.panel = panel;
      this.panelDir = dir;
    } else this.panel.reveal(vscode.ViewColumn.Active, false);
    const base = this.panel.webview.asWebviewUri(vscode.Uri.file(dir)).toString();
    const theme = this.state?.get<unknown>(REPORT_THEME_KEY);
    this.panel.webview.html = previewHtml(
      html,
      base.endsWith("/") ? base : base + "/",
      isReportTheme(theme) ? theme : undefined,
    );
  }

  /** Saves the report as one self-contained HTML file, by default into its own report folder. */
  async exportHtml(project?: Project): Promise<void> {
    const file = this.panelDir
      ? path.join(this.panelDir, "index.html")
      : await this.locate(project);
    if (!file) {
      await vscode.window.showInformationMessage("No WinTestKit report found. Run the tests first.");
      return;
    }
    const dir = path.dirname(file);
    this.templateText ??= await readFile(this.templateFile ?? "", "utf8");
    const html = await buildReportHtml(dir, this.templateText);
    const target = await vscode.window.showSaveDialog({
      defaultUri: vscode.Uri.file(file),
      filters: { "HTML report": ["html"] },
      title: "Export the WinTestKit report as HTML",
    });
    if (!target) return;
    await writeFile(target.fsPath, html, "utf8");
    const openIt = "Open in Browser";
    const where =
      path.dirname(target.fsPath) === dir
        ? ""
        : ` Screenshots and replay frames load from ${path.join(dir, "artifacts")}, so keep that folder with it.`;
    const choice = await vscode.window.showInformationMessage(
      `Exported ${path.basename(target.fsPath)}.${where}`,
      openIt,
    );
    if (choice === openIt) await vscode.env.openExternal(target);
  }

  private async locate(project: Project | undefined): Promise<string | undefined> {
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
    return project
      ? reportPath(summary?.report ?? (key && this.last.get(key)), reportDir, project.root.fsPath)
      : this.latest;
  }

  async open(project: Project | undefined): Promise<void> {
    const file = await this.locate(project);
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
