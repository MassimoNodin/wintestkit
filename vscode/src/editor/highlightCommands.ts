import * as vscode from "vscode";
import type { Projects } from "../projects";
import { normalizedPath } from "../projects";
import type { DiscoveryStore } from "../discovery/store";
import type {
  ElementHighlightResult,
  ScreenCheckResult,
} from "../protocol/generated";
import { ServerManager, type Project } from "../server/serverManager";
import { RpcError } from "../server/jsonrpc";
import { CheckResultsStore } from "./decorations";
import { formatDiagnostic, shortElement } from "./diagnostics";

export interface ElementTarget {
  file: string;
  qualname: string;
}
export interface ScreenTarget {
  file: string;
  screen: string;
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
        "wintestkit.checkScreen",
        (target?: ScreenTarget) => this.safe(() => this.checkScreen(target)),
      ),
    ];
  }
  private async safe(action: () => Promise<void>): Promise<void> {
    try {
      await action();
    } catch (error) {
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
      ? { file: located.screen.file, qualname: located.element.qualname }
      : undefined;
  }
  private async request<Result>(
    project: Project,
    method: string,
    params: Record<string, unknown>,
    retry = true,
  ): Promise<Result> {
    const connection = await this.servers.get(project);
    try {
      return await connection.client.request<Result>(method, params);
    } catch (error) {
      if (retry && error instanceof RpcError && error.code === -32002) {
        const choice = await vscode.window.showInformationMessage(
          "The app isn't running.",
          "Launch App",
        );
        if (choice) {
          await connection.client.request("app.launch");
          return this.request(project, method, params, false);
        }
      }
      throw error;
    }
  }
  private async highlight(input?: ElementTarget): Promise<void> {
    const target = this.target(input);
    if (!target) return;
    const uri = vscode.Uri.file(target.file);
    const project = this.projects.projectFor(uri);
    if (!project) return;
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
      const screen = this.discovery
        .get(project)
        ?.screens.find(
          (screen) =>
            normalizedPath(screen.file) === normalizedPath(target.file) &&
            screen.elements.some(
              (element) => element.qualname === target.qualname,
            ),
        );
      const element = screen?.elements.find(
        (element) => element.qualname === target.qualname,
      );
      if (screen && element)
        this.checks.set({
          project,
          screen,
          element,
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
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  private async checkElement(input?: ElementTarget): Promise<void> {
    const target = this.target(input);
    if (!target) return;
    const project = this.projects.projectFor(vscode.Uri.file(target.file));
    if (!project) return;
    const screen = this.discovery
      .get(project)
      ?.screens.find(
        (screen) =>
          normalizedPath(screen.file) === normalizedPath(target.file) &&
          screen.elements.some(
            (element) => element.qualname === target.qualname,
          ),
      );
    if (screen)
      await this.checkScreen(
        { file: screen.file, screen: screen.qualname },
        target.qualname,
      );
  }
  private async checkScreen(
    input?: ScreenTarget,
    filter?: string,
  ): Promise<void> {
    let target = input;
    if (!target) {
      const editor = vscode.window.activeTextEditor;
      const project = editor && this.projects.projectFor(editor.document.uri);
      const screen =
        project &&
        this.discovery
          .get(project)
          ?.screens.find(
            (screen) =>
              normalizedPath(screen.file) ===
                normalizedPath(editor.document.uri.fsPath) &&
              screen.range.start.line <= editor.selection.active.line &&
              screen.range.end.line >= editor.selection.active.line,
          );
      if (screen) target = { file: screen.file, screen: screen.qualname };
    }
    if (!target) return;
    const project = this.projects.projectFor(vscode.Uri.file(target.file));
    if (!project) return;
    const screen = this.discovery
      .get(project)
      ?.screens.find(
        (screen) =>
          normalizedPath(screen.file) === normalizedPath(target.file) &&
          screen.qualname === target.screen,
      );
    if (!screen) return;
    const result = await this.request<ScreenCheckResult>(
      project,
      "screen.check",
      { file: target.file, screen: target.screen },
    );
    for (const checked of result.results) {
      if (filter && checked.qualname !== filter) continue;
      const element = screen.elements.find(
        (element) => element.qualname === checked.qualname,
      );
      if (element)
        this.checks.set({ project, screen, element, result: checked });
    }
    if (!filter) {
      const found = result.results.filter(
        (result) => result.status === "found",
      ).length;
      vscode.window.setStatusBarMessage(
        "Checked " +
          result.results.length +
          " elements: " +
          found +
          " found, " +
          (result.results.length - found) +
          " missing.",
        5000,
      );
    }
  }
  dispose(): void {
    this.subscriptions.forEach((subscription) => subscription.dispose());
  }
}
