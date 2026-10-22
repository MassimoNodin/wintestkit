import * as vscode from "vscode";
import type { CheckResultsStore } from "./decorations";
import { normalizedPath } from "../projects";

export class RelocationActions implements vscode.Disposable {
  private readonly registration: vscode.Disposable;
  constructor(private readonly checks: CheckResultsStore) {
    this.registration = vscode.languages.registerCodeActionsProvider(
      { language: "python", scheme: "file" },
      this,
      { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] },
    );
  }

  provideCodeActions(
    document: vscode.TextDocument,
    range: vscode.Range,
  ): vscode.CodeAction[] {
    const actions: vscode.CodeAction[] = [];
    for (const entry of this.checks.entries.values()) {
      if (normalizedPath(entry.page.file) !== normalizedPath(document.uri.fsPath)) continue;
      const elementRange = new vscode.Range(
        entry.element.range.start.line,
        entry.element.range.start.character,
        entry.element.range.end.line,
        entry.element.range.end.character,
      );
      if (!elementRange.intersection(range)) continue;
      for (const relocation of entry.result.diagnostic?.relocations ?? []) {
        const action = new vscode.CodeAction(
          "Reveal relocated element in Spy",
          vscode.CodeActionKind.QuickFix,
        );
        action.command = {
          command: "wintestkit.spy.revealRelocation",
          title: action.title,
          arguments: [relocation.path],
        };
        actions.push(action);
      }
    }
    return actions;
  }

  dispose(): void {
    this.registration.dispose();
  }
}
