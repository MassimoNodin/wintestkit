import * as vscode from "vscode";
import type { Projects } from "../projects";
import type { DiscoveryStore } from "../discovery/store";
import type { TestOutcome } from "../protocol/generated";
import { buildLenses } from "./lensModel";
import type { CheckResultsStore } from "./decorations";

export class CodeLenses implements vscode.CodeLensProvider, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this.changed.event;
  private readonly subscriptions: vscode.Disposable[];
  readonly lastResults = new Map<string, TestOutcome>();
  constructor(
    private readonly projects: Projects,
    private readonly discovery: DiscoveryStore,
    private readonly checks: CheckResultsStore,
  ) {
    this.subscriptions = [
      discovery.onDidChange(() => this.refresh()),
      checks.onDidChange(() => this.refresh()),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration("wintestkit.codeLens.enabled"))
          this.refresh();
      }),
      vscode.languages.registerCodeLensProvider(
        { language: "python", scheme: "file" },
        this,
      ),
    ];
  }
  refresh(): void {
    this.changed.fire();
  }
  provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
    if (
      !vscode.workspace
        .getConfiguration("wintestkit", document.uri)
        .get<boolean>("codeLens.enabled", true)
    )
      return [];
    const project = this.projects.projectFor(document.uri);
    const result = project && this.discovery.get(project);
    if (!result) return [];
    return buildLenses(
      result,
      document.uri.fsPath,
      this.lastResults,
      this.checks.feedback,
    ).map(
      (spec) =>
        new vscode.CodeLens(new vscode.Range(spec.line, 0, spec.line, 0), {
          title: spec.title,
          command: spec.command,
          arguments: spec.args,
          tooltip: spec.tooltip,
        }),
    );
  }
  dispose(): void {
    this.subscriptions.forEach((subscription) => subscription.dispose());
    this.changed.dispose();
  }
}
