import * as vscode from "vscode";
import type { Projects } from "../projects";
import { normalizedPath } from "../projects";
import type { DiscoveryStore, LocatedElement } from "../discovery/store";
import type {
  CheckResult,
  DiscoveryResult,
  ElementCheckResult,
  ElementHighlightResult,
  PageCheckResult,
} from "../protocol/generated";
import { ServerManager, type Project } from "../server/serverManager";
import { RpcError } from "../server/jsonrpc";
import { summarizeChecks } from "./checkStatus";
import { CheckResultsStore } from "./decorations";
import { formatDiagnostic, shortElement } from "./diagnostics";
import type { ActionStatus } from "./lensModel";
import { recoverStoppedApp } from "./appRecovery";

export interface ElementTarget {
  file: string;
  qualname: string;
}
export interface PageTarget {
  file: string;
  page: string;
}
/** An element a whole-page check reports on, under the name the server gives its result. */
interface CheckedTarget {
  resultName: string;
  located: LocatedElement;
  /** Page Tree row of this element under the page that was checked. */
  nodeId: string;
  /** Declared by the checked page itself, not by a component it mounts. */
  own: boolean;
}
/**
 * Every element a page check covers: the page's own, and those of the components it mounts (at any
 * depth), which the server reports as `Page.member.element` but discovery lists under the
 * component's own page. The row ids follow the Page Tree's, where a mounted component's rows are
 * prefixed with the mount that holds them.
 */
export function pageCheckTargets(
  project: LocatedElement["project"],
  discovery: DiscoveryResult,
  host: DiscoveryResult["pages"][number],
): CheckedTarget[] {
  const pages = new Map(discovery.pages.map((page) => [page.id, page]));
  const targets: CheckedTarget[] = [];
  const walk = (
    page: typeof host,
    prefix: string,
    instance: string | undefined,
    lineage: ReadonlySet<string>,
  ) => {
    for (const element of page.elements) {
      const row = discovery.root + "|" + element.id;
      targets.push({
        resultName: prefix + "." + element.name,
        located: { project, page, element },
        nodeId: instance === undefined ? row : instance + "|" + row,
        own: instance === undefined,
      });
    }
    for (const child of page.children ?? []) {
      const mounted = pages.get(child.pageId);
      if (mounted && !lineage.has(child.pageId))
        walk(
          mounted,
          prefix + "." + child.name,
          (instance ?? discovery.root + "|" + host.id) + "|" + JSON.stringify([child.name, child.pageId]),
          new Set([...lineage, child.pageId]),
        );
    }
  };
  walk(host, host.qualname, undefined, new Set([host.id]));
  return targets;
}
class AppNotRunningError extends Error {
  constructor(readonly project: Project) {
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
        await this.safe(async () => {
          if (await recoverStoppedApp(error.project, this.servers))
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
        throw new AppNotRunningError(project);
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
    if (!target) throw new Error("Select an element declaration to check.");
    const project = this.projects.projectFor(vscode.Uri.file(target.file));
    if (!project) throw new Error("No WinTestKit project was found for this element. Refresh project discovery and try again.");
    const page = this.discovery
      .get(project)
      ?.pages.find(
        (page) =>
          normalizedPath(page.file) === normalizedPath(target.file) &&
          page.elements.some((element) => element.qualname === target.qualname),
      );
    const element = page?.elements.find((item) => item.qualname === target.qualname);
    const located = page && element ? { project, page, element } : undefined;
    const pendingStatus: ActionStatus = { status: "running" };
    if (located) this.checks.setFeedback(located, "check", pendingStatus);
    this.log.info("Checking element " + target.qualname + " in " + target.file);
    try {
      const checked = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: "Checking " + target.qualname,
        },
        () => this.request<ElementCheckResult>(project, "element.check", { ...target }),
      );
      if (!checked || !["found", "not_found", "ambiguous", "error"].includes(checked.status))
        throw new Error("The server returned no check result for this element.");
      const result = { ...checked, qualname: target.qualname };
      if (located && this.checks.setFeedback(located, "check", result, pendingStatus))
        this.checks.set({ ...located, result });
      this.log.info("Check " + target.qualname + ": " + checked.status);
      if (checked.status === "found") {
        vscode.window.setStatusBarMessage("$(check) Check: Found " + target.qualname, 5000);
      } else {
        await vscode.window.showWarningMessage(
          "Check " + target.qualname + ": " + (checked.diagnostic?.message ?? checked.message ?? checked.status),
        );
      }
    } catch (error) {
      const result = {
        qualname: target.qualname,
        status: "error" as const,
        message: error instanceof RpcError && error.code === -32601
          ? "Check Element captures need a newer wintestkit package in the project's Python environment."
          : error instanceof Error ? error.message : String(error),
        durationMs: 0,
      };
      if (located && this.checks.setFeedback(located, "check", result, pendingStatus))
        this.checks.set({ ...located, result });
      if (error instanceof RpcError && error.code === -32601) throw new Error(result.message);
      throw error;
    }
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
    const discovered = this.discovery.get(project);
    if (!discovered) return;
    const targets = pageCheckTargets(project, discovered, page).filter(
      (item) => !filter || item.resultName === filter,
    );
    const pendingStatus: ActionStatus = { status: "running" };
    // A component's elements are shared by every page that mounts it, so only the page's own are
    // shown as checking in the editor.
    for (const { located, own } of targets)
      if (own) this.checks.setFeedback(located, "check", pendingStatus);
    this.checks.setPageRunning(page.file, page.qualname, true);
    this.log.info("Checking all elements in " + page.qualname + " (" + targets.length + ")");
    try {
      const result = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: "Checking all elements in " + page.qualname,
        },
        () =>
          this.request<PageCheckResult>(project, "page.check", {
            file: target.file,
            page: target.page,
          }),
      );
      const scoped = new Map<string, CheckResult>();
      for (const { resultName, located, nodeId, own } of targets) {
        const checked = result.results.find(
          (checked) => checked.qualname === resultName,
        ) ?? {
          qualname: resultName,
          status: "error" as const,
          message: "The server returned no check result for this element.",
          durationMs: 0,
        };
        // A mounted component's result belongs to this page's rows alone: filing it under the
        // element would also mark the same component under every other page that mounts it.
        if (!own) scoped.set(nodeId, { ...checked, qualname: located.element.qualname });
        else if (this.checks.setFeedback(located, "check", checked, pendingStatus))
          this.checks.set({ ...located, result: checked });
      }
      this.checks.setScopedResults(scoped);
      this.checks.setPageRunning(page.file, page.qualname, false);
      if (!filter) {
        const summary = summarizeChecks(result.results);
        vscode.window.setStatusBarMessage(
          summary,
          5000,
        );
        const failures = result.results.filter((item) => item.status !== "found");
        if (failures.length) {
          const choice = await vscode.window.showInformationMessage(
            summary,
            "View failures",
          );
          if (choice === "View failures") {
            const selected = await vscode.window.showQuickPick(
              failures.map((item) => ({
                label: item.qualname,
                description: item.status === "not_found" ? "Not found on the current screen" : item.status,
                detail: item.diagnostic?.relocations?.map((relocation) => relocation.path ?? relocation.window).join("; ") ?? item.diagnostic?.hint ?? item.message,
                item,
              })),
              { title: "Check failures", placeHolder: "Select an element to open its definition" },
            );
            if (selected) {
              const failed = targets.find((item) => item.resultName === selected.item.qualname)?.located;
              const definition = failed?.element;
              if (failed && definition) {
                const document = await vscode.workspace.openTextDocument(failed.page.file);
                const editor = await vscode.window.showTextDocument(document);
                const position = new vscode.Position(definition.range.start.line, definition.range.start.character);
                editor.selection = new vscode.Selection(position, position);
                editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
              }
            }
          }
        }
      }
    } catch (error) {
      const scoped = new Map<string, CheckResult>();
      for (const { located, nodeId, own } of targets) {
        const result = {
          qualname: located.element.qualname,
          status: "error" as const,
          message: error instanceof Error ? error.message : String(error),
          durationMs: 0,
        };
        if (!own) scoped.set(nodeId, result);
        else if (this.checks.setFeedback(located, "check", result, pendingStatus))
          this.checks.set({ ...located, result });
      }
      this.checks.setScopedResults(scoped);
      throw error;
    } finally {
      this.checks.setPageRunning(page.file, page.qualname, false);
    }
  }
  dispose(): void {
    this.subscriptions.forEach((subscription) => subscription.dispose());
  }
}
