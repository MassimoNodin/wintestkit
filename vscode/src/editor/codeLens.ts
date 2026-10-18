import * as vscode from "vscode";
import type { Projects } from "../projects";
import type { DiscoveryStore } from "../discovery/store";
import { buildLenses } from "./lensModel";
import type { CheckResultsStore } from "./decorations";
import { flowKey, type FlowRuns } from "./flowRuns";

export class CodeLenses implements vscode.CodeLensProvider, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this.changed.event;
  private readonly subscriptions: vscode.Disposable[];
  constructor(
    private readonly projects: Projects,
    private readonly discovery: DiscoveryStore,
    private readonly checks: CheckResultsStore,
    private readonly flows: FlowRuns,
  ) {
    this.subscriptions = [
      discovery.onDidChange(() => this.refresh()),
      checks.onDidChange(() => this.refresh()),
      flows.onDidChange(() => this.refresh()),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (
          event.affectsConfiguration("wintestkit.codeLens.enabled") ||
          event.affectsConfiguration("wintestkit.codeLens.classOnly")
        )
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
    const configuration = vscode.workspace.getConfiguration("wintestkit", document.uri);
    return buildLenses(
      result,
      document.uri.fsPath,
      this.checks.feedback,
      (file, name) => this.flows.states.get(flowKey({ file, name })),
      configuration.get<boolean>("codeLens.classOnly", false),
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
