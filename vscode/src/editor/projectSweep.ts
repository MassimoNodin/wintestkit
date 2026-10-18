import * as vscode from "vscode";
import { normalizedPath, type Projects } from "../projects";
import type { DiscoveryStore } from "../discovery/store";
import type { ServerManager } from "../server/serverManager";
import { readConfiguration } from "../settings/files";
import type { FlowEntry, PageCheckResult, PageEntry, FlowRunResult } from "../protocol/generated";
import { rememberedPageFlows, type Binding } from "./checkAfterFlow";

export function classifySweepBindings(
  bindings: readonly Binding[],
  pages: readonly PageEntry[],
  flows: readonly FlowEntry[],
): { supported: Binding[]; skipped: PageEntry[] } {
  const supported = bindings.filter((binding) => {
    const pageExists = pages.some(
      (page) =>
        normalizedPath(page.file) === normalizedPath(binding.file) &&
        page.qualname === binding.page,
    );
    const flow = flows.find(
      (item) =>
        normalizedPath(item.file) === normalizedPath(binding.flowFile) &&
        item.name === binding.flowName,
    );
    return (
      pageExists &&
      flow?.runnable === true &&
      !(flow.parameters ?? []).some((parameter) => parameter.required)
    );
  });
  const boundPages = new Set(
    supported.map(
      (binding) => normalizedPath(binding.file) + "::" + binding.page,
    ),
  );
  return {
    supported,
    skipped: pages.filter(
      (page) =>
        !boundPages.has(normalizedPath(page.file) + "::" + page.qualname),
    ),
  };
}

/** Runs explicitly remembered page navigation flows, then checks their page classes. */
export class ProjectSweep implements vscode.Disposable {
  private readonly diagnostics = vscode.languages.createDiagnosticCollection(
    "wintestkit-sweep",
  );
  private readonly registration: vscode.Disposable;
  constructor(
    private readonly projects: Projects,
    private readonly discovery: DiscoveryStore,
    private readonly servers: ServerManager,
    private readonly state: vscode.Memento,
  ) {
    this.registration = vscode.commands.registerCommand(
      "wintestkit.sweepProject",
      () => this.run(),
    );
  }
  private async run(): Promise<void> {
    const editor = vscode.window.activeTextEditor?.document.uri;
    const project = (editor && this.projects.projectFor(editor)) ?? this.projects.all[0];
    if (!project) return;
    const config = await readConfiguration(project.root);
    if (config.launch === "attach") {
      await vscode.window.showWarningMessage(
        "Project sweep requires Launch for tests mode. Select either per-session or per-test launch in Test Target settings, then try again.",
      );
      return;
    }
    const approved = await vscode.window.showWarningMessage(
      "Project sweep will run remembered navigation flows. These flows may change application state. Continue?",
      { modal: true }, "Run sweep");
    if (approved !== "Run sweep") return;
    const discovery = this.discovery.get(project);
    if (!discovery) return;
    const pages = discovery.pages;
    const { supported, skipped } = classifySweepBindings(
      rememberedPageFlows(this.state),
      pages,
      discovery.flows ?? [],
    );
    const entries: string[] = [];
    const problems: { uri: vscode.Uri; diagnostic: vscode.Diagnostic }[] = [];
    let cancelled = false;
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "WinTestKit project sweep",
        cancellable: true,
      },
      async (progress, token) => {
      const subscription = token.onCancellationRequested(() => { cancelled = true; });
      try {
        const connection = await this.servers.get(project);
        for (let index = 0; index < supported.length; index++) {
          if (cancelled) break;
          const binding = supported[index];
          if (!binding) break;
          progress.report({
            message: `Navigating to ${binding.page} (${index + 1}/${supported.length})`,
            increment: supported.length ? 100 / supported.length : 0,
          });
          let flow: FlowRunResult;
          try {
            flow = await connection.client.request<FlowRunResult>(
              "flow.run",
              {
                file: binding.flowFile,
                name: binding.flowName,
                arguments: {},
              },
              10 * 60 * 1000,
            );
          } catch (error) {
            entries.push(`- ${binding.page}: flow ${binding.flowName} failed: ${String(error)}`);
            continue;
          }
          if (flow.status !== "passed") {
            entries.push(
              `- ${binding.page}: flow ${binding.flowName} failed: ${flow.message ?? "unknown error"}`,
            );
            continue;
          }
          if (cancelled) break;
          const result = await connection.client.request<PageCheckResult>(
            "page.check",
            { file: binding.file, page: binding.page },
          );
          const failures = result.results.filter((item) => item.status !== "found");
          entries.push(
            `- ${binding.page}: ${result.results.length - failures.length}/${result.results.length} found${failures.length ? `; ${failures.length} not found or errors` : ""}`,
          );
          for (const failure of failures) {
            const definition = pages
              .find(
                (page) =>
                  normalizedPath(page.file) === normalizedPath(binding.file) &&
                  page.qualname === binding.page,
              )
              ?.elements.find((item) => item.qualname === failure.qualname);
            const detail = [
              failure.message,
              failure.diagnostic?.hint,
              ...(failure.diagnostic?.relocations ?? []).map((item) =>
                item.kind === "element" ? item.path : item.window,
              ),
            ]
              .filter(Boolean)
              .join("\n");
            const line = definition?.range.start.line ?? 0;
            const diagnostic = new vscode.Diagnostic(
              new vscode.Range(line, 0, line, 1),
              detail || "Not found on the current screen",
              vscode.DiagnosticSeverity.Warning,
            );
            diagnostic.source = "WinTestKit sweep";
            problems.push({ uri: vscode.Uri.file(binding.file), diagnostic });
          }
        }
      } finally {
        subscription.dispose();
      }
      },
    );
    this.diagnostics.clear();
    const grouped = new Map<string, vscode.Diagnostic[]>();
    for (const item of problems) grouped.set(item.uri.toString(), [...(grouped.get(item.uri.toString()) ?? []), item.diagnostic]);
    for (const [uri, items] of grouped) this.diagnostics.set(vscode.Uri.parse(uri), items);
    const report = [
      "# WinTestKit project sweep",
      "",
      `Project: ${project.root.fsPath}`,
      `Completed: ${new Date().toISOString()}`,
      `Status: ${cancelled ? "Cancelled" : "Complete"}`,
      "",
      "## Results",
      ...(entries.length ? entries : ["- No remembered reach flows were run."]),
      "",
      "## Skipped pages",
      ...(skipped.length
        ? skipped.map(
            (page) =>
              `- ${page.qualname} (${vscode.workspace.asRelativePath(page.file)})`,
          )
        : ["- None"]),
      "",
    ].join("\n");
    const uri = vscode.Uri.joinPath(project.root, "wtk-report", "project-sweep.md");
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(project.root, "wtk-report"));
    await vscode.workspace.fs.writeFile(uri, Buffer.from(report, "utf8"));
    await vscode.window.showInformationMessage(
      `Project sweep ${cancelled ? "cancelled" : "complete"}. ${entries.length} flows run; ${skipped.length} pages skipped. Problems and report updated.`,
    );
    await vscode.commands.executeCommand("vscode.open", uri);
  }
  dispose(): void {
    this.registration.dispose();
    this.diagnostics.dispose();
  }
}
