import * as vscode from "vscode";
import type { DiscoveryStore, LocatedElement } from "../discovery/store";
import type { CheckResult } from "../protocol/generated";
import { normalizedPath } from "../projects";
import type { ActionFeedback, ActionStatus, ElementAction } from "./lensModel";

export interface CheckedElement extends LocatedElement {
  result: CheckResult;
}
export class CheckResultsStore implements vscode.Disposable {
  readonly results = new Map<string, CheckResult>();
  readonly entries = new Map<string, CheckedElement>();
  readonly feedback = new Map<string, ActionFeedback>();
  private readonly feedbackLocations = new Map<string, LocatedElement>();
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChange = this.changed.event;
  private readonly subscriptions: vscode.Disposable[];
  constructor(discovery: DiscoveryStore) {
    this.subscriptions = [
      vscode.workspace.onDidChangeTextDocument((event) => {
        for (const [id, entry] of new Map([
          ...this.entries,
          ...this.feedbackLocations,
        ])) {
          if (
            normalizedPath(entry.page.file) !==
            normalizedPath(event.document.uri.fsPath)
          )
            continue;
          if (
            event.contentChanges.some(
              (change) =>
                change.range.start.line <= entry.element.range.end.line &&
                change.range.end.line >= entry.element.range.start.line,
            )
          )
            this.remove(id);
        }
      }),
      discovery.onDidChange((project) => {
        for (const [id, entry] of new Map([
          ...this.entries,
          ...this.feedbackLocations,
        ])) {
          if (entry.project.root.toString() === project.root.toString())
            this.remove(id);
        }
      }),
    ];
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
    this.feedback.delete(id);
    this.feedbackLocations.delete(id);
    this.results.delete(id);
    this.entries.delete(id);
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
  constructor(
    private readonly results: CheckResultsStore,
    extensionUri: vscode.Uri,
  ) {
    this.styles = Object.fromEntries(
      ["found", "not_found", "ambiguous", "error"].map((status) => [
        status,
        vscode.window.createTextEditorDecorationType({
          gutterIconPath: vscode.Uri.joinPath(
            extensionUri,
            "media",
            status === "found"
              ? "check.svg"
              : status === "ambiguous"
                ? "warning.svg"
                : "cross.svg",
          ),
          gutterIconSize: "contain",
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
            entry.page.file !== editor.document.uri.fsPath ||
            entry.result.status !== status
          )
            continue;
          const line = entry.element.range.start.line;
          const text =
            status === "found"
              ? "  \u2713 found"
              : status === "ambiguous"
                ? "  \u26a0 " + entry.result.diagnostic?.matchCount + " matches"
                : status === "error"
                  ? "  \u2717 error"
                  : "  \u2717 not found";
          options.push({
            range: new vscode.Range(line, 0, line, 0),
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
