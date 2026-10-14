import * as vscode from "vscode";
import type { Projects } from "../projects";
import type { DiscoveryStore } from "../discovery/store";
import type { CheckResultsStore } from "../editor/decorations";
import type { DiscoveryResult } from "../protocol/generated";
import { buildTree, type ElementNode } from "./elementsTreeModel";

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
      vscode.commands.registerCommand(
        "wintestkit.elements.goTo",
        async (node: ElementNode) => {
          if (!node?.file || !node.range) return;
          const range = new vscode.Range(
            node.range.start.line,
            node.range.start.character,
            node.range.end.line,
            node.range.end.character,
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
  getChildren(node?: ElementNode): ElementNode[] {
    return (
      node?.children ??
      buildTree(
        this.projects.all
          .map((project) => this.discovery.get(project))
          .filter((result): result is DiscoveryResult => result !== undefined),
      )
    );
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
    item.contextValue = node.kind;
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
