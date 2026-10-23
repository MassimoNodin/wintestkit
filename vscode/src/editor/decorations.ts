import * as vscode from "vscode";
import type { DiscoveryStore, LocatedElement } from "../discovery/store";
import type { CheckResult } from "../protocol/generated";
import { normalizedPath } from "../projects";
import { pageKey, type ActionFeedback, type ActionStatus, type ElementAction } from "./lensModel";

/** VS Code clamps a column past the end of a line to the end of that line. */
const END_OF_LINE = Number.MAX_SAFE_INTEGER;

export interface CheckedElement extends LocatedElement {
  result: CheckResult;
}
export class CheckResultsStore implements vscode.Disposable {
  readonly results = new Map<string, CheckResult>();
  readonly entries = new Map<string, CheckedElement>();
  readonly feedback = new Map<string, ActionFeedback>();
  /**
   * Whole-page check results of mounted components' elements, by Page Tree row id. A component's
   * rows repeat under every page that mounts it, so these belong to the one page that was checked.
   */
  readonly scopedResults = new Map<string, CheckResult>();
  private readonly feedbackLocations = new Map<string, LocatedElement>();
  private readonly runningPages = new Set<string>();
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChange = this.changed.event;
  private readonly subscriptions: vscode.Disposable[];
  /**
   * Results outlive file closes, saves and edits. Only a window reload (this store lives in memory)
   * or `clear()` discards them; a rediscovery just moves each result to where its element now is.
   */
  constructor(private readonly discovery: DiscoveryStore) {
    this.subscriptions = [
      discovery.onDidChange((project) => this.relocate(project)),
    ];
  }
  private relocate(project: LocatedElement["project"]): void {
    const discovered = this.discovery.get(project);
    if (!discovered) return;
    const current = new Map<string, LocatedElement>();
    for (const page of discovered.pages)
      for (const element of page.elements)
        current.set(element.id, { project, page, element });
    const key = project.root.toString();
    let changed = false;
    for (const [id, entry] of this.entries) {
      if (entry.project.root.toString() !== key) continue;
      const moved = current.get(id);
      if (moved) this.entries.set(id, { ...entry, ...moved });
      else this.drop(id);
      changed = true;
    }
    for (const [id, entry] of this.feedbackLocations) {
      if (entry.project.root.toString() !== key) continue;
      const moved = current.get(id);
      if (moved) this.feedbackLocations.set(id, moved);
      else this.drop(id);
      changed = true;
    }
    if (changed) this.changed.fire();
  }
  private drop(id: string): void {
    this.feedback.delete(id);
    this.feedbackLocations.delete(id);
    this.results.delete(id);
    this.entries.delete(id);
  }
  setScopedResults(results: ReadonlyMap<string, CheckResult>): void {
    for (const [id, result] of results) this.scopedResults.set(id, result);
    this.changed.fire();
  }
  setPageRunning(file: string, qualname: string, running: boolean): void {
    const key = pageKey(file, qualname);
    if (running === this.runningPages.has(key)) return;
    if (running) this.runningPages.add(key);
    else this.runningPages.delete(key);
    this.changed.fire();
  }
  isPageRunning(file: string, qualname: string): boolean {
    return this.runningPages.has(pageKey(file, qualname));
  }
  /** Discards every stored result, as the Page Tree's clear button does. */
  clear(): void {
    this.results.clear();
    this.scopedResults.clear();
    this.entries.clear();
    this.feedback.clear();
    this.feedbackLocations.clear();
    this.changed.fire();
  }
  setFeedback(
    entry: LocatedElement,
    action: ElementAction,
    status: ActionStatus,
    expected?: ActionStatus,
  ): boolean {
    if (expected && this.feedback.get(entry.element.id)?.[action] !== expected)
      return false;
    this.feedbackLocations.set(entry.element.id, entry);
    this.feedback.set(entry.element.id, {
      ...this.feedback.get(entry.element.id),
      [action]: status,
    });
    this.changed.fire();
    return true;
  }
  set(entry: CheckedElement): void {
    this.entries.set(entry.element.id, entry);
    this.results.set(entry.element.id, entry.result);
    this.changed.fire();
  }
  remove(id: string): void {
    this.drop(id);
    this.changed.fire();
  }
  dispose(): void {
    this.subscriptions.forEach((subscription) => subscription.dispose());
    this.changed.dispose();
  }
}

export class CheckDecorations implements vscode.Disposable {
  private readonly diagnostics = vscode.languages.createDiagnosticCollection(
    "wintestkit-elements",
  );
  private readonly styles: Record<string, vscode.TextEditorDecorationType>;
  private readonly subscriptions: vscode.Disposable[];
  constructor(private readonly results: CheckResultsStore) {
    // Only problems are marked, with inline text and no gutter icon. A passing element is left
    // unmarked; the "Check: Found" CodeLens still reports it.
    this.styles = Object.fromEntries(
      ["not_found", "ambiguous", "error"].map((status) => [
        status,
        vscode.window.createTextEditorDecorationType({
          after: { color: new vscode.ThemeColor("editorCodeLens.foreground") },
        }),
      ]),
    );
    this.subscriptions = [
      results.onDidChange(() => this.update()),
      vscode.window.onDidChangeVisibleTextEditors(() => this.update()),
    ];
  }
  private update(): void {
    this.diagnostics.clear();
    const diagnostics = new Map<string, vscode.Diagnostic[]>();
    for (const entry of this.results.entries.values()) {
      if (entry.result.status === "found") continue;
      const range = entry.element.nameRange;
      const diagnostic = new vscode.Diagnostic(
        new vscode.Range(
          range.start.line,
          range.start.character,
          range.end.line,
          range.end.character,
        ),
        entry.result.diagnostic?.message ??
          entry.result.message ??
          "Element resolution failed",
        vscode.DiagnosticSeverity.Warning,
      );
      diagnostic.source = "WinTestKit";
      const list = diagnostics.get(entry.page.file) ?? [];
      list.push(diagnostic);
      diagnostics.set(entry.page.file, list);
    }
    for (const [file, list] of diagnostics)
      this.diagnostics.set(vscode.Uri.file(file), list);
    for (const editor of vscode.window.visibleTextEditors) {
      for (const [status, style] of Object.entries(this.styles)) {
        const options: vscode.DecorationOptions[] = [];
        for (const entry of this.results.entries.values()) {
          if (
            normalizedPath(entry.page.file) !== normalizedPath(editor.document.uri.fsPath) ||
            entry.result.status !== status
          )
            continue;
          const line = entry.element.range.start.line;
          const text =
            status === "ambiguous"
              ? "  \u26a0 " + entry.result.diagnostic?.matchCount + " matches"
              : status === "error"
                ? "  \u2717 error"
                : "  \u2717 not found";
          options.push({
            // An empty range at the end of the line puts the text after the code, not before it.
            range: new vscode.Range(line, END_OF_LINE, line, END_OF_LINE),
            hoverMessage:
              entry.result.diagnostic?.message ?? entry.result.message,
            renderOptions: { after: { contentText: text } },
          });
        }
        editor.setDecorations(style, options);
      }
    }
  }
  dispose(): void {
    this.subscriptions.forEach((subscription) => subscription.dispose());
    Object.values(this.styles).forEach((style) => style.dispose());
    this.diagnostics.dispose();
  }
}
