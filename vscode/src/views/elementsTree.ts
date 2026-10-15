import * as vscode from "vscode";
import type { Projects } from "../projects";
import { normalizedPath } from "../projects";
import type { DiscoveryStore } from "../discovery/store";
import type { CheckResultsStore } from "../editor/decorations";
import type { DiscoveryResult } from "../protocol/generated";
import { buildTree, type ElementNode } from "./elementsTreeModel";
import { buildProjectTree, type ProjectSection } from "./projectTreeModel";

export class ElementsTree
  implements vscode.TreeDataProvider<ElementNode>, vscode.Disposable
{
  private readonly changed = new vscode.EventEmitter<ElementNode | undefined>();
  readonly onDidChangeTreeData = this.changed.event;
  private readonly subscriptions: vscode.Disposable[];
  constructor(
    private readonly projects: Projects,
    private readonly discovery: DiscoveryStore,
    private readonly checks: CheckResultsStore,
  ) {
    const refresh = () => this.changed.fire(undefined);
    this.subscriptions = [
      projects.onDidChange(refresh),
      discovery.onDidChange(refresh),
      checks.onDidChange(refresh),
      vscode.window.registerTreeDataProvider("wintestkit.elements", this),
      ...(["flows", "tests"] as const).map((section) =>
        vscode.window.registerTreeDataProvider("wintestkit." + section, {
          onDidChangeTreeData: this.onDidChangeTreeData,
          getChildren: (node?: ElementNode) => this.getChildren(node, section),
          getTreeItem: (node: ElementNode) => this.getTreeItem(node),
        }),
      ),
      ...(["run", "debug"] as const).map((action) =>
        vscode.commands.registerCommand(
          "wintestkit.tests." + action,
          async (node: ElementNode) => {
            if (node?.testId === undefined || !node.root) return;
            const project = this.projects.all.find(
              (candidate) =>
                normalizedPath(candidate.root.fsPath) ===
                normalizedPath(node.root!),
            );
            if (project)
              await vscode.commands.executeCommand(
                action === "run"
                  ? "wintestkit.runTest"
                  : "wintestkit.debugTest",
                { id: node.testId, project },
              );
          },
        ),
      ),
      vscode.commands.registerCommand(
        "wintestkit.elements.goTo",
        async (node: ElementNode) => {
          if (!node?.file) return;
          const location = node.range ?? {
            start: { line: 0, character: 0 },
            end: { line: 0, character: 0 },
          };
          const range = new vscode.Range(
            location.start.line,
            location.start.character,
            location.end.line,
            location.end.character,
          );
          const editor = await vscode.window.showTextDocument(
            vscode.Uri.file(node.file),
            { selection: range },
          );
          editor.revealRange(
            range,
            vscode.TextEditorRevealType.InCenterIfOutsideViewport,
          );
        },
      ),
    ];
  }
  getChildren(node?: ElementNode, section?: ProjectSection): ElementNode[] {
    if (node) return node.children;
    const discoveries = this.projects.all
      .map((project) => this.discovery.get(project))
      .filter((result): result is DiscoveryResult => result !== undefined);
    return section
      ? buildProjectTree(discoveries, section)
      : buildTree(discoveries);
  }
  getTreeItem(node: ElementNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      node.label,
      node.children.length
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
    );
    item.id = node.id;
    item.description = node.description;
    item.tooltip = node.tooltip ?? node.description;
    item.contextValue =
      node.testId !== undefined &&
      (node.kind === "file" || node.kind === "project")
        ? "test-" + node.kind
        : node.kind;
    item.iconPath = new vscode.ThemeIcon(node.icon);
    const result = node.elementId && this.checks.results.get(node.elementId);
    if (result) {
      const passed = result.status === "found";
      const ambiguous = result.status === "ambiguous";
      item.iconPath = new vscode.ThemeIcon(
        passed ? "pass" : ambiguous ? "warning" : "error",
        new vscode.ThemeColor(
          passed
            ? "testing.iconPassed"
            : ambiguous
              ? "list.warningForeground"
              : "testing.iconFailed",
        ),
      );
    }
    if (node.file)
      item.command = {
        command: "wintestkit.elements.goTo",
        title: "Go to Definition",
        arguments: [node],
      };
    return item;
  }
  dispose(): void {
    this.subscriptions.forEach((subscription) => subscription.dispose());
    this.changed.dispose();
  }
}
