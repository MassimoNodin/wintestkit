import * as vscode from "vscode";
import type { Projects } from "../projects";
import { normalizedPath } from "../projects";
import type { DiscoveryStore } from "../discovery/store";
import type {
  ElementHighlightResult,
  PageCheckResult,
} from "../protocol/generated";
import { ServerManager, type Project } from "../server/serverManager";
import { RpcError } from "../server/jsonrpc";
import { summarizeChecks } from "./checkStatus";
import { CheckResultsStore } from "./decorations";
import { formatDiagnostic, shortElement } from "./diagnostics";
import type { ActionStatus } from "./lensModel";

export interface ElementTarget {
  file: string;
  qualname: string;
}
export interface PageTarget {
  file: string;
  page: string;
}
class AppNotRunningError extends Error {
  constructor(readonly launch: () => Promise<unknown>) {
    super("The app isn't running.");
  }
}
export class HighlightCommands implements vscode.Disposable {
  private readonly subscriptions: vscode.Disposable[];
  constructor(
    private readonly projects: Projects,
    private readonly discovery: DiscoveryStore,
    private readonly servers: ServerManager,
    private readonly checks: CheckResultsStore,
    private readonly log: vscode.LogOutputChannel,
  ) {
    this.subscriptions = [
      vscode.commands.registerCommand(
        "wintestkit.highlightElement",
        (target?: ElementTarget) => this.safe(() => this.highlight(target)),
      ),
      vscode.commands.registerCommand(
        "wintestkit.checkElement",
        (target?: ElementTarget) => this.safe(() => this.checkElement(target)),
      ),
      vscode.commands.registerCommand(
        "wintestkit.checkPage",
        (target?: PageTarget) => this.safe(() => this.checkPage(target)),
      ),
    ];
  }
  private async safe(action: () => Promise<void>, retry = true): Promise<void> {
    try {
      await action();
    } catch (error) {
      if (retry && error instanceof AppNotRunningError) {
        const choice = await vscode.window.showInformationMessage(
          error.message,
          "Launch App",
        );
        if (choice === "Launch App")
          await this.safe(async () => {
            await error.launch();
            await action();
          }, false);
        return;
      }
      this.log.error(String(error));
      const choice = await vscode.window.showErrorMessage(
        error instanceof Error ? error.message : String(error),
        "Show Output",
      );
      if (choice) this.log.show();
    }
  }
  private target(target?: ElementTarget): ElementTarget | undefined {
    if (target) return { file: target.file, qualname: target.qualname };
    const editor = vscode.window.activeTextEditor;
    const located =
      editor &&
      this.discovery.elementAt(
        editor.document.uri,
        editor.selection.active.line,
      );
    return located
      ? { file: located.page.file, qualname: located.element.qualname }
      : undefined;
  }
  private async request<Result>(
    project: Project,
    method: string,
    params: Record<string, unknown>,
  ): Promise<Result> {
    const connection = await this.servers.get(project);
    try {
      return await connection.client.request<Result>(method, params);
    } catch (error) {
      if (error instanceof RpcError && error.code === -32002)
        throw new AppNotRunningError(() =>
          connection.client.request("app.launch"),
        );
      throw error;
    }
  }
  private async highlight(input?: ElementTarget): Promise<void> {
    const target = this.target(input);
    if (!target) return;
    const uri = vscode.Uri.file(target.file);
    const project = this.projects.projectFor(uri);
    if (!project) return;
    const page = this.discovery
      .get(project)
      ?.pages.find(
        (page) =>
          normalizedPath(page.file) === normalizedPath(target.file) &&
          page.elements.some((element) => element.qualname === target.qualname),
      );
    const element = page?.elements.find(
      (element) => element.qualname === target.qualname,
    );
    const located = page && element ? { project, page, element } : undefined;
    const pendingStatus: ActionStatus = { status: "running" };
    if (located) this.checks.setFeedback(located, "highlight", pendingStatus);
    const durationMs = vscode.workspace
      .getConfiguration("wintestkit", uri)
      .get<number>("highlight.durationMs", 1500);
    const operation = this.request<ElementHighlightResult>(
      project,
      "element.highlight",
      { ...target, durationMs },
    );
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const pending = await Promise.race([
        operation.then(() => false),
        new Promise<boolean>((resolve) => {
          timer = setTimeout(() => resolve(true), 500);
        }),
      ]);
      const result = pending
        ? await vscode.window.withProgress(
            {
              location: vscode.ProgressLocation.Notification,
              title: "Highlighting element",
            },
            () => operation,
          )
        : await operation;
      if (
        located &&
        this.checks.setFeedback(located, "highlight", result, pendingStatus)
      )
        this.checks.set({
          ...located,
          result: { ...result, qualname: target.qualname },
        });
      if (result.status === "found" && result.element)
        vscode.window.setStatusBarMessage(
          "$(eye) Found " + shortElement(result.element),
          5000,
        );
      else {
        const choice = await vscode.window.showWarningMessage(
          result.diagnostic?.message ??
            result.message ??
            "Element was not found",
          "Show Details",
          "Open Spy",
        );
        if (choice === "Show Details") {
          this.log.info(
            result.diagnostic
              ? formatDiagnostic(result.diagnostic)
              : (result.message ?? "Element resolution failed"),
          );
          this.log.show();
        }
        if (choice === "Open Spy")
          await vscode.commands.executeCommand("wintestkit.spy.focus");
      }
    } catch (error) {
      const result = {
        status: "error" as const,
        message: error instanceof Error ? error.message : String(error),
        durationMs: 0,
        qualname: target.qualname,
      };
      if (
        located &&
        this.checks.setFeedback(located, "highlight", result, pendingStatus)
      )
        this.checks.set({ ...located, result });
      throw error;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  private async checkElement(input?: ElementTarget): Promise<void> {
    const target = this.target(input);
    if (!target) return;
    const project = this.projects.projectFor(vscode.Uri.file(target.file));
    if (!project) return;
    const page = this.discovery
      .get(project)
      ?.pages.find(
        (page) =>
          normalizedPath(page.file) === normalizedPath(target.file) &&
          page.elements.some((element) => element.qualname === target.qualname),
      );
    if (page)
      await this.checkPage(
        { file: page.file, page: page.qualname },
        target.qualname,
      );
  }
  private async checkPage(input?: PageTarget, filter?: string): Promise<void> {
    let target = input;
    if (!target) {
      const editor = vscode.window.activeTextEditor;
      const project = editor && this.projects.projectFor(editor.document.uri);
      const page =
        project &&
        this.discovery
          .get(project)
          ?.pages.find(
            (page) =>
              normalizedPath(page.file) ===
                normalizedPath(editor.document.uri.fsPath) &&
              page.range.start.line <= editor.selection.active.line &&
              page.range.end.line >= editor.selection.active.line,
          );
      if (page) target = { file: page.file, page: page.qualname };
    }
    if (!target) return;
    const project = this.projects.projectFor(vscode.Uri.file(target.file));
    if (!project) return;
    const page = this.discovery
      .get(project)
      ?.pages.find(
        (page) =>
          normalizedPath(page.file) === normalizedPath(target.file) &&
          page.qualname === target.page,
      );
    if (!page) return;
    const elements = filter
      ? page.elements.filter((element) => element.qualname === filter)
      : page.elements;
    const pendingStatus: ActionStatus = { status: "running" };
    for (const element of elements)
      this.checks.setFeedback(
        { project, page, element },
        "check",
        pendingStatus,
      );
    try {
      const result = await this.request<PageCheckResult>(
        project,
        "page.check",
        {
          file: target.file,
          page: target.page,
        },
      );
      for (const element of elements) {
        const checked = result.results.find(
          (checked) => checked.qualname === element.qualname,
        ) ?? {
          qualname: element.qualname,
          status: "error" as const,
          message: "The server returned no check result for this element.",
          durationMs: 0,
        };
        const located = { project, page, element };
        if (this.checks.setFeedback(located, "check", checked, pendingStatus))
          this.checks.set({ ...located, result: checked });
      }
      if (!filter)
        vscode.window.setStatusBarMessage(
          summarizeChecks(result.results),
          5000,
        );
    } catch (error) {
      for (const element of elements) {
        const result = {
          qualname: element.qualname,
          status: "error" as const,
          message: error instanceof Error ? error.message : String(error),
          durationMs: 0,
        };
        const located = { project, page, element };
        if (this.checks.setFeedback(located, "check", result, pendingStatus))
          this.checks.set({ ...located, result });
      }
      throw error;
    }
  }
  dispose(): void {
    this.subscriptions.forEach((subscription) => subscription.dispose());
  }
}
